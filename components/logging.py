import socket
import datetime
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QThread, Signal
from components.icon_utils import themed_icon

# --- Placeholder for settings import ---
# Assuming 'utils' and 'settings' exist in your environment.
# If 'settings' is not available, replace settings.get("log_port") with a default port number (e.g., 8080).
try:
    from utils import settings
except ImportError:
    print("Warning: 'utils.settings' not found. Using default port 8080.")
    class DummySettings:
        def get(self, key):
            return 8080
    settings = DummySettings()
# ---------------------------------------

## 🎨 Color Definitions

COLOR_TIMESTAMP = "#888888"  # Gray
COLOR_CONNECT = "#00AA00"    # Green
COLOR_DISCONNECT = "#FF0000" # Red
COLOR_BLOCK_LOG = "#00BFFF"  # Blue (for network/socket status blocks)
COLOR_TRACE_LOG = "#FFFFFF"  # White (for game traces/app logs)

## 📡 Log Server Thread
# Handles socket connection, buffering, timestamping, and signal emission.

class LogServerThread(QThread):
    # Signal now passes the full timestamped log and the raw content for color checking
    log_signal = Signal(str, str)

    def __init__(self, port=8080):
        super().__init__()
        self.port = port
        self.running = True
        self.server_socket = None
        self.recv_buffer = {} # Dictionary to hold incomplete log data for each client

    def get_timestamp(self):
        """Returns the current time in HH:MM:SS format."""
        return datetime.datetime.now().strftime("%H:%M:%S")

    def process_data(self, addr, data):
        """
        Processes received data to prepend a timestamp to each complete log line.
        Removes the trailing newline from the log entry itself to prevent double spacing in the GUI.
        """
        addr_key = addr[0]
        
        if addr_key not in self.recv_buffer:
            self.recv_buffer[addr_key] = ""
            
        self.recv_buffer[addr_key] += data
        
        lines = self.recv_buffer[addr_key].split('\n')
        
        self.recv_buffer[addr_key] = lines[-1]
        
        for line in lines[:-1]:
            # The line emitted will NOT end with \n. The GUI will add it using appendHtml.
            timestamped_line = f"{self.get_timestamp()} : {line}" 
            self.log_signal.emit(timestamped_line, line) # Emit the full line and the log message content

    def run(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.server_socket.bind(('0.0.0.0', self.port))
            self.log_signal.emit(f"{self.get_timestamp()} : --- Server Started on Port {self.port} ---", "SERVER_START") 
            self.server_socket.listen(128)
            self.server_socket.settimeout(1.0) 

            while self.running:
                try:
                    client_socket, addr = self.server_socket.accept()
                    conn_msg = f"[{addr[0]}] Connected"
                    self.log_signal.emit(f"{self.get_timestamp()} : {conn_msg}", conn_msg) 
                    client_socket.settimeout(5.0)

                    with client_socket:
                        while self.running:
                            try:
                                data = client_socket.recv(1024)
                                if not data:
                                    break
                                
                                text_data = data.decode('utf-8', errors='replace')
                                self.process_data(addr, text_data)
                                
                            except socket.timeout:
                                continue
                            except OSError:
                                break
                                
                        # Client disconnected cleanup
                        addr_key = addr[0]
                        if addr_key in self.recv_buffer:
                            if self.recv_buffer[addr_key]:
                                # Flush any remaining data as a final log entry
                                timestamped_line = f"{self.get_timestamp()} : {self.recv_buffer[addr_key]}"
                                self.log_signal.emit(timestamped_line, self.recv_buffer[addr_key])
                            del self.recv_buffer[addr_key]
                        
                        # Disconnection message
                        disconn_msg = f"[{addr[0]}] Disconnected"
                        self.log_signal.emit(f"{self.get_timestamp()} : {disconn_msg}", disconn_msg)

                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        error_msg = f"Socket Error: {e}"
                        self.log_signal.emit(f"{self.get_timestamp()} : {error_msg}", error_msg)

        except Exception as e:
            bind_error = f"Bind/Listen Error: {e}"
            self.log_signal.emit(f"{self.get_timestamp()} : {bind_error}", bind_error)
        finally:
            if self.server_socket:
                self.server_socket.close()
            self.log_signal.emit(f"{self.get_timestamp()} : --- Server Stopped ---", "SERVER_STOP")

    def stop(self):
        self.running = False
        # Closing the socket gracefully
        if self.server_socket:
            self.server_socket.close()
        self.wait()

## 🖥️ Logging Tab (GUI Component)
# Handles the display of logs and color application.

class LoggingTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        console_frame = QFrame()
        console_frame.setObjectName("logOutputContainer")
        console_layout = QVBoxLayout(console_frame)
        console_layout.setContentsMargins(6, 6, 6, 6)
        console_layout.setSpacing(4)

        header_layout = QHBoxLayout()
        header_layout.setObjectName("logOutputToolbar")
        header_layout.setContentsMargins(4, 2, 4, 2)
        header_layout.addWidget(QLabel("Log Output:"))
        header_layout.addStretch()

        self.btn_copy = QPushButton()
        self.btn_copy.setFixedSize(28, 28)
        self.btn_copy.setToolTip("Copy Log to Clipboard")
        self.btn_copy.clicked.connect(self.copy_output_to_clipboard)
        header_layout.addWidget(self.btn_copy)

        self.btn_clear = QPushButton()
        self.btn_clear.setFixedSize(28, 28)
        self.btn_clear.setToolTip("Clear Log")
        self.btn_clear.clicked.connect(self.clear_output)
        header_layout.addWidget(self.btn_clear)

        console_layout.addLayout(header_layout)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setObjectName("logOutput")
        console_layout.addWidget(self.log_output)
        layout.addWidget(console_frame)
        self.apply_theme_icons()
        
        # Start Server automatically
        log_port = self._coerce_port(settings.get("log_port"), 8080)
        self.server_thread = LogServerThread(port=log_port)
        self.server_thread.log_signal.connect(self.append_log)
        self.server_thread.start()

    @staticmethod
    def _coerce_port(raw_port, default_port=8080):
        try:
            return int(raw_port)
        except (TypeError, ValueError):
            return int(default_port)

    def determine_log_color(self, content_text):
            """Determines the log message color based on content keywords."""
            
            # 1. Fixed Colors (Connection/Disconnection)
            if "Connected" in content_text:
                return COLOR_CONNECT
            if "Disconnected" in content_text:
                return COLOR_DISCONNECT
            if content_text in ("SERVER_START", "SERVER_STOP"):
                return COLOR_TRACE_LOG # White for server status

            # 2. Block Log (Blue) Detection
            
            # Keywords for Network/Socket Status (from previous version)
            block_keywords = [
                "Local ", " Remote ", "ID:", "R-Q:", "S-Q:", "ESTABLISHED", "LISTEN", 
                "TIME_WAIT", "CLOSE_WAIT", "UNKNOWN", "SYN_SENT", "CLOSING"
            ]
            if any(kw in content_text for kw in block_keywords):
                return COLOR_BLOCK_LOG
                
            # New: Detection for Sce/Module Loading blocks
            # This covers lines like: [SceMsgMiddleWare ]:text=0x...
            if content_text.strip().startswith(('[Sce', '[kkr')):
                return COLOR_BLOCK_LOG

            # 3. Trace Log (White) Detection - Default for App/Code information
            # This will catch 'Unresolved import', 'code cave', 'SDL_RWFromFile', etc.
            return COLOR_TRACE_LOG


    def append_log(self, full_log_text, content_text):
        
        # 1. Determine the color
        content_color = self.determine_log_color(content_text)

        # 2. Separate the timestamp (HH:MM:SS) from the rest of the log
        try:
            time_part, msg_part = full_log_text.split(" : ", 1)
        except ValueError:
            time_part = ""
            msg_part = full_log_text

        # 3. Construct the HTML string
        html_output = (
            f'<span style="color: {COLOR_TIMESTAMP};">{time_part} : </span>' # Gray Timestamp
            f'<span style="color: {content_color};">{msg_part}</span>'        # Colored Message (Blue or White)
        )

        # 4. Append using appendHtml (which correctly handles line breaks without double spacing)
        self.log_output.appendHtml(html_output)

    def restart_server(self, port):
        port = self._coerce_port(port, 8080)
        self.server_thread.stop()
        self.server_thread = LogServerThread(port=port)
        self.server_thread.log_signal.connect(self.append_log)
        self.server_thread.start()
        # This log message will now be white (COLOR_TRACE_LOG)
        self.append_log(f"{self.server_thread.get_timestamp()} : Restarting server on port {port}...", "Restarting server on port...")

    def sync_with_settings(self):
        """Ensures the log server uses the port from the active workspace."""
        self.apply_theme_icons()
        expected_port = self._coerce_port(settings.get("log_port"), 8080)
        if getattr(self.server_thread, "port", None) != expected_port:
            self.restart_server(expected_port)

    def apply_theme_icons(self):
        self.btn_copy.setIcon(themed_icon("alt-clipboard.svg", 18))
        self.btn_copy.setIconSize(self.btn_copy.size() * 0.6)
        self.btn_clear.setIcon(themed_icon("alt-trash.svg", 18))
        self.btn_clear.setIconSize(self.btn_clear.size() * 0.6)

    def copy_output_to_clipboard(self):
        QApplication.clipboard().setText(self.log_output.toPlainText())

    def clear_output(self):
        self.log_output.clear()

    def cleanup(self):
        if self.server_thread:
            self.server_thread.stop()
