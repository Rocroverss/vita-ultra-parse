import sys
import socket
import threading
from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLabel, QLineEdit, QCheckBox, QTabWidget, QPlainTextEdit, QFileDialog,
    QFrame, QGroupBox, QSpinBox
)
from PySide6.QtGui import QColor, QPainter, QTextCursor, QFont, QIntValidator
from PySide6.QtCore import Qt, QThread, Signal, Slot

# ==========================================
# 1. The Socket Server Thread
# ==========================================
class LogServerThread(QThread):
    """
    Translates the original C/Winsock logic into a Python QThread.
    """
    log_signal = Signal(str)

    def __init__(self, port=8080):
        super().__init__()
        self.port = port
        self.running = True
        self.server_socket = None

    def run(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Allow reuse of the address to avoid "Address already in use" on quick restarts
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.server_socket.bind(('0.0.0.0', self.port))
            self.log_signal.emit(f"--- Server Started on Port {self.port} ---\n")
            
            self.server_socket.listen(128)
            self.log_signal.emit("Listening for connections...\n")
            
            # Set a timeout so we can check 'self.running' periodically
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
                                # Decode and emit
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
                    if self.running: # Only log error if we didn't intentionally stop
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
# 2. UI Components
# ==========================================

class ColorDot(QFrame):
    """ Small colored status dot """
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

# ==========================================
# 3. Main Application
# ==========================================

class VitaDeckModern(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vitadeck")
        self.resize(1200, 700)
        
        # Application State
        self.log_font_size = 12
        self.current_port = 8080

        main_layout = QVBoxLayout(self)

        # ======================
        #        TABS
        # ======================
        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")

        # --- Logging Tab ---
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setObjectName("logOutput")
        log_layout.addWidget(self.log_output)
        self.tabs.addTab(log_tab, "Logging")

        # --- Core dump tab ---
        core_tab = QWidget()
        core_layout = QVBoxLayout(core_tab)
        core_layout.addWidget(QLabel("Core dump output or controls here..."))
        self.tabs.addTab(core_tab, "Core dump")

        # --- Command palette tab ---
        cmd_tab = QWidget()
        cmd_layout = QVBoxLayout(cmd_tab)
        cmd_layout.addWidget(QLabel("Command palette content goes here..."))
        self.tabs.addTab(cmd_tab, "Command palette")

        # --- File transfer tab ---
        ft_tab = QWidget()
        ft_layout = QVBoxLayout(ft_tab)
        ft_layout.addWidget(QLabel("File transfer details go here..."))
        self.tabs.addTab(ft_tab, "File transfer")

        # --- Settings Tab (NEW) ---
        st_tab = QWidget()
        self.setup_settings_tab(st_tab)
        self.tabs.addTab(st_tab, "Settings ⚙")

        # Tabs + content area
        content_and_sidebar = QHBoxLayout()
        content_and_sidebar.addWidget(self.tabs, stretch=4)

        # ======================
        #       SIDEBAR
        # ======================
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sb = QVBoxLayout(sidebar)

        # PS Vita IP
        sb.addWidget(QLabel("PS Vita IP"))
        self.ip_entry = QLineEdit("192.168.1.21")
        sb.addWidget(self.ip_entry)

        btn_reconnect = QPushButton("Reconnect")
        sb.addWidget(btn_reconnect)

        sb.addSpacing(12)

        # Core dumps
        sb.addWidget(QLabel("Core dumps"))
        sb.addWidget(QPushButton("Fetch and parse"))
        sb.addWidget(QPushButton("Fetch and parse (VCP)"))

        sb.addSpacing(12)

        # Run Executable
        sb.addWidget(QLabel("Run executable"))
        self.exec_entry = QLineEdit("D:/Repos/demos/test/bu")
        sb.addWidget(self.exec_entry)

        self.appid_entry = QLineEdit("APPL00001")
        sb.addWidget(self.appid_entry)

        self.temp_checkbox = QCheckBox("Use temporary App ID")
        sb.addWidget(self.temp_checkbox)

        sb.addWidget(QPushButton("Upload and launch"))

        sb.addSpacing(12)

        # Quick commands
        sb.addWidget(QLabel("Quick commands"))
        sb.addWidget(QPushButton("Quit all apps"))
        sb.addWidget(QPushButton("Reboot"))

        sb.addStretch()

        content_and_sidebar.addWidget(sidebar, stretch=1)
        main_layout.addLayout(content_and_sidebar)

        # ======================
        #   STATUS BAR (BOTTOM)
        # ======================
        status_bar = QHBoxLayout()
        status_bar.setContentsMargins(10, 5, 10, 10)

        # Connection indicator
        self.conn_dot = ColorDot("#3ecf4c")  # green dot
        status_bar.addWidget(self.conn_dot)

        self.conn_label = QLabel(f"Connected to the console @ {self.ip_entry.text()}")
        status_bar.addWidget(self.conn_label)

        status_bar.addSpacing(30)

        # File transfer status
        self.ft_dot = ColorDot("#777")  # gray = idle
        status_bar.addWidget(self.ft_dot)

        self.ft_label = QLabel("No file transfer in progress")
        self.ft_label.setStyleSheet("color: #777;")
        status_bar.addWidget(self.ft_label)

        status_bar.addStretch()
        main_layout.addLayout(status_bar)

        # Apply Styling and Defaults
        self.apply_style()
        self.update_font(0) # Apply initial font size

        # ======================
        # START THE LOG SERVER
        # ======================
        self.log_thread = None
        self.start_log_server(self.current_port)

    # ==========================
    #  Settings Tab Setup
    # ==========================
    def setup_settings_tab(self, parent_widget):
        layout = QVBoxLayout(parent_widget)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignTop)

        # --- Server Configuration Group ---
        grp_server = QGroupBox("Logging Server Configuration")
        srv_layout = QVBoxLayout(grp_server)
        
        lbl_port = QLabel("Listening Port:")
        self.port_input = QLineEdit(str(self.current_port))
        self.port_input.setValidator(QIntValidator(1024, 65535)) # Restrict to valid ports
        
        btn_apply_port = QPushButton("Apply & Restart Server")
        btn_apply_port.setCursor(Qt.PointingHandCursor)
        btn_apply_port.clicked.connect(self.restart_server_with_new_port)

        srv_layout.addWidget(lbl_port)
        srv_layout.addWidget(self.port_input)
        srv_layout.addWidget(btn_apply_port)
        
        layout.addWidget(grp_server)

        # --- Appearance Group ---
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

        # Preview Area
        app_layout.addWidget(QLabel("Preview:"))
        self.preview_box = QPlainTextEdit()
        self.preview_box.setReadOnly(True)
        self.preview_box.setMaximumHeight(80)
        self.preview_box.setPlainText("DEBUG: socket initialized\nINFO: connection accepted\nWARNING: buffer threshold reached")
        self.preview_box.setObjectName("logOutput") # Re-use styling
        app_layout.addWidget(self.preview_box)

        layout.addWidget(grp_appearance)
        layout.addStretch()

    # ==========================
    #  Logic: Font & Restart
    # ==========================

    def update_font(self, delta):
        """Increases or decreases font size and updates UI"""
        new_size = self.log_font_size + delta
        if new_size < 8: new_size = 8
        if new_size > 32: new_size = 32
        
        self.log_font_size = new_size
        self.lbl_font_size.setText(f"Font Size: {self.log_font_size}px")

        # Create font object
        font = QFont("Consolas") # Or "Monospace"
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(self.log_font_size)

        # Apply to Log Window
        self.log_output.setFont(font)
        
        # Apply to Preview Window
        self.preview_box.setFont(font)

    def restart_server_with_new_port(self):
        """Stops the current thread and starts a new one with the new port"""
        try:
            new_port = int(self.port_input.text())
        except ValueError:
            self.log_output.appendHtml("<font color='red'>Invalid Port Number</font>")
            return

        self.log_output.appendHtml(f"<br><font color='#ff9900'><b>Restaring server on port {new_port}...</b></font><br>")
        
        # 1. Stop existing thread
        if self.log_thread and self.log_thread.isRunning():
            self.log_thread.stop()
        
        # 2. Update state
        self.current_port = new_port
        
        # 3. Start new thread
        self.start_log_server(self.current_port)

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
        if self.log_thread:
            self.log_thread.stop()
        event.accept()

    # ==========================
    #  Styling
    # ==========================
    def apply_style(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                color: #dcdcdc;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }

            /* Groups */
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

            /* Sidebar */
            #sidebar {
                background-color: #252525;
                border-left: 1px solid #3c3c3c;
                padding: 12px;
            }

            /* Inputs */
            QLineEdit {
                padding: 6px;
                border-radius: 5px;
                background-color: #2d2d2d;
                border: 1px solid #444;
                color: #e0e0e0;
            }
            QLineEdit:focus {
                border: 1px solid #3a5f80;
            }

            /* Buttons */
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

            /* Tabs */
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

            /* Log Output (Main and Preview) */
            QPlainTextEdit#logOutput {
                background-color: #111;
                border: 1px solid #333;
                padding: 8px;
                color: #c0c0c0;
                /* Font is set programmatically via update_font() */
            }
        """)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VitaDeckModern()
    window.show()
    sys.exit(app.exec())