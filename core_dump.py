# core_dump.py
# Fully integrated Vita Crash Dump Analyzer for Python 3 / PySide6
# Includes colorized output.

import os
import sys
import struct
import subprocess
import gzip
from collections import defaultdict
import traceback

# Importaciones de PySide6 (ajustadas para usar QTextEdit y el flag de Qt)
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QTextEdit, QFileDialog, QMessageBox) 
from PySide6.QtCore import QThread, Signal, Slot, Qt
from PySide6.QtGui import QTextCursor

# ==========================================
# COLORS & UTILITIES
# ==========================================

# --- COLOR DEFINITIONS (HTML HEX CODES) ---
COLOR_RED = "#F44747"       # Crash/Error information
COLOR_YELLOW = "#FFD700"    # General labels (ID:, Status:, etc.) - Strong Gold
COLOR_GREY = "#D4D4D4"      # General text, non-highlighted output
COLOR_BLUE = "#569CD6"      # Reserved
COLOR_TEAL = "#00FFFF"      # New color for headers (Bright Cyan)
COLOR_ORANGE = "#FF8C00"    # New color for registers

# Colores para el contraste solicitado:
COLOR_THREAD_NAME = "#4EC9B0" # Nuevo color para nombres de hilos (Teal/Aqua)
COLOR_SYM_NAME = "#85C664"    # Nuevo color para la estructura simbólica (Brighter Green)
COLOR_ADDR_BASE = "#FFFFFF"   # Nuevo color para los valores de dirección (White)

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
    
    # FIX: Use &nbsp; to force space rendering in HTML for indentation.
    prefix = ("&nbsp;&nbsp;&nbsp;&nbsp;" * _indent_level)
    
    text = " ".join(str(a) for a in args)
    
    # Maneja llamadas vacías (iprint()) para un simple salto de línea.
    if not text.strip() and not _indent_level:
        if _log_callback:
            _log_callback("<br>", is_html=True)
        return
    
    out = text
    html_out = ""
    
    # Dividir por nueva línea para procesar la sangría y '!!!' por línea
    out_lines = out.split('\n')
    
    for line in out_lines:
        line_stripped = line.strip()
        line_color = color
        
        # Regla: Las líneas que empiezan/terminan con '!!!' son siempre ROJAS
        if line_stripped.startswith('!!!') and line_stripped.endswith('!!!'):
            line_color = COLOR_RED

        # Si la línea tiene contenido
        if line or (len(out_lines) > 1 and not line.strip()):
            
            # Si el texto ya contiene HTML (ej. de VitaAddress.to_string o llamadas manuales)
            if '<span' in line and color != COLOR_GREY:
                # FIX: Añadir el prefijo &nbsp; solo una vez al comienzo de la línea HTML
                html_out += prefix + line + '<br>'
            else:
                # Envolver toda la línea (incluyendo la sangría/prefijo) en el color solicitado + <br>
                html_out += f'<span style="color:{line_color};">{prefix}{line}</span><br>'
        else:
            # Línea vacía que no es solo un resultado de un split de una cadena multilínea
            pass

    # Enviar HTML a la GUI
    if _log_callback:
        if not html_out.endswith('<br>'):
            html_out += '<br>'
            
        try:
            _log_callback(html_out, is_html=True)
        except Exception:
            # Fallback para errores/QTextEdit faltante
            print(out, end="\n")
    else:
        # Fallback para depuración CLI
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
# SETTINGS MOCK
# ==========================================
class _Settings:
    def __init__(self):
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
    """Minimal ELF32 parser fallback."""
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

# ==========================================
# DATA MODELS (VITA STRUCTS)
# ==========================================

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
            # Título de Desensamblaje es AMARILLO, pero el prefijo es GREEN para la estructura
            iprint(f"DISASSEMBLY AROUND {self.__symbol}: 0x{addr_to_display:x} ({state}):", color=COLOR_YELLOW)
            try:
                # La salida del desensamblaje será GRIS/ROJO
                elf_parser.disas_around_addr(self.__offset, self.__vaddr)
            except Exception as e:
                # Mensajes de error son GRISES
                iprint(f"[Disassembly failed: {str(e)}]", color=COLOR_GREY)
                iprint("[Ensure Vita SDK is in PATH or set in settings]", color=COLOR_GREY)

    def to_string(self, elf_parser=None, include_symbol=True):
        """
        Returns HTML string with colors for symbolic address (Green structure, White numbers).
        If include_symbol is False, it omits the "PC: " or "LR: " prefix (used for stack values).
        """
        vaddr_color = COLOR_ADDR_BASE 
        output = ""
        
        # FIX: Only print the symbol (PC:, LR:, R0:, etc.) if requested
        if include_symbol:
            output = f'<span style="color:{COLOR_SYM_NAME};">{self.__symbol}: </span>'
        
        # Dirección (White)
        output += f'<span style="color:{vaddr_color};">0x{self.__vaddr:x}</span>'
        
        if self.is_located():
            # Módulo/Segmento/Offset (Green)
            output += f'<span style="color:{COLOR_SYM_NAME};"> ({self.__module.name}@{self.__segment.num} + </span>'
            
            # Offset (White)
            output += f'<span style="color:{vaddr_color};">0x{self.__offset:x}</span>'
            
            line_info = ""
            # Intentar obtener número de línea
            if elf_parser and self.__module.name.endswith(".elf") and self.__segment.num == 1:
                try:
                    line_info = elf_parser.addr2line(self.__offset)
                    if line_info:
                        # Información de línea (Green)
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

# ==========================================
# CORE PARSER
# ==========================================

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

# ==========================================
# ELF PARSER
# ==========================================

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
        if self.sdk_path and os.path.isdir(self.sdk_path):
            full_path = os.path.join(self.sdk_path, tool)
            if os.name == 'nt' and not full_path.endswith('.exe'):
                full_path += '.exe'
            return full_path
        return tool

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
            # Added stderr=subprocess.DEVNULL to clean up objdump output
            output = subprocess.check_output(args, stderr=subprocess.DEVNULL) 
            text_output = output.decode('utf-8', errors='replace')
            lines = text_output.splitlines()

            keep = False
            final_lines = []
            
            for line in lines:
                if "Disassembly of section" in line:
                    keep = True
                    continue
                if keep:
                    # Highlight the specific instruction with the '!!!' markers
                    if f"{abs_addr:x}:" in line:
                        # Clean up tabs/spaces before adding markers
                        line = line.strip()
                        line = "!!! " + line + " !!!"
                    final_lines.append(line)

            if final_lines:
                # iprint handles the default GREY color and the RED '!!!' color.
                iprint("\n".join(final_lines))
            else:
                iprint("(No disassembly output found)", color=COLOR_GREY)

        except FileNotFoundError:
            raise FileNotFoundError(f"Tool not found: {cmd}")
        except subprocess.CalledProcessError as e:
            # Use GREY for tool errors
            iprint(f"Objdump error: {e.output.decode('utf-8', errors='replace')}", color=COLOR_GREY)

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
# GUI / WORKER
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
        """Sends output to the main thread's log window."""
        self.output_signal.emit(str(text), is_html)

    def run(self):
        set_log_callback(self.emit_log)
        set_indent_level(0)

        self.progress_signal.emit("Parsing...")
        try:
            # Colores de información de inicio (GREY)
            iprint("--- Starting Analysis ---", color=COLOR_GREY)
            iprint(f"Core: {self.core_file}", color=COLOR_GREY)
            iprint(f"ELF: {self.elf_file}", color=COLOR_GREY)
            iprint(f"SDK: {self.sdk_path or 'System PATH'}") # Salto de linea automatico
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

            # Encabezado principal (TEAL/CYAN)
            iprint("=== THREADS ===", color=COLOR_TEAL)
            crashed = []

            # Listar todos los hilos
            with IndentManager(): # Level 1 Indentation for Thread Name
                for thread in core.threads:
                    if thread.stop_reason != 0:
                        crashed.append(thread)

                    # Nombre del hilo (THREAD_NAME)
                    iprint(thread.name, color=COLOR_THREAD_NAME) 
                    
                    with IndentManager(): # Level 2 Indentation for details
                        # Información general (YELLOW para la etiqueta, ADDR_BASE/RED para el valor)
                        
                        # ID (Yellow label, White value)
                        iprint(f"ID: <span style=\"color:{COLOR_ADDR_BASE};\">0x{thread.uid:x}</span>", color=COLOR_YELLOW)
                        
                        # Razón de detención (Yellow label, dynamic color value)
                        reason_str = str_stop_reason[thread.stop_reason]
                        
                        reason_color = COLOR_YELLOW
                        if "abort" in reason_str or "instruction" in reason_str:
                            reason_color = COLOR_RED
                        
                        # Usar iprint con HTML para mantener la sangría y el formato
                        html_line = f'<span style="color:{COLOR_YELLOW};">Stop reason: </span>'
                        html_line += f'<span style="color:{COLOR_ADDR_BASE};">0x{thread.stop_reason:x} (</span>'
                        html_line += f'<span style="color:{reason_color};">{reason_str}</span>'
                        html_line += f'<span style="color:{COLOR_ADDR_BASE};">)</span>'
                        iprint(html_line, color=COLOR_YELLOW) # Usar COLOR_YELLOW para el color general/prefijo

                        # Estado (Yellow label, White value)
                        status_str = str_status[thread.status]
                        html_line = f'<span style="color:{COLOR_YELLOW};">Status: </span>'
                        html_line += f'<span style="color:{COLOR_ADDR_BASE};">0x{thread.status:x} ({status_str})</span>'
                        iprint(html_line, color=COLOR_YELLOW)

                        # PC/LR (Yellow label, Green/White symbolic structure)
                        pc = core.get_address_notation("PC", thread.pc)
                        lr = core.get_address_notation("LR", thread.regs.gpr[14] if thread.regs else 0)
                        
                        # PC (Label is part of VitaAddress, color is SYM_NAME)
                        iprint(pc.to_string(self.elf_parser), color=COLOR_SYM_NAME) # Using SYM_NAME for the label part
                        
                        # Only print LR if it's different from PC
                        if lr.to_string(self.elf_parser) != pc.to_string(self.elf_parser):
                            iprint(lr.to_string(self.elf_parser), color=COLOR_SYM_NAME)


            iprint()

            # Información detallada del crash
            for thread in crashed:
                reason = str_stop_reason[thread.stop_reason]
                reason_color = COLOR_RED
                
                # Encabezado de Crash (GREY + RED reason)
                html_line = f'<span style="color:{COLOR_GREY};">=== THREAD "{thread.name}" </span>'
                html_line += f'<span style="color:{COLOR_ADDR_BASE};"><0x{thread.uid:x}></span>'
                html_line += f'<span style="color:{COLOR_GREY};"> CRASHED (</span>'
                html_line += f'<span style="color:{reason_color};">{reason}</span>'
                html_line += f'<span style="color:{COLOR_GREY};">) ===</span>'
                iprint(html_line, color=COLOR_GREY) 

                pc = core.get_address_notation('PC', thread.regs.gpr[15] if thread.regs else thread.pc)
                pc.print_disas_if_available(self.elf_parser)

                # Encabezado de Registros (TEAL/CYAN)
                iprint("\nREGISTERS:", color=COLOR_TEAL)
                with IndentManager(): # Level 1 Indentation for Registers
                    if thread.regs:
                        for x in range(16):
                            reg = reg_names.get(x, f"R{x}")
                            # Valores de Registros (ORANGE label, WHITE value)
                            html_line = f'<span style="color:{COLOR_ORANGE};">{reg}: </span>'
                            html_line += f'<span style="color:{COLOR_ADDR_BASE};">0x{thread.regs.gpr[x]:x}</span>'
                            iprint(html_line, color=COLOR_ORANGE)
                        
                        # PC/LR Simbólicos (Green/White) - Already at Level 1, no further indent needed
                        # The symbolic notation is printed here, using the SYM_NAME color for the label part
                        iprint(pc.to_string(self.elf_parser), color=COLOR_SYM_NAME)
                        iprint(lr.to_string(self.elf_parser), color=COLOR_SYM_NAME)
                    else:
                        iprint("No register info available.", color=COLOR_GREY)

                # Encabezado de Stack (TEAL/CYAN)
                iprint("\nSTACK CONTENTS AROUND SP:", color=COLOR_TEAL)
                with IndentManager(): # Level 1 Indentation for Stack
                    if thread.regs:
                        sp = thread.regs.gpr[13]
                        stack_range = 24
                        for x in range(-16, stack_range):
                            addr = 4 * x + sp
                            data = core.read_vaddr(addr, 4)
                            if data:
                                val = u32(data, 0)
                                prefix = "          "
                                
                                # 1. Prepare the stack address label (SP => 0x...)
                                if addr == sp:
                                    prefix = "SP => "
                                
                                # 2. Prepare the stack *value* notation
                                # We pass an empty symbol here, as we only want the symbolic module info for the value (val)
                                data_notation = core.get_address_notation("", val) 
                                
                                # 3. Combine and print
                                # Stack Address Label: Green for prefix, White for address
                                html_line = f'<span style="color:{COLOR_SYM_NAME};">{prefix}</span>'
                                html_line += f'<span style="color:{COLOR_ADDR_BASE};">0x{addr:x}: </span>'
                                # Stack Value Notation: Call to_string with include_symbol=False to prevent duplication
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


class CoreDumpTab(QWidget):
    def __init__(self):
        super().__init__()
        self.selected_elf = None
        self.selected_core = None
        self.parser_thread = None
        
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
        self.core_output = QTextEdit() 
        self.core_output.setReadOnly(True)
        self.core_output.setObjectName("logOutput")
        
        # Habilitar selección de texto
        self.core_output.setTextInteractionFlags(self.core_output.textInteractionFlags() | 
                                               Qt.TextInteractionFlag.TextSelectableByMouse)

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
        self.btn_load_elf.setStyleSheet("""
            background-color: #2e7d32; 
            color: white; 
            border: 1px solid #4caf50;
        """)
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
        self.btn_load_crash.setStyleSheet("""
            background-color: #2e7d32; 
            color: white; 
            border: 1px solid #4caf50;
        """)
        self.check_parse_ready()

    def check_parse_ready(self):
        if self.selected_elf and self.selected_core:
            self.btn_parse.setEnabled(True)
            self.btn_parse.setText("Analyze Crash Dump")
            self.btn_parse.setStyleSheet("""
                background-color: #2f4f6f;
                color: white;
                border: 1px solid #3a5f80;
            """)

    def start_core_parser(self):
        sdk_path = settings.get("sdk_path")
        self.core_output.clear()
        
        self.parser_thread = DumpParserThread(self.selected_core, self.selected_elf, sdk_path)
        self.parser_thread.output_signal.connect(self.update_core_log)
        self.parser_thread.finished_signal.connect(self.parser_finished)
        self.parser_thread.progress_signal.connect(lambda s: self.btn_parse.setText(f"Analyzing... ({s})"))
        
        self.btn_parse.setEnabled(False)
        self.parser_thread.start()

    @Slot(str, bool)
    def update_core_log(self, text, is_html): 
        self.core_output.moveCursor(QTextCursor.End)
        if is_html:
            self.core_output.insertHtml(text)
        else:
            # Fallback for plain text, ensuring a clean break if HTML failed
            self.core_output.insertPlainText(text) 
        self.core_output.moveCursor(QTextCursor.End)

    @Slot()
    def parser_finished(self):
        self.check_parse_ready()
        self.core_output.insertHtml(f'<br><span style="color:{COLOR_GREY};">Done.</span>')
    def fetch_and_parse_last_crash(self):
        QMessageBox.information(
            self,
            "Feature Unavailable",
            "Automatic Fetch and Parse is planned for a later version.\nPlease use 'Load .elf' and 'Load crash' manually."
        )