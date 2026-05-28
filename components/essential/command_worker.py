import re
import socket
import threading

from PySide6.QtCore import QThread, Signal


class CommandWorker(QThread):
    command_output_signal = Signal(str, str)
    battery_signal = Signal(int, bool)

    def __init__(self, settings_instance):
        super().__init__()
        self.settings = settings_instance
        self.host = self.settings.get("vita_ip", "192.168.1.100")
        self.port = 1338
        self.command_queue = []
        self.running = True
        self.mutex = threading.Lock()

    def add_command(self, cmd_string):
        with self.mutex:
            self.command_queue.append(cmd_string)

    def set_host(self, host):
        self.host = host

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
                if command != "battery":
                    self.command_output_signal.emit(
                        f"Attempting to send command: '{command}'", "orange"
                    )

                s.connect((self.host, self.port))
                s.sendall(f"{command}\n".encode("utf-8"))
                response = s.recv(1024).decode("utf-8", errors="ignore").strip()

                if command == "battery":
                    match = re.search(r"Battery:\s*(\d+)%\s*\((.*)\)", response)
                    if match:
                        level = int(match.group(1))
                        status_text = match.group(2).lower()
                        is_charging = "not charging" not in status_text
                        self.battery_signal.emit(level, is_charging)
                    return

                self.command_output_signal.emit(
                    f"Cmd: {command} -> {response}", "#3ecf4c"
                )
        except Exception as e:
            if command != "battery":
                self.command_output_signal.emit(f"Cmd Error: {e}", "red")

    def stop(self):
        self.running = False
        self.wait()
