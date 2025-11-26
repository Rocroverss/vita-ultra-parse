import sys
import os
import socket
import threading
from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, 
    QPushButton, QLabel, QLineEdit, QTabWidget, 
    QGroupBox, QMessageBox, QFrame, QFileDialog, QStyle,
    QTextEdit, QSpinBox, QSplitter 
)
from PySide6.QtGui import QColor, QPainter, QFont, QIntValidator
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer 

# Import Modules (Mocked for standalone execution if missing)
try:
    from utils import settings
    from logging import LoggingTab 
    from core_dump import CoreDumpTab
    from build import BuildTab
    from file_transfer import FileTransferTab
    from sdk_installation import SdkInstallationTab
except ImportError:
    # --- MOCK MODULES FOR STANDALONE RUNNING ---
    class MockSettings:
        _data = {"log_font_size": 13, "vita_ip": "192.168.1.100", "sdk_path": "", "last_build_dir": os.getcwd(), "log_port": 8080, "exec_path": "", "target_app_id": "PCSG00000", "launch_title_id": "VHBB00001"}
        def get(self, key, default): return self._data.get(key, default)
        def set(self, key, value): self._data[key] = value
        def save(self): pass
    settings = MockSettings()
    
    class MockTab(QWidget):
        def __init__(self):
            super().__init__()
            self.setLayout(QVBoxLayout(self)); self.layout().addWidget(QLabel(f"Mock Tab Content")); self.layout().addStretch()
        def cleanup(self): pass

    class LoggingTab(MockTab):
        def __init__(self):
            super().__init__()
            self.log_output = QTextEdit(); self.log_output.setObjectName("logOutput"); self.layout().addWidget(self.log_output)
        def append_log(self, message, color):
            self.log_output.append(f'<span style="color: {color};">{message}</span>')
        def restart_server(self, port):
            QMessageBox.information(None, "Server", f"Log Server Restarted on port {port}")
    
    class FileTransferTab(MockTab):
        class MockFTPThread(QThread):
            status_signal = Signal(str, str); progress_signal = Signal(str)
            def run(self):
                self.status_signal.emit("Connected (FTP)", "#3ecf4c"); self.progress_signal.emit("Idle"); self.exec()
            def add_command(self, cmd, *args):
                if cmd == 'upload':
                    self.progress_signal.emit("Uploading eboot.bin..."); QTimer.singleShot(2000, lambda: self.progress_signal.emit("Idle"))
        def __init__(self):
            super().__init__(); self.ftp_thread = self.MockFTPThread(); self.ftp_thread.start()
        def connect_ftp(self):
            QMessageBox.information(None, "FTP", "Connecting FTP..."); self.ftp_thread.status_signal.emit("Connecting...", "orange")
            QTimer.singleShot(1000, lambda: self.ftp_thread.status_signal.emit("Connected (FTP)", "#3ecf4c"))

    CoreDumpTab = lambda: MockTab()
    BuildTab = lambda: MockTab()
    SdkInstallationTab = lambda: MockTab()
    # -------------------------------------------


# ==========================================
# 0. UI UTILS
# ==========================================
class ColorDot(QWidget):
    """A small colored circle widget for status indication."""
    def __init__(self, color="#777", size=10):
        super().__init__()
        self._color = QColor(color)
        self.setFixedSize(size, size)
        self.setMinimumSize(size, size)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self._color)
        painter.setPen(Qt.NoPen)
        rect = self.rect()
        diameter = min(rect.width(), rect.height())
        dot_diameter = diameter * 0.8 
        painter.drawEllipse(
            rect.center().x() - dot_diameter // 2, 
            rect.center().y() - dot_diameter // 2, 
            dot_diameter, 
            dot_diameter
        )

# ==========================================
# 1. HELP TAB
# ==========================================
class HelpTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        
        info_icon = QWidget().style().standardIcon(QStyle.SP_MessageBoxInformation)
        icon_label = QLabel()
        icon_label.setPixmap(info_icon.pixmap(24, 24))
        
        title_label = QLabel("ℹ️ <b>Vitadeck Manager & Debugger Help</b>")
        title_label.setFont(QFont("Arial", 16, QFont.Bold))
        
        title_hbox = QHBoxLayout()
        title_hbox.addWidget(icon_label)
        title_hbox.addWidget(title_label)
        title_hbox.addStretch()
        layout.addLayout(title_hbox)

        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setHtml(f"""
            <p><b>PS Vita Debugging Tool Suite</b></p>
            <hr>

            <p><b>Important Information:</b></p>
            <ul>
                <li><b>How to use the application:</b>
                    <ul>
                        <li>Connect your PS Vita using <b>VitaCompanion</b> and make sure ports 1337 (FTP) and 1338 (Commands) are accessible.</li>
                        <li>Use the <b>File Transfer</b> tab to manage files through FTP.</li>
                        <li>Use <b>Quick Commands</b> or <b>Upload & Launch</b> to send commands or upload/launch homebrew apps.</li>
                        <li>For core dump analysis, configure the paths to <b>VitaSDK/devkitARM</b> in the <b>Settings</b> tab.</li>
                    </ul>
                </li>

                <li><b>How to install VitaCompanion:</b>
                    <ul>
                        <li>Official repository: <a href="https://github.com/devnoname120/vitacompanion">https://github.com/devnoname120/vitacompanion</a></li>
                        <li>Download the VPK from Releases and install it on your PS Vita using VitaShell.</li>
                    </ul>
                </li>

                <li><b>How to install CatLog:</b>
                    <ul>
                        <li>Official repository: <a href="https://github.com/isage/catlog">https://github.com/isage/catlog</a></li>
                        <li>CatLog allows viewing real-time logs directly from the console.</li>
                    </ul>
                </li>
            </ul>

            <p><b>Connectivity:</b></p>
            <ul>
                <li>The application connects to a PS Vita running <b>VitaCompanion</b> (or an equivalent homebrew) through two ports:
                    <ul>
                        <li><b>FTP (1337):</b> used by the <b>File Transfer</b> tab.</li>
                        <li><b>Commands (1338):</b> used for <b>Quick Commands</b> and <b>Upload & Launch</b>.</li>
                    </ul>
                </li>
            </ul>

            <p><b>Core Dump:</b></p>
            <ul>
                <li>Requires <b>VitaSDK/devkitARM</b> configured in the <b>Settings</b> tab.</li>
                <li>Uses <b>.psp2dmp</b> files together with their corresponding <b>.elf</b> executable for analysis.</li>
            </ul>

            <p><b>Build:</b></p>
            <ul>
                <li>Allows quick execution of common build steps (CMake, Make, Clean) in a specified directory.</li>
            </ul>

            <p><b>Additional Resources:</b></p>
            <ul>
                <li><b>gl33ntwine’s development guides:</b>
                    <ul>
                        <li>Development guide: <a href="https://gl33ntwine.com/posts/develop-for-vita/">https://gl33ntwine.com/posts/develop-for-vita/</a></li>
                        <li>Common library issues: <a href="https://gl33ntwine.com/notes/vita-find-symbol.html">https://gl33ntwine.com/notes/vita-find-symbol.html</a></li>
                    </ul>
                </li>

                <li><b>Useful SDK Resources:</b>
                    <ul>
                        <li><a href="https://vitasdk.org/">https://vitasdk.org/</a></li>
                    </ul>
                </li>

                <li><b>SO Guide (homebrew & tooling guide):</b>
                    <ul>
                        <li><a href="https://github.com/Rocroverss/vitasoguide">https://github.com/Rocroverss/vitasoguide</a></li>
                    </ul>
                </li>

                <li><b>Project Templates:</b>
                    <ul>
                        <li><a href="https://github.com/v-atamanenko/soloader-boilerplate">https://github.com/v-atamanenko/soloader-boilerplate</a></li>
                    </ul>
                </li>
            </ul>
        """)

        
        layout.addWidget(help_text)

# ==========================================
# 2. SETTINGS TAB
# ==========================================
class SettingsTab(QWidget):
    restart_log_server_signal = Signal(int)
    apply_style_signal = Signal() 

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        # 1. SDK Configuration
        grp_sdk = QGroupBox("VitaSDK & Build Configuration")
        lay_sdk = QVBoxLayout(grp_sdk)
        
        lay_sdk.addWidget(QLabel("VitaSDK Path:"))
        hbox_sdk = QHBoxLayout()
        self.sdk_input = QLineEdit(settings.get("sdk_path", ""))
        self.btn_sdk = QPushButton("Browse SDK Root")
        self.btn_sdk.clicked.connect(lambda: self.browse_folder(self.sdk_input, "sdk_path", is_file=False))
        hbox_sdk.addWidget(self.sdk_input)
        hbox_sdk.addWidget(self.btn_sdk)
        lay_sdk.addLayout(hbox_sdk)

        lay_sdk.addWidget(QLabel("Default Build Folder:"))
        hbox_build = QHBoxLayout()
        self.build_input = QLineEdit(settings.get("last_build_dir", os.getcwd()))
        self.btn_build = QPushButton("Browse Build Folder")
        self.btn_build.clicked.connect(lambda: self.browse_folder(self.build_input, "last_build_dir", is_file=False))
        hbox_build.addWidget(self.build_input)
        hbox_build.addWidget(self.btn_build)
        lay_sdk.addLayout(hbox_build)
        
        self.sdk_input.textChanged.connect(lambda t: settings.set("sdk_path", t))
        self.build_input.textChanged.connect(lambda t: settings.set("last_build_dir", t))
        
        layout.addWidget(grp_sdk)
        
        # 2. Logging Server Configuration
        grp_log = QGroupBox("Logging Server Configuration")
        lay_log = QVBoxLayout(grp_log)
        
        lay_log.addWidget(QLabel("Log Server Port (Requires Restart):"))
        hbox_port = QHBoxLayout()
        self.log_port_input = QLineEdit(str(settings.get("log_port", 8080)))
        self.log_port_input.setValidator(QIntValidator(1024, 65535))
        btn_port = QPushButton("Apply Port & Restart Server")
        btn_port.clicked.connect(self.apply_port_and_restart)
        hbox_port.addWidget(self.log_port_input)
        hbox_port.addWidget(btn_port)
        lay_log.addLayout(hbox_port)
        
        layout.addWidget(grp_log)

        # 3. Log Appearance
        grp_appearance = QGroupBox("Log/Terminal Appearance")
        lay_appearance = QVBoxLayout(grp_appearance)
        
        lay_appearance.addWidget(QLabel("Log Output Font Size (pt):"))
        hbox_font = QHBoxLayout()
        self.font_size_spinbox = QSpinBox()
        self.font_size_spinbox.setRange(8, 30)
        self.font_size_spinbox.setValue(settings.get("log_font_size", 13)) 
        self.font_size_spinbox.valueChanged.connect(lambda v: settings.set("log_font_size", v))
        btn_apply_font = QPushButton("Apply Style Changes")
        btn_apply_font.clicked.connect(self.apply_style_signal.emit)
        
        hbox_font.addWidget(self.font_size_spinbox)
        hbox_font.addWidget(btn_apply_font)
        lay_appearance.addLayout(hbox_font)
        
        layout.addWidget(grp_appearance)
        
        layout.addStretch()

    def browse_folder(self, line_edit, setting_key, is_file=False):
        if is_file:
            d, _ = QFileDialog.getOpenFileName(self, "Select File", line_edit.text())
        else:
            d = QFileDialog.getExistingDirectory(self, "Select Folder", line_edit.text())
        
        if d:
            line_edit.setText(d)
            settings.set(setting_key, d)

    def apply_port_and_restart(self):
        try:
            port = int(self.log_port_input.text())
            if port < 1024 or port > 65535:
                QMessageBox.warning(self, "Port Error", "Port must be between 1024 and 65535.")
                return
            settings.set("log_port", port)
            self.restart_log_server_signal.emit(port)
        except ValueError:
            QMessageBox.critical(self, "Input Error", "Invalid port number.")


# ==========================================
# COMMAND WORKER
# ==========================================
class CommandWorker(QThread):
    command_output_signal = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.host = settings.get("vita_ip", "192.168.1.100")
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
            self.msleep(100)

    def _do_send_command(self, command):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                self.command_output_signal.emit(f"Attempting to send command: '{command}'", "orange")
                s.connect((self.host, self.port))
                s.sendall(f"{command}\n".encode('utf-8'))
                response = s.recv(1024).decode('utf-8', errors='ignore').strip()
                self.command_output_signal.emit(f"Cmd: {command} -> {response}", "#3ecf4c")
        except Exception as e:
            self.command_output_signal.emit(f"Cmd Error: {e}", "red")

    def set_host(self, host):
        self.host = host

    def stop(self):
        self.running = False
        self.wait()

# ==========================================
# MAIN WINDOW (VitaDeckModern)
# ==========================================
class VitaDeckModern(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vitadeck - Manager & Debugger")
        self.resize(1200, 700)
        
        self.cmd_thread = CommandWorker()
        self.cmd_thread.start()

        main_layout = QVBoxLayout(self)
        content_and_sidebar = QHBoxLayout()

        # Tabs
        self.tabs = QTabWidget()
        
        # Instantiate Tabs
        self.tab_logging = LoggingTab()
        self.cmd_thread.command_output_signal.connect(self.tab_logging.append_log)
        self.tabs.addTab(self.tab_logging, "Logging")
        
        self.tab_core = CoreDumpTab()
        self.tabs.addTab(self.tab_core, "Core Dump")
        
        self.tab_build = BuildTab()
        self.tabs.addTab(self.tab_build, "Build")
        
        self.tab_transfer = FileTransferTab()
        self.tab_transfer.ftp_thread.status_signal.connect(self.update_connection_status)
        self.tab_transfer.ftp_thread.progress_signal.connect(self.update_transfer_status)
        self.tabs.addTab(self.tab_transfer, "File Transfer")
        
        self.tab_sdk = SdkInstallationTab()
        self.tabs.addTab(self.tab_sdk, "SDK Install")
        
        self.tab_help = HelpTab()
        self.tabs.addTab(self.tab_help, "ℹ️ Help")

        self.tab_settings = SettingsTab()
        self.tabs.addTab(self.tab_settings, "Settings")
        
        self.tab_settings.restart_log_server_signal.connect(self.restart_logging_server)
        self.tab_settings.apply_style_signal.connect(self.apply_style)

        content_and_sidebar.addWidget(self.tabs, stretch=4)
        
        # Sidebar
        self.setup_sidebar(content_and_sidebar)
        main_layout.addLayout(content_and_sidebar)

        # Status Bar
        self.setup_status_bar(main_layout)
        
        self.apply_style(initial=True)
        
        self.cmd_thread.set_host(settings.get("vita_ip", "192.168.1.100"))

    # ==========================================
    # SETTINGS/STYLE METHODS
    # ==========================================

    @Slot(int)
    def restart_logging_server(self, port):
        self.tab_logging.restart_server(port)

    @Slot()
    def apply_style(self, initial=False):
        log_font_size = settings.get("log_font_size", 13)
        base_font_size = 10 

        self.setStyleSheet(self._get_style_sheet(base_font_size, log_font_size))
        
        if not initial:
            QMessageBox.information(self, "Style Applied", f"Application style applied. Log output font size: {log_font_size}pt.")

    def _get_style_sheet(self, base_font_size, log_font_size):
        log_font = "Consolas, Monospace" 
        
        return f"""
            QWidget {{
                background-color: #1e1e1e;
                color: #dcdcdc;
                font-family: 'Segoe UI', sans-serif;
                font-size: {base_font_size}pt;
            }}
            QGroupBox {{
                border: 1px solid #3c3c3c;
                border-radius: 6px;
                margin-top: 20px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
                color: #aaa;
            }}
            #sidebar {{
                background-color: #252525;
                border: 1px solid #3c3c3c; 
                border-radius: 8px; 
                padding: 12px;
            }}
            QLineEdit, QTextEdit, QSpinBox {{
                padding: 6px;
                border-radius: 5px;
                background-color: #2d2d2d;
                border: 1px solid #444;
                color: #e0e0e0;
            }}
            QPushButton {{
                background-color: #2f4f6f;
                border: 1px solid #3a5f80;
                padding: 8px 10px;
                border-radius: 4px;
                color: white;
            }}
            QPushButton:hover {{
                background-color: #3a668a;
            }}
            QPushButton:pressed {{
                background-color: #2a5975;
            }}
            QPushButton:disabled {{
                background-color: #222;
                color: #555;
                border: 1px solid #333;
            }}
            QPushButton[style*="#8B0000"] {{ 
                background-color: #8B0000;
                border: 1px solid #FF4500;
            }}
            QPushButton[style*="#8B0000"]:hover {{
                background-color: #A52A2A;
            }}
            QPushButton[style*="#8B0000"]:pressed {{
                background-color: #690000;
            }}
            /* Tab Pane with rounded top corners */
            QTabWidget::pane {{
                border: 1px solid #3c3c3c;
                border-top-left-radius: 8px; 
                border-top-right-radius: 8px; 
                background: #1e1e1e;
            }}
            QTabBar::tab {{
                padding: 8px 18px;
                background: #2a2a2a;
                color: #dcdcdc;
                border: 1px solid #3c3c3c;
                border-bottom: none; 
                border-radius: 6px 6px 0 0; /* Rounded top, flat bottom */
                margin-right: 2px;
            }}
            /* Color selected tab distinctly */
            QTabBar::tab:selected {{
                background: #2f4f6f; 
                border-color: #3a5f80; 
                border-bottom: none;
                color: white;
            }}
            QTabBar::tab:hover {{ 
                background: #3a3a3a;
            }}
            QPlainTextEdit#logOutput {{
                background-color: #111;
                border: 1px solid #333;
                border-radius: 8px; 
                padding: 8px;
                color: #c0c0c0;
                font-family: {log_font}; 
                font-size: {log_font_size}pt; 
            }}
            QTreeView {{
                alternate-background-color: #222222;
                background-color: #1e1e1e;
                border: 1px solid #333;
                selection-background-color: #2f4f6f;
            }}
        """

    # ==========================================
    # SIDEBAR SETUP (MODIFIED TO USE QGroupBox)
    # ==========================================
    def setup_ip_group(self, layout):
        grp_ip = QGroupBox("PS Vita IP")
        ip_layout = QVBoxLayout(grp_ip)
        
        self.ip_entry = QLineEdit(settings.get("vita_ip", "192.168.1.100"))
        self.ip_entry.textChanged.connect(lambda t: settings.set("vita_ip", t))
        self.ip_entry.textChanged.connect(self.update_command_worker_host)
        ip_layout.addWidget(self.ip_entry)
        
        btn_reconnect = QPushButton("Reconnect FTP")
        btn_reconnect.clicked.connect(self.tab_transfer.connect_ftp) 
        ip_layout.addWidget(btn_reconnect)

        layout.addWidget(grp_ip)
        
    def setup_core_dump_group(self, layout):
        grp_core = QGroupBox("Core Dumps Quick Actions")
        core_layout = QVBoxLayout(grp_core)

        btn_fetch_parse = QPushButton("Fetch and parse last crash")
        btn_fetch_parse.clicked.connect(self.tab_core.fetch_and_parse_last_crash)
        core_layout.addWidget(btn_fetch_parse)

        layout.addWidget(grp_core)

    def setup_sidebar(self, layout):
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sb = QVBoxLayout(sidebar)
        
        # IP Group 
        self.setup_ip_group(sb)
        sb.addSpacing(12) 

        # Core Dumps Group 
        self.setup_core_dump_group(sb)
        sb.addSpacing(12) 
        
        # RUN EXECUTABLE SIDEBAR 
        self.setup_run_executable_sidebar(sb)
        sb.addSpacing(12)

        # QUICK COMMANDS SIDEBAR
        self.setup_quick_commands_sidebar(sb)

        sb.addStretch()
        layout.addWidget(sidebar, stretch=1)
        
    @Slot(str)
    def update_command_worker_host(self, host):
        self.cmd_thread.set_host(host)
        
    def setup_run_executable_sidebar(self, layout):
        grp_run_exec = QGroupBox("Run Local Executable")
        run_exec_layout = QVBoxLayout(grp_run_exec)
        
        run_exec_layout.addWidget(QLabel("Local Executable (e.g., eboot.bin):"))
        hbox_exec = QHBoxLayout()
        self.exec_entry = QLineEdit(settings.get("exec_path", os.path.join(os.getcwd(), "eboot.bin"))) 
        self.exec_entry.setPlaceholderText("Path to eboot.bin or *.self")
        btn_browse_exec = QPushButton("Browse...")
        btn_browse_exec.clicked.connect(self.browse_exec_file)
        hbox_exec.addWidget(self.exec_entry)
        hbox_exec.addWidget(btn_browse_exec)
        run_exec_layout.addLayout(hbox_exec)
        
        run_exec_layout.addWidget(QLabel("Target App ID (e.g., PCSG00000):"))
        self.appid_entry = QLineEdit(settings.get("target_app_id", "PCSG00000"))
        self.appid_entry.textChanged.connect(lambda t: settings.set("target_app_id", t))
        run_exec_layout.addWidget(self.appid_entry)
        
        self.btn_upload_launch = QPushButton("Upload and Launch")
        self.btn_upload_launch.setStyleSheet("background-color: #2f4f6f; color: white;")
        self.btn_upload_launch.clicked.connect(self.upload_and_launch)
        run_exec_layout.addWidget(self.btn_upload_launch)
        
        layout.addWidget(grp_run_exec)

    def setup_quick_commands_sidebar(self, layout):
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
        
        hbox_launch = QHBoxLayout()
        self.launch_id_entry = QLineEdit(settings.get("launch_title_id", "VHBB00001"))
        self.launch_id_entry.textChanged.connect(lambda t: settings.set("launch_title_id", t))
        self.launch_id_entry.setPlaceholderText("Enter Title ID")
        btn_launch_id = QPushButton("Launch Title ID")
        btn_launch_id.clicked.connect(self.launch_title_id)
        hbox_launch.addWidget(self.launch_id_entry)
        hbox_launch.addWidget(btn_launch_id)
        quick_layout_sb.addLayout(hbox_launch)

        grp_quick_sb.setLayout(quick_layout_sb)
        layout.addWidget(grp_quick_sb)

    # ==========================================
    # SIDEBAR ACTION METHODS
    # ==========================================
    def browse_exec_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select eboot.bin/Self", settings.get("exec_path", ""), 
            "Executable Files (eboot.bin *.self);;All Files (*)"
        )
        if filename:
            self.exec_entry.setText(filename)
            settings.set("exec_path", filename)

    def upload_and_launch(self):
        local_path = self.exec_entry.text().strip()
        app_id = self.appid_entry.text().strip()
        
        if not os.path.isfile(local_path):
            QMessageBox.warning(self, "File Error", "Local executable file not found.")
            return
        if not app_id:
            QMessageBox.warning(self, "Input Error", "Please enter a target Application ID.")
            return
        
        remote_path = f"ux0:/app/{app_id}/eboot.bin"
        
        reply = QMessageBox.question(
            self, "Confirm Upload & Launch", 
            f"Upload '{os.path.basename(local_path)}' to '{remote_path}' and launch '{app_id}'?\n\nNOTE: This will overwrite the existing eboot.bin! Confirm to replace.", 
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        self.tab_logging.append_log(f"Starting forced upload of {os.path.basename(local_path)} to {remote_path}...", "orange")
        self.tab_transfer.ftp_thread.add_command('upload', local_path, remote_path, True)
        self.send_command(f"launch {app_id}")


    def launch_title_id(self):
        title_id = self.launch_id_entry.text().strip()
        if not title_id:
            QMessageBox.warning(self, "Input Error", "Please enter a Title ID to launch.")
            return
        self.send_command(f"launch {title_id}")

    def send_command(self, command):
        if command in ("destroy", "reboot"):
            reply = QMessageBox.question(
                self, "Confirm Command", 
                f"Are you sure you want to run '{command}'? This may close apps or reboot your device.", 
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        self.cmd_thread.add_command(command)
        self.tabs.setCurrentIndex(0)

    # ==========================================
    # STATUS BAR
    # ==========================================
    def setup_status_bar(self, layout):
        status_bar_layout = QHBoxLayout()
        status_bar_layout.setContentsMargins(12, 4, 12, 4)
        
        self.conn_dot = ColorDot("#777", size=12) 
        status_bar_layout.addWidget(self.conn_dot)
        self.conn_label = QLabel("Not connected")
        self.conn_label.setStyleSheet("color: #777;")
        status_bar_layout.addWidget(self.conn_label)
        
        status_bar_layout.addSpacing(20)
        
        self.transfer_dot = ColorDot("#777", size=12)
        status_bar_layout.addWidget(self.transfer_dot)
        self.transfer_label = QLabel("Not transfer file in progress")
        self.transfer_label.setStyleSheet("color: #777;")
        status_bar_layout.addWidget(self.transfer_label)
        
        status_bar_layout.addStretch()
        
        layout.addLayout(status_bar_layout)

    @Slot(str, str)
    def update_connection_status(self, message, color):
        self.conn_label.setStyleSheet(f"color: {color};")
        self.conn_label.setText(message)
        self.conn_dot.set_color(color)

    @Slot(str)
    def update_transfer_status(self, status_msg):
        color = "#777"
        text = status_msg
        
        if status_msg.lower() == "idle":
            text = "File transfer idle"
            color = "#3ecf4c"
        elif "error" in status_msg.lower():
            text = f"Transfer Error: {status_msg}"
            color = "red"
        elif status_msg.startswith(("Uploading", "Downloading", "Renaming", "Deleting")):
            color = "orange"
        else:
            text = "Not transfer file in progress"
            color = "#777" 
            
        self.transfer_label.setText(text)
        self.transfer_dot.set_color(color)
        self.transfer_label.setStyleSheet(f"color: {color};")


    def closeEvent(self, event):
        self.tab_logging.cleanup()
        self.tab_transfer.cleanup()
        self.tab_build.cleanup()
        self.cmd_thread.stop()
        settings.save()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = VitaDeckModern()
    window.show()
    sys.exit(app.exec())