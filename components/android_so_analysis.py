"""
android_so_analysis_refactored.py

Refactored Android/Vita .so analyzer tab for PySide6.

Key improvements:
- MVC-ish separation: BinaryAnalysisService encapsulates subprocess execution + parsing.
- Dataclasses for Symbol and Instruction.
- "Deep Analysis" UI section with stubbed entry points (AI-extension ready).
- "Analyze Selection" button to send selected code-view text to analysis function.
- Strong typing and docstrings throughout.

This module is designed to be dropped into an existing PySide6 application that hosts tabs/widgets.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# Optional: pyelftools can accelerate parsing and provide richer ELF metadata.
# The application still works without it by falling back to shell tools (readelf/objdump).
try:
    from elftools.elf.elffile import ELFFile  # type: ignore
    from elftools.elf.sections import SymbolTableSection  # type: ignore
    _HAS_PYELFTOOLS = True
except Exception:
    ELFFile = None  # type: ignore
    SymbolTableSection = None  # type: ignore
    _HAS_PYELFTOOLS = False

from PySide6.QtCore import QObject, Qt, QProcess, QByteArray, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QFrame,
    QScrollArea,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from components.icon_utils import themed_icon


# --------------------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ToolInfo:
    """Represents an external tool dependency and its resolved path (if found)."""
    name: str
    exe: str
    found: bool
    path: Optional[str] = None


@dataclass(frozen=True, slots=True)
class Symbol:
    """Represents an ELF symbol (primarily FUNC symbols for this UI)."""
    name: str
    addr: int
    size: Optional[int] = None
    source: Optional[str] = None  # e.g., 'readelf -sW', 'DT_INIT'


@dataclass(frozen=True, slots=True)
class Instruction:
    """
    Represents a disassembled instruction.

    Parsing is best-effort: objdump output formats vary across toolchains.
    """
    address: Optional[int]
    bytes_hex: Optional[str]
    mnemonic: Optional[str]
    operands: Optional[str]
    comment: Optional[str]
    raw_line: str


@dataclass(frozen=True, slots=True)
class SectionInfo:
    """Represents a section row from `readelf -S`."""
    name: str
    nr: int
    addr: int
    offset: int
    size: int


@dataclass(frozen=True, slots=True)
class EntrypointReport:
    """Represents loader entrypoint analysis results."""
    lines: List[str]
    candidates: List[Symbol]


# --------------------------------------------------------------------------------------
# View helper: Syntax highlighter (optimized)
# --------------------------------------------------------------------------------------

class AsmHighlighter(QSyntaxHighlighter):
    """
    Highlights ARM/Thumb assembly output (objdump/llvm-objdump style).

    Optimization:
    - Regex patterns are compiled once in __init__.
    - highlightBlock iterates over a small fixed set of rules.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._rules: List[Tuple[re.Pattern[str], QTextCharFormat]] = []

        # 1) Address at start of line (e.g., "   1050:")
        addr_fmt = QTextCharFormat()
        addr_fmt.setForeground(QColor("#808080"))  # gray
        self._rules.append((re.compile(r"^\s*[0-9a-fA-F]+:"), addr_fmt))

        # 2) Hex bytes (e.g., "e92d 4ff0" / "f0 4f 2d e9")
        hex_fmt = QTextCharFormat()
        hex_fmt.setForeground(QColor("#008080"))  # teal
        self._rules.append((re.compile(r"\b[0-9a-fA-F]{2,8}\b"), hex_fmt))

        # 3) Registers (r0-r15, sp, lr, pc, cpsr, etc.)
        reg_fmt = QTextCharFormat()
        reg_fmt.setForeground(QColor("#D35400"))  # orange/red
        reg_fmt.setFontWeight(QFont.Bold)
        self._rules.append((re.compile(r"\b(r[0-9]|r1[0-5]|sp|lr|pc|cpsr|apsr)\b"), reg_fmt))

        # 4) Common ARM/Thumb mnemonics
        inst_fmt = QTextCharFormat()
        inst_fmt.setForeground(QColor("#0000FF"))  # blue
        inst_fmt.setFontWeight(QFont.Bold)
        keywords = [
            "mov", "movs", "ldr", "ldrb", "ldrh", "str", "strb", "strh",
            "bl", "blx", "bx", "push", "pop", "add", "sub", "cmp", "cmn",
            "b", "beq", "bne", "bgt", "blt", "bge", "ble", "bhi", "blo",
            "and", "orr", "eor", "bic", "lsl", "lsr", "asr", "nop", "tst",
        ]
        self._rules.append((re.compile(r"\b(" + "|".join(keywords) + r")\b"), inst_fmt))

        # 5) Comments / Symbols
        comment_fmt = QTextCharFormat()
        comment_fmt.setForeground(QColor("#008000"))  # green
        self._rules.append((re.compile(r";.*"), comment_fmt))
        self._rules.append((re.compile(r"<.*>"), comment_fmt))

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)


# --------------------------------------------------------------------------------------
# Service layer: subprocess execution + parsing
# --------------------------------------------------------------------------------------

class BinaryAnalysisService(QObject):
    """
    Encapsulates all subprocess interactions (readelf/objdump/radare2) and parsing.

    The UI should:
    - call service methods (requests)
    - listen to service signals (responses/logs)

    This makes the codebase "AI-extension ready" because future automation/agents can plug
    additional analysis steps into the service without touching UI wiring.
    """

    # Generic logging (goes to system log)
    log_message = Signal(str)
    error_message = Signal(str)

    # Data delivery signals
    tools_detected = Signal(list)               # List[ToolInfo]
    symbols_loaded = Signal(list)               # List[Symbol]
    disassembly_ready = Signal(str, list)       # raw_text, List[Instruction]
    entrypoints_ready = Signal(object)          # EntrypointReport
    sections_loaded = Signal(dict, object)      # Dict[str, SectionInfo], Optional[Tuple[int,int]]

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self._proc: Optional[QProcess] = None
        self._queue: List[Tuple[List[str], Optional[str], Optional[str], Optional[Callable[[str], None]]]] = []
        self._current_cmd_str: Optional[str] = None

        # Capture support
        self._capture_tag: Optional[str] = None
        self._capture_buf: bytearray = bytearray()
        self._capture_on_done: Optional[Callable[[str], None]] = None

        # Cached ELF information
        self._sections: Dict[str, SectionInfo] = {}
        self._text_range: Optional[Tuple[int, int]] = None

        # Parsing regexes
        self._sym_func_re = re.compile(
            r"^\s*\d+:\s*([0-9a-fA-F]+)\s+(\d+)\s+FUNC\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+)$"
        )
        self._sec_row_re = re.compile(
            r"^\s*\[\s*(\d+)\]\s+(\S+)\s+(\S+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+",
            re.IGNORECASE,
        )
        self._dyn_tag_re = re.compile(r"\(\s*([A-Z0-9_]+)\s*\).*?(0x[0-9a-fA-F]+)\s*$")
        self._data_prefixes: Tuple[str, ...] = ("_ZTS", "_ZTI", "_ZTV")

        # Best-effort instruction parse (objdump-like)
        # Example: "   1050:\t e92d4ff0\tpush\t{r4, r5, ...}"
        self._insn_re = re.compile(
            r"^\s*([0-9a-fA-F]+):\s*([0-9a-fA-F ]+)?\s*([a-zA-Z][\w\.\-]*)?\s*(.*?)\s*(?:;(.+))?$"
        )

    # -------------------------- Public API: tool detection --------------------------

    def detect_tools(self) -> List[ToolInfo]:
        """
        Detect external tools in PATH.

        Returns:
            List[ToolInfo]: Detected tools. Also emitted via tools_detected.
        """
        candidates = [
            ("readelf", "readelf"),
            ("arm-vita-eabi-objdump", "arm-vita-eabi-objdump"),
            ("llvm-objdump", "llvm-objdump"),
            ("objdump", "objdump"),
            ("radare2", "r2"),
        ]
        tools: List[ToolInfo] = []
        for name, exe in candidates:
            path = shutil.which(exe)
            tools.append(ToolInfo(name=name, exe=exe, found=path is not None, path=path))
        self.tools_detected.emit(tools)

        summary = " | ".join([f"{t.name}={'OK' if t.found else 'MISSING'}" for t in tools])
        self.log_message.emit("== Tool detection ==")
        self.log_message.emit(f"Tools: {summary}")
        for t in tools:
            if t.found:
                self.log_message.emit(f"[OK] {t.name}: {t.path}")
            else:
                self.error_message.emit(f"[MISSING] {t.name}: not found in PATH ({t.exe})")
        return tools

    # -------------------------- Public API: queue/process --------------------------

    def stop(self) -> None:
        """Stop current process and clear queued commands."""
        if self._proc and self._proc.state() != QProcess.NotRunning:
            self.error_message.emit(f"[STOP] Killing process: {self._current_cmd_str}")
            self._proc.kill()
        self._queue.clear()
        self._capture_tag = None
        self._capture_buf = bytearray()
        self._capture_on_done = None

    def run_command_capture(
        self,
        cmd: Sequence[str],
        *,
        cwd: Optional[str] = None,
        capture_tag: Optional[str] = None,
        on_done: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Enqueue a command for execution.

        Args:
            cmd: Program + args (already split; no shell).
            cwd: Optional working directory.
            capture_tag: If set, capture merged stdout/stderr into a buffer.
            on_done: Callback executed when the process finishes; receives captured text.
        """
        self._queue.append((list(cmd), cwd, capture_tag, on_done))
        self._start_next()

    def run_commands(self, cmds: Sequence[Sequence[str]], *, cwd: Optional[str] = None) -> None:
        """Enqueue multiple commands in order."""
        for cmd in cmds:
            self._queue.append((list(cmd), cwd, None, None))
        self._start_next()

    # -------------------------- Public API: analysis operations --------------------------

    def load_sections(self, so_path: str) -> None:
        """
        Parse `readelf -S` and cache section info, including .text range.

        Emits:
            sections_loaded(sections_by_name, text_range)
        """
        if not self._ensure_file(so_path):
            return

        # Prefer pyelftools when available; fall back to readelf.
        py = self._try_load_sections_pyelftools(so_path)
        if py is not None:
            sections, text_range = py
            self.sections_loaded.emit(sections, text_range)
            return

        if not self._ensure_tool("readelf"):
            return

        def _done(txt: str) -> None:
            sections, text_range = self._parse_sections(txt)
            self._sections = sections
            self._text_range = text_range
            self.sections_loaded.emit(sections, text_range)

        self.run_command_capture(["readelf", "-S", so_path], cwd=os.path.dirname(so_path), capture_tag="sec", on_done=_done)

    def load_func_symbols(self, so_path: str) -> None:
        """
        Load function symbols via `readelf -sW` and emit them as dataclasses.

        Emits:
            symbols_loaded(List[Symbol])
        """
        if not self._ensure_file(so_path):
            return

        # Prefer pyelftools when available; fall back to readelf.
        sym = self._try_load_symbols_pyelftools(so_path)
        if sym is not None and sym:
            self.symbols_loaded.emit(sym)
            return

        if not self._ensure_tool("readelf"):
            return

        def _done(txt: str) -> None:
            symbols = self._parse_func_symbols(txt)
            self.symbols_loaded.emit(symbols)
            self.log_message.emit(f"[OK] Loaded {len(symbols)} function symbol(s).")

        self.log_message.emit("Loading FUNC symbols: readelf -sW <so>")
        self.run_command_capture(["readelf", "-sW", so_path], cwd=os.path.dirname(so_path), capture_tag="sym", on_done=_done)

    def disassemble_range(
        self,
        so_path: str,
        *,
        start: int,
        stop: int,
        tool_choice: str,
        force_thumb: bool,
    ) -> None:
        """
        Disassemble an address range and emit raw text + parsed instructions.

        Emits:
            disassembly_ready(raw_text, instructions)
        """
        if not self._ensure_file(so_path):
            return

        if stop <= start:
            self.error_message.emit("ERROR: stop must be > start.")
            return

        cmd = self._build_disasm_command(
            so_path=so_path,
            tool_choice=tool_choice,
            start=start,
            stop=stop,
            force_thumb=force_thumb,
        )
        if not cmd:
            return

        self.log_message.emit("[RUN] " + " ".join(shlex.quote(x) for x in cmd))

        def _done(txt: str) -> None:
            instructions = self._parse_instructions(txt)
            self.disassembly_ready.emit(txt, instructions)

        self.run_command_capture(cmd, cwd=os.path.dirname(so_path), capture_tag="disasm", on_done=_done)

    def run_ragen_analysis(self, so_path: str) -> None:
        """Run a batch of readelf commands (legacy 'RAGEN' convenience)."""
        if not self._ensure_file(so_path):
            return
        if not self._ensure_tool("readelf"):
            return

        cmds = [
            ["readelf", "-h", so_path],
            ["readelf", "-l", so_path],
            ["readelf", "-S", so_path],
            ["readelf", "-dW", so_path],
            ["readelf", "-rW", so_path],
            ["readelf", "-sW", so_path],
        ]
        self.log_message.emit("== RAGEN analysis: running batch ==")
        self.run_commands(cmds, cwd=os.path.dirname(so_path))

    def find_loader_entrypoints(self, so_path: str) -> None:
        """
        Find loader entrypoint candidates based on DT_INIT/INIT_ARRAY/.init and symbols.

        Emits:
            entrypoints_ready(EntrypointReport)
        """
        if not self._ensure_file(so_path):
            return
        if not self._ensure_tool("readelf"):
            return

        self.log_message.emit("== Finding loader entrypoints (DT_INIT / INIT_ARRAY / .init / JNI_OnLoad) ==")

        captures: Dict[str, str] = {}

        pending = {"dyn", "sec", "sym"}

        def _done(tag: str) -> Callable[[str], None]:
            def _inner(txt: str) -> None:
                nonlocal pending
                captures[tag] = txt
                pending.discard(tag)
                if not pending:
                    report = self._analyze_loader_entrypoints(
                        dyn_txt=captures.get("dyn", ""),
                        sec_txt=captures.get("sec", ""),
                        sym_txt=captures.get("sym", ""),
                    )
                    self.entrypoints_ready.emit(report)
            return _inner

        self.run_command_capture(["readelf", "-dW", so_path], cwd=os.path.dirname(so_path), capture_tag="dyn", on_done=_done("dyn"))
        self.run_command_capture(["readelf", "-S", so_path], cwd=os.path.dirname(so_path), capture_tag="sec", on_done=_done("sec"))
        self.run_command_capture(["readelf", "-sW", so_path], cwd=os.path.dirname(so_path), capture_tag="sym", on_done=_done("sym"))

    # -------------------------- Deep analysis hooks (stubs) --------------------------

    def deep_analyze_selection(self, selection_text: str) -> None:
        """
        Stub entry point for analyzing a selected snippet from the code view.

        Future AI tooling can replace this with:
        - instruction normalization
        - basic block recovery
        - pattern recognition (e.g., prologues/epilogues)
        - vulnerability heuristics
        """
        if not selection_text.strip():
            self.error_message.emit("[DEEP] No selection provided.")
            return
        self.log_message.emit("[DEEP] Analyze selection invoked (stub).")
        self.log_message.emit(f"[DEEP] Selection length: {len(selection_text)} characters.")

    def identify_function_prologues(self) -> None:
        """Stub for a future prologue identification pass."""
        self.log_message.emit("[DEEP] Identify Function Prologues (stub).")

    def generate_control_flow(self) -> None:
        """Stub for a future CFG generation pass."""
        self.log_message.emit("[DEEP] Generate Control Flow (stub).")

    def heuristic_vulnerability_scan(self) -> None:
        """Stub for a future vulnerability scan pass."""
        self.log_message.emit("[DEEP] Heuristic Vulnerability Scan (stub).")

    # -------------------------- Internal: process runner --------------------------

    def _start_next(self) -> None:
        if self._proc and self._proc.state() != QProcess.NotRunning:
            return
        if not self._queue:
            self._current_cmd_str = None
            return

        cmd, cwd, tag, on_done = self._queue.pop(0)
        program = cmd[0] if cmd else ""
        args = cmd[1:] if len(cmd) > 1 else []

        if not program:
            self.error_message.emit("[ERROR] Empty command.")
            self._start_next()
            return

        self._capture_tag = tag
        self._capture_buf = bytearray()
        self._capture_on_done = on_done
        self._current_cmd_str = " ".join(shlex.quote(x) for x in cmd)

        self.log_message.emit(f"$ {self._current_cmd_str}")

        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        if cwd:
            self._proc.setWorkingDirectory(cwd)

        self._proc.readyReadStandardOutput.connect(self._on_proc_output)
        self._proc.errorOccurred.connect(self._on_proc_error)
        self._proc.finished.connect(self._on_proc_finished)
        self._proc.start(program, args)

    def _on_proc_output(self) -> None:
        if not self._proc:
            return
        data: QByteArray = self._proc.readAllStandardOutput()
        raw = bytes(data)
        if self._capture_tag:
            self._capture_buf.extend(raw)
        # Stream non-captured output to log for visibility.
        if self._capture_tag is None:
            self.log_message.emit(raw.decode(errors="replace"))

    def _on_proc_error(self, err: Any) -> None:
        self.error_message.emit(f"[PROCESS ERROR] {err} while running: {self._current_cmd_str}")

    def _on_proc_finished(self, exit_code: int, exit_status: Any) -> None:
        if self._capture_tag:
            captured = self._capture_buf.decode(errors="replace")
            if self._capture_on_done:
                try:
                    self._capture_on_done(captured)
                except Exception as e:
                    self.error_message.emit(f"[CAPTURE CALLBACK ERROR] {e}")

        if exit_code != 0:
            self.error_message.emit(f"[DONE] exit_code={exit_code} (command failed)")
        else:
            self.log_message.emit(f"[DONE] exit_code={exit_code}")

        self._capture_tag = None
        self._capture_buf = bytearray()
        self._capture_on_done = None
        self._start_next()

    # -------------------------- Internal: validation helpers --------------------------

    def _ensure_file(self, so_path: str) -> bool:
        if not so_path or not os.path.isfile(so_path):
            self.error_message.emit("ERROR: Select a valid .so file first.")
            return False
        return True


    def has_pyelftools(self) -> bool:
        """Return True if pyelftools is available in the current Python environment."""
        return bool(_HAS_PYELFTOOLS)

    def _try_load_sections_pyelftools(
        self, so_path: str
    ) -> Optional[Tuple[Dict[str, SectionInfo], Optional[Tuple[int, int]]]]:
        """Parse ELF sections using pyelftools. Returns None if unavailable or parsing fails."""
        if not _HAS_PYELFTOOLS:
            return None
        try:
            with open(so_path, "rb") as f:
                elf = ELFFile(f)  # type: ignore[misc]
                sections: Dict[str, SectionInfo] = {}
                text_range: Optional[Tuple[int, int]] = None
                for sec_idx, sec in enumerate(elf.iter_sections()):
                    name = sec.name or f"section_{sec_idx}"
                    hdr = sec.header
                    sh_addr = int(hdr.get("sh_addr", 0))
                    sh_offset = int(hdr.get("sh_offset", 0))
                    sh_size = int(hdr.get("sh_size", 0))
                    si = SectionInfo(name=name, nr=sec_idx, addr=sh_addr, offset=sh_offset, size=sh_size)
                    sections[name] = si
                    if name == ".text" and sh_size > 0:
                        text_range = (sh_addr, sh_addr + sh_size)
                return sections, text_range
        except Exception as e:
            self.log_message.emit(f"[WARN] pyelftools section parse failed: {e}")
            return None

    def _try_load_symbols_pyelftools(self, so_path: str) -> Optional[List[Symbol]]:
        """Parse STT_FUNC symbols using pyelftools from symtab/dynsym. Returns None on failure."""
        if not _HAS_PYELFTOOLS:
            return None
        try:
            with open(so_path, "rb") as f:
                elf = ELFFile(f)  # type: ignore[misc]
                out: List[Symbol] = []
                for sec in elf.iter_sections():
                    if SymbolTableSection is None or not isinstance(sec, SymbolTableSection):  # type: ignore[arg-type]
                        continue
                    for sym in sec.iter_symbols():
                        try:
                            info = sym["st_info"]
                            st_type = info.get("type") if hasattr(info, "get") else None
                            if st_type != "STT_FUNC":
                                continue
                            name = sym.name or ""
                            if not name:
                                continue
                            addr = int(sym["st_value"])
                            size = int(sym["st_size"])
                            out.append(Symbol(name=name, addr=addr, size=size, source=sec.name))
                        except Exception:
                            continue

                uniq: Dict[Tuple[int, str], Symbol] = {}
                for s in out:
                    uniq[(s.addr, s.name)] = s
                return sorted(uniq.values(), key=lambda s: s.addr)
        except Exception as e:
            self.log_message.emit(f"[WARN] pyelftools symbol parse failed: {e}")
            return None

    def _ensure_tool(self, exe: str) -> bool:
        if shutil.which(exe) is None:
            self.error_message.emit(f"ERROR: {exe} not found in PATH.")
            return False
        return True

    # -------------------------- Internal: parsing --------------------------

    def _parse_sections(self, sec_txt: str) -> Tuple[Dict[str, SectionInfo], Optional[Tuple[int, int]]]:
        sections: Dict[str, SectionInfo] = {}
        text_range: Optional[Tuple[int, int]] = None

        for line in sec_txt.splitlines():
            m = self._sec_row_re.match(line)
            if not m:
                continue
            nr = int(m.group(1))
            name = m.group(2)
            addr = int(m.group(4), 16)
            off = int(m.group(5), 16)
            size = int(m.group(6), 16)
            sections[name] = SectionInfo(name=name, nr=nr, addr=addr, offset=off, size=size)
            if name == ".text":
                text_range = (addr, addr + size)

        return sections, text_range

    def _parse_func_symbols(self, sym_txt: str) -> List[Symbol]:
        syms: List[Symbol] = []
        for line in sym_txt.splitlines():
            m = self._sym_func_re.match(line)
            if not m:
                continue

            addr_hex = m.group(1)
            size_dec = m.group(2)
            name = m.group(6).strip()

            if addr_hex.lower() == "00000000":
                continue
            if name.startswith(self._data_prefixes):
                continue

            addr = int(addr_hex, 16)
            size = None
            try:
                size = int(size_dec)
            except Exception:
                size = None

            syms.append(Symbol(name=name, addr=addr, size=size, source="readelf -sW"))
        return syms

    def _parse_dynamic_tags(self, dyn_txt: str) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for line in dyn_txt.splitlines():
            m = self._dyn_tag_re.search(line)
            if not m:
                continue
            tag = m.group(1).strip()
            val = m.group(2).strip()
            try:
                out[tag] = int(val, 16)
            except Exception:
                continue
        return out

    def _parse_symbols_of_interest(self, sym_txt: str) -> List[Symbol]:
        out: List[Symbol] = []
        for line in sym_txt.splitlines():
            m = self._sym_func_re.match(line)
            if not m:
                continue
            addr_hex = m.group(1)
            name = m.group(6).strip()
            if addr_hex.lower() == "00000000":
                continue
            if name.startswith(self._data_prefixes):
                continue

            addr = int(addr_hex, 16)
            low = name.lower()

            if name in ("JNI_OnLoad", "JNI_OnUnload", "_init"):
                out.append(Symbol(name=name, addr=addr, source="readelf -sW (standard)"))
            elif "jni_onload" in low:
                out.append(Symbol(name=name, addr=addr, source="readelf -sW (JNI-ish)"))
            elif "init" in low:
                out.append(Symbol(name=name, addr=addr, source="readelf -sW (init substring)"))
        return out

    def _analyze_loader_entrypoints(self, *, dyn_txt: str, sec_txt: str, sym_txt: str) -> EntrypointReport:
        lines: List[str] = []
        candidates: List[Symbol] = []

        # Sections cache for `.init` detection
        sections, _ = self._parse_sections(sec_txt)

        dyn_map = self._parse_dynamic_tags(dyn_txt)
        dt_init = dyn_map.get("INIT")
        dt_init_array = dyn_map.get("INIT_ARRAY")

        if dt_init is not None:
            lines.append(f"DT_INIT: 0x{dt_init:08X}")
            candidates.append(Symbol(name="_init (DT_INIT)", addr=dt_init, source="readelf -dW"))
        else:
            lines.append("DT_INIT: (not present)")

        if dt_init_array is not None:
            lines.append(f"DT_INIT_ARRAY: 0x{dt_init_array:08X}")
            candidates.append(Symbol(name=".init_array (DT_INIT_ARRAY addr)", addr=dt_init_array, source="readelf -dW"))
        else:
            lines.append("DT_INIT_ARRAY: (not present)")

        init_sec = sections.get(".init")
        if init_sec:
            lines.append(f".init section addr: 0x{init_sec.addr:08X}")
            candidates.append(Symbol(name=".init section", addr=init_sec.addr, source="readelf -S"))

        sym_candidates = self._parse_symbols_of_interest(sym_txt)
        if sym_candidates:
            lines.append("Symbol candidates:")
            for sc in sym_candidates:
                src = sc.source or "readelf -sW"
                lines.append(f"  0x{sc.addr:08X}  {sc.name}  ({src})")
            candidates.extend(sym_candidates)

        # Deduplicate
        uniq: Dict[Tuple[int, str], Symbol] = {}
        for c in candidates:
            uniq[(c.addr, c.name)] = c

        out = list(uniq.values())
        out.sort(key=lambda s: s.addr)

        return EntrypointReport(lines=lines, candidates=out)

    def _parse_instructions(self, disasm_txt: str) -> List[Instruction]:
        insns: List[Instruction] = []
        for line in disasm_txt.splitlines():
            m = self._insn_re.match(line)
            if not m:
                insns.append(Instruction(
                    address=None,
                    bytes_hex=None,
                    mnemonic=None,
                    operands=None,
                    comment=None,
                    raw_line=line,
                ))
                continue

            addr_s = m.group(1)
            bytes_s = (m.group(2) or "").strip() or None
            mnemonic = (m.group(3) or "").strip() or None
            operands = (m.group(4) or "").strip() or None
            comment = (m.group(5) or "").strip() or None

            addr = None
            try:
                addr = int(addr_s, 16)
            except Exception:
                addr = None

            insns.append(Instruction(
                address=addr,
                bytes_hex=bytes_s,
                mnemonic=mnemonic,
                operands=operands,
                comment=comment,
                raw_line=line,
            ))
        return insns

    # -------------------------- Internal: command builder --------------------------

    def _build_disasm_command(
        self,
        *,
        so_path: str,
        tool_choice: str,
        start: int,
        stop: int,
        force_thumb: bool,
    ) -> Optional[List[str]]:
        start_s = f"0x{start:08X}"
        stop_s = f"0x{stop:08X}"

        if tool_choice.startswith("arm-vita-eabi-objdump"):
            if not self._ensure_tool("arm-vita-eabi-objdump"):
                return None
            cmd: List[str] = ["arm-vita-eabi-objdump", "-d"]
            if force_thumb:
                cmd += ["-M", "force-thumb"]
            cmd += [f"--start-address={start_s}", f"--stop-address={stop_s}", so_path]
            return cmd

        if tool_choice.startswith("llvm-objdump"):
            if not self._ensure_tool("llvm-objdump"):
                return None
            return ["llvm-objdump", "-d", f"--start-address={start_s}", f"--stop-address={stop_s}", so_path]

        if tool_choice == "objdump":
            if not self._ensure_tool("objdump"):
                return None
            cmd = ["objdump", "-d"]
            if force_thumb:
                cmd += ["-M", "force-thumb"]
            cmd += [f"--start-address={start_s}", f"--stop-address={stop_s}", so_path]
            return cmd

        if tool_choice.startswith("radare2"):
            if not self._ensure_tool("r2"):
                return None
            # NOTE: radare2 command is not an address-range disasm in the same way; kept as legacy option.
            return ["r2", "-2", "-A", "-q", "-c", f"s {start_s}; pd 128", so_path]

        self.error_message.emit(f"ERROR: Unknown tool selection: {tool_choice}")
        return None


# --------------------------------------------------------------------------------------
# UI layer: AndroidSoAnalysisTab (View/Controller)
# --------------------------------------------------------------------------------------

class AndroidSoAnalysisTab(QWidget):
    """
    UI tab for Android/Vita .so analysis.

    Responsibilities:
    - capture user events
    - display results from BinaryAnalysisService
    - no parsing/subprocess logic (delegated to service)
    """

    def __init__(self, settings: Any = None, cmd_thread: Any = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.cmd_thread = cmd_thread

        self.service = BinaryAnalysisService(self)
        self._all_symbols: List[Symbol] = []
        self._text_range: Optional[Tuple[int, int]] = None

        self._connect_service_signals()
        self._build_ui()
        self.service.detect_tools()

    # ---------------- UI build ----------------

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        # --- File Selection ---
        file_row = QHBoxLayout()
        self.file_path_label = QLabel("SO File:")
        self.file_path_edit = QLineEdit("")
        self.file_path_edit.setPlaceholderText("Select a .so file")
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self._select_so_file)
        file_row.addWidget(self.file_path_label)
        file_row.addWidget(self.file_path_edit, 1)
        file_row.addWidget(self.browse_button)
        main_layout.addLayout(file_row)

        # --- Tools status row ---
        tools_row = QHBoxLayout()
        self.tools_status = QLabel("Tools: (detecting...)")
        self.refresh_tools_btn = QPushButton("Re-detect tools")
        self.refresh_tools_btn.clicked.connect(self.service.detect_tools)
        tools_row.addWidget(self.tools_status, 1)
        tools_row.addWidget(self.refresh_tools_btn)
        main_layout.addLayout(tools_row)

        splitter = QSplitter(Qt.Horizontal)

        # ---------------- Left panel: symbols ----------------
        left = QWidget()
        left_layout = QVBoxLayout(left)

        self.symbol_search = QLineEdit()
        self.symbol_search.setPlaceholderText("Filter symbols (regex /.../ or substring)...")
        self.symbol_search.textChanged.connect(self._filter_symbols)
        left_layout.addWidget(self.symbol_search)

        self.symbols_list = QListWidget()
        self.symbols_list.itemSelectionChanged.connect(self._on_symbol_selected)
        self.symbols_list.itemDoubleClicked.connect(self._prefill_disasm_from_item)
        left_layout.addWidget(self.symbols_list, 1)

        sym_btns = QHBoxLayout()
        self.load_symbols_btn = QPushButton("Load symbols (FUNC)")
        self.load_symbols_btn.clicked.connect(self._on_load_symbols_clicked)
        self.clear_symbols_btn = QPushButton("Clear")
        self.clear_symbols_btn.clicked.connect(self._clear_symbols)
        sym_btns.addWidget(self.load_symbols_btn)
        sym_btns.addWidget(self.clear_symbols_btn)
        left_layout.addLayout(sym_btns)

        splitter.addWidget(left)

        # ---------------- Right panel: controls + output ----------------
        right = QWidget()
        right_layout = QVBoxLayout(right)

        # Controls are placed in a scroll area so action groups (including Deep Analysis)
        # remain accessible even when the tab is vertically constrained.
        controls_container = QWidget()
        controls_layout = QVBoxLayout(controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)

        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setFrameShape(QScrollArea.NoFrame)
        controls_scroll.setWidget(controls_container)


        # Quick disasm group
        disasm_group = QGroupBox("Quick disassemble")
        disasm_layout = QVBoxLayout(disasm_group)

        row1 = QHBoxLayout()
        self.start_addr = QLineEdit("0x0")
        self.stop_addr = QLineEdit("0x0")
        self.start_addr.setPlaceholderText("start address (hex), e.g. 0x00F95040")
        self.stop_addr.setPlaceholderText("stop address (hex), e.g. 0x00F950C0")
        row1.addWidget(QLabel("Start:"))
        row1.addWidget(self.start_addr, 1)
        row1.addWidget(QLabel("Stop:"))
        row1.addWidget(self.stop_addr, 1)
        disasm_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.thumb_checkbox = QCheckBox("Force Thumb (objdump -M force-thumb)")
        self.thumb_checkbox.setChecked(True)
        self.tool_selector = QComboBox()
        self.tool_selector.addItems([
            "arm-vita-eabi-objdump (recommended for Vita)",
            "llvm-objdump",
            "objdump",
            "radare2 (pd)",
        ])
        row2.addWidget(self.thumb_checkbox)
        row2.addStretch(1)
        row2.addWidget(QLabel("Tool:"))
        row2.addWidget(self.tool_selector)
        disasm_layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.disasm_btn = QPushButton("Disassemble range")
        self.disasm_btn.clicked.connect(self._on_disassemble_clicked)
        self.disasm_cmd_preview = QLineEdit("")
        self.disasm_cmd_preview.setReadOnly(True)
        row3.addWidget(self.disasm_btn)
        row3.addWidget(QLabel("Preview:"))
        row3.addWidget(self.disasm_cmd_preview, 1)
        disasm_layout.addLayout(row3)

        # "Analyze Selection" (new)
        row4 = QHBoxLayout()
        self.analyze_selection_btn = QPushButton("Analyze Selection")
        self.analyze_selection_btn.setEnabled(False)
        self.analyze_selection_btn.clicked.connect(self._on_analyze_selection_clicked)
        row4.addWidget(self.analyze_selection_btn)
        row4.addStretch(1)
        disasm_layout.addLayout(row4)

        controls_layout.addWidget(disasm_group)

        # Automated analysis group
        auto_group = QGroupBox("Automated analysis")
        auto_layout = QVBoxLayout(auto_group)

        auto_row = QHBoxLayout()
        self.btn_ragen = QPushButton("RAGEN analysis")
        self.btn_ragen.clicked.connect(self._on_ragen_clicked)
        self.btn_entryloads = QPushButton("Find loader entrypoints")
        self.btn_entryloads.clicked.connect(self._on_entrypoints_clicked)
        auto_row.addWidget(self.btn_ragen)
        auto_row.addWidget(self.btn_entryloads)
        auto_row.addStretch(1)
        auto_layout.addLayout(auto_row)

        util_row = QHBoxLayout()
        self.btn_text_range = QPushButton("Fill .text range")
        self.btn_text_range.clicked.connect(self._on_fill_text_range_clicked)
        self.btn_disasm_selected = QPushButton("Disasm selected symbol")
        self.btn_disasm_selected.clicked.connect(self._on_disasm_selected_symbol_clicked)
        util_row.addWidget(self.btn_text_range)
        util_row.addWidget(self.btn_disasm_selected)
        util_row.addStretch(1)
        auto_layout.addLayout(util_row)

        controls_layout.addWidget(auto_group)

        # Deep Analysis group (new) - AI-extension ready
        deep_group = QGroupBox("Deep Analysis (AI/Heuristics)")
        deep_layout = QVBoxLayout(deep_group)

        deep_btn_row = QHBoxLayout()
        self.btn_prologues = QPushButton("Identify Function Prologues")
        self.btn_prologues.clicked.connect(self._on_identify_function_prologues_clicked)

        self.btn_cfg = QPushButton("Generate Control Flow")
        self.btn_cfg.clicked.connect(self._on_generate_control_flow_clicked)

        self.btn_vuln = QPushButton("Heuristic Vulnerability Scan")
        self.btn_vuln.clicked.connect(self._on_heuristic_vuln_scan_clicked)

        deep_btn_row.addWidget(self.btn_prologues)
        deep_btn_row.addWidget(self.btn_cfg)
        deep_btn_row.addWidget(self.btn_vuln)
        deep_btn_row.addStretch(1)
        deep_layout.addLayout(deep_btn_row)

        deep_hint = QLabel(
            "These actions are placeholders. Implement logic in BinaryAnalysisService "
            "without changing UI wiring."
        )
        deep_hint.setWordWrap(True)
        deep_layout.addWidget(deep_hint)

        controls_layout.addWidget(deep_group)

        right_layout.addWidget(controls_scroll)

        # --- Output splitter: Code view (top) + System log (bottom)
        right_vertical_splitter = QSplitter(Qt.Vertical)

        self.code_view = QPlainTextEdit()
        self.code_view.setObjectName("logOutput")
        self.code_view.setReadOnly(True)
        font = QFont("Courier New")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        self.code_view.setFont(font)
        self.code_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.code_view.setPlaceholderText("Disassembly output will appear here...")
        self.code_view.copyAvailable.connect(self.analyze_selection_btn.setEnabled)
        self.highlighter = AsmHighlighter(self.code_view.document())
        right_vertical_splitter.addWidget(self.code_view)

        self.output_log = QTextEdit()
        self.output_log.setObjectName("logOutput")
        self.output_log.setReadOnly(True)
        self.output_log.setText("--- System Log ---\n")
        self.output_log.setMaximumHeight(180)
        right_vertical_splitter.addWidget(self.output_log)

        output_frame = QFrame()
        output_frame.setObjectName("logOutputContainer")
        output_frame_layout = QVBoxLayout(output_frame)
        output_frame_layout.setContentsMargins(6, 6, 6, 6)
        output_frame_layout.setSpacing(4)

        output_toolbar = QHBoxLayout()
        output_toolbar.setObjectName("logOutputToolbar")
        output_toolbar.setContentsMargins(4, 2, 4, 2)
        output_toolbar.addWidget(QLabel("Console Actions:"))
        output_toolbar.addStretch()

        self.btn_copy_console = QPushButton()
        self.btn_copy_console.setFixedSize(28, 28)
        self.btn_copy_console.setToolTip("Copy Console Output")
        self.btn_copy_console.clicked.connect(self._copy_console_output)
        output_toolbar.addWidget(self.btn_copy_console)

        self.btn_clear_console = QPushButton()
        self.btn_clear_console.setFixedSize(28, 28)
        self.btn_clear_console.setToolTip("Clear Console Output")
        self.btn_clear_console.clicked.connect(self._clear_console_output)
        output_toolbar.addWidget(self.btn_clear_console)

        output_frame_layout.addLayout(output_toolbar)
        output_frame_layout.addWidget(right_vertical_splitter, 1)
        right_layout.addWidget(output_frame, 1)
        self.apply_theme_icons()

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        main_layout.addWidget(splitter, 1)

    def _connect_service_signals(self) -> None:
        self.service.log_message.connect(self._log)
        self.service.error_message.connect(self._log_err)
        self.service.tools_detected.connect(self._on_tools_detected)
        self.service.symbols_loaded.connect(self._on_symbols_loaded)
        self.service.sections_loaded.connect(self._on_sections_loaded)
        self.service.disassembly_ready.connect(self._on_disassembly_ready)
        self.service.entrypoints_ready.connect(self._on_entrypoints_ready)

    # ---------------- UI utilities ----------------

    def _log(self, msg: str) -> None:
        self.output_log.append(msg)
        self.output_log.ensureCursorVisible()

    def _log_err(self, msg: str) -> None:
        self.output_log.append(f"<span style='color:#ff7070;'>{msg}</span>")
        self.output_log.ensureCursorVisible()

    def apply_theme_icons(self) -> None:
        self.btn_copy_console.setIcon(themed_icon("alt-clipboard.svg", 18))
        self.btn_copy_console.setIconSize(self.btn_copy_console.size() * 0.6)
        self.btn_clear_console.setIcon(themed_icon("alt-trash.svg", 18))
        self.btn_clear_console.setIconSize(self.btn_clear_console.size() * 0.6)

    def _copy_console_output(self) -> None:
        text = (
            "=== Disassembly ===\n"
            + self.code_view.toPlainText()
            + "\n\n=== System Log ===\n"
            + self.output_log.toPlainText()
        )
        QApplication.clipboard().setText(text)

    def _clear_console_output(self) -> None:
        self.code_view.clear()
        self.output_log.clear()
        self.output_log.setText("--- System Log ---\n")

    def _get_so_path(self) -> Optional[str]:
        so_file = self.file_path_edit.text().strip()
        if not so_file or not os.path.isfile(so_file):
            return None
        return so_file

    def _clear_symbols(self) -> None:
        self.symbols_list.clear()
        self._all_symbols = []

    # ---------------- UI event handlers ----------------

    def _select_so_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Shared Object File (.so)",
            "",
            "Shared Object Files (*.so);;All Files (*)",
        )
        if not file_path:
            return
        self.file_path_edit.setText(file_path)
        self._log(f"Selected file: {file_path}")
        self._text_range = None

    def _on_tools_detected(self, tools: List[ToolInfo]) -> None:
        summary = " | ".join([f"{t.name}={'OK' if t.found else 'MISSING'}" for t in tools])
        self.tools_status.setText("Tools: " + summary)

    def _on_load_symbols_clicked(self) -> None:
        so = self._get_so_path()
        if not so:
            self._log_err("ERROR: Select a valid .so first.")
            return
        self._clear_symbols()
        self.service.load_func_symbols(so)

    def _on_fill_text_range_clicked(self) -> None:
        so = self._get_so_path()
        if not so:
            self._log_err("ERROR: Select a valid .so first.")
            return
        self.service.load_sections(so)

    def _on_sections_loaded(self, sections: Dict[str, SectionInfo], text_range: Optional[Tuple[int, int]]) -> None:
        self._text_range = text_range
        if not text_range:
            self._log_err("Could not find .text in readelf -S output.")
            return
        start, end = text_range
        self.start_addr.setText(f"0x{start:08X}")
        self.stop_addr.setText(f"0x{end:08X}")
        self._log(f"[OK] .text range: 0x{start:08X} - 0x{end:08X}")

    def _on_symbols_loaded(self, symbols: List[Symbol]) -> None:
        self._all_symbols = symbols
        self._apply_symbol_filter(self.symbol_search.text().strip())

    def _filter_symbols(self, text: str) -> None:
        self._apply_symbol_filter(text.strip())

    def _apply_symbol_filter(self, filt: str) -> None:
        self.symbols_list.clear()
        if not self._all_symbols:
            return

        regex: Optional[re.Pattern[str]] = None
        if len(filt) >= 2 and filt.startswith("/") and filt.endswith("/"):
            try:
                regex = re.compile(filt[1:-1], re.IGNORECASE)
            except re.error as e:
                self._log_err(f"[FILTER] Bad regex: {e}")
                regex = None

        shown = 0
        for s in self._all_symbols:
            ok = True
            if filt:
                if regex:
                    ok = bool(regex.search(s.name))
                else:
                    ok = filt.lower() in s.name.lower()
            if not ok:
                continue

            item = QListWidgetItem(f"0x{s.addr:08X}  {s.name}")
            item.setData(Qt.UserRole, s)
            self.symbols_list.addItem(item)
            shown += 1

        if filt:
            self._log(f"[FILTER] Showing {shown}/{len(self._all_symbols)} symbol(s)")

    def _on_symbol_selected(self) -> None:
        item = self.symbols_list.currentItem()
        if not item:
            return
        sym = item.data(Qt.UserRole)
        if isinstance(sym, Symbol):
            self._log(f"[SELECT] 0x{sym.addr:08X} {sym.name}")

    def _prefill_disasm_from_item(self, item: QListWidgetItem) -> None:
        sym = item.data(Qt.UserRole)
        if not isinstance(sym, Symbol):
            return

        start = max(0, sym.addr - 0x40)
        stop = sym.addr + 0x120
        self.start_addr.setText(f"0x{start:08X}")
        self.stop_addr.setText(f"0x{stop:08X}")
        self._log(f"[PREFILL] start=0x{start:08X} stop=0x{stop:08X} (from 0x{sym.addr:08X})")

    def _on_disassemble_clicked(self) -> None:
        so = self._get_so_path()
        if not so:
            self._log_err("ERROR: Select a valid .so first.")
            return

        start_s = self.start_addr.text().strip()
        stop_s = self.stop_addr.text().strip()

        # Stop is optional: if omitted, disassemble a default window.
        default_window = 0x200
        try:
            start = int(start_s, 16)
        except Exception:
            self._log_err("ERROR: Start must be valid hex (e.g., 0x537cd4).")
            return

        if stop_s:
            try:
                stop = int(stop_s, 16)
            except Exception:
                self._log_err("ERROR: Stop must be valid hex (e.g., 0x537ef0).")
                return
        else:
            stop = start + default_window
            self.stop_addr.setText(f"0x{stop:08X}")


        if self._text_range:
            ts, te = self._text_range
            if not (ts <= start < te or ts <= (stop - 1) < te):
                self._log_err(f"[WARN] Range not in .text (0x{ts:08X}-0x{te:08X}).")

        tool_choice = self.tool_selector.currentText()
        force_thumb = self.thumb_checkbox.isChecked()

        # Preview is best-effort (string-based); actual command is built in the service.
        self.disasm_cmd_preview.setText(
            f"{tool_choice} --start-address=0x{start:08X} --stop-address=0x{stop:08X} <so>"
        )

        self.code_view.clear()
        self.code_view.setPlainText("Disassembling... please wait.")
        self.service.disassemble_range(
            so,
            start=start,
            stop=stop,
            tool_choice=tool_choice,
            force_thumb=force_thumb,
        )

    def _on_disassembly_ready(self, raw_text: str, instructions: List[Instruction]) -> None:
        self.code_view.setPlainText(raw_text)
        # Note: `instructions` is not displayed directly, but is available for future AI tooling.
        self._log(f"[OK] Disassembly loaded ({len(instructions)} parsed lines).")

    def _on_disasm_selected_symbol_clicked(self) -> None:
        item = self.symbols_list.currentItem()
        if not item:
            self._log_err("Select a symbol first.")
            return
        sym = item.data(Qt.UserRole)
        if not isinstance(sym, Symbol):
            self._log_err("Selected item has no usable symbol data.")
            return

        start = max(0, sym.addr - 0x40)
        stop = sym.addr + 0x120
        self.start_addr.setText(f"0x{start:08X}")
        self.stop_addr.setText(f"0x{stop:08X}")
        self._on_disassemble_clicked()

    def _on_ragen_clicked(self) -> None:
        so = self._get_so_path()
        if not so:
            self._log_err("ERROR: Select a valid .so first.")
            return
        self.service.run_ragen_analysis(so)

    def _on_entrypoints_clicked(self) -> None:
        so = self._get_so_path()
        if not so:
            self._log_err("ERROR: Select a valid .so first.")
            return
        self.service.find_loader_entrypoints(so)

    def _on_entrypoints_ready(self, report: EntrypointReport) -> None:
        self._log("\n== Loader entrypoint candidates ==")
        for line in report.lines:
            self._log(line)

        self.symbols_list.clear()
        for c in report.candidates:
            src = c.source or "unknown"
            item = QListWidgetItem(f"0x{c.addr:08X}  {c.name}   [{src}]")
            item.setData(Qt.UserRole, c)
            self.symbols_list.addItem(item)

        if report.candidates:
            self._log(f"[INFO] Added {len(report.candidates)} candidate(s) to the list.")

    # ---------------- Deep analysis UI actions (stubs calling service) ----------------

    def _on_analyze_selection_clicked(self) -> None:
        cursor = self.code_view.textCursor()
        selection = cursor.selectedText()  # note: Qt uses U+2029 for line breaks
        selection = selection.replace("\u2029", "\n")
        self.service.deep_analyze_selection(selection)

    def _on_identify_function_prologues_clicked(self) -> None:
        self.service.identify_function_prologues()

    def _on_generate_control_flow_clicked(self) -> None:
        self.service.generate_control_flow()

    def _on_heuristic_vuln_scan_clicked(self) -> None:
        self.service.heuristic_vulnerability_scan()

    # ---------------- Cleanup ----------------

    def cleanup(self) -> None:
        """Stop running processes when the tab is closed/destroyed."""
        self.service.stop()
