import os
import sys
import shutil
import subprocess
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QLabel, QLineEdit, QGroupBox, QPlainTextEdit, 
                               QFileDialog, QMessageBox)
from PySide6.QtCore import QProcess, Slot
from PySide6.QtGui import QTextCursor
from utils import settings

class BuildTab(QWidget):
    def __init__(self):
        super().__init__()
        self.build_dir = settings.get("last_build_dir")
        self.build_queue = []
        self.build_process = QProcess()
        self.build_process.readyReadStandardOutput.connect(self.handle_build_output)
        self.build_process.readyReadStandardError.connect(self.handle_build_output)
        self.build_process.finished.connect(self.build_process_finished)

        layout = QVBoxLayout(self)

        # Top Row
        top_row_layout = QHBoxLayout()
        
        # 1. Directory
        dir_group = QGroupBox("Build Directory")
        dir_layout = QVBoxLayout()
        path_row = QHBoxLayout()
        self.build_dir_input = QLineEdit(self.build_dir) 
        btn_browse = QPushButton("Browse")
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self.browse_build_dir)
        path_row.addWidget(self.build_dir_input)
        path_row.addWidget(btn_browse)
        
        btn_term = QPushButton("Open Terminal in Build Directory")
        btn_term.clicked.connect(self.open_terminal_in_build_dir)
        dir_layout.addLayout(path_row)
        dir_layout.addWidget(btn_term)
        dir_group.setLayout(dir_layout)

        # 2. Commands
        self.cmd_group = QGroupBox("Build Commands")
        cmd_layout = QVBoxLayout()
        btn_rebuild = QPushButton("Rebuild (make clean make)")
        btn_rebuild.clicked.connect(lambda: self.run_build_sequence("rebuild"))
        btn_full_build = QPushButton("Full Build (rm -rf *, cmake .., make)")
        btn_full_build.clicked.connect(lambda: self.run_build_sequence("full_build"))
        cmd_layout.addWidget(btn_rebuild)
        cmd_layout.addWidget(btn_full_build)
        self.cmd_group.setLayout(cmd_layout)

        top_row_layout.addWidget(dir_group, 3)
        top_row_layout.addWidget(self.cmd_group, 2)
        layout.addLayout(top_row_layout)

        # Output
        layout.addWidget(QLabel("Build Output:"))
        self.build_output = QPlainTextEdit()
        self.build_output.setReadOnly(True)
        self.build_output.setStyleSheet("""
            QPlainTextEdit {
                background-color: #000000; 
                color: #3ecf4c; 
                font-family: Consolas, Monospace;
                border: 1px solid #444;
            }
        """)
        layout.addWidget(self.build_output)

    def browse_build_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Build Directory", self.build_dir)
        if folder:
            self.build_dir = folder
            self.build_dir_input.setText(folder)
            settings.set("last_build_dir", folder)

    def open_terminal_in_build_dir(self):
        current_dir = self.build_dir
        if not os.path.isdir(current_dir):
            return
        if sys.platform == "win32":
            subprocess.Popen(['start', 'cmd', '/K', 'cd', '/D', current_dir], shell=True)
        elif sys.platform == "darwin":
            subprocess.Popen(['open', '-a', 'Terminal', current_dir])
        else:
            subprocess.Popen(['x-terminal-emulator', '--working-directory=' + current_dir])

    def run_build_sequence(self, mode):
        if self.build_process.state() != QProcess.NotRunning:
            QMessageBox.warning(self, "Build In Progress", "A build is already running.")
            return
        if not os.path.isdir(self.build_dir):
            QMessageBox.warning(self, "Error", "Invalid build directory.")
            return

        self.build_output.clear()
        self.set_buttons_enabled(False)

        if mode == "rebuild":
            self.build_queue = [['make', ['clean']], ['make', []]]
        elif mode == "full_build":
            self.build_queue = [['python_cleanup'], ['cmake', ['..']], ['make', []]]
        
        self.execute_next_command()

    def execute_next_command(self):
        if not self.build_queue:
            self.build_output.appendPlainText("\n--- Build Complete ---")
            self.set_buttons_enabled(True)
            return

        cmd_info = self.build_queue.pop(0)
        cmd, args = cmd_info[0], cmd_info[1]

        if cmd == 'python_cleanup':
            self.build_output.appendPlainText("Running cleanup...")
            try:
                for item in os.listdir(self.build_dir):
                    item_path = os.path.join(self.build_dir, item)
                    if os.path.isfile(item_path): os.remove(item_path)
                    elif os.path.isdir(item_path): shutil.rmtree(item_path)
                self.execute_next_command()
            except Exception as e:
                self.build_output.appendPlainText(f"Cleanup Error: {e}")
                self.set_buttons_enabled(True)
            return

        self.build_output.appendPlainText(f"\n> Running: {cmd} {' '.join(args)}")
        self.build_process.setWorkingDirectory(self.build_dir)
        self.build_process.start(cmd, args)
        if not self.build_process.waitForStarted(1000):
            self.build_output.appendPlainText(f"ERROR: Failed to start {cmd}")
            self.set_buttons_enabled(True)

    def set_buttons_enabled(self, enabled):
        for btn in self.cmd_group.findChildren(QPushButton):
            btn.setEnabled(enabled)

    @Slot()
    def handle_build_output(self):
        out = self.build_process.readAllStandardOutput().data().decode('utf-8', errors='ignore')
        err = self.build_process.readAllStandardError().data().decode('utf-8', errors='ignore')
        if out: self.build_output.insertPlainText(out)
        if err: self.build_output.insertPlainText(err)
        self.build_output.moveCursor(QTextCursor.End)

    @Slot(int, QProcess.ExitStatus)
    def build_process_finished(self, exitCode, exitStatus):
        if exitCode != 0:
            self.build_output.appendPlainText(f"\n!!! Failed (Code: {exitCode}) !!!")
            self.set_buttons_enabled(True)
        else:
            self.execute_next_command()
    
    def cleanup(self):
        if self.build_process.state() != QProcess.NotRunning:
            self.build_process.terminate()