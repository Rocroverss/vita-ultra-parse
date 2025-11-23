import sys
import socket
import threading
import struct
import string
import subprocess
import os
from collections import defaultdict

# PySide6 Imports
from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLabel, QLineEdit, QCheckBox, QTabWidget, QPlainTextEdit, QFileDialog,
    QFrame, QGroupBox, QSpinBox, QMessageBox
)
from PySide6.QtGui import QColor, QPainter, QTextCursor, QFont, QIntValidator
from PySide6.QtCore import Qt, QThread, Signal, Slot

# Elftools Import
try:
    from elftools.elf.elffile import ELFFile
except ImportError:
    print("Error: 'pyelftools' not installed. Please run 'pip install pyelftools'")
    sys.exit(1)

# ==========================================
# 1. UTILS & INDENT (Python 3)
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
        if not elf_parser: return
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
                iprint(f"Disassembly failed (Is arm-vita-eabi-objdump in PATH?): {e}")

    def to_string(self, elf_parser=None):
        if self.is_located():
            output = "{}: 0x{:x} ({}@{} + 0x{:x}".format(self.__symbol, self.__vaddr,
                       self.__module.name, self.__segment.num, self.__offset)
            if elf_parser and self.__module.name.endswith(".elf") and self.__segment.num == 1:
                try:
                    line_info = elf_parser.addr2line(self.__offset)
                    output += " => {}".format(line_info)
                except:
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
        # Handle GZIP check
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
        if "MODULE_INFO" not in self.notes: return
        data = self.notes["MODULE_INFO"]
        if isinstance(data, str): data = data.encode('latin-1')
        
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
        if "THREAD_INFO" not in self.notes: return
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
        if "THREAD_REG_INFO" not in self.notes: return
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
    def __init__(self, filename):
        self.filename = filename
        self.f = open(filename, "rb")
        self.elf = ELFFile(self.f)
        self.rx_vaddr = -1
        self.parse_segments()
        self.f.close()
        self.a2l = None

    def parse_segments(self):
        for seg in self.elf.iter_segments():
            if seg["p_type"] != "PT_LOAD": continue
            if seg["p_flags"] == 5: # RX
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

        args = ["arm-vita-eabi-objdump", "-d", "-S",
            "--start-address=0x{:x}".format(start), 
            "--stop-address=0x{:x}".format(end), 
            self.filename]
        
        if thumb:
            args += ['-Mforce-thumb']

        output = subprocess.check_output(args)
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
            self.a2l = subprocess.Popen(
                ["arm-vita-eabi-addr2line", "-e", self.filename, "-f", "-p", "-C"], 
                stdin=subprocess.PIPE, stdout=subprocess.PIPE
            )
        
        abs_addr = offset + self.rx_vaddr
        msg = f"{hex(abs_addr)}\n".encode('utf-8')
        self.a2l.stdin.write(msg)
        self.a2l.stdin.flush()
        out = self.a2l.stdout.readline()
        return out.strip().decode('utf-8')

# ==========================================
# 3. BACKGROUND THREADS
# ==========================================

class DumpParserThread(QThread):
    output_signal = Signal(str)
    finished_signal = Signal()

    def __init__(self, core_file, elf_file):
        super().__init__()
        self.core_file = core_file
        self.elf_file = elf_file

    def run(self):
        global LOG_CALLBACK
        LOG_CALLBACK = self.emit_log
        
        try:
            self.emit_log(f"--- Starting Analysis ---\nCore: {self.core_file}\nELF: {self.elf_file}\n")
            
            core = CoreParser(self.core_file)
            elf = ElfParserObj(self.elf_file)

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

                pc = core.get_address_notation('PC', thread.pc)
                pc.print_disas_if_available(elf)
                
                lr = core.get_address_notation('LR', thread.regs.gpr[14])
                lr.print_disas_if_available(elf)

                iprint("REGISTERS:")
                with IndentManager():
                    for x in range(16):
                        reg = reg_names.get(x, "R{}".format(x))
                        iprint("{}: 0x{:x}".format(reg, thread.regs.gpr[x]))
                    iprint(pc.to_string())
                    iprint(lr.to_string())

                iprint()
                iprint("STACK CONTENTS AROUND SP:")
                with IndentManager():
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

        except Exception as e:
            import traceback
            self.emit_log(f"\nCRITICAL ERROR DURING PARSE:\n{str(e)}\n{traceback.format_exc()}")
        
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
                                if not data: break
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
        self.wait()

# ==========================================
# 4. MAIN UI APPLICATION
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
        core_layout.addWidget(QLabel("Core Dump Analysis Output:"))
        self.core_output = QPlainTextEdit()
        self.core_output.setReadOnly(True)
        self.core_output.setObjectName("logOutput")
        core_layout.addWidget(self.core_output)
        self.tabs.addTab(core_tab, "Core dump")

        # Tab 3: Command palette
        cmd_tab = QWidget()
        cmd_layout = QVBoxLayout(cmd_tab)
        cmd_layout.addWidget(QLabel("Command palette content goes here..."))
        self.tabs.addTab(cmd_tab, "Command palette")

        # Tab 4: File transfer
        ft_tab = QWidget()
        ft_layout = QVBoxLayout(ft_tab)
        ft_layout.addWidget(QLabel("File transfer details go here..."))
        self.tabs.addTab(ft_tab, "File transfer")

        # Tab 5: Settings
        st_tab = QWidget()
        self.setup_settings_tab(st_tab)
        self.tabs.addTab(st_tab, "Settings ⚙")

        content_and_sidebar = QHBoxLayout()
        content_and_sidebar.addWidget(self.tabs, stretch=4)

        # Sidebar
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sb = QVBoxLayout(sidebar)

        sb.addWidget(QLabel("PS Vita IP"))
        self.ip_entry = QLineEdit("192.168.1.21")
        sb.addWidget(self.ip_entry)

        btn_reconnect = QPushButton("Reconnect")
        sb.addWidget(btn_reconnect)
        sb.addSpacing(12)

        # === CORE DUMPS SECTION (UPDATED) ===
        sb.addWidget(QLabel("Core dumps"))
        
        # Button 1: Load ELF
        self.btn_load_elf = QPushButton("Load .elf")
        self.btn_load_elf.clicked.connect(self.load_elf_file)
        sb.addWidget(self.btn_load_elf)

        # Button 2: Load Crash
        self.btn_load_crash = QPushButton("Load crash")
        self.btn_load_crash.clicked.connect(self.load_crash_file)
        sb.addWidget(self.btn_load_crash)
        
        # Button 3: Run Analysis (Disabled initially)
        self.btn_parse = QPushButton("Analyze Crash Dump")
        self.btn_parse.setEnabled(False) 
        self.btn_parse.clicked.connect(self.start_core_parser)
        sb.addWidget(self.btn_parse)

        sb.addSpacing(12)
        sb.addWidget(QLabel("Run executable"))
        self.exec_entry = QLineEdit("D:/Repos/demos/test/bu")
        sb.addWidget(self.exec_entry)
        self.appid_entry = QLineEdit("APPL00001")
        sb.addWidget(self.appid_entry)
        self.temp_checkbox = QCheckBox("Use temporary App ID")
        sb.addWidget(self.temp_checkbox)
        sb.addWidget(QPushButton("Upload and launch"))
        sb.addSpacing(12)
        sb.addWidget(QLabel("Quick commands"))
        sb.addWidget(QPushButton("Quit all apps"))
        sb.addWidget(QPushButton("Reboot"))
        sb.addStretch()

        content_and_sidebar.addWidget(sidebar, stretch=1)
        main_layout.addLayout(content_and_sidebar)

        # Status Bar
        status_bar = QHBoxLayout()
        status_bar.setContentsMargins(10, 5, 10, 10)
        self.conn_dot = ColorDot("#3ecf4c")
        status_bar.addWidget(self.conn_dot)
        self.conn_label = QLabel(f"Connected to the console @ {self.ip_entry.text()}")
        status_bar.addWidget(self.conn_label)
        status_bar.addSpacing(30)
        self.ft_dot = ColorDot("#777")
        status_bar.addWidget(self.ft_dot)
        self.ft_label = QLabel("No file transfer in progress")
        self.ft_label.setStyleSheet("color: #777;")
        status_bar.addWidget(self.ft_label)
        status_bar.addStretch()
        main_layout.addLayout(status_bar)

        self.apply_style()
        self.update_font(0) 

        # Start Server
        self.start_log_server(self.current_port)

    # ==========================
    #  Settings Logic
    # ==========================
    def setup_settings_tab(self, parent_widget):
        layout = QVBoxLayout(parent_widget)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignTop)

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

    def update_font(self, delta):
        new_size = self.log_font_size + delta
        if new_size < 8: new_size = 8
        if new_size > 32: new_size = 32
        
        self.log_font_size = new_size
        self.lbl_font_size.setText(f"Font Size: {self.log_font_size}px")

        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(self.log_font_size)

        self.log_output.setFont(font)
        self.core_output.setFont(font)
        self.preview_box.setFont(font)

    def restart_server_with_new_port(self):
        try:
            new_port = int(self.port_input.text())
        except ValueError:
            return

        self.log_output.appendHtml(f"<br><font color='#ff9900'><b>Restarting server on port {new_port}...</b></font><br>")
        if self.log_thread and self.log_thread.isRunning():
            self.log_thread.stop()
        self.current_port = new_port
        self.start_log_server(self.current_port)

    # ==========================
    #  Core Parser Logic
    # ==========================
    
    def load_elf_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Select ELF File", "", "ELF Binary (*.elf);;All Files (*)")
        if not filename:
            return
            
        # Validate format
        if not filename.lower().endswith(".elf"):
            self.log_gui_message("ERROR: Incorrect ELF format. File must end with <b>.elf</b> (e.g., 'eboot.elf')", "red")
            self.tabs.setCurrentIndex(0) # Switch to Log tab to show error
            return
            
        self.selected_elf = filename
        self.btn_load_elf.setText("ELF Loaded ✓")
        self.btn_load_elf.setStyleSheet("color: #3ecf4c; border: 1px solid #3ecf4c;")
        self.log_gui_message(f"ELF loaded: {os.path.basename(filename)}", "#3ecf4c")
        self.check_parse_ready()

    def load_crash_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Select Crash Dump", "", "Core Dump (*.psp2dmp);;All Files (*)")
        if not filename:
            return
            
        # Validate format
        if not filename.lower().endswith(".psp2dmp"):
            self.log_gui_message("ERROR: Incorrect Crash Dump format. File must end with <b>.psp2dmp</b> or <b>.bin.psp2dmp</b>", "red")
            self.tabs.setCurrentIndex(0) # Switch to Log tab to show error
            return
            
        self.selected_core = filename
        self.btn_load_crash.setText("Crash Loaded ✓")
        self.btn_load_crash.setStyleSheet("color: #3ecf4c; border: 1px solid #3ecf4c;")
        self.log_gui_message(f"Crash dump loaded: {os.path.basename(filename)}", "#3ecf4c")
        self.check_parse_ready()
        
    def check_parse_ready(self):
        """Enables the parse button only if both files are loaded"""
        if self.selected_elf and self.selected_core:
            self.btn_parse.setEnabled(True)
            self.btn_parse.setText("Analyze Crash Dump")
            self.btn_parse.setStyleSheet("background-color: #2f4f6f;") # Reset style

    def start_core_parser(self):
        if not self.selected_elf or not self.selected_core:
            return
            
        # 1. Switch to Core Tab
        self.tabs.setCurrentIndex(1)
        self.core_output.clear()
        self.core_output.appendPlainText("Initializing Parser...\n")

        # 2. Start Thread
        self.parser_thread = DumpParserThread(self.selected_core, self.selected_elf)
        self.parser_thread.output_signal.connect(self.update_core_log)
        self.parser_thread.finished_signal.connect(self.parser_finished)
        self.btn_parse.setEnabled(False)
        self.btn_parse.setText("Analyzing...")
        self.parser_thread.start()

    @Slot(str)
    def update_core_log(self, text):
        self.core_output.moveCursor(QTextCursor.End)
        self.core_output.insertPlainText(text) 
        self.core_output.moveCursor(QTextCursor.End)

    @Slot()
    def parser_finished(self):
        self.btn_parse.setEnabled(True)
        self.btn_parse.setText("Analyze Crash Dump")
        self.core_output.appendPlainText("\nDone.")

    def log_gui_message(self, message, color="white"):
        """Helper to print formatted messages to the main log"""
        self.log_output.moveCursor(QTextCursor.End)
        self.log_output.appendHtml(f"<font color='{color}'>{message}</font>")
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

    def closeEvent(self, event):
        if self.log_thread: self.log_thread.stop()
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
        """)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VitaDeckModern()
    window.show()
    sys.exit(app.exec())