# core_dump.py
# Fully integrated Vita Crash Dump Analyzer for Python 3 / PySide6
# Based on original work by xyzz, integrated and fixed for modern environments.

import os
import sys
import struct
import subprocess
import gzip
from collections import defaultdict
import traceback

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QPlainTextEdit, QFileDialog, QMessageBox)
from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtGui import QTextCursor

# ==========================================
# UTILITIES & LOGGING
# ==========================================

_log_callback = None
_indent_level = 0

def set_log_callback(cb):
    global _log_callback
    _log_callback = cb

def set_indent_level(val):
    global _indent_level
    _indent_level = val

def iprint(*args, **kwargs):
    """Indent-aware print to log callback."""
    prefix = "    " * _indent_level
    text = " ".join(str(a) for a in args)
    out = prefix + text + ("\n" if not text.endswith("\n") else "")
    
    # Send to GUI if callback exists, otherwise stdout
    if _log_callback:
        try:
            _log_callback(out)
        except Exception:
            print(out, end="")
    else:
        print(out, end="")

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
        # In bytes, 0 is an integer, not a char
        idx = sub.index(0)
        return sub[:idx].decode('utf-8', errors='ignore')
    except ValueError:
        # No null terminator found, decode whole string
        return sub.decode('utf-8', errors='ignore')

# ==========================================
# SETTINGS MOCK
# ==========================================
class _Settings:
    def __init__(self):
        # Tries to get SDK path from environment variable, or defaults to empty
        self._d = {"sdk_path": os.environ.get("VITA_SDK_PATH", ""),
                   "dump_folder": os.getcwd()}

    def get(self, key, default=None):
        return self._d.get(key, default)

    def set(self, key, value):
        self._d[key] = value

settings = _Settings()

# ==========================================
# ELF PARSING (pyelftools with Fallback)
# ==========================================
try:
    from elftools.elf.elffile import ELFFile
    HAS_PYELFTOOLS = True
except ImportError:
    HAS_PYELFTOOLS = False
    ELFFile = None

# Fallback classes for when pyelftools is missing
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
        """Parse ELF notes manually."""
        data = self._data
        off = 0
        notes = []
        while off + 12 <= len(data):
            # Parse Note Header (namesz, descsz, type)
            namesz, descsz, ntype = struct.unpack_from("<III", data, off)
            off += 12
            
            # Read Name (padded to 4 bytes)
            name_data = data[off:off + namesz]
            off += ((namesz + 3) // 4) * 4
            
            # Read Desc (padded to 4 bytes)
            desc_data = data[off:off + descsz]
            off += ((descsz + 3) // 4) * 4
            
            # Decode name
            try:
                name_str = name_data.split(b'\x00', 1)[0].decode('utf-8', errors='ignore')
            except Exception:
                name_str = ""
            
            notes.append({"n_name": name_str, "n_desc": desc_data, "n_type": ntype})
        return notes

class SimpleELFFile:
    """Minimal ELF32 parser fallback."""
    def __init__(self, fileobj):
        self._f = fileobj
        self._parse_header()

    def _parse_header(self):
        self._f.seek(0)
        e_ident = self._f.read(16)
        if len(e_ident) < 16 or e_ident[0:4] != b'\x7fELF':
            raise ValueError("Not an ELF file")
        
        # Read the rest of the header (standard ELF32 header size is 52 bytes total)
        # We need e_phoff (offset 28), e_phentsize (42), e_phnum (44)
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
            
            # p_type(4), p_offset(4), p_vaddr(4), p_paddr(4), p_filesz(4), p_memsz(4), p_flags(4), p_align(4)
            vals = struct.unpack_from("<IIIIIIII", ph_data, 0)
            p_type, p_offset, p_vaddr, _, p_filesz, _, p_flags, _ = vals
            
            header = _SegmentHeader(p_type, p_offset, p_vaddr, p_filesz, p_flags)
            
            # Save current pos, read data, restore pos
            cur = self._f.tell()
            self._f.seek(p_offset)
            data = self._f.read(p_filesz)
            self._f.seek(cur)
            
            segs.append(SimpleSegment(header, data))
        return segs

# Wrapper to select the correct ELF class
def GetELFParser(fileobj):
    if HAS_PYELFTOOLS:
        return ELFFile(fileobj)
    else:
        return SimpleELFFile(fileobj)

# ==========================================
# DATA MODELS (VITA STRUCTS)
# ==========================================

class VitaThread:
    def __init__(self, data):
        self.uid = u32(data, 4)
        self.name = c_str(data, 8)
        # Offsets based on observed core dumps
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
            iprint(f"DISASSEMBLY AROUND {self.__symbol}: 0x{addr_to_display:x} ({state}):")
            try:
                # Correctly calling the method on ElfParserObj
                elf_parser.disas_around_addr(self.__offset, self.__vaddr)
            except Exception as e:
                iprint(f"[Disassembly failed: {str(e)}]")
                iprint("[Ensure Vita SDK is in PATH or set in settings]")

    def to_string(self, elf_parser=None):
        if self.is_located():
            output = "{}: 0x{:x} ({}@{} + 0x{:x}".format(self.__symbol, self.__vaddr,
                       self.__module.name, self.__segment.num, self.__offset)
            
            # Try to get line number if it's the main executable
            if elf_parser and self.__module.name.endswith(".elf") and self.__segment.num == 1:
                try:
                    line_info = elf_parser.addr2line(self.__offset)
                    if line_info:
                        output += " => {}".format(line_info)
                except Exception:
                    pass
            output += ')'
        else:
            output = "{}: 0x{:x}".format(self.__symbol, self.__vaddr)
        return output

class CoreSegment:
    def __init__(self, vaddr, data):
        self.vaddr = vaddr
        self.data = data
        self.size = len(data)

# ==========================================
# PARSERS
# ==========================================

class CoreParser:
    def __init__(self, filename):
        # Open file (handle GZIP transparently)
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
        
        # We can close the file handle now as we've read everything into memory
        self.file_handle.close()

    def init_notes(self):
        self.notes = dict()
        self.segments = []
        
        for seg in self.elf.iter_segments():
            # Handle p_type differences (int vs string depending on library/fallback)
            p_type = seg.header.p_type
            
            is_note = (p_type == 4) or (p_type == "PT_NOTE")
            is_load = (p_type == 1) or (p_type == "PT_LOAD")

            if is_note:
                for note in seg.iter_notes():
                    # note['n_name'] is string, note['n_desc'] is bytes
                    self.notes[note["n_name"]] = note["n_desc"]
            elif is_load:
                self.segments.append(CoreSegment(seg.header.p_vaddr, seg.data()))

    def parse_modules(self):
        self.modules = []
        if "MODULE_INFO" not in self.notes:
            return
            
        data = self.notes["MODULE_INFO"]
        # Ensure data is bytes
        if isinstance(data, str):
            data = data.encode('latin-1')

        if len(data) < 8: return

        num = u32(data, 4)
        off = 8
        for _ in range(num):
            # Module Header
            sz = 0x50
            if off + sz > len(data): break
            module = VitaModule(data[off:off+sz])
            off += sz
            
            # Module Segments
            seg_sz = module.num_segs * 0x14
            if off + seg_sz <= len(data):
                module.parse_segs(data[off:off+seg_sz])
                off += seg_sz
            
            # Module Footer
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

class ElfParserObj:
    def __init__(self, filename, sdk_path=None):
        self.filename = filename
        self.sdk_path = sdk_path
        self.f = open(filename, "rb")
        self.elf = GetELFParser(self.f)
        self.rx_vaddr = -1
        self.parse_segments()
        
        # We don't close self.f here just in case pyelftools reads lazily, 
        # but usually it's fine. We close it on destruction or when thread ends.
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
        if self.sdk_path and os.path.isdir(self.sdk_path):
            full_path = os.path.join(self.sdk_path, tool)
            if os.name == 'nt' and not full_path.endswith('.exe'):
                full_path += '.exe'
            return full_path
        return tool

    def parse_segments(self):
        for seg in self.elf.iter_segments():
            # Unify access to p_flags/p_vaddr between pyelftools and fallback
            p_flags = getattr(seg.header, 'p_flags', None)
            if p_flags is None and hasattr(seg, '__getitem__'):
                 p_flags = seg['p_flags']
            
            p_vaddr = getattr(seg.header, 'p_vaddr', None)
            if p_vaddr is None and hasattr(seg, '__getitem__'):
                p_vaddr = seg['p_vaddr']

            # Check for RX segment (Flags == 5 or "5")
            if str(p_flags) == "5":
                self.rx_vaddr = p_vaddr

    def disas_around_addr(self, offset, vaddr):
        # Calculate absolute address for objdump
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
        args = [cmd, "-d", "-S",
                f"--start-address=0x{start:x}",
                f"--stop-address=0x{end:x}",
                self.filename]
        
        if thumb:
            args += ['-Mforce-thumb']

        try:
            # IMPORTANT: Capture stderr to prevent noise
            output = subprocess.check_output(args, stderr=subprocess.STDOUT)
            
            # Decode bytes to string
            text_output = output.decode('utf-8', errors='replace')
            lines = text_output.splitlines()

            keep = False
            final_lines = []
            
            for line in lines:
                if "Disassembly of section" in line:
                    keep = True
                    continue
                if keep:
                    # Highlight the specific instruction
                    if f"{abs_addr:x}:" in line:
                        line = ">>> " + line.strip()
                    final_lines.append(line)

            if final_lines:
                iprint("\n".join(final_lines))
            else:
                iprint("(No disassembly output found)")

        except FileNotFoundError:
            raise FileNotFoundError(f"Tool not found: {cmd}")
        except subprocess.CalledProcessError as e:
            iprint(f"Objdump error: {e.output.decode('utf-8', errors='replace')}")

    def addr2line(self, offset):
        if not self.a2l:
            cmd = self.get_tool_command("arm-vita-eabi-addr2line")
            try:
                self.a2l = subprocess.Popen(
                    [cmd, "-e", self.filename, "-f", "-p", "-C"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                )
            except FileNotFoundError:
                raise FileNotFoundError("addr2line tool not found")

        # Addr2line needs the absolute address
        abs_addr = offset + self.rx_vaddr if self.rx_vaddr != -1 else offset
        
        msg = f"{abs_addr:x}\n".encode('utf-8')
        try:
            self.a2l.stdin.write(msg)
            self.a2l.stdin.flush()
            out = self.a2l.stdout.readline()
            return out.strip().decode('utf-8')
        except (IOError, BrokenPipeError):
            self.a2l = None # Restart next time
            return ""

# ==========================================
# GUI / WORKER
# ==========================================

class DumpParserThread(QThread):
    output_signal = Signal(str)
    finished_signal = Signal()
    progress_signal = Signal(str)

    def __init__(self, core_file, elf_file, sdk_path=None):
        super().__init__()
        self.core_file = core_file
        self.elf_file = elf_file
        self.sdk_path = sdk_path
        self.elf_parser = None

    def run(self):
        # Bind the logging callback to this thread's signal
        set_log_callback(self.emit_log)
        set_indent_level(0)

        self.progress_signal.emit("Parsing...")
        try:
            self.emit_log(f"--- Starting Analysis ---\nCore: {self.core_file}\nELF: {self.elf_file}\nSDK: {self.sdk_path or 'System PATH'}\n")

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

            iprint("=== THREADS ===")
            crashed = []

            # List all threads
            with IndentManager():
                for thread in core.threads:
                    if thread.stop_reason != 0:
                        crashed.append(thread)

                    iprint(thread.name)
                    with IndentManager():
                        iprint(f"ID: 0x{thread.uid:x}")
                        reason_str = str_stop_reason[thread.stop_reason]
                        iprint(f"Stop reason: 0x{thread.stop_reason:x} ({reason_str})")
                        status_str = str_status[thread.status]
                        iprint(f"Status: 0x{thread.status:x} ({status_str})")

                        # Resolve PC
                        pc = core.get_address_notation("PC", thread.pc)
                        iprint(pc.to_string(self.elf_parser))
                        
                        # If PC not resolved, try LR (Link Register)
                        if not pc.is_located() and thread.regs:
                            lr_val = thread.regs.gpr[14]
                            iprint(core.get_address_notation("LR", lr_val).to_string(self.elf_parser))

            iprint()

            # Detailed crash info
            for thread in crashed:
                reason = str_stop_reason[thread.stop_reason]
                iprint(f'=== THREAD "{thread.name}" <0x{thread.uid:x}> CRASHED ({reason}) ===')

                # Determine PC and LR from registers if available, else struct
                cur_pc_val = thread.regs.gpr[15] if thread.regs else thread.pc
                cur_lr_val = thread.regs.gpr[14] if thread.regs else 0

                pc = core.get_address_notation('PC', cur_pc_val)
                pc.print_disas_if_available(self.elf_parser)

                lr = core.get_address_notation('LR', cur_lr_val)
                lr.print_disas_if_available(self.elf_parser)

                iprint("\nREGISTERS:")
                with IndentManager():
                    if thread.regs:
                        for x in range(16):
                            reg = reg_names.get(x, f"R{x}")
                            iprint(f"{reg}: 0x{thread.regs.gpr[x]:x}")
                        
                        # Reprint symbolic PC/LR
                        iprint(pc.to_string())
                        iprint(lr.to_string())
                    else:
                        iprint("No register info available.")

                iprint("\nSTACK CONTENTS AROUND SP:")
                with IndentManager():
                    if thread.regs:
                        sp = thread.regs.gpr[13]
                        # Print range relative to SP (e.g. -16 to +24 words)
                        stack_range = 24
                        for x in range(-16, stack_range):
                            addr = 4 * x + sp
                            data = core.read_vaddr(addr, 4)
                            if data:
                                val = u32(data, 0)
                                prefix = "     "
                                if addr == sp:
                                    prefix = "SP =>"
                                
                                symbol = f"{prefix} 0x{addr:x}"
                                data_notation = core.get_address_notation(symbol, val)
                                iprint(data_notation.to_string(self.elf_parser))
                    else:
                        iprint("No stack info available.")

        except Exception as e:
            self.emit_log(f"\nCRITICAL ERROR DURING ANALYSIS:\n{str(e)}\n{traceback.format_exc()}")
            self.progress_signal.emit("Error")
        finally:
            if self.elf_parser:
                self.elf_parser.close()

        self.emit_log("\n--- Analysis Finished ---")
        self.finished_signal.emit()

    def emit_log(self, text):
        self.output_signal.emit(str(text))

class CoreDumpTab(QWidget):
    def __init__(self):
        super().__init__()
        self.selected_elf = None
        self.selected_core = None
        self.parser_thread = None
        
        # Use existing settings or default
        self.dump_folder = settings.get("dump_folder", os.getcwd())

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

        controls_layout.addWidget(self.btn_load_elf)
        controls_layout.addWidget(self.btn_load_crash)
        controls_layout.addWidget(self.btn_parse)
        controls_layout.addStretch()

        layout.addLayout(controls_layout)

        # Log Output
        layout.addWidget(QLabel("Core Dump Analysis Output:"))
        self.core_output = QPlainTextEdit()
        self.core_output.setReadOnly(True)
        self.core_output.setObjectName("logOutput")
        # Monospace font for alignment
        font = self.core_output.font()
        if os.name == 'nt':
            font.setFamily("Consolas")
        else:
            font.setFamily("Monospace")
        self.core_output.setFont(font)
        
        layout.addWidget(self.core_output)

    def load_elf_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select ELF File", self.dump_folder, "ELF Binary (*.elf);;All Files (*)"
        )
        if not filename: return

        if not filename.lower().endswith(".elf"):
            QMessageBox.warning(self, "Error", "File must end with .elf")
            return

        self.selected_elf = filename
        self.btn_load_elf.setText("ELF Loaded ✓")
        self.btn_load_elf.setStyleSheet("color: green;")
        self.check_parse_ready()

    def load_crash_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select Crash Dump", self.dump_folder, "Core Dump (*.psp2dmp);;All Files (*)"
        )
        if not filename: return

        if not filename.lower().endswith(".psp2dmp"):
            QMessageBox.warning(self, "Error", "File must end with .psp2dmp")
            return

        self.selected_core = filename
        self.btn_load_crash.setText("Crash Loaded ✓")
        self.btn_load_crash.setStyleSheet("color: green;")
        self.check_parse_ready()

    def check_parse_ready(self):
        if self.selected_elf and self.selected_core:
            self.btn_parse.setEnabled(True)
            self.btn_parse.setText("Analyze Crash Dump")

    def start_core_parser(self):
        sdk_path = settings.get("sdk_path")
        self.core_output.clear()
        self.core_output.appendPlainText("Initializing Parser...\n")

        self.parser_thread = DumpParserThread(self.selected_core, self.selected_elf, sdk_path)
        self.parser_thread.output_signal.connect(self.update_core_log)
        self.parser_thread.finished_signal.connect(self.parser_finished)
        self.parser_thread.progress_signal.connect(lambda s: self.btn_parse.setText(f"Analyzing... ({s})"))
        
        self.btn_parse.setEnabled(False)
        self.parser_thread.start()

    @Slot(str)
    def update_core_log(self, text):
        self.core_output.moveCursor(QTextCursor.End)
        self.core_output.insertPlainText(text)
        self.core_output.moveCursor(QTextCursor.End)

    @Slot()
    def parser_finished(self):
        self.check_parse_ready()
        self.core_output.appendPlainText("\nDone.")

    # --- ESTE ES EL MÉTODO QUE FALTABA ---
    def fetch_and_parse_last_crash(self):
        QMessageBox.information(
            self,
            "Feature Unavailable",
            "Automatic Fetch and Parse is planned for a later version.\nPlease use 'Load .elf' and 'Load crash' manually."
        )
