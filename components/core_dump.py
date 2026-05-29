# core_dump.py
# Fully integrated Vita Crash Dump Analyzer for Python 3 / PySide6
# Includes colorized output, save functionality, and FTP crash fetching.

import os
import sys
import struct
import subprocess
import gzip
import shutil
import ftplib
import threading
import time
from datetime import datetime
from collections import defaultdict
import traceback
import re

# Importaciones de PySide6
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QTextEdit, QFileDialog, QMessageBox, QInputDialog,
                               QApplication, QFrame) # Added QApplication
from PySide6.QtCore import QThread, Signal, Slot, Qt, QDir
from PySide6.QtGui import QTextCursor
from components.icon_utils import themed_icon

# ==========================================
# COLORS & UTILITIES
# ==========================================

# --- COLOR DEFINITIONS (HTML HEX CODES) ---
COLOR_RED = "#F44747"
COLOR_YELLOW = "#FFD700"
COLOR_GREY = "#D4D4D4"
COLOR_BLUE = "#569CD6"
COLOR_TEAL = "#00FFFF"
COLOR_ORANGE = "#FF8C00"
COLOR_THREAD_NAME = "#4EC9B0"
COLOR_SYM_NAME = "#85C664"
COLOR_ADDR_BASE = "#FFFFFF"
COLOR_BTN_BG = "#2d2d2d" # Added from build.py

_log_callback = None
_indent_level = 0

def set_log_callback(cb):
    global _log_callback
    _log_callback = cb

def set_indent_level(val):
    global _indent_level
    _indent_level = val

def iprint(*args, color=COLOR_GREY, **kwargs):
    """Indent-aware print to log callback, supporting HTML coloring, ensuring line breaks."""
    global _log_callback

    prefix = ("&nbsp;&nbsp;&nbsp;&nbsp;" * _indent_level)

    text = " ".join(str(a) for a in args)

    if not text.strip() and not _indent_level:
        if _log_callback:
            _log_callback("<br>", is_html=True)
        return

    out = text
    html_out = ""

    out_lines = out.split('\n')

    for line in out_lines:
        line_stripped = line.strip()
        line_color = color

        if line_stripped.startswith('!!!') and line_stripped.endswith('!!!'):
            line_color = COLOR_RED

        if line or (len(out_lines) > 1 and not line.strip()):
            if '<span' in line and color != COLOR_GREY:
                html_out += prefix + line + '<br>'
            else:
                html_out += f'<span style="color:{line_color};">{prefix}{line}</span><br>'
        else:
            pass

    if _log_callback:
        if not html_out.endswith('<br>'):
            html_out += '<br>'

        try:
            _log_callback(html_out, is_html=True)
        except Exception:
            print(out, end="\n")
    else:
        print(out, end="\n")


class IndentManager:
    """Context manager for indentation."""
    def __enter__(self):
        global _indent_level
        _indent_level += 1

    def __exit__(self, exc_type, exc, tb):
        global _indent_level
        _indent_level = max(0, _indent_level - 1)

def u32(data, offset=0):
    """Read unsigned 32-bit integer from bytes."""
    try:
        return struct.unpack_from("<I", data, offset)[0]
    except struct.error:
        return 0

def u16(data, offset=0):
    """Read unsigned 16-bit integer from bytes."""
    try:
        return struct.unpack_from("<H", data, offset)[0]
    except struct.error:
        return 0

def c_str(data, offset=0):
    """Read null-terminated C-string from bytes."""
    if offset >= len(data):
        return ""
    sub = data[offset:]
    try:
        idx = sub.index(0)
        return sub[:idx].decode('utf-8', errors='ignore')
    except ValueError:
        return sub.decode('utf-8', errors='ignore')

# ==========================================
# SETTINGS MOCK (Adjusted for separate IP/Port)
# ==========================================

try:
    from utils import choose_preferred_elf, settings
except ImportError:
    class _Settings:
        def __init__(self):
            # Adjusted mock to use separate IP and Port, mirroring settings.json
            self._d = {"sdk_path": os.environ.get("VITA_SDK_PATH", ""),
                       "dump_folder": os.getcwd(),
                       "vita_ip": "192.168.1.100",  # Mocked IP
                       "vita_port": 1337,           # Mocked Port
                       "last_build_dir": os.getcwd()}

        def get(self, key, default=None):
            return self._d.get(key, default)

        def set(self, key, value):
            self._d[key] = value
    settings = _Settings()

    def choose_preferred_elf(build_dir, fallback_dirs):
        candidates = []
        for directory in [build_dir, *(fallback_dirs or [])]:
            if not directory or not os.path.isdir(directory):
                continue
            for filename in os.listdir(directory):
                if not filename.lower().endswith(".elf"):
                    continue
                full_path = os.path.join(directory, filename)
                try:
                    with open(full_path, "rb") as handle:
                        if handle.read(4) != b"\x7fELF":
                            continue
                    candidates.append(full_path)
                except Exception:
                    continue
        if not candidates:
            return None
        return max(candidates, key=os.path.getmtime)


# ==========================================
# ELF PARSING (pyelftools with Fallback)
# (Classes are kept here for full file)
# ==========================================
try:
    from elftools.elf.elffile import ELFFile
    HAS_PYELFTOOLS = True
except ImportError:
    HAS_PYELFTOOLS = False
    ELFFile = None

class _SegmentHeader:
    def __init__(self, p_type, p_offset, p_vaddr, p_filesz, p_flags):
        self.p_type = p_type
        self.p_offset = p_offset
        self.p_vaddr = p_vaddr
        self.p_filesz = p_filesz
        self.p_flags = p_flags

class SimpleSegment:
    def __init__(self, header, data_bytes):
        self.header = header
        self._data = data_bytes

    def data(self):
        return self._data

    def iter_notes(self):
        data = self._data
        off = 0
        notes = []
        while off + 12 <= len(data):
            namesz, descsz, ntype = struct.unpack_from("<III", data, off)
            off += 12

            name_data = data[off:off + namesz]
            off += ((namesz + 3) // 4) * 4

            desc_data = data[off:off + descsz]
            off += ((descsz + 3) // 4) * 4

            try:
                name_str = name_data.split(b'\x00', 1)[0].decode('utf-8', errors='ignore')
            except Exception:
                name_str = ""

            notes.append({"n_name": name_str, "n_desc": desc_data, "n_type": ntype})
        return notes

class SimpleELFFile:
    def __init__(self, fileobj):
        self._f = fileobj
        self._parse_header()

    def _parse_header(self):
        self._f.seek(0)
        e_ident = self._f.read(16)
        if len(e_ident) < 16 or e_ident[0:4] != b'\x7fELF':
            raise ValueError("Not an ELF file")

        self._f.seek(28)
        self.e_phoff = struct.unpack("<I", self._f.read(4))[0]
        self._f.seek(42)
        self.e_phentsize = struct.unpack("<H", self._f.read(2))[0]
        self.e_phnum = struct.unpack("<H", self._f.read(2))[0]

    def iter_segments(self):
        segs = []
        self._f.seek(self.e_phoff)
        for _ in range(self.e_phnum):
            ph_data = self._f.read(self.e_phentsize)
            if len(ph_data) < 32:
                break

            vals = struct.unpack_from("<IIIIIIII", ph_data, 0)
            p_type, p_offset, p_vaddr, _, p_filesz, _, p_flags, _ = vals

            header = _SegmentHeader(p_type, p_offset, p_vaddr, p_filesz, p_flags)

            cur = self._f.tell()
            self._f.seek(p_offset)
            data = self._f.read(p_filesz)
            self._f.seek(cur)

            segs.append(SimpleSegment(header, data))
        return segs

def GetELFParser(fileobj):
    if HAS_PYELFTOOLS:
        return ELFFile(fileobj)
    else:
        return SimpleELFFile(fileobj)

class VitaThread:
    def __init__(self, data):
        self.uid = u32(data, 4)
        self.name = c_str(data, 8)
        self.stop_reason = u32(data, 0x74) if len(data) >= 0x78 else 0
        self.status = u16(data, 0x30) if len(data) >= 0x32 else 0
        self.pc = u32(data, 0x9C) if len(data) >= 0xA0 else 0
        self.regs = None

class VitaModuleSegment:
    def __init__(self, data, num):
        self.num = num
        self.attr = u32(data, 4)
        self.start = u32(data, 8)
        self.size = u32(data, 12)
        self.align = u32(data, 16)

class VitaModule:
    def __init__(self, data):
        self.uid = u32(data, 4)
        self.num_segs = u32(data, 0x4C) if len(data) >= 0x50 else 0
        self.name = c_str(data, 0x24) if len(data) >= 0x25 else ""
        self.segments = []

    def parse_segs(self, data):
        for x in range(self.num_segs):
            sz = 0x14
            self.segments.append(VitaModuleSegment(data[sz*x:sz*(x+1)], x + 1))

    def parse_foot(self, data):
        pass

class VitaRegs:
    def __init__(self, data):
        self.tid = u32(data, 4)
        self.gpr = []
        for x in range(16):
            val = u32(data, 8 + 4 * x) if len(data) >= 8 + 4 * (x+1) else 0
            self.gpr.append(val)

class VitaAddress:
    def __init__(self, symbol, vaddr, module=None, segment=None, offset=None):
        self.__symbol = symbol
        self.__module = module
        self.__segment = segment
        self.__offset = offset
        self.__vaddr = vaddr

    def is_located(self):
        return self.__module and self.__segment and self.__offset is not None

    def print_disas_if_available(self, elf_parser):
        if not elf_parser:
            return

        addr_to_display = self.__vaddr
        state = "ARM"
        if addr_to_display & 1:
            state = "Thumb"
            addr_to_display &= ~1

        if self.is_located():
            iprint()
            iprint(f"DISASSEMBLY AROUND {self.__symbol}: 0x{addr_to_display:x} ({state}):", color=COLOR_YELLOW)
            with IndentManager():
                try:
                    elf_parser.disas_around_addr(self.__offset, self.__vaddr)
                except Exception as e:
                    iprint(f"[Disassembly failed: {str(e)}]", color=COLOR_GREY)
                    iprint("[Ensure Vita SDK is in PATH or set in settings]", color=COLOR_GREY)

    def to_string(self, elf_parser=None, include_symbol=True):
        vaddr_color = COLOR_ADDR_BASE
        output = ""

        if include_symbol:
            output = f'<span style="color:{COLOR_SYM_NAME};">{self.__symbol}: </span>'

        output += f'<span style="color:{vaddr_color};">0x{self.__vaddr:x}</span>'

        if self.is_located():
            output += f'<span style="color:{COLOR_SYM_NAME};"> ({self.__module.name}@{self.__segment.num} + </span>'
            output += f'<span style="color:{vaddr_color};">0x{self.__offset:x}</span>'

            line_info = ""
            if elf_parser and self.__module.name.endswith(".elf") and self.__segment.num == 1:
                try:
                    line_info = elf_parser.addr2line(self.__offset)
                    if line_info:
                        line_info = f'<span style="color:{COLOR_SYM_NAME};"> => {line_info}</span>'
                except Exception:
                    pass

            output += f'<span style="color:{COLOR_SYM_NAME};">)</span>{line_info}'

        return output

class CoreSegment:
    def __init__(self, vaddr, data):
        self.vaddr = vaddr
        self.data = data
        self.size = len(data)

class CoreParser:
    def __init__(self, filename):
        f = open(filename, "rb")
        header = f.read(2)
        f.seek(0)

        if header == b'\x1f\x8b':
            f.close()
            self.file_handle = gzip.open(filename, "rb")
        else:
            self.file_handle = f

        self.elf = GetELFParser(self.file_handle)

        self.init_notes()
        self.parse_modules()
        self.parse_threads()
        self.parse_thread_regs()

        self.file_handle.close()

    def init_notes(self):
        self.notes = dict()
        self.segments = []

        for seg in self.elf.iter_segments():
            p_type = seg.header.p_type

            is_note = (p_type == 4) or (p_type == "PT_NOTE")
            is_load = (p_type == 1) or (p_type == "PT_LOAD")

            if is_note:
                for note in seg.iter_notes():
                    self.notes[note["n_name"]] = note["n_desc"]
            elif is_load:
                self.segments.append(CoreSegment(seg.header.p_vaddr, seg.data()))

    def parse_modules(self):
        self.modules = []
        if "MODULE_INFO" not in self.notes:
            return

        data = self.notes["MODULE_INFO"]
        if isinstance(data, str):
            data = data.encode('latin-1')

        if len(data) < 8: return

        num = u32(data, 4)
        off = 8
        for _ in range(num):
            sz = 0x50
            if off + sz > len(data): break
            module = VitaModule(data[off:off+sz])
            off += sz

            seg_sz = module.num_segs * 0x14
            if off + seg_sz <= len(data):
                module.parse_segs(data[off:off+seg_sz])
                off += seg_sz

            sz = 0x10
            if off + sz <= len(data):
                module.parse_foot(data[off:off+sz])
                off += sz

            self.modules.append(module)

    def parse_threads(self):
        self.threads = []
        self.tid_to_thread = dict()
        if "THREAD_INFO" not in self.notes:
            return

        data = self.notes["THREAD_INFO"]
        if len(data) < 8: return

        num = u32(data, 4)
        off = 8
        for _ in range(num):
            if off + 4 > len(data): break
            sz = u32(data, off)
            if off + sz > len(data): break

            thread = VitaThread(data[off:off+sz])
            self.threads.append(thread)
            self.tid_to_thread[thread.uid] = thread
            off += sz

    def parse_thread_regs(self):
        if "THREAD_REG_INFO" not in self.notes:
            return

        data = self.notes["THREAD_REG_INFO"]
        if len(data) < 8: return

        num = u32(data, 4)
        off = 8
        for _ in range(num):
            if off + 4 > len(data): break
            sz = u32(data, off)
            if off + sz > len(data): break

            regs = VitaRegs(data[off:off+sz])
            if regs.tid in self.tid_to_thread:
                self.tid_to_thread[regs.tid].regs = regs
            off += sz

    def get_address_notation(self, symbol, vaddr):
        for module in self.modules:
            for segment in module.segments:
                if segment.start <= vaddr < (segment.start + segment.size):
                    return VitaAddress(symbol, vaddr, module, segment, vaddr - segment.start)
        return VitaAddress(symbol, vaddr)

    def read_vaddr(self, addr, size):
        for segment in self.segments:
            if segment.vaddr <= addr < (segment.vaddr + segment.size):
                local_addr = addr - segment.vaddr
                return segment.data[local_addr:local_addr+size]
        return None

# ELF PARSER (ElfParserObj) remains here...

class ElfParserObj:
    def __init__(self, filename, sdk_path=None):
        self.filename = filename
        self.sdk_path = sdk_path
        self.f = open(filename, "rb")
        self.elf = GetELFParser(self.f)
        self.rx_vaddr = -1
        self.parse_segments()
        self.a2l = None

    def close(self):
        if self.f:
            self.f.close()
        if self.a2l:
            try:
                self.a2l.kill()
            except:
                pass

    def get_tool_command(self, tool):
        # FIX: Check /bin subfolder and handle Windows extension, then PATH
        tool_name = tool
        if os.name == 'nt' and not tool_name.endswith('.exe'):
            tool_name += '.exe'

        if self.sdk_path and os.path.isdir(self.sdk_path):
            # Direct SDK path
            p1 = os.path.join(self.sdk_path, tool_name)
            if os.path.exists(p1):
                return p1
            # SDK/bin
            p2 = os.path.join(self.sdk_path, "bin", tool_name)
            if os.path.exists(p2):
                return p2

        # System PATH
        import shutil as _shutil
        path_tool = _shutil.which(tool)
        if path_tool:
            return path_tool

        # Fallback to the name
        return tool_name

    def parse_segments(self):
        for seg in self.elf.iter_segments():
            p_flags = getattr(seg.header, 'p_flags', None)
            if p_flags is None and hasattr(seg, '__getitem__'):
                p_flags = seg['p_flags']

            p_vaddr = getattr(seg.header, 'p_vaddr', None)
            if p_vaddr is None and hasattr(seg, '__getitem__'):
                p_vaddr = seg['p_vaddr']

            # 5 is PT_LOAD with PF_R | PF_X (Read-Execute)
            if str(p_flags) == "5":
                self.rx_vaddr = p_vaddr

    def disas_around_addr(self, offset, vaddr):
        # --- helpers ---
        def html_escape(s: str) -> str:
            return (
                s.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )

        # r0..r15, sp, lr, pc
        reg_pattern = re.compile(r"\b(r1[0-5]|r[0-9]|sp|lr|pc)\b", re.IGNORECASE)

        def colorize_registers(text: str) -> str:
            """Escape HTML and then wrap register tokens in COLOR_ORANGE."""
            escaped = html_escape(text)

            def repl(m):
                reg = m.group(0)
                return f'<span style="color:{COLOR_ORANGE};">{reg}</span>'

            return reg_pattern.sub(repl, escaped)

        # --- compute absolute address & Thumb state ---
        if self.rx_vaddr != -1:
            abs_addr = offset + self.rx_vaddr
        else:
            abs_addr = offset

        thumb = False
        if vaddr & 1:
            thumb = True
            abs_addr &= ~1

        start = abs_addr - 0x10
        end = abs_addr + 0x10

        cmd = self.get_tool_command("arm-vita-eabi-objdump")
        args = [
            cmd, "-d", "-S",
            f"--start-address=0x{start:x}",
            f"--stop-address=0x{end:x}",
            self.filename,
        ]

        if thumb:
            args += ["-Mforce-thumb"]

        try:
            proc = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            # Show objdump warnings (if any)
            stderr_text = proc.stderr.decode("utf-8", errors="replace")
            if stderr_text.strip():
                for line in stderr_text.splitlines():
                    if line.strip():
                        iprint(line, color=COLOR_YELLOW)

            text_output = proc.stdout.decode("utf-8", errors="replace")
            lines = text_output.splitlines()

            keep = False
            final_lines = []  # list of (raw_line, is_target)

            for line in lines:
                if "Disassembly of section" in line:
                    keep = True
                    continue
                if not keep:
                    continue

                is_target = f"{abs_addr:x}:" in line
                final_lines.append((line, is_target))

            if final_lines:
                # addr:  bytes  instruction
                dis_line_re = re.compile(
                    r"^\s*([0-9a-fA-F]+):\s+([0-9a-fA-F ]+)\s*(.*)$"
                )

                for raw_line, is_target in final_lines:
                    line = raw_line.rstrip("\n")

                    # Try to parse a normal disassembly line
                    m = dis_line_re.match(line)
                    if not m:
                        # Labels / source lines / empty
                        text = html_escape(line)

                        if not text.strip():
                            iprint("&nbsp;", color=COLOR_ADDR_BASE)
                            continue

                        if is_target:
                            # Entire label/source line in RED
                            html_line = (
                                f'<span style="color:{COLOR_RED}; font-weight:bold;">'
                                f'!!! &emsp;{text} !!!'
                                f'</span>'
                            )
                        else:
                            html_line = f'<span style="color:{COLOR_GREY};">{text}</span>'

                        # Indent inside the disassembly block
                        html_line = "&nbsp;&nbsp;" + html_line
                        iprint(html_line, color=COLOR_ADDR_BASE)
                        continue

                    # Parsed instruction parts
                    addr_str, bytes_str, asm_part = m.groups()
                    addr_str = addr_str.strip()
                    bytes_str = bytes_str.strip()
                    asm_part = asm_part.strip()

                    if is_target:
                        # ============================
                        # CRASHING LINE: FULL RED
                        # ============================
                        # We drop the address (like your example) and show:
                        # !!!   bytes   instr   !!!
                        # all in red.
                        target_text = ""

                        if bytes_str:
                            target_text += html_escape(bytes_str)
                        if asm_part:
                            # little gap between bytes and mnemonic
                            target_text += "&emsp;&emsp;" + html_escape(asm_part)

                        html_line = (
                            f'<span style="color:{COLOR_RED}; font-weight:bold;">'
                            f'!!! &emsp;{target_text} !!!'
                            f'</span>'
                        )
                        html_line = "&nbsp;&nbsp;" + html_line
                        iprint(html_line, color=COLOR_ADDR_BASE)
                        continue

                    # ============================
                    # NORMAL INSTRUCTION LINES
                    # ============================

                    # Address (left, not indented)
                    addr_html = (
                        f'<span style="color:{COLOR_ADDR_BASE};">'
                        f'{html_escape(addr_str)}:</span>'
                    )

                    # Opcode bytes
                    bytes_html = ""
                    if bytes_str:
                        bytes_html = (
                            f'<span style="color:{COLOR_TEAL};">'
                            f'{html_escape(bytes_str)}</span>'
                        )

                    # Instruction (mnemonic + operands), with registers colored
                    asm_html = ""
                    if asm_part:
                        parts = asm_part.split(None, 1)
                        mnemonic = parts[0]
                        rest = parts[1] if len(parts) > 1 else ""

                        mnemonic_html = (
                            f'<span style="color:{COLOR_BLUE};">'
                            f'{html_escape(mnemonic)}</span>'
                        )

                        if rest:
                            rest_html = colorize_registers(rest)
                            asm_html = f"{mnemonic_html} {rest_html}"
                        else:
                            asm_html = mnemonic_html

                    # Layout: addr :  <TAB> bytes  <TAB>  instr
                    # Use &emsp; to simulate the indentation in your example.
                    core_html = addr_html
                    if bytes_html:
                        core_html += "&emsp;" + bytes_html
                    if asm_html:
                        # EXTRA INDENT for instruction part
                        core_html += "&emsp;&emsp;" + asm_html

                    # Small left indent inside the disassembly block
                    html_line = "&nbsp;&nbsp;" + core_html

                    iprint(html_line, color=COLOR_ADDR_BASE)
            else:
                iprint("(No disassembly output found)", color=COLOR_GREY)

        except FileNotFoundError:
            raise FileNotFoundError(f"Tool not found: {cmd}")
        except Exception:
            iprint("Objdump error", color=COLOR_GREY)


    def addr2line(self, offset):
        if not self.a2l:
            cmd = self.get_tool_command("arm-vita-eabi-addr2line")
            try:
                self.a2l = subprocess.Popen(
                    [cmd, "-e", self.filename, "-f", "-p", "-C"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                )
            except FileNotFoundError:
                # FIX: return empty string instead of throwing hard
                return ""

        abs_addr = offset + self.rx_vaddr if self.rx_vaddr != -1 else offset

        msg = f"{abs_addr:x}\n".encode('utf-8')
        try:
            self.a2l.stdin.write(msg)
            self.a2l.stdin.flush()
            out = self.a2l.stdout.readline()
            return out.strip().decode('utf-8')
        except (IOError, BrokenPipeError):
            self.a2l = None
            return ""

# ==========================================
# WORKERS / THREADS
# ==========================================

class DumpParserThread(QThread):
    output_signal = Signal(str, bool)
    finished_signal = Signal()
    progress_signal = Signal(str)

    def __init__(self, core_file, elf_file, sdk_path=None):
        super().__init__()
        self.core_file = core_file
        self.elf_file = elf_file
        self.sdk_path = sdk_path
        self.elf_parser = None

    def emit_log(self, text, is_html=False):
        self.output_signal.emit(str(text), is_html)

    def run(self):
        set_log_callback(self.emit_log)
        set_indent_level(0)

        self.progress_signal.emit("Parsing...")
        try:
            iprint("--- Starting Analysis ---", color=COLOR_GREY)
            iprint(f"Core: {self.core_file}", color=COLOR_GREY)
            iprint(f"ELF: {self.elf_file}", color=COLOR_GREY)
            iprint(f"SDK: {self.sdk_path or 'System PATH'}")
            iprint()

            core = CoreParser(self.core_file)
            self.elf_parser = ElfParserObj(self.elf_file, self.sdk_path)

            str_stop_reason = defaultdict(str, {
                0: "No reason",
                0x30002: "Undefined instruction",
                0x30003: "Prefetch abort",
                0x30004: "Data abort",
                0x60080: "Division by zero",
            })
            str_status = defaultdict(lambda: "Unknown", {
                1: "Running",
                8: "Waiting",
                16: "Not started"
            })
            reg_names = {13: "SP", 14: "LR", 15: "PC"}

            iprint("=== THREADS ===", color=COLOR_TEAL)
            crashed = []

            with IndentManager():
                for thread in core.threads:
                    if thread.stop_reason != 0:
                        crashed.append(thread)

                    iprint(thread.name, color=COLOR_THREAD_NAME)

                    with IndentManager():
                        iprint(f"ID: <span style=\"color:{COLOR_ADDR_BASE};\">0x{thread.uid:x}</span>", color=COLOR_YELLOW)

                        reason_str = str_stop_reason[thread.stop_reason]
                        reason_color = COLOR_YELLOW
                        if "abort" in reason_str or "instruction" in reason_str:
                            reason_color = COLOR_RED

                        html_line = f'<span style="color:{COLOR_YELLOW};">Stop reason: </span>'
                        html_line += f'<span style="color:{COLOR_ADDR_BASE};">0x{thread.stop_reason:x} (</span>'
                        html_line += f'<span style="color:{reason_color};">{reason_str}</span>'
                        html_line += f'<span style="color:{COLOR_ADDR_BASE};">)</span>'
                        iprint(html_line, color=COLOR_YELLOW)

                        status_str = str_status[thread.status]
                        html_line = f'<span style="color:{COLOR_YELLOW};">Status: </span>'
                        html_line += f'<span style="color:{COLOR_ADDR_BASE};">0x{thread.status:x} ({status_str})</span>'
                        iprint(html_line, color=COLOR_YELLOW)

                        pc = core.get_address_notation("PC", thread.pc)
                        lr = core.get_address_notation("LR", thread.regs.gpr[14] if thread.regs else 0)

                        iprint(pc.to_string(self.elf_parser), color=COLOR_SYM_NAME)

                        if lr.to_string(self.elf_parser) != pc.to_string(self.elf_parser):
                            iprint(lr.to_string(self.elf_parser), color=COLOR_SYM_NAME)

            iprint()

            for thread in crashed:
                reason = str_stop_reason[thread.stop_reason]
                reason_color = COLOR_RED

                html_line = f'<span style="color:{COLOR_GREY};">=== THREAD "{thread.name}" </span>'
                html_line += f'<span style="color:{COLOR_ADDR_BASE};"><0x{thread.uid:x}></span>'
                html_line += f'<span style="color:{COLOR_GREY};"> CRASHED (</span>'
                html_line += f'<span style="color:{reason_color};">{reason}</span>'
                html_line += f'<span style="color:{COLOR_GREY};">) ===</span>'
                iprint(html_line, color=COLOR_GREY)

                pc = core.get_address_notation('PC', thread.regs.gpr[15] if thread.regs else thread.pc)
                lr = core.get_address_notation('LR', thread.regs.gpr[14] if thread.regs else 0)

                # Print PC disassembly
                pc.print_disas_if_available(self.elf_parser)

                # FIX: Also print LR disassembly (when different)
                if lr.to_string() != pc.to_string():
                    lr.print_disas_if_available(self.elf_parser)

                iprint("\nREGISTERS:", color=COLOR_TEAL)
                with IndentManager():
                    if thread.regs:
                        for x in range(14):
                            reg = reg_names.get(x, f"R{x}")
                            html_line = f'<span style="color:{COLOR_ORANGE};">{reg}: </span>'
                            html_line += f'<span style="color:{COLOR_ADDR_BASE};">0x{thread.regs.gpr[x]:x}</span>'
                            iprint(html_line, color=COLOR_ORANGE)

                        iprint(pc.to_string(self.elf_parser), color=COLOR_SYM_NAME)
                        iprint(lr.to_string(self.elf_parser), color=COLOR_SYM_NAME)
                    else:
                        iprint("No register info available.", color=COLOR_GREY)

                iprint("\nSTACK CONTENTS AROUND SP:", color=COLOR_TEAL)
                with IndentManager():
                    if thread.regs:
                        sp = thread.regs.gpr[13]
                        stack_range = 24
                        for x in range(-16, stack_range):
                            addr = 4 * x + sp
                            data = core.read_vaddr(addr, 4)
                            if data:
                                val = u32(data, 0)
                                prefix = "          "

                                if addr == sp:
                                    prefix = "SP => "

                                data_notation = core.get_address_notation("", val)

                                html_line = f'<span style="color:{COLOR_SYM_NAME};">{prefix}</span>'
                                html_line += f'<span style="color:{COLOR_ADDR_BASE};">0x{addr:x}: </span>'
                                html_line += data_notation.to_string(self.elf_parser, include_symbol=False)

                                iprint(html_line, color=COLOR_SYM_NAME)
                    else:
                        iprint("No stack info available.", color=COLOR_GREY)

        except Exception as e:
            self.emit_log(f'\n<span style="color:{COLOR_RED};">CRITICAL ERROR DURING ANALYSIS:</span><br>', is_html=True)
            self.emit_log(f'<span style="color:{COLOR_GREY};">{str(e)}\n{traceback.format_exc()}</span>', is_html=True)
            self.progress_signal.emit("Error")
        finally:
            if self.elf_parser:
                self.elf_parser.close()

        self.emit_log(f'<br><span style="color:{COLOR_GREY};">--- Analysis Finished ---</span><br>', is_html=True)
        self.finished_signal.emit()

# --- NEW: CrashFetchThread (FIXED + SEARCH IN ux0:/data/) ---
class CrashFetchThread(QThread):
    progress_signal = Signal(str, bool)  # Text, is_html
    error_signal = Signal(str)
    fetched_files_signal = Signal(str, str)  # elf_path, core_path

    # __init__ adjusted to take separate IP and Port
    def __init__(self, vita_ip, vita_port, build_dir, parent=None):
        super().__init__(parent)
        self.vita_ip = vita_ip
        self.vita_port = vita_port
        self.build_dir = build_dir
        self.temp_core_path = None

    def run(self):
        # 1. Get IP and Port from instance variables
        ip = self.vita_ip
        port = self.vita_port

        if not ip or not port:
            self.error_signal.emit("Vita IP or Port not configured.")
            return

        # Log now uses the correct port from settings
        self.progress_signal.emit(f"Connecting to <b>{ip}:{port}</b>...", True)

        # 2. Connect to FTP
        ftp = None
        try:
            ftp = ftplib.FTP()
            # Explicitly use the configured IP and Port
            ftp.connect(ip, int(port), timeout=10)
            ftp.login()

            # FIX: Changed directory to ux0:/data/
            search_dir = "ux0:/data/"
            self.progress_signal.emit(f"Searching in {search_dir}...", False)
            ftp.cwd(search_dir)

            lines = []
            ftp.retrlines("LIST", lines.append)

            candidates = []
            for line in lines:
                parts = line.split()
                if len(parts) < 4:
                    continue

                # robust filename (handles spaces)
                filename = line.split(maxsplit=8)[-1]

                if filename.endswith(".psp2dmp"):
                    timestamp = 0
                    try:
                        # try parse "Mon DD HH:MM" (assume current year) OR "Mon DD YYYY"
                        if ":" in parts[7]:
                            date_str = f"{parts[5]} {parts[6]} {parts[7]} {datetime.now().year}"
                            timestamp = datetime.strptime(date_str, "%b %d %H:%M %Y").timestamp()
                        else:
                            date_str = f"{parts[5]} {parts[6]} {parts[7]}"
                            timestamp = datetime.strptime(date_str, "%b %d %Y").timestamp()
                    except Exception:
                        # fall back to 0; list order will decide
                        pass

                    candidates.append((timestamp, filename))

            if not candidates:
                self.error_signal.emit(f"No .psp2dmp files found in {search_dir}.")
                return

            # newest first
            candidates.sort(key=lambda x: x[0], reverse=True)
            latest_file = candidates[0][1]

            self.progress_signal.emit(f"Found crash dump: <b>{latest_file}</b>. Downloading...", True)

            # 4. Download the latest crash dump to a temporary location
            temp_dir = QDir.tempPath()
            self.temp_core_path = os.path.join(temp_dir, latest_file)

            with open(self.temp_core_path, 'wb') as local_file:
                ftp.retrbinary(f'RETR {latest_file}', local_file.write)

            self.progress_signal.emit("Download complete.", False)

            # 5. Locate the freshest valid ELF from the build directory first,
            # then fall back to the app/parse-core directory if needed.
            build_dir = self.build_dir
            fallback_dir = settings.get("dump_folder", "")

            if build_dir and not os.path.isdir(build_dir):
                self.progress_signal.emit(
                    f"Configured build directory unavailable: <b>{build_dir}</b>.",
                    True,
                )
            if fallback_dir and not os.path.isdir(fallback_dir):
                self.progress_signal.emit(
                    f"Fallback ELF directory unavailable: <b>{fallback_dir}</b>.",
                    True,
                )

            preferred_elf = choose_preferred_elf(build_dir, [fallback_dir])
            if preferred_elf is None:
                self.error_signal.emit(
                    "No valid .elf files found in the build directory or fallback project directory."
                )
                return

            latest_elf_path = str(preferred_elf)
            self.progress_signal.emit(
                "Using ELF: "
                f"<b>{os.path.basename(latest_elf_path)}</b> "
                f"from <b>{os.path.dirname(latest_elf_path)}</b>.",
                True,
            )

            # 6. Signal the main thread to start parsing
            self.fetched_files_signal.emit(latest_elf_path, self.temp_core_path)

        except ftplib.all_errors as e:
            self.error_signal.emit(f"FTP Error: {e}")
        except Exception as e:
            self.error_signal.emit(f"Fetch Error: {str(e)}")
        finally:
            if ftp:
                try:
                    ftp.quit()
                except:
                    pass
            self.progress_signal.emit("Thread finished.", False)
# --- End CrashFetchThread ---


class CoreDumpTab(QWidget):
    def __init__(self, ftp_worker_reference=None):
        super().__init__()
        self.selected_elf = None
        self.selected_core = None
        self.parser_thread = None
        self.fetch_thread = None
        self.analysis_complete = False

        self.dump_folder = settings.get("dump_folder", os.getcwd())
        # FIX: Get separate IP and Port fields
        self.vita_ip = settings.get("vita_ip", "")
        self.vita_port = settings.get("vita_port", 21)  # Default to 21 if not found
        self.build_dir = settings.get("last_build_dir", "")

        layout = QVBoxLayout(self)

        # Controls
        controls_layout = QHBoxLayout()

        self.btn_load_elf = QPushButton("Load .elf")
        self.btn_load_elf.clicked.connect(self.load_elf_file)

        self.btn_load_crash = QPushButton("Load crash")
        self.btn_load_crash.clicked.connect(self.load_crash_file)

        self.btn_parse = QPushButton("Analyze Crash Dump")
        self.btn_parse.setEnabled(False)
        self.btn_parse.clicked.connect(self.start_core_parser)

        # NEW: Fetch & Parse Button
        self.btn_fetch_parse = QPushButton("Fetch & Parse Last Crash")
        self.btn_fetch_parse.clicked.connect(self.fetch_and_parse_last_crash)
        # Check if settings for FTP are available to enable button
        is_ftp_ready = bool(self.vita_ip and self.vita_port and self.build_dir and os.path.isdir(self.build_dir))
        self.btn_fetch_parse.setEnabled(is_ftp_ready)

        # NEW: Save Button
        self.btn_save = QPushButton("Save Analysis")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.save_analysis)

        controls_layout.addWidget(self.btn_load_elf)
        controls_layout.addWidget(self.btn_load_crash)
        controls_layout.addWidget(self.btn_parse)
        controls_layout.addWidget(self.btn_fetch_parse)
        controls_layout.addWidget(self.btn_save)
        controls_layout.addStretch()

        layout.addLayout(controls_layout)

        output_frame = QFrame()
        output_frame.setObjectName("logOutputContainer")
        output_layout = QVBoxLayout(output_frame)
        output_layout.setContentsMargins(6, 6, 6, 6)
        output_layout.setSpacing(4)

        # --- Output actions ---
        header_layout = QHBoxLayout()
        header_layout.setObjectName("logOutputToolbar")
        header_layout.setContentsMargins(4, 2, 4, 2)
        header_layout.addWidget(QLabel("Core Dump Analysis Output:"))
        header_layout.addStretch()

        self.btn_copy = QPushButton()
        self.btn_copy.setToolTip("Copy Log to Clipboard")
        self.btn_copy.setFixedSize(28, 28)
        self.btn_copy.clicked.connect(self.copy_output_to_clipboard)
        header_layout.addWidget(self.btn_copy)

        self.btn_clear = QPushButton()
        self.btn_clear.setToolTip("Clear Analysis Output")
        self.btn_clear.setFixedSize(28, 28)
        self.btn_clear.clicked.connect(self.clear_output)
        header_layout.addWidget(self.btn_clear)

        output_layout.addLayout(header_layout)

        # Log Output Area
        self.core_output = QTextEdit()
        self.core_output.setReadOnly(True)
        self.core_output.setObjectName("logOutput")

        self.core_output.setTextInteractionFlags(self.core_output.textInteractionFlags() |
                                               Qt.TextInteractionFlag.TextSelectableByMouse)

        font = self.core_output.font()
        if os.name == 'nt':
            font.setFamily("Consolas")
        else:
            font.setFamily("Monospace")
        self.core_output.setFont(font)

        output_layout.addWidget(self.core_output)
        layout.addWidget(output_frame)
        self.apply_theme_icons()
        self.sync_with_settings()

    def sync_with_settings(self):
        """Refreshes cached workspace-dependent settings used by this tab."""
        self.dump_folder = settings.get("dump_folder", os.getcwd())
        self.vita_ip = settings.get("vita_ip", "")
        self.vita_port = settings.get("vita_port", 21)
        self.build_dir = settings.get("last_build_dir", "")

        if hasattr(self, "btn_fetch_parse"):
            is_ftp_ready = bool(self.vita_ip and self.vita_port and self.build_dir and os.path.isdir(self.build_dir))
            self.btn_fetch_parse.setEnabled(is_ftp_ready)
        self.apply_theme_icons()

    def copy_output_to_clipboard(self):
        QApplication.clipboard().setText(self.core_output.toPlainText())

    def clear_output(self):
        self.core_output.clear()

    def apply_theme_icons(self):
        self.btn_copy.setIcon(themed_icon("alt-clipboard.svg", 18))
        self.btn_copy.setIconSize(self.btn_copy.size() * 0.6)
        self.btn_clear.setIcon(themed_icon("alt-trash.svg", 18))
        self.btn_clear.setIconSize(self.btn_clear.size() * 0.6)


    def load_elf_file(self):
        initial_dir = self.build_dir if self.build_dir and os.path.isdir(self.build_dir) else self.dump_folder
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select ELF File", initial_dir, "ELF Binary (*.elf);;All Files (*)"
        )
        if not filename: return

        if not filename.lower().endswith(".elf"):
            QMessageBox.warning(self, "Error", "File must end with .elf")
            return

        self.selected_elf = filename
        # FIX: Remove filename from button text
        self.btn_load_elf.setText(f"ELF Loaded ✓")
        self.btn_load_elf.setStyleSheet("""
            background-color: #2e7d32;
            color: white;
            border: 1px solid #4caf50;
        """)
        self.check_parse_ready()
        self.analysis_complete = False
        self.btn_save.setEnabled(False)

    def load_crash_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select Crash Dump", self.dump_folder, "Core Dump (*.psp2dmp);;All Files (*)"
        )
        if not filename: return

        if not filename.lower().endswith(".psp2dmp"):
            QMessageBox.warning(self, "Error", "File must end with .psp2dmp")
            return

        self.selected_core = filename
        # FIX: Remove filename from button text
        self.btn_load_crash.setText(f"Crash Loaded ✓")
        self.btn_load_crash.setStyleSheet("""
            background-color: #2e7d32;
            color: white;
            border: 1px solid #4caf50;
        """)
        self.check_parse_ready()
        self.analysis_complete = False
        self.btn_save.setEnabled(False)

    def check_parse_ready(self):
        # Enable the parse button if both files are selected and not currently parsing
        is_parsing = self.parser_thread and self.parser_thread.isRunning()
        is_fetching = self.fetch_thread and self.fetch_thread.isRunning()

        if self.selected_elf and self.selected_core and not is_parsing and not is_fetching:
            self.btn_parse.setEnabled(True)
            self.btn_parse.setText("Analyze Crash Dump")
            self.btn_parse.setStyleSheet("""
                background-color: #2f4f6f;
                color: white;
                border: 1px solid #3a5f80;
            """)
        else:
            self.btn_parse.setEnabled(False)

    def start_core_parser(self):
        sdk_path = settings.get("sdk_path")
        self.core_output.clear()
        self.analysis_complete = False
        self.btn_save.setEnabled(False)
        self.check_parse_ready()

        self.parser_thread = DumpParserThread(self.selected_core, self.selected_elf, sdk_path)
        self.parser_thread.output_signal.connect(self.update_core_log)
        self.parser_thread.finished_signal.connect(self.parser_finished)
        self.parser_thread.progress_signal.connect(lambda s: self.btn_parse.setText(f"Analyzing... ({s})"))

        self.btn_parse.setEnabled(False)
        self.btn_fetch_parse.setEnabled(False)
        self.parser_thread.start()

    @Slot(str, bool)
    def update_core_log(self, text, is_html):
        self.core_output.moveCursor(QTextCursor.End)
        if is_html:
            self.core_output.insertHtml(text)
        else:
            self.core_output.insertPlainText(text + "\n")
        self.core_output.moveCursor(QTextCursor.End)

    @Slot()
    def parser_finished(self):
        self.check_parse_ready()

        # Enable save button on successful completion
        self.analysis_complete = True
        self.btn_save.setEnabled(True)

        # Re-enable fetch button if settings allow
        is_ftp_ready = bool(self.vita_ip and self.vita_port and self.build_dir and os.path.isdir(self.build_dir))
        self.btn_fetch_parse.setEnabled(is_ftp_ready)

        self.core_output.moveCursor(QTextCursor.End)
        self.core_output.insertHtml(f'<br><span style="color:{COLOR_GREY};">Done.</span>')
        self.core_output.moveCursor(QTextCursor.End)

    # --- Save Functionality ---
    @Slot()
    def save_analysis(self):
        if not self.analysis_complete or not self.selected_elf or not self.selected_core:
            QMessageBox.warning(self, "Warning", "Please run a successful analysis first.")
            return

        base_dir = QFileDialog.getExistingDirectory(
            self, "Select Save Directory", self.dump_folder, QFileDialog.ShowDirsOnly
        )
        if not base_dir: return

        # Create a unique subfolder (e.g., 'elfname_crash_YYYYMMDD_HHMMSS')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        elf_name = os.path.splitext(os.path.basename(self.selected_elf))[0]

        save_folder_name = f"{elf_name}_crash_{timestamp}"
        save_path = os.path.join(base_dir, save_folder_name)

        try:
            os.makedirs(save_path, exist_ok=True)

            # Copy ELF
            elf_dest = os.path.join(save_path, os.path.basename(self.selected_elf))
            shutil.copy2(self.selected_elf, elf_dest)

            # Copy Crash Dump
            core_dest = os.path.join(save_path, os.path.basename(self.selected_core))
            shutil.copy2(self.selected_core, core_dest)

            # Save Analysis Output (as HTML for colors)
            output_html = self.core_output.toHtml()
            output_file = os.path.join(save_path, "analysis_output.html")
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(output_html)

            QMessageBox.information(self, "Success", f"Analysis saved successfully to:\n{save_path}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save analysis: {str(e)}")

    # --- Fetch & Parse Functionality (FIXED) ---
    @Slot()
    def fetch_and_parse_last_crash(self):
        self.sync_with_settings()
        if not (self.vita_ip and self.vita_port and self.build_dir):
            QMessageBox.critical(self, "Error", "Vita IP/Port or Build Directory not set in settings.")
            return

        if self.fetch_thread and self.fetch_thread.isRunning():
            QMessageBox.warning(self, "Warning", "Crash fetching is already in progress.")
            return

        # Clear output area and prepare UI
        self.core_output.clear()
        self.analysis_complete = False
        self.btn_save.setEnabled(False)
        self.btn_parse.setEnabled(False)
        self.btn_fetch_parse.setEnabled(False)
        self.btn_fetch_parse.setText("Fetching...")

        self.update_core_log("Starting crash fetch process...", is_html=False)

        # PASS separate IP and Port
        self.fetch_thread = CrashFetchThread(self.vita_ip, self.vita_port, self.build_dir, self)
        self.fetch_thread.progress_signal.connect(lambda s, h: self.update_core_log(f"-> {s}", is_html=h))
        self.fetch_thread.error_signal.connect(self.handle_fetch_error)
        self.fetch_thread.fetched_files_signal.connect(self.handle_fetched_files)
        self.fetch_thread.finished.connect(self.fetch_finished_cleanup)

        self.fetch_thread.start()

    @Slot(str, str)
    def handle_fetched_files(self, elf_path, core_path):
        """Called when CrashFetchThread successfully downloads the files."""
        self.selected_elf = elf_path
        self.selected_core = core_path

        # Update file buttons (no long file names)
        self.btn_load_elf.setText(f"ELF Loaded ✓")
        self.btn_load_crash.setText(f"Crash Loaded ✓")
        self.btn_load_elf.setStyleSheet("""background-color: #2e7d32; color: white; border: 1px solid #4caf50;""")
        self.btn_load_crash.setStyleSheet("""background-color: #2e7d32; color: white; border: 1px solid #4caf50;""")

        self.update_core_log("\nStarting automated analysis...", is_html=False)
        self.start_core_parser()

    @Slot(str)
    def handle_fetch_error(self, message):
        """Called when CrashFetchThread encounters an error."""
        self.update_core_log(f'<span style="color:{COLOR_RED};">!!! FETCH ERROR: {message} !!!</span>', is_html=True)
        QMessageBox.critical(self, "Fetch Error", "Failed to retrieve and/or locate files.")

    @Slot()
    def fetch_finished_cleanup(self):
        """Called when CrashFetchThread finishes (success or failure)."""
        self.btn_fetch_parse.setText("Fetch & Parse Last Crash")

        # Re-enable the button if parsing hasn't started (i.e., if fetching failed)
        is_parsing = self.parser_thread and self.parser_thread.isRunning()
        if not is_parsing:
            self.check_parse_ready()
            is_ftp_ready = bool(self.vita_ip and self.vita_port and self.build_dir and os.path.isdir(self.build_dir))
            self.btn_fetch_parse.setEnabled(is_ftp_ready)

        if self.fetch_thread and self.fetch_thread.temp_core_path and not is_parsing:
            try:
                os.remove(self.fetch_thread.temp_core_path)
            except Exception:
                pass
