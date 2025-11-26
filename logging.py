import socket
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPlainTextEdit
from PySide6.QtCore import QThread, Signal
from utils import settings

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
        self.wait()

class LoggingTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setObjectName("logOutput")
        layout.addWidget(self.log_output)
        
        # Start Server automatically
        self.server_thread = LogServerThread(port=settings.get("log_port"))
        self.server_thread.log_signal.connect(self.append_log)
        self.server_thread.start()

    def append_log(self, text):
        self.log_output.appendPlainText(text)

    def restart_server(self, port):
        self.server_thread.stop()
        self.server_thread = LogServerThread(port=port)
        self.server_thread.log_signal.connect(self.append_log)
        self.server_thread.start()
        self.append_log(f"Restarting server on port {port}...")

    def cleanup(self):
        if self.server_thread:
            self.server_thread.stop()