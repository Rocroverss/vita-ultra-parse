import sys
import socket
import threading
import struct
import string
import subprocess
import os
from collections import defaultdict
import ftplib
import time
import shutil # Added for full build cleanup

# PySide6 Imports
from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLabel, QLineEdit, QCheckBox, QTabWidget, QPlainTextEdit, QFileDialog,
    QFrame, QGroupBox, QSpinBox, QMessageBox, QSplitter, QTreeView, 
    QFileSystemModel, QHeaderView, QMenu, QAbstractItemView, QStyle,
    QInputDialog
)
from PySide6.QtGui import (
    QColor, QPainter, QTextCursor, QFont, QIntValidator, 
    QAction, QStandardItemModel, QStandardItem
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QDir, QProcess # QProcess imported

# Elftools Import
try:
    from elftools.elf.elffile import ELFFile
except ImportError:
    print("Error: 'pyelftools' not installed. Please run 'pip install pyelftools'")
    pass  # Continue running so FTP still works

# ==========================================
# 1. UTILS & INDENT
# ==========================================

LOG_CALLBACK = print 

def iprint(text=""):
    indent_spaces = " " * IndentManager.current
    LOG_CALLBACK(f"{indent_spaces}{text}\n")

class IndentManager:
    INDENT_WIDTH = 4
    current = 0
    
    def __enter__(self):
        IndentManager.current += IndentManager.INDENT_WIDTH
    
    def __exit__(self, *args, **kwargs):
        IndentManager.current -= IndentManager.INDENT_WIDTH

def u16(buf, off):
    val = buf[off:off+2]
    return struct.unpack("<H", val)[0]

def u32(buf, off):
    val = buf[off:off+4]
    return struct.unpack("<I", val)[0]

def c_str(buf, off):
    out = ""
    while off < len(buf) and buf[off] != 0:
        out += chr(buf[off])
        off += 1
    return out

# ==========================================
# 2. CORE & ELF PARSER CLASSES
# ==========================================

class VitaThread:
    def __init__(self, data):
        self.uid = u32(data, 4)
        self.name = c_str(data, 8)
        self.stop_reason = u32(data, 0x74)
        self.status = u16(data, 0x30)
        self.pc = u32(data, 0x9C)
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
        self.num_segs = u32(data, 0x4C)
        self.name = c_str(data, 0x24)
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
            self.gpr.append(u32(data, 8 + 4 * x))

class VitaAddress:
    def __init__(self, symbol, vaddr, module=None, segment=None, offset=None):
        self.__symbol = symbol
        self.__module = module
        self.__segment = segment
        self.__offset = offset
        self.__vaddr = vaddr

    def is_located(self):
        return self.__module and self.__segment and self.__offset

    def print_disas_if_available(self, elf_parser):
        if not elf_parser:
            return
        addr_to_display = self.__vaddr
        if addr_to_display & 1 == 0:
            state = "ARM"
        else:
            state = "Thumb"
            addr_to_display &= ~1

        if self.is_located():
            iprint()
            iprint("DISASSEMBLY AROUND {}: 0x{:x} ({}):".format(self.__symbol, addr_to_display, state))
            try:
                elf_parser.disas_around_addr(self.__offset, self.__vaddr)
            except Exception as e:
                iprint(f"Disassembly failed: {e}")
                iprint("Ensure SDK Path is set correctly in Settings.")

    def to_string(self, elf_parser=None):
        if self.is_located():
            output = "{}: 0x{:x} ({}@{} + 0x{:x}".format(self.__symbol, self.__vaddr,
                       self.__module.name, self.__segment.num, self.__offset)
            if elf_parser and self.__module.name.endswith(".elf") and self.__segment.num == 1:
                try:
                    line_info = elf_parser.addr2line(self.__offset)
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

class CoreParser:
    def __init__(self, filename):
        self.file_handle = open(filename, "rb")
        header = self.file_handle.read(2)
        self.file_handle.seek(0)
        
        if header == b'\x1f\x8b':
            import gzip
            self.file_handle.close()
            self.file_handle = gzip.open(filename, "rb")

        self.elf = ELFFile(self.file_handle)
        
        self.init_notes()
        self.parse_modules()
        self.parse_threads()
        self.parse_thread_regs()
        
        self.file_handle.close()

    def init_notes(self):
        self.notes = dict()
        self.segments = []
        for seg in self.elf.iter_segments():
            if seg.header.p_type == "PT_NOTE":
                for note in seg.iter_notes():
                    self.notes[note["n_name"]] = note["n_desc"]
            elif seg.header.p_type == "PT_LOAD":
                self.segments.append(CoreSegment(seg.header.p_vaddr, seg.data()))

    def parse_modules(self):
        self.modules = []
        if "MODULE_INFO" not in self.notes:
            return
        data = self.notes["MODULE_INFO"]
        if isinstance(data, str):
            data = data.encode('latin-1')
        
        num = u32(data, 4)
        off = 8
        for x in range(num):
            sz = 0x50
            module = VitaModule(data[off:off+sz])
            off += sz
            sz = module.num_segs * 0x14
            module.parse_segs(data[off:off+sz])
            off += sz
            sz = 0x10
            module.parse_foot(data[off:off+sz])
            off += sz
            self.modules.append(module)

    def parse_threads(self):
        self.threads = []
        self.tid_to_thread = dict()
        if "THREAD_INFO" not in self.notes:
            return
        data = self.notes["THREAD_INFO"]
        num = u32(data, 4)
        off = 8
        for x in range(num):
            sz = u32(data, off)
            thread = VitaThread(data[off:off+sz])
            self.threads.append(thread)
            self.tid_to_thread[thread.uid] = thread
            off += sz

    def parse_thread_regs(self):
        if "THREAD_REG_INFO" not in self.notes:
            return
        data = self.notes["THREAD_REG_INFO"]
        num = u32(data, 4)
        off = 8
        for x in range(num):
            sz = u32(data, off)
            regs = VitaRegs(data[off:off+sz])
            if regs.tid in self.tid_to_thread:
                self.tid_to_thread[regs.tid].regs = regs
            off += sz

    def get_address_notation(self, symbol, vaddr):
        for module in self.modules:
            for segment in module.segments:
                if vaddr >= segment.start and vaddr < segment.start + segment.size:
                    return VitaAddress(symbol, vaddr, module, segment, vaddr - segment.start)
        return VitaAddress(symbol, vaddr)

    def read_vaddr(self, addr, size):
        for segment in self.segments:
            if addr >= segment.vaddr and addr < segment.vaddr + segment.size:
                local_addr = addr - segment.vaddr
                return segment.data[local_addr:local_addr+size]
        return None

class ElfParserObj:
    def __init__(self, filename, sdk_path=None):
        self.filename = filename
        self.sdk_path = sdk_path
        self.f = open(filename, "rb")
        self.elf = ELFFile(self.f)
        self.rx_vaddr = -1
        self.parse_segments()
        self.f.close()
        self.a2l = None

    def get_tool_command(self, tool):
        # If sdk_path is set, prepend it. Otherwise assume it's in PATH.
        if self.sdk_path and os.path.isdir(self.sdk_path):
            full_path = os.path.join(self.sdk_path, tool)
            # Add .exe extension for Windows if missing
            if os.name == 'nt' and not full_path.endswith('.exe'):
                full_path += '.exe'
            return full_path
        return tool

    def parse_segments(self):
        for seg in self.elf.iter_segments():
            if seg["p_type"] != "PT_LOAD":
                continue
            if seg["p_flags"] == 5:  # RX
                self.rx_vaddr = seg["p_vaddr"]

    def disas_around_addr(self, offset, vaddr):
        if vaddr & 1 != 0:
            thumb = True
            vaddr &= ~1
        else:
            thumb = False

        abs_addr = offset + self.rx_vaddr 
        start = abs_addr - 0x10
        end = abs_addr + 0x10

        cmd = self.get_tool_command("arm-vita-eabi-objdump")
        
        args = [cmd, "-d", "-S",
            "--start-address=0x{:x}".format(start), 
            "--stop-address=0x{:x}".format(end), 
            self.filename]
        
        if thumb:
            args += ['-Mforce-thumb']

        # Use shell=False to avoid issues, but ensure path is correct
        output = subprocess.check_output(args, stderr=subprocess.STDOUT)
        text_output = output.decode('utf-8', errors='replace')
        lines = text_output.split("\n")
        
        keep = False
        final_lines = []
        for line in lines:
            if "Disassembly of section" in line:
                keep = True
                continue
            if keep:
                if "{:x}:".format(abs_addr) in line:
                    line = ">>> " + line.strip()
                final_lines.append(line)
        
        iprint("\n".join(final_lines))

    def addr2line(self, offset):
        if not self.a2l:
            cmd = self.get_tool_command("arm-vita-eabi-addr2line")
            self.a2l = subprocess.Popen(
                [cmd, "-e", self.filename, "-f", "-p", "-C"], 
                stdin=subprocess.PIPE, stdout=subprocess.PIPE
            )
        
        abs_addr = offset + self.rx_vaddr
        msg = f"{hex(abs_addr)}\n".encode('utf-8')
        self.a2l.stdin.write(msg)
        self.a2l.stdin.flush()
        out = self.a2l.stdout.readline()
        return out.strip().decode('utf-8')

# ==========================================
# 3. BACKGROUND THREADS & PROTOCOLS
# ==========================================

class FtpWorker(QThread):
    """Handles FTP operations in background to keep UI responsive"""
    status_signal = Signal(str, str)  # status_msg, color_code
    listing_signal = Signal(list)     # list of items for the model
    progress_signal = Signal(str)     # Transfer details
    finished_signal = Signal()
    
    def __init__(self):
        super().__init__()
        self.ftp = None
        self.host = ""
        self.port = 1337
        self.current_path = "/"
        self.command_queue = [] 
        self.running = True
        self.mutex = threading.Lock()

    def add_command(self, cmd, *args):
        with self.mutex:
            self.command_queue.append((cmd, args))

    def run(self):
        while self.running:
            if self.command_queue:
                with self.mutex:
                    cmd, args = self.command_queue.pop(0)
                
                try:
                    if cmd == 'connect':
                        self._do_connect(args[0], args[1])
                    elif cmd == 'list':
                        self._do_list(args[0])
                    elif cmd == 'upload':
                        self._do_upload(args[0], args[1], args[2]) # Added force_replace arg
                    elif cmd == 'download':
                        self._do_download(args[0], args[1])
                    elif cmd == 'mk_dir':
                        self._do_mkdir(args[0])
                    elif cmd == 'rename':
                        self._do_rename(args[0], args[1])
                    elif cmd == 'delete':
                        self._do_delete(args[0], args[1])
                except ftplib.error_perm as e:
                    # Specific FTP error for file exists/permission issues
                    self.status_signal.emit(f"FTP Permission Error: {str(e)}", "red")
                    self.progress_signal.emit("Error")
                except Exception as e:
                    self.status_signal.emit(f"FTP Error: {str(e)}", "red")
                    self.progress_signal.emit("Error")
            
            time.sleep(0.1)

    def _do_connect(self, ip, port):
        self.status_signal.emit(f"Connecting to {ip}:{port}...", "orange")
        try:
            self.ftp = ftplib.FTP()
            self.ftp.connect(ip, int(port), timeout=10)
            self.ftp.login() 
            self.host = ip
            self.status_signal.emit(f"Connected to Console @ {ip}", "#3ecf4c") 
            self.progress_signal.emit("Idle")
            self._do_list("/")
        except Exception as e:
            self.status_signal.emit(f"Connection Failed: {e}", "red")

    def _do_list(self, path):
        if not self.ftp:
            return
        try:
            self.ftp.cwd(path)
            self.current_path = path
            
            entries = []
            lines = []
            self.ftp.dir(lines.append)
            
            for line in lines:
                parts = line.split()
                if len(parts) < 9:
                    continue
                
                name = " ".join(parts[8:])
                is_dir = line.startswith('d')
                size = parts[4]
                date = f"{parts[5]} {parts[6]} {parts[7]}"
                
                if name == "." or name == "..":
                    continue
                
                entries.append({
                    "name": name,
                    "is_dir": is_dir,
                    "size": size,
                    "date": date
                })
            
            entries.sort(key=lambda x: (not x['is_dir'], x['name']))
            self.listing_signal.emit(entries)
            
        except Exception as e:
            self.status_signal.emit(f"List Error: {e}", "orange")

    def _do_upload(self, local_path, remote_name, force_replace=False):
        if not self.ftp:
            return
        try:
            self.progress_signal.emit(f"Uploading {remote_name}...")
            # Check if file exists, if not forcing replace
            if not force_replace:
                try:
                    self.ftp.size(remote_name)
                    # If size call succeeds, file exists
                    raise FileExistsError(f"File '{remote_name}' already exists on remote server.")
                except ftplib.error_perm as e:
                    # 550 File not found is expected if file doesn't exist.
                    # Any other error is an issue, so we continue.
                    if '550' not in str(e):
                        # The error contains 550 if the file is not found, which is fine.
                        # If it contains 550 but another message, or another error, it might be a problem.
                        pass
                    elif '550' in str(e) and 'No such file or directory' not in str(e):
                         # If it's a 550 error but *not* file not found (e.g., 550 Permission denied)
                         raise
                except Exception as e:
                    # Catch other exceptions from size() call if they occur
                    self.status_signal.emit(f"Upload Pre-check Error: {e}", "red")
                    self.progress_signal.emit("Error")
                    return

            # Note: STOR command uses the current working directory, so remote_name is just the file name.
            # However, for upload and launch, the filename is the full path. We'll rely on the
            # VitaCompanion FTP server allowing full paths in the STOR command for simplicity here.
            with open(local_path, 'rb') as f:
                # Use the full path provided by the caller for STOR
                self.ftp.storbinary(f'STOR {remote_name}', f) 
                
            self.status_signal.emit(f"Upload Complete: {os.path.basename(local_path)} to {remote_name}", "#3ecf4c")
            self.progress_signal.emit("Idle")
            
            # If the upload destination is the current directory, refresh the view
            if remote_name.startswith('ux0:/') or remote_name.startswith('ur0:/'):
                # We can't refresh if the full path was used in STOR unless we change directory first
                pass
            else:
                 self._do_list(self.current_path) 

        except FileExistsError:
            self.status_signal.emit(f"Upload Failed: File exists. Use 'Upload & Replace' or delete first.", "red")
            self.progress_signal.emit("Error")
        except Exception as e:
            self.status_signal.emit(f"Upload Error: {e}", "red")
            self.progress_signal.emit("Error")

    def _do_download(self, remote_name, local_path):
        if not self.ftp:
            return
        try:
            self.progress_signal.emit(f"Downloading {remote_name}...")
            # We use os.path.basename to get the final filename, even if remote_name was a full path (unlikely in this context)
            local_filename = os.path.join(local_path, os.path.basename(remote_name))
            with open(local_filename, 'wb') as f:
                self.ftp.retrbinary(f'RETR {remote_name}', f.write)
            self.status_signal.emit(f"Download Complete: {remote_name}", "#3ecf4c")
            self.progress_signal.emit("Idle")
        except Exception as e:
            self.status_signal.emit(f"Download Error: {e}", "red")

    def _do_mkdir(self, folder_name):
        if not self.ftp:
            return
        try:
            self.ftp.mkd(folder_name)
            self._do_list(self.current_path)
        except Exception as e:
            self.status_signal.emit(f"Mkdir Error: {e}", "red")

    def _do_rename(self, old_name, new_name):
        if not self.ftp:
            return
        try:
            self.progress_signal.emit(f"Renaming {old_name} -> {new_name}...")
            self.ftp.rename(old_name, new_name)
            self.status_signal.emit(f"Renamed to {new_name}", "#3ecf4c")
            self.progress_signal.emit("Idle")
            self._do_list(self.current_path)
        except Exception as e:
            self.status_signal.emit(f"Rename Error: {e}", "red")
            self.progress_signal.emit("Error")

    def _do_delete(self, name, is_dir):
        if not self.ftp:
            return
        try:
            self.progress_signal.emit(f"Deleting {name}...")
            if is_dir:
                # NOTE: will only work if directory is empty
                self.ftp.rmd(name)
            else:
                self.ftp.delete(name)
            self.status_signal.emit(f"Deleted: {name}", "#3ecf4c")
            self.progress_signal.emit("Idle")
            self._do_list(self.current_path)
        except Exception as e:
            self.status_signal.emit(f"Delete Error: {e}", "red")

    def stop(self):
        self.running = False
        if self.ftp:
            try:
                self.ftp.quit()
            except Exception:
                pass
        self.wait()


class CommandWorker(QThread):
    """Handles sending commands to VitaCompanion on port 1338"""
    command_output_signal = Signal(str, str) # message, color

    def __init__(self):
        super().__init__()
        self.host = ""
        self.port = 1338
        self.command_queue = []
        self.running = True
        self.mutex = threading.Lock()

    def add_command(self, cmd_string):
        with self.mutex:
            self.command_queue.append(cmd_string)

    def run(self):
        while self.running:
            if self.command_queue:
                with self.mutex:
                    command = self.command_queue.pop(0)

                self._do_send_command(command)
            
            time.sleep(0.1)

    def _do_send_command(self, command):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                self.command_output_signal.emit(f"Attempting to send command: '{command}'", "orange")
                s.connect((self.host, self.port))
                
                # Command must be terminated by a newline
                s.sendall(f"{command}\n".encode('utf-8'))
                
                # Receive response (optional, but good practice)
                response = s.recv(1024).decode('utf-8', errors='ignore').strip()
                
                if response:
                    self.command_output_signal.emit(f"Command '{command}' sent. Response: {response}", "#3ecf4c")
                else:
                    self.command_output_signal.emit(f"Command '{command}' sent. No response received.", "#3ecf4c")

        except ConnectionRefusedError:
            self.command_output_signal.emit(f"Command Failed: Connection refused to {self.host}:{self.port}. Is VitaCompanion running?", "red")
        except socket.timeout:
            self.command_output_signal.emit(f"Command Failed: Timeout connecting to {self.host}:{self.port}.", "red")
        except Exception as e:
            self.command_output_signal.emit(f"Command Error: {e}", "red")

    def set_host(self, host):
        self.host = host

    def stop(self):
        self.running = False
        self.wait()

class DumpParserThread(QThread):
    output_signal = Signal(str)
    finished_signal = Signal()
    progress_signal = Signal(str) # For UI

    def __init__(self, core_file, elf_file, sdk_path=None):
        super().__init__()
        self.core_file = core_file
        self.elf_file = elf_file
        self.sdk_path = sdk_path

    def run(self):
        global LOG_CALLBACK
        LOG_CALLBACK = self.emit_log
        
        self.progress_signal.emit("Parsing...")
        try:
            self.emit_log(f"--- Starting Analysis ---\nCore: {self.core_file}\nELF: {self.elf_file}\nSDK Path: {self.sdk_path}\n")
            
            core = CoreParser(self.core_file)
            elf = ElfParserObj(self.elf_file, self.sdk_path)

            str_stop_reason = defaultdict(str, {
                0: "No reason", 0x30002: "Undefined instruction exception",
                0x30003: "Prefetch abort exception", 0x30004: "Data abort exception",
                0x60080: "Division by zero",
            })
            str_status = defaultdict(str, {1: "Running", 8: "Waiting", 16: "Not started"})
            reg_names = {13: "SP", 14: "LR", 15: "PC"}

            iprint("=== THREADS ===")
            crashed = []
            
            with IndentManager():
                for thread in core.threads:
                    if thread.stop_reason != 0:
                        crashed.append(thread)
                    
                    iprint(thread.name)
                    with IndentManager():
                        iprint("ID: 0x{:x}".format(thread.uid))
                        iprint("Stop reason: 0x{:x} ({})".format(thread.stop_reason, str_stop_reason[thread.stop_reason]))
                        iprint("Status: 0x{:x} ({})".format(thread.status, str_status[thread.status]))
                        
                        pc = core.get_address_notation("PC", thread.pc)
                        iprint(pc.to_string(elf))
                        if not pc.is_located() and thread.regs:
                            lr_val = thread.regs.gpr[14] if thread.regs else 0
                            iprint(core.get_address_notation("LR", lr_val).to_string(elf))

            iprint()
            
            for thread in crashed:
                iprint('=== THREAD "{}" <0x{:x}> CRASHED ({}) ==='.format(
                    thread.name, thread.uid, str_stop_reason[thread.stop_reason]))

                pc = core.get_address_notation('PC', thread.regs.gpr[15] if thread.regs else thread.pc)
                pc.print_disas_if_available(elf)
                
                lr = core.get_address_notation('LR', thread.regs.gpr[14] if thread.regs else 0)
                lr.print_disas_if_available(elf)

                iprint("REGISTERS:")
                with IndentManager():
                    if thread.regs:
                        for x in range(16):
                            reg = reg_names.get(x, "R{}".format(x))
                            iprint("{}: 0x{:x}".format(reg, thread.regs.gpr[x]))
                        iprint(pc.to_string())
                        iprint(lr.to_string())
                    else:
                        iprint("No register info available.")

                iprint()
                iprint("STACK CONTENTS AROUND SP:")
                with IndentManager():
                    if thread.regs:
                        sp = thread.regs.gpr[13]
                        stackSize = 24
                        for x in range(-16, stackSize):
                            addr = 4 * x + sp
                            data = core.read_vaddr(addr, 4)
                            if data:
                                val = u32(data, 0)
                                prefix = "     "
                                if addr == sp:
                                    prefix = "SP =>"
                                data_notation = core.get_address_notation("{} 0x{:x}".format(prefix, addr), val)
                                iprint(data_notation.to_string(elf))
                    else:
                        iprint("No stack info available.")


        except Exception as e:
            import traceback
            self.emit_log(f"\nCRITICAL ERROR DURING PARSE:\n{str(e)}\n{traceback.format_exc()}")
            self.progress_signal.emit("Error")
        
        self.emit_log("\n--- Analysis Finished ---")
        self.finished_signal.emit()

    def emit_log(self, text):
        self.output_signal.emit(str(text))


class LogServerThread(QThread):
    log_signal = Signal(str)

    def __init__(self, port=8080):
        super().__init__()
        self.port = port
        self.running = True
        self.server_socket = None

    def run(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.server_socket.bind(('0.0.0.0', self.port))
            self.log_signal.emit(f"--- Server Started on Port {self.port} ---\n")
            self.server_socket.listen(128)
            self.server_socket.settimeout(1.0) 

            while self.running:
                try:
                    client_socket, addr = self.server_socket.accept()
                    self.log_signal.emit(f"[{addr[0]}] Connected\n")
                    client_socket.settimeout(5.0)

                    with client_socket:
                        while self.running:
                            try:
                                data = client_socket.recv(1024)
                                if not data:
                                    break
                                text_data = data.decode('utf-8', errors='replace')
                                self.log_signal.emit(text_data)
                            except socket.timeout:
                                continue
                            except OSError:
                                break
                    self.log_signal.emit(f"[{addr[0]}] Disconnected\n")

                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.log_signal.emit(f"Socket Error: {e}\n")

        except Exception as e:
            self.log_signal.emit(f"Bind/Listen Error: {e}\n")
        finally:
            if self.server_socket:
                self.server_socket.close()
            self.log_signal.emit("--- Server Stopped ---\n")

    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                # Force close on another thread to unblock accept()
                socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(('127.0.0.1', self.port))
            except Exception:
                pass
        self.wait()

# ==========================================
# 4. MAIN UI APPLICATION (CONTINUED)
# ==========================================

class ColorDot(QFrame):
    def __init__(self, color="#777"):
        super().__init__()
        self.color = QColor(color)
        self.setFixedSize(12, 12)

    def set_color(self, color):
        self.color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self.color)
        painter.setPen(Qt.NoPen)
        radius = min(self.width(), self.height()) / 2
        painter.drawEllipse(int(self.width()/2 - radius), int(self.height()/2 - radius), int(radius*2), int(radius*2))


class VitaDeckModern(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vitadeck - Manager & Debugger")
        self.resize(1200, 700)
        
        # Application State
        self.log_font_size = 12
        self.current_port = 8080
        self.parser_thread = None
        self.log_thread = None
        self.core_sdk_path = "" # Path to VitaSDK bin/
        
        # Build State
        self.build_dir = QDir.currentPath()
        self.build_process = QProcess()
        self.build_process.readyReadStandardOutput.connect(self.handle_build_output)
        self.build_process.readyReadStandardError.connect(self.handle_build_output)
        self.build_process.finished.connect(self.build_process_finished)
        self.build_queue = []
        
        # FIX: Initialize ip_entry here so it exists when setup_ftp_tab is called later
        self.ip_entry = QLineEdit("192.168.1.21") 
        
        # Files for parser
        self.selected_elf = None
        self.selected_core = None

        main_layout = QVBoxLayout(self)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")

        # Tab 1: Logging
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setObjectName("logOutput")
        log_layout.addWidget(self.log_output)
        self.tabs.addTab(log_tab, "Logging")

        # Tab 2: Core dump
        core_tab = QWidget()
        core_layout = QVBoxLayout(core_tab)
        
        # --- Toolbar for Core Dump Controls ---
        core_controls_layout = QHBoxLayout()
        core_controls_layout.setContentsMargins(0, 0, 0, 10)
        
        self.btn_load_elf = QPushButton("Load .elf")
        self.btn_load_elf.clicked.connect(self.load_elf_file)
        
        self.btn_load_crash = QPushButton("Load crash")
        self.btn_load_crash.clicked.connect(self.load_crash_file)
        
        self.btn_parse = QPushButton("Analyze Crash Dump")
        self.btn_parse.setEnabled(False) 
        self.btn_parse.clicked.connect(self.start_core_parser)
        
        core_controls_layout.addWidget(self.btn_load_elf)
        core_controls_layout.addWidget(self.btn_load_crash)
        core_controls_layout.addWidget(self.btn_parse)
        core_controls_layout.addStretch()
        
        core_layout.addLayout(core_controls_layout)
        
        # --- Core Output Text ---
        core_layout.addWidget(QLabel("Core Dump Analysis Output:"))
        self.core_output = QPlainTextEdit()
        self.core_output.setReadOnly(True)
        self.core_output.setObjectName("logOutput")
        core_layout.addWidget(self.core_output)
        
        self.tabs.addTab(core_tab, "Core dump")

        # Tab 3: Build (New Tab)
        build_tab = QWidget()
        self.setup_build_tab()
        #self.tabs.addTab(build_tab, "Build") # Renamed from "Command palette"

        # Tab 4: File transfer
        ft_tab = QWidget()
        ft_layout = QVBoxLayout(ft_tab)
        self.setup_ftp_tab(ft_layout)
        self.tabs.addTab(ft_tab, "File Transfer")

        # Tab 5: SDK Installation (NEW)
        sdk_install_tab = QWidget()
        self.setup_sdk_installation_tab(sdk_install_tab)
        self.tabs.addTab(sdk_install_tab, "SDK Installation")

        # Tab 6: Settings
        st_tab = QWidget()
        self.setup_settings_tab(st_tab)
        self.tabs.addTab(st_tab, "Settings ⚙")

        content_and_sidebar = QHBoxLayout()
        content_and_sidebar.addWidget(self.tabs, stretch=4)

        # Sidebar (simplified)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sb = QVBoxLayout(sidebar)
        
        # 1. PS Vita IP
        sb.addWidget(QLabel("PS Vita IP"))
        sb.addWidget(self.ip_entry) 
        self.ip_entry.textChanged.connect(self.update_command_worker_host)

        btn_reconnect = QPushButton("Reconnect")
        btn_reconnect.clicked.connect(self.ftp_connect)
        sb.addWidget(btn_reconnect)
        sb.addSpacing(12)

        # 2. CORE DUMPS SIDEBAR
        sb.addWidget(QLabel("Core Dumps Quick Actions"))
        btn_fetch_parse = QPushButton("Fetch and parse last crash")
        btn_fetch_parse.clicked.connect(self.fetch_and_parse_last_crash)
        sb.addWidget(btn_fetch_parse)
        sb.addWidget(QPushButton("Fetch and parse (VCP)")) # VCP not implemented in this version

        sb.addSpacing(12)
        
        # 3. RUN EXECUTABLE SIDEBAR (MOVED FROM COMMAND PALETTE)
        self.setup_run_executable_sidebar(sb)
        
        sb.addSpacing(12) 
        
        # 4. QUICK COMMANDS SIDEBAR (UPDATED)
        grp_quick_sb = QGroupBox("Quick Commands")
        quick_layout_sb = QVBoxLayout(grp_quick_sb)

        btn_quit_all_sb = QPushButton("Quit All Apps")
        btn_quit_all_sb.clicked.connect(lambda: self.send_command("destroy"))
        quick_layout_sb.addWidget(btn_quit_all_sb)

        btn_reboot_sb = QPushButton("Reboot Console")
        btn_reboot_sb.clicked.connect(lambda: self.send_command("reboot"))
        quick_layout_sb.addWidget(btn_reboot_sb)

        hbox_screen_sb = QHBoxLayout()
        btn_screen_on_sb = QPushButton("Screen ON")
        btn_screen_on_sb.clicked.connect(lambda: self.send_command("screen on"))
        btn_screen_off_sb = QPushButton("Screen OFF")
        btn_screen_off_sb.clicked.connect(lambda: self.send_command("screen off"))
        hbox_screen_sb.addWidget(btn_screen_on_sb)
        hbox_screen_sb.addWidget(btn_screen_off_sb)
        quick_layout_sb.addLayout(hbox_screen_sb)
        
        # MOVED: Launch Title ID control (as requested, below screen commands)
        hbox_launch = QHBoxLayout()
        self.launch_id_entry = QLineEdit("VHBB00001")
        self.launch_id_entry.setPlaceholderText("Enter Title ID")
        btn_launch_id = QPushButton("Launch Title ID")
        btn_launch_id.clicked.connect(self.launch_title_id)
        hbox_launch.addWidget(self.launch_id_entry)
        hbox_launch.addWidget(btn_launch_id)
        quick_layout_sb.addLayout(hbox_launch)
        
        grp_quick_sb.setLayout(quick_layout_sb)
        sb.addWidget(grp_quick_sb)

        sb.addStretch()

        content_and_sidebar.addWidget(sidebar, stretch=1)
        main_layout.addLayout(content_and_sidebar)

        # Status Bar
        status_bar = QHBoxLayout()
        status_bar.setContentsMargins(10, 5, 10, 10)
        self.conn_dot = ColorDot("#777")
        status_bar.addWidget(self.conn_dot)
        self.conn_label = QLabel(f"Not connected")
        self.conn_label.setStyleSheet("color: #777;")
        status_bar.addWidget(self.conn_label)
        status_bar.addSpacing(30)
        self.ft_dot = ColorDot("#777")
        status_bar.addWidget(self.ft_dot)
        self.ft_label = QLabel("No file transfer in progress")
        self.ft_label.setStyleSheet("color: #777;")
        status_bar.addWidget(self.ft_label)
        status_bar.addStretch()
        main_layout.addLayout(status_bar)

        # Initialize Workers
        self.ftp_thread = FtpWorker()
        self.ftp_thread.status_signal.connect(self.update_connection_status)
        self.ftp_thread.listing_signal.connect(self.update_remote_view)
        self.ftp_thread.progress_signal.connect(self.update_transfer_status)
        self.ftp_thread.start()
        
        self.cmd_thread = CommandWorker()
        self.cmd_thread.command_output_signal.connect(self.log_command_output)
        self.cmd_thread.set_host(self.ip_entry.text())
        self.cmd_thread.start()

        self.apply_style()
        self.update_font(0) 

        # Start Server
        self.start_log_server(self.current_port)

    # In class VitaDeckModern:

    # ==========================
    #  New Tab Logic
    # ==========================
    def setup_sdk_installation_tab(self, parent_widget):
        """Sets up the layout for the SDK Installation tab."""
        # Implementation will be added later, as requested.
        layout = QVBoxLayout(parent_widget)
        layout.setAlignment(Qt.AlignTop)
        
        grp_install = QGroupBox("Vita SDK Installer")
        install_layout = QVBoxLayout(grp_install)
        install_layout.addWidget(QLabel("SDK Installation features will be implemented here later."))
        
        # Placeholder button
        btn_install_placeholder = QPushButton("Start SDK Installation (Future Feature)")
        install_layout.addWidget(btn_install_placeholder)
        
        layout.addWidget(grp_install)
        layout.addStretch()

    
    # ==========================
    #  Build Tab Logic (FIXED)
    # ==========================

    def setup_build_tab(self):
        build_tab = QWidget()
        main_build_layout = QVBoxLayout(build_tab)

        # --- TOP SECTION: HORIZONTAL (Directory | Commands) ---
        top_row_layout = QHBoxLayout()

        # 1. Build Directory Group
        self.build_dir_group = QGroupBox("Build Directory")
        build_dir_layout = QVBoxLayout()
        
        path_row = QHBoxLayout()
        self.build_dir_input = QLineEdit(self.build_dir) 
        self.btn_browse_build = QPushButton("Browse")
        self.btn_browse_build.setFixedWidth(80)
        self.btn_browse_build.clicked.connect(self.browse_build_dir)
        
        path_row.addWidget(self.build_dir_input)
        path_row.addWidget(self.btn_browse_build)
        
        self.btn_term = QPushButton("Open Terminal in Build Directory")
        self.btn_term.clicked.connect(self.open_terminal_in_build_dir)

        build_dir_layout.addLayout(path_row)
        build_dir_layout.addWidget(self.btn_term)
        self.build_dir_group.setLayout(build_dir_layout)

        # 2. Build Commands Group
        self.build_cmd_group = QGroupBox("Build Commands")
        build_cmd_layout = QVBoxLayout()

        self.btn_rebuild = QPushButton("Rebuild (make clean make)")
        self.btn_rebuild.clicked.connect(lambda: self.run_build_sequence("rebuild"))
        
        self.btn_full_build = QPushButton("Full Build (rm -rf *, cmake .., make)")
        self.btn_full_build.clicked.connect(lambda: self.run_build_sequence("full_build"))

        build_cmd_layout.addWidget(self.btn_rebuild)
        build_cmd_layout.addWidget(self.btn_full_build)
        self.build_cmd_group.setLayout(build_cmd_layout)

        # Add groups to Horizontal Layout
        top_row_layout.addWidget(self.build_dir_group, 3) 
        top_row_layout.addWidget(self.build_cmd_group, 2)
        main_build_layout.addLayout(top_row_layout)

        # --- BOTTOM SECTION: Output ---
        output_label = QLabel("Build Output:")
        main_build_layout.addWidget(output_label)

        self.build_output = QPlainTextEdit()
        self.build_output.setReadOnly(True)
        # FIX FOR BUG 2: Force Black Background
        self.build_output.setStyleSheet("""
            QPlainTextEdit {
                background-color: #000000; 
                color: #3ecf4c; 
                font-family: Consolas, Monospace;
                border: 1px solid #444;
            }
        """)
        main_build_layout.addWidget(self.build_output)

        self.tabs.addTab(build_tab, "Build")

    # ==========================
    #  Helper Functions
    # ==========================

    def browse_build_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Build Directory", self.build_dir)
        if folder:
            self.build_dir = folder
            self.build_dir_input.setText(folder)
            self.update_build_dir(folder)

    def update_build_dir(self, path):
        self.build_dir = path
        self.build_process.setWorkingDirectory(path)

    def open_terminal_in_build_dir(self):
        current_dir = self.build_dir
        if not os.path.isdir(current_dir):
            QMessageBox.warning(self, "Error", "Build directory not found.")
            return

        if sys.platform == "win32":
            subprocess.Popen(['start', 'cmd', '/K', 'cd', '/D', current_dir], shell=True)
        elif sys.platform == "darwin":
            subprocess.Popen(['open', '-a', 'Terminal', current_dir])
        else:
            # Linux fallback
            try:
                subprocess.Popen(['gnome-terminal', '--working-directory', current_dir])
            except FileNotFoundError:
                try:
                    subprocess.Popen(['xterm', '-e', f'cd "{current_dir}" && bash'])
                except FileNotFoundError:
                    QMessageBox.warning(self, "Error", "No terminal found.")

    def open_terminal(self):
        import subprocess
        if os.name == 'nt':
            subprocess.Popen(['start', 'cmd', '/k', f'cd /d {self.build_dir}'], shell=True)
        else:
            subprocess.Popen(['x-terminal-emulator', '--working-directory=' + self.build_dir])





    def run_build_sequence(self, mode):
        if self.build_process.state() != QProcess.NotRunning:
            QMessageBox.warning(self, "Build In Progress", "A build process is already running.")
            return
            
        build_path = self.build_dir
        if not build_path or not os.path.isdir(build_path):
            QMessageBox.warning(self, "Error", "Invalid build directory.")
            return

        self.build_output.clear()
        self.build_output.appendPlainText(f"--- Starting {mode.upper()} in {build_path} ---\n")
        
        # Disable buttons during build
        self.set_build_buttons_enabled(False)

        if mode == "rebuild":
            self.build_queue = [['make', ['clean']], ['make', []]]
        elif mode == "full_build":
            # Full build sequence: remove_contents, cmake, make
            self.build_queue = [['python_cleanup'], ['cmake', ['..']], ['make', []]]
        
        self.execute_next_build_command()

    def execute_next_build_command(self):
        if not self.build_queue:
            self.build_output.appendPlainText("\n--- Build Sequence Complete ---")
            self.set_build_buttons_enabled(True)
            return

        command_info = self.build_queue.pop(0)
        command = command_info[0]
        args = command_info[1]

        if command == 'python_cleanup':
            self.build_output.appendPlainText("Running Python cleanup (removing all files in directory)...")
            try:
                # Remove all files and folders in the build directory, except the directory itself
                for item in os.listdir(self.build_dir):
                    item_path = os.path.join(self.build_dir, item)
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                self.build_output.appendPlainText("Cleanup complete.")
                self.execute_next_build_command()
            except Exception as e:
                self.build_output.appendPlainText(f"Cleanup Error: {e}")
                self.set_build_buttons_enabled(True)
            return

        self.build_output.appendPlainText(f"\n> Running: {command} {' '.join(args)}")
        self.build_process.setWorkingDirectory(self.build_dir)
        self.build_process.start(command, args)
        if not self.build_process.waitForStarted(1000):
            self.build_output.appendPlainText(f"ERROR: Failed to start process: {command}. Is it in PATH?")
            self.set_build_buttons_enabled(True)
            
    def set_build_buttons_enabled(self, enabled):
        # Find the buttons inside the Build Commands QGroupBox
        grp_cmds = self.findChild(QGroupBox, "Build Commands") 
        if grp_cmds:
            for widget in grp_cmds.findChildren(QPushButton):
                if widget.objectName().startswith("btn_"):
                    widget.setEnabled(enabled)

    @Slot()
    def handle_build_output(self):
        # Read standard output
        data_out = self.build_process.readAllStandardOutput().data().decode('utf-8', errors='ignore')
        if data_out:
            self.build_output.moveCursor(QTextCursor.End)
            self.build_output.insertPlainText(data_out)
            self.build_output.moveCursor(QTextCursor.End)
        
        # Read standard error
        data_err = self.build_process.readAllStandardError().data().decode('utf-8', errors='ignore')
        if data_err:
            self.build_output.moveCursor(QTextCursor.End)
            self.build_output.insertPlainText(data_err)
            self.build_output.moveCursor(QTextCursor.End)

    @Slot(int, QProcess.ExitStatus)
    def build_process_finished(self, exitCode, exitStatus):
        if exitCode != 0 or exitStatus != QProcess.NormalExit:
            self.build_output.appendPlainText(f"\n!!! Command failed (Exit Code: {exitCode}) !!!")
            self.set_build_buttons_enabled(True)
            return
        
        self.execute_next_build_command() # Run next command in queue

    # ==========================
    #  Settings Logic
    # ==========================
    def setup_settings_tab(self, parent_widget):
        layout = QVBoxLayout(parent_widget)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignTop)

        # 1. Vita SDK Config
        grp_sdk = QGroupBox("Vita SDK Configuration (for Crash Analysis)")
        sdk_layout = QVBoxLayout(grp_sdk)
        sdk_layout.addWidget(QLabel("Path to VitaSDK 'bin' folder (e.g. C:/VitaSDK/bin):"))
        
        hbox_sdk = QHBoxLayout()
        self.sdk_path_input = QLineEdit()
        self.sdk_path_input.setPlaceholderText("Select folder containing arm-vita-eabi-objdump...")
        self.sdk_path_input.textChanged.connect(self.update_sdk_path)
        
        btn_browse_sdk = QPushButton("Browse")
        btn_browse_sdk.clicked.connect(self.browse_sdk_path)
        
        hbox_sdk.addWidget(self.sdk_path_input)
        hbox_sdk.addWidget(btn_browse_sdk)
        
        sdk_layout.addLayout(hbox_sdk)
        
        # Crash Dump Folder Setting
        sdk_layout.addWidget(QLabel("Custom Folder for ELF/Crash Dump Storage:"))
        hbox_dump_folder = QHBoxLayout()
        self.dump_folder_input = QLineEdit(os.getcwd())
        self.dump_folder_input.setPlaceholderText("Select folder for downloaded dumps and ELFs...")
        
        btn_browse_dump = QPushButton("Browse")
        btn_browse_dump.clicked.connect(self.browse_dump_folder)
        
        hbox_dump_folder.addWidget(self.dump_folder_input)
        hbox_dump_folder.addWidget(btn_browse_dump)
        sdk_layout.addLayout(hbox_dump_folder)
        
        layout.addWidget(grp_sdk)
        self.core_sdk_path = self.sdk_path_input.text().strip()


        # 2. Server Config
        grp_server = QGroupBox("Logging Server Configuration")
        srv_layout = QVBoxLayout(grp_server)
        lbl_port = QLabel("Listening Port:")
        self.port_input = QLineEdit(str(self.current_port))
        self.port_input.setValidator(QIntValidator(1024, 65535))
        btn_apply_port = QPushButton("Apply & Restart Server")
        btn_apply_port.setCursor(Qt.PointingHandCursor)
        btn_apply_port.clicked.connect(self.restart_server_with_new_port)
        srv_layout.addWidget(lbl_port)
        srv_layout.addWidget(self.port_input)
        srv_layout.addWidget(btn_apply_port)
        layout.addWidget(grp_server)

        # 3. Appearance
        grp_appearance = QGroupBox("Log Appearance")
        app_layout = QVBoxLayout(grp_appearance)
        font_ctrl_layout = QHBoxLayout()
        self.lbl_font_size = QLabel(f"Font Size: {self.log_font_size}px")
        
        btn_minus = QPushButton("-")
        btn_minus.setFixedSize(40, 30)
        btn_minus.clicked.connect(lambda: self.update_font(-1))
        
        btn_plus = QPushButton("+")
        btn_plus.setFixedSize(40, 30)
        btn_plus.clicked.connect(lambda: self.update_font(1))

        font_ctrl_layout.addWidget(self.lbl_font_size)
        font_ctrl_layout.addStretch()
        font_ctrl_layout.addWidget(btn_minus)
        font_ctrl_layout.addWidget(btn_plus)
        app_layout.addLayout(font_ctrl_layout)

        app_layout.addWidget(QLabel("Preview:"))
        self.preview_box = QPlainTextEdit()
        self.preview_box.setReadOnly(True)
        self.preview_box.setMaximumHeight(80)
        self.preview_box.setPlainText("DEBUG: socket initialized\nINFO: connection accepted")
        self.preview_box.setObjectName("logOutput")
        app_layout.addWidget(self.preview_box)
        layout.addWidget(grp_appearance)
        layout.addStretch()

    def browse_sdk_path(self):
        folder = QFileDialog.getExistingDirectory(self, "Select VitaSDK bin directory")
        if folder:
            self.sdk_path_input.setText(folder)
            self.update_sdk_path(folder)

    def update_sdk_path(self, path):
        self.core_sdk_path = path

    def browse_dump_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Crash Dump/ELF directory")
        if folder:
            self.dump_folder_input.setText(folder)

    def update_font(self, delta):
        new_size = self.log_font_size + delta
        if new_size < 8:
            new_size = 8
        if new_size > 32:
            new_size = 32
        
        self.log_font_size = new_size
        self.lbl_font_size.setText(f"Font Size: {self.log_font_size}px")

        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(self.log_font_size)

        self.log_output.setFont(font)
        self.core_output.setFont(font)
        self.preview_box.setFont(font)
        # Also update build output font
        if hasattr(self, 'build_output'):
            self.build_output.setFont(font)


    def restart_server_with_new_port(self):
        try:
            new_port = int(self.port_input.text())
        except ValueError:
            return

        self.log_gui_message(f"<b>Restarting server on port {new_port}...</b>", "#ff9900")
        if self.log_thread and self.log_thread.isRunning():
            self.log_thread.stop()
        self.current_port = new_port
        self.start_log_server(self.current_port)

    # ==========================
    #  Core Parser Logic
    # ==========================
    
    def load_elf_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, 
            "Select ELF File", 
            self.dump_folder_input.text(), 
            "ELF Binary (*.elf);;All Files (*)"
        )
        if not filename:
            return
            
        if not filename.lower().endswith(".elf"):
            self.log_gui_message("ERROR: Incorrect ELF format. File must end with <b>.elf</b>", "red")
            self.tabs.setCurrentIndex(0)
            return
            
        self.selected_elf = filename
        self.btn_load_elf.setText("ELF Loaded ✓")
        self.btn_load_elf.setStyleSheet("color: #3ecf4c; border: 1px solid #3ecf4c;")
        self.check_parse_ready()

    def load_crash_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, 
            "Select Crash Dump", 
            self.dump_folder_input.text(),
            "Core Dump (*.psp2dmp);;All Files (*)"
        )
        if not filename:
            return
            
        if not filename.lower().endswith(".psp2dmp"):
            self.log_gui_message("ERROR: Incorrect Crash Dump format. File must end with <b>.psp2dmp</b>", "red")
            self.tabs.setCurrentIndex(0)
            return
            
        self.selected_core = filename
        self.btn_load_crash.setText("Crash Loaded ✓")
        self.btn_load_crash.setStyleSheet("color: #3ecf4c; border: 1px solid #3ecf4c;")
        self.check_parse_ready()
        
    def check_parse_ready(self):
        if self.selected_elf and self.selected_core:
            self.btn_parse.setEnabled(True)
            self.btn_parse.setText("Analyze Crash Dump")
            self.btn_parse.setStyleSheet("background-color: #2f4f6f; color: white;")
        else:
            self.btn_parse.setEnabled(False)
            self.btn_parse.setText("Analyze Crash Dump")
            self.btn_parse.setStyleSheet("")

    def start_core_parser(self):
        if not self.selected_elf or not self.selected_core:
            return
        
        reply = QMessageBox.question(
            self,
            "Confirm Analysis",
            f"Start analysis for:\n\nELF: {os.path.basename(self.selected_elf)}\nDump: {os.path.basename(self.selected_core)}\n\nProceed?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return
            
        self.core_output.clear()
        self.core_output.appendPlainText("Initializing Parser...\n")

        self.parser_thread = DumpParserThread(self.selected_core, self.selected_elf, self.core_sdk_path)
        self.parser_thread.output_signal.connect(self.update_core_log)
        self.parser_thread.finished_signal.connect(self.parser_finished)
        self.parser_thread.progress_signal.connect(self.update_parser_progress)
        self.btn_parse.setEnabled(False)
        self.btn_parse.setText("Analyzing...")
        self.parser_thread.start()

    @Slot(str)
    def update_core_log(self, text):
        self.core_output.moveCursor(QTextCursor.End)
        self.core_output.insertPlainText(text) 
        self.core_output.moveCursor(QTextCursor.End)

    @Slot(str)
    def update_parser_progress(self, status):
        self.btn_parse.setText(f"Analyzing... ({status})")

    @Slot()
    def parser_finished(self):
        self.check_parse_ready() # Will re-enable if files are loaded
        self.core_output.appendPlainText("\nDone.")
        self.log_gui_message("Core Dump Analysis Finished.", "#3ecf4c")

    def fetch_and_parse_last_crash(self):
        # NOTE: This is a placeholder as the full logic to list and parse remote files is complex.
        
        QMessageBox.information(
            self, 
            "Feature Not Fully Implemented", 
            "This feature requires complex remote file listing and synchronization. "
            "In this version, please manually load the .elf and .psp2dmp files using 'Load .elf' and 'Load crash'."
        )
        self.tabs.setCurrentIndex(1)
        
    def log_gui_message(self, message, color="white"):
        self.log_output.moveCursor(QTextCursor.End)
        # Using a slight delay to ensure it appears after thread output
        QThread.msleep(10) 
        self.log_output.appendHtml(f"<br><font color='{color}'>{message}</font><br>")
        self.log_output.moveCursor(QTextCursor.End)

    # ==========================
    #  Log Server Logic
    # ==========================
    def start_log_server(self, port):
        self.log_thread = LogServerThread(port=port)
        self.log_thread.log_signal.connect(self.update_log)
        self.log_thread.start()

    @Slot(str)
    def update_log(self, text):
        self.log_output.moveCursor(QTextCursor.End)
        self.log_output.insertPlainText(text)
        self.log_output.moveCursor(QTextCursor.End)

    # ==========================
    #  Command Logic
    # ==========================
    def setup_run_executable_sidebar(self, layout):
        # --- Run Executable Group (Moved to Sidebar) ---
        grp_run = QGroupBox("Run Executable")
        run_layout = QVBoxLayout(grp_run)
        
        run_layout.addWidget(QLabel("Local eboot.bin/Self File:"))
        hbox_exec = QHBoxLayout()
        self.exec_entry = QLineEdit("D:/game/build/eboot.bin")
        btn_browse_exec = QPushButton("Browse")
        btn_browse_exec.clicked.connect(self.browse_exec_file)
        hbox_exec.addWidget(self.exec_entry)
        hbox_exec.addWidget(btn_browse_exec)
        run_layout.addLayout(hbox_exec)

        run_layout.addWidget(QLabel("Target App ID (e.g., APPL00001):"))
        self.appid_entry = QLineEdit("APPL00001")
        run_layout.addWidget(self.appid_entry)
        
        self.btn_upload_launch = QPushButton("Upload and Launch")
        self.btn_upload_launch.clicked.connect(self.upload_and_launch)
        run_layout.addWidget(self.btn_upload_launch)
        
        layout.addWidget(grp_run)

    # Removed setup_command_palette as its contents were moved or redundant

    def update_command_worker_host(self, host):
        self.cmd_thread.set_host(host)

    @Slot(str, str)
    def log_command_output(self, message, color):
        self.log_gui_message(message, color)

    def send_command(self, command):
        # Confirm for destructive commands
        if command in ("destroy", "reboot"):
            reply = QMessageBox.question(
                self,
                "Confirm Command",
                f"Are you sure you want to run '{command}'? This may close apps or reboot your device.",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        self.cmd_thread.add_command(command)
        self.tabs.setCurrentIndex(0) # Switch to log tab

    def launch_title_id(self):
        title_id = self.launch_id_entry.text().strip()
        if not title_id:
            QMessageBox.warning(self, "Input Error", "Please enter a Title ID to launch.")
            return
        self.send_command(f"launch {title_id}")

    def browse_exec_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Select eboot.bin/Self", "", "Executable Files (eboot.bin *.self);;All Files (*)")
        if filename:
            self.exec_entry.setText(filename)

    def upload_and_launch(self):
        local_path = self.exec_entry.text().strip()
        app_id = self.appid_entry.text().strip()
        
        if not os.path.isfile(local_path):
            QMessageBox.warning(self, "File Error", "Local executable file not found.")
            return

        if not app_id:
            QMessageBox.warning(self, "Input Error", "Please enter a target Application ID.")
            return

        # Remote path for eboot.bin replacement
        remote_path = f"ux0:/app/{app_id}/eboot.bin"
        
        reply = QMessageBox.question(
            self,
            "Confirm Upload & Launch",
            f"Upload '{os.path.basename(local_path)}' to '{remote_path}' and launch '{app_id}'?\n\nNOTE: This will overwrite the existing eboot.bin! Confirm to replace.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        # 1. Upload the file, forcing replace, using the full remote path.
        self.log_gui_message(f"Starting forced upload of {os.path.basename(local_path)} to {remote_path}...", "orange")
        
        # The FtpWorker will handle the upload and emit status signals.
        # We assume the FTP operation starts and the Command is queued immediately after.
        # A fully robust solution would use a signal/slot chain: FTP finished -> Command start.
        self.ftp_thread.add_command('upload', local_path, remote_path, True) # True for force_replace

        # 2. Send launch command immediately after starting upload.
        self.cmd_thread.add_command(f"launch {app_id}")
        self.tabs.setCurrentIndex(0) # Switch to log tab

    # ==========================
    #  FTP TAB LOGIC
    # ==========================

    def setup_ftp_tab(self, layout):
        # 1. Connection Bar
        conn_bar = QHBoxLayout()
        conn_bar.addWidget(QLabel("PS Vita IP:"))
        
        current_ip = self.ip_entry.text() if hasattr(self, 'ip_entry') else "192.168.1.21"
        self.ftp_ip_input = QLineEdit(current_ip)
        self.ftp_ip_input.textChanged.connect(self.ip_entry.setText) # Mirror IP
        conn_bar.addWidget(self.ftp_ip_input)
        
        conn_bar.addWidget(QLabel("Port:"))
        self.ftp_port_input = QLineEdit("1337") 
        self.ftp_port_input.setFixedWidth(60)
        conn_bar.addWidget(self.ftp_port_input)
        
        self.btn_ftp_connect = QPushButton("Connect")
        self.btn_ftp_connect.clicked.connect(self.ftp_connect)
        conn_bar.addWidget(self.btn_ftp_connect)
        
        conn_bar.addStretch()
        layout.addLayout(conn_bar)
        
        layout.addWidget(QFrame(frameShape=QFrame.HLine))

        # 2. Split View (Local vs Remote)
        splitter = QSplitter(Qt.Horizontal)
        
        # --- LEFT: LOCAL ---
        local_widget = QWidget()
        local_layout = QVBoxLayout(local_widget)
        local_layout.addWidget(QLabel("Local Site:"))
        
        self.local_model = QFileSystemModel()
        self.local_model.setRootPath(QDir.rootPath())
        
        self.local_tree = QTreeView()
        self.local_tree.setModel(self.local_model)
        self.local_tree.setRootIndex(self.local_model.index(os.path.expanduser("~"))) 
        self.local_tree.setColumnWidth(0, 200)
        self.local_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        local_layout.addWidget(self.local_tree)
        
        # --- MIDDLE: BUTTONS ---
        btn_layout = QVBoxLayout()
        btn_layout.addStretch()

        self.btn_upload = QPushButton("Upload ->")
        self.btn_upload.clicked.connect(self.ftp_upload_selected)
        btn_layout.addWidget(self.btn_upload)

        self.btn_upload_replace = QPushButton("Upload & Replace ->")
        self.btn_upload_replace.clicked.connect(lambda: self.ftp_upload_selected(force_replace=True))
        btn_layout.addWidget(self.btn_upload_replace)
        
        self.btn_download = QPushButton("<- Download")
        self.btn_download.clicked.connect(self.ftp_download_selected)
        btn_layout.addWidget(self.btn_download)

        self.btn_rename = QPushButton("Rename")
        self.btn_rename.clicked.connect(self.ftp_rename_selected)
        btn_layout.addWidget(self.btn_rename)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.clicked.connect(self.ftp_delete_selected)
        self.btn_delete.setStyleSheet("background-color: #8B0000; border: 1px solid #FF4500;") # Red color for delete
        btn_layout.addWidget(self.btn_delete)

        btn_layout.addStretch()
        
        btn_container = QWidget()
        btn_container.setLayout(btn_layout)

        # --- RIGHT: REMOTE ---
        remote_widget = QWidget()
        remote_layout = QVBoxLayout(remote_widget)
        remote_layout.addWidget(QLabel("Remote Site:"))
        
        self.remote_model = QStandardItemModel()
        self.remote_model.setHorizontalHeaderLabels(["Filename", "Size", "Date"])
        
        self.remote_tree = QTreeView()
        self.remote_tree.setModel(self.remote_model)
        self.remote_tree.doubleClicked.connect(self.remote_double_click)
        self.remote_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.remote_tree.customContextMenuRequested.connect(self.show_remote_context_menu)
        self.remote_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        remote_layout.addWidget(self.remote_tree)

        splitter.addWidget(local_widget)
        splitter.addWidget(btn_container)
        splitter.addWidget(remote_widget)
        splitter.setSizes([400, 50, 400])
        
        layout.addWidget(splitter)

    def ftp_connect(self):
        ip = self.ftp_ip_input.text()
        port = self.ftp_port_input.text()
        self.ftp_thread.add_command('connect', ip, port)
        self.btn_ftp_connect.setEnabled(False)
        self.btn_ftp_connect.setText("Connecting...")

    @Slot(str, str)
    def update_connection_status(self, msg, color_code):
        # Update Bottom Bar
        self.conn_label.setText(msg)
        self.conn_dot.set_color(color_code)
        self.conn_label.setStyleSheet(f"color: {color_code}; font-weight: bold;")
        
        # Update FTP Tab Button
        if "Connected" in msg:
            self.btn_ftp_connect.setText("Connected")
            self.btn_ftp_connect.setStyleSheet("background-color: #2e7d32; color: white;")
        elif "Failed" in msg or "Error" in msg:
            self.btn_ftp_connect.setEnabled(True)
            self.btn_ftp_connect.setText("Connect")
            self.btn_ftp_connect.setStyleSheet("")
        elif "Connecting" in msg:
            # Keep disabled during connection attempt
            pass
        else: # other status messages
            self.btn_ftp_connect.setEnabled(True)
            self.btn_ftp_connect.setText("Connect")
            self.btn_ftp_connect.setStyleSheet("")


    @Slot(list)
    def update_remote_view(self, entries):
        self.remote_model.removeRows(0, self.remote_model.rowCount())
        
        # Add ".." for going up
        if self.ftp_thread.current_path != "/":
            up_item = QStandardItem("..")
            up_item.setEditable(False)
            up_item.setData("dir", Qt.UserRole)
            self.remote_model.appendRow([up_item, QStandardItem(""), QStandardItem("")])

        file_icon = self.style().standardIcon(QStyle.SP_FileIcon)
        dir_icon = self.style().standardIcon(QStyle.SP_DirIcon)

        for entry in entries:
            name_item = QStandardItem(entry['name'])
            name_item.setEditable(False)
            
            if entry['is_dir']:
                name_item.setIcon(dir_icon)
                name_item.setData("dir", Qt.UserRole)
            else:
                name_item.setIcon(file_icon)
                name_item.setData("file", Qt.UserRole)
                
            size_item = QStandardItem(str(entry['size']))
            date_item = QStandardItem(entry['date'])
            
            self.remote_model.appendRow([name_item, size_item, date_item])

    def remote_double_click(self, index):
        name_idx = index.siblingAtColumn(0)
        item = self.remote_model.itemFromIndex(name_idx)
        name = item.text()
        type_data = item.data(Qt.UserRole)
        
        if name == "..":
            # Go Up
            new_path = os.path.dirname(self.ftp_thread.current_path.rstrip('/'))
            if not new_path:
                new_path = "/"
            self.ftp_thread.add_command('list', new_path)
            
        elif type_data == "dir":
            # Go Down
            current = self.ftp_thread.current_path
            # Normalize path for Vita format
            new_path = os.path.join(current.replace('\\', '/'), name.replace('\\', '/')).replace('\\', '/')
            if not new_path.startswith('/'):
                new_path = '/' + new_path
            self.ftp_thread.add_command('list', new_path)

    def ftp_upload_selected(self, force_replace=False):
        indexes = self.local_tree.selectionModel().selectedIndexes()
        if not indexes:
            return
        
        paths = []
        for idx in indexes:
            if idx.column() == 0:
                paths.append(self.local_model.filePath(idx))
        
        for path in paths:
            if os.path.isfile(path):
                filename = os.path.basename(path)
                
                # Confirmation for replace
                if force_replace:
                     reply = QMessageBox.question(
                        self,
                        "Confirm Replace",
                        f"Are you sure you want to replace '{filename}' on the remote server?",
                        QMessageBox.Yes | QMessageBox.No
                    )
                     if reply == QMessageBox.No:
                         continue
                
                # The remote_name in the worker is used in the STOR command.
                # If we're in the FTP tab, we assume it's relative to current path.
                self.ftp_thread.add_command('upload', path, filename, force_replace)
            elif os.path.isdir(path):
                QMessageBox.information(self, "Info", "Folder upload not implemented in this demo.")

    def ftp_download_selected(self):
        indexes = self.remote_tree.selectionModel().selectedIndexes()
        if not indexes:
            return
        
        # Get selected local directory
        local_dest = self.local_model.filePath(self.local_tree.currentIndex())
        if not local_dest or not os.path.isdir(local_dest):
            local_dest = self.dump_folder_input.text()
            QMessageBox.information(self, "Download Location", f"Downloading to default folder: {local_dest}")
            
        if not os.path.isdir(local_dest):
            local_dest = os.getcwd()
            
        for idx in indexes:
            if idx.column() == 0:
                item = self.remote_model.itemFromIndex(idx)
                if item.text() == "..":
                    continue
                
                if item.data(Qt.UserRole) == "file":
                    self.ftp_thread.add_command('download', item.text(), local_dest)

    def ftp_upload_dialog(self, force_replace=False):
        if not self.ftp_thread.ftp:
            QMessageBox.warning(self, "FTP", "Not connected to FTP server.")
            return

        paths, _ = QFileDialog.getOpenFileNames(self, "Select files to upload")
        for path in paths:
            if os.path.isfile(path):
                filename = os.path.basename(path)
                
                if force_replace:
                     reply = QMessageBox.question(
                        self,
                        "Confirm Replace",
                        f"Are you sure you want to replace '{filename}' on the remote server?",
                        QMessageBox.Yes | QMessageBox.No
                    )
                     if reply == QMessageBox.No:
                         continue
                
                # Remote name is the filename, as FTP Worker uses CWD
                self.ftp_thread.add_command('upload', path, filename, force_replace) 

    def ftp_download_names(self, names):
        local_dest = self.local_model.filePath(self.local_tree.currentIndex())
        if os.path.isfile(local_dest):
            local_dest = os.path.dirname(local_dest)
        if not local_dest:
            local_dest = self.dump_folder_input.text()
        if not os.path.isdir(local_dest):
            local_dest = os.getcwd()

        for name in names:
            self.ftp_thread.add_command('download', name, local_dest)

    def ftp_rename_item(self, name):
        new_name, ok = QInputDialog.getText(
            self,
            "Rename",
            f"New name for '{name}':",
            QLineEdit.Normal,
            name
        )
        if ok and new_name and new_name != name:
            self.ftp_thread.add_command('rename', name, new_name)

    def ftp_rename_selected(self):
        indexes = self.remote_tree.selectionModel().selectedIndexes()
        if not indexes:
            return

        for idx in indexes:
            if idx.column() == 0:
                item = self.remote_model.itemFromIndex(idx)
                name = item.text()
                if name == "..":
                    return
                self.ftp_rename_item(name)
                break

    def ftp_delete_item(self, name, is_dir):
        # Confirmation for delete
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to permanently delete '{name}'? This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.ftp_thread.add_command('delete', name, is_dir)

    def ftp_delete_selected(self):
        indexes = self.remote_tree.selectionModel().selectedIndexes()
        if not indexes:
            return

        items = []
        for idx in indexes:
            if idx.column() != 0:
                continue
            item = self.remote_model.itemFromIndex(idx)
            name = item.text()
            if name == "..":
                continue
            is_dir = item.data(Qt.UserRole) == "dir"
            items.append((name, is_dir))

        if not items:
            return

        if len(items) == 1:
            name, is_dir = items[0]
            self.ftp_delete_item(name, is_dir)
        else:
            # Confirmation for multiple items
            reply = QMessageBox.question(
                self,
                "Confirm Delete Multiple",
                f"Are you sure you want to permanently delete {len(items)} items? This action cannot be undone.",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                for name, is_dir in items:
                    self.ftp_thread.add_command('delete', name, is_dir)

    def show_remote_context_menu(self, pos):
        index = self.remote_tree.indexAt(pos)
        if not index.isValid():
            return

        name_idx = index.siblingAtColumn(0)
        item = self.remote_model.itemFromIndex(name_idx)
        name = item.text()
        if name == "..":
            return

        item_type = item.data(Qt.UserRole)
        is_dir = (item_type == "dir")

        menu = QMenu(self)

        # Upload: choose local files to upload to current remote directory
        upload_action = QAction("Upload...", self)
        upload_action.triggered.connect(lambda: self.ftp_upload_dialog(force_replace=False))
        menu.addAction(upload_action)
        
        # Upload and Replace
        upload_replace_action = QAction("Upload & Replace...", self)
        upload_replace_action.triggered.connect(lambda: self.ftp_upload_dialog(force_replace=True))
        menu.addAction(upload_replace_action)
        menu.addSeparator()

        # Download only for files
        if item_type == "file":
            download_action = QAction("Download", self)
            download_action.triggered.connect(lambda: self.ftp_download_names([name]))
            menu.addAction(download_action)
            menu.addSeparator()

        # Rename
        rename_action = QAction("Rename", self)
        rename_action.triggered.connect(lambda: self.ftp_rename_item(name))
        menu.addAction(rename_action)

        # Delete
        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(lambda: self.ftp_delete_item(name, is_dir))
        delete_action.setStyleSheet("color: red;") # Context menu item color
        menu.addAction(delete_action)

        menu.exec(self.remote_tree.viewport().mapToGlobal(pos))

    @Slot(str)
    def update_transfer_status(self, status):
        self.ft_label.setText(status)
        if "Uploading" in status or "Downloading" in status or "Renaming" in status or "Deleting" in status:
            self.ft_dot.set_color("#ff9900")  # Orange
            self.ft_label.setStyleSheet("color: #ff9900;")
        elif "Error" in status:
            self.ft_dot.set_color("red")
            self.ft_label.setStyleSheet("color: red;")
        else:
            self.ft_dot.set_color("#777")
            self.ft_label.setStyleSheet("color: #777;")

    def closeEvent(self, event):
        if self.log_thread:
            self.log_thread.stop()
        if self.ftp_thread:
            self.ftp_thread.stop()
        if self.cmd_thread:
            self.cmd_thread.stop()
        if self.build_process and self.build_process.state() != QProcess.NotRunning:
            self.build_process.terminate()
        event.accept()

    def apply_style(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                color: #dcdcdc;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QGroupBox {
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                margin-top: 20px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
                color: #aaa;
            }
            #sidebar {
                background-color: #252525;
                border-left: 1px solid #3c3c3c;
                padding: 12px;
            }
            QLineEdit {
                padding: 6px;
                border-radius: 5px;
                background-color: #2d2d2d;
                border: 1px solid #444;
                color: #e0e0e0;
            }
            QPushButton {
                background-color: #2f4f6f;
                border: 1px solid #3a5f80;
                padding: 8px 10px;
                border-radius: 4px;
                color: white;
            }
            QPushButton:hover {
                background-color: #3a668a;
            }
            QPushButton:pressed {
                background-color: #2a5975;
            }
            QPushButton:disabled {
                background-color: #222;
                color: #555;
                border: 1px solid #333;
            }
            /* Styling for the red delete button */
            QPushButton[style*="#8B0000"] { 
                background-color: #8B0000;
                border: 1px solid #FF4500;
            }
            QPushButton[style*="#8B0000"]:hover {
                background-color: #A52A2A;
            }
            QPushButton[style*="#8B0000"]:pressed {
                background-color: #690000;
            }
            QTabWidget::pane {
                border: 1px solid #3c3c3c;
                background: #1e1e1e;
            }
            QTabBar::tab {
                padding: 8px 18px;
                background: #2a2a2a;
                color: #dcdcdc;
                border: 1px solid #3c3c3c;
                border-bottom: none;
                border-radius: 6px 6px 0 0;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #3e3e3e;
                border-bottom: none;
                color: white;
            }
            QPlainTextEdit#logOutput {
                background-color: #111;
                border: 1px solid #333;
                padding: 8px;
                color: #c0c0c0;
            }
            QTreeView {
                alternate-background-color: #222222;
                background-color: #1e1e1e;
                border: 1px solid #333;
                selection-background-color: #2f4f6f;
            }
        """)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VitaDeckModern()
    window.show()
    sys.exit(app.exec())