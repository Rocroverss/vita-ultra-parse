import os
import sys
import shutil
import subprocess
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QLabel, QLineEdit, QGroupBox, QPlainTextEdit, 
                               QFileDialog, QMessageBox, QApplication)
from PySide6.QtCore import QProcess, Slot, QByteArray, Qt
from PySide6.QtGui import QTextCursor, QColor, QTextCharFormat, QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from utils import settings

# --- COLOR DEFINITIONS ---
COLOR_RED = "#F44747"       
COLOR_YELLOW = "#FFD700"    
COLOR_GREY = "#D4D4D4"      
COLOR_BLUE = "#569CD6"      
COLOR_TEAL = "#00FFFF"      
COLOR_ORANGE = "#FF8C00"    
COLOR_THREAD_NAME = "#4EC9B0" 
COLOR_SYM_NAME = "#85C664"    
COLOR_ADDR_BASE = "#FFFFFF"   
COLOR_BACKGROUND = "#1E1E1E" 
COLOR_BTN_BG = "#2d2d2d"      

# Your SVG Icon (I added fill="#D4D4D4" so it is visible on the dark button)
COPY_ICON_SVG = """
<svg clip-rule="evenodd" fill-rule="evenodd" stroke-linejoin="round" stroke-miterlimit="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <path fill="#D4D4D4" d="m6 19v2c0 .621.52 1 1 1h2v-1.5h-1.5v-1.5zm7.5 3h-3.5v-1.5h3.5zm4.5 0h-3.5v-1.5h3.5zm4-3h-1.5v1.5h-1.5v1.5h2c.478 0 1-.379 1-1zm-1.5-1v-3.363h1.5v3.363zm0-4.363v-3.637h1.5v3.637zm-13-3.637v3.637h-1.5v-3.637zm11.5-4v1.5h1.5v1.5h1.5v-2c0-.478-.379-1-1-1zm-10 0h-2c-.62 0-1 .519-1 1v2h1.5v-1.5h1.5zm4.5 1.5h-3.5v-1.5h3.5zm3-1.5v-2.5h-13v13h2.5v-1.863h1.5v3.363h-4.5c-.48 0-1-.379-1-1v-14c0-.481.38-1 1-1h14c.621 0 1 .522 1 1v4.5h-3.5v-1.5z" fill-rule="nonzero"/>
</svg>
"""

class BuildTab(QWidget):
    def __init__(self):
        super().__init__()
        self.build_dir = settings.get("last_build_dir")
        self.build_queue = []
        self.build_process = QProcess()
        
        self.build_process.setProcessChannelMode(QProcess.MergedChannels)
        self.build_process.readyReadStandardOutput.connect(self.handle_build_output)
        self.build_process.finished.connect(self.build_process_finished)

        layout = QVBoxLayout(self)

        # Top Row
        top_row_layout = QHBoxLayout()
        
        # 1. Directory Group
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

        # 2. Commands Group
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

        # --- OUTPUT HEADER WITH COPY BUTTON ---
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Build Output:"))
        header_layout.addStretch() # Push button to the right

        # Create Copy Button
        self.btn_copy = QPushButton()
        self.btn_copy.setToolTip("Copy Log to Clipboard")
        self.btn_copy.setFixedSize(32, 32) # Small square button
        
        # Set Icon from SVG String
        self.btn_copy.setIcon(self.create_icon_from_string(COPY_ICON_SVG))
        self.btn_copy.setIconSize(self.btn_copy.size() * 0.6) # Scale icon slightly down

        # Style the Copy Button
        self.btn_copy.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_BTN_BG};
                border-radius: 6px;
                border: 1px solid #3E3E3E;
            }}
            QPushButton:hover {{
                background-color: #3d3d3d;
                border: 1px solid #555;
            }}
            QPushButton:pressed {{
                background-color: #569CD6;
            }}
        """)
        self.btn_copy.clicked.connect(self.copy_output_to_clipboard)
        header_layout.addWidget(self.btn_copy)

        layout.addLayout(header_layout)

        # Output Text Area
        self.build_output = QPlainTextEdit()
        self.build_output.setReadOnly(True)
        self.build_output.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {COLOR_BACKGROUND}; 
                color: {COLOR_GREY}; 
                font-family: Consolas, 'Courier New', Monospace;
                border: 1px solid #444;
                font-size: 10pt;
            }}
        """)
        layout.addWidget(self.build_output)

    def create_icon_from_string(self, svg_str):
        """Helper to convert SVG string to QIcon"""
        renderer = QSvgRenderer(QByteArray(svg_str.encode()))
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)

    def copy_output_to_clipboard(self):
        """Copies content of the build output to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.build_output.toPlainText())
        
        # Optional: Flash the button green briefly to indicate success
        original_style = self.btn_copy.styleSheet()
        self.btn_copy.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SYM_NAME};
                border-radius: 6px;
            }}
        """)
        # Reset style after 200ms
        from PySide6.QtCore import QTimer
        QTimer.singleShot(200, lambda: self.btn_copy.setStyleSheet(original_style))

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
            try:
                subprocess.Popen(['x-terminal-emulator', '--working-directory=' + current_dir])
            except FileNotFoundError:
                subprocess.Popen(['gnome-terminal', '--working-directory=' + current_dir])

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
            self.append_colored_line("--- Build Complete ---", COLOR_SYM_NAME)
            self.set_buttons_enabled(True)
            return

        cmd_info = self.build_queue.pop(0)
        cmd, args = cmd_info[0], cmd_info[1]

        if cmd == 'python_cleanup':
            self.append_colored_line("Running clean up...", COLOR_YELLOW)
            try:
                if len(self.build_dir) < 5: 
                    raise Exception("Build path too short, unsafe to delete.")
                for item in os.listdir(self.build_dir):
                    item_path = os.path.join(self.build_dir, item)
                    if ".git" in item: continue 
                    if os.path.isfile(item_path): os.remove(item_path)
                    elif os.path.isdir(item_path): shutil.rmtree(item_path)
                self.execute_next_command()
            except Exception as e:
                self.append_colored_line(f"Cleanup Error: {e}", COLOR_RED)
                self.set_buttons_enabled(True)
            return

        self.append_colored_line(f"\n> Running: {cmd} {' '.join(args)}", COLOR_THREAD_NAME)
        self.build_process.setWorkingDirectory(self.build_dir)
        self.build_process.start(cmd, args)
        
        if not self.build_process.waitForStarted(1000):
            self.append_colored_line(f"ERROR: Failed to start {cmd}", COLOR_RED)
            self.set_buttons_enabled(True)

    def set_buttons_enabled(self, enabled):
        for btn in self.cmd_group.findChildren(QPushButton):
            btn.setEnabled(enabled)

    def append_colored_line(self, text, color_hex):
        self.build_output.moveCursor(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color_hex))
        cursor = self.build_output.textCursor()
        cursor.setCharFormat(fmt)
        cursor.insertText(text + "\n")
        self.build_output.setTextCursor(cursor)
        sb = self.build_output.verticalScrollBar()
        sb.setValue(sb.maximum())

    @Slot()
    def handle_build_output(self):
        data = self.build_process.readAllStandardOutput().data()
        try:
            text_chunk = data.decode('utf-8', errors='ignore')
        except:
            return

        lines = text_chunk.splitlines()
        for line in lines:
            line_lower = line.lower()
            color = COLOR_GREY 
            if "error:" in line_lower or "failed" in line_lower or "fatal" in line_lower:
                color = COLOR_RED
            elif "warning:" in line_lower:
                color = COLOR_ORANGE
            elif "[100%]" in line:
                color = COLOR_SYM_NAME 
            elif "scanning dependencies" in line_lower:
                color = COLOR_TEAL
            elif "built target" in line_lower or "linking" in line_lower:
                color = COLOR_BLUE
            elif "make" in line_lower and ("entering" in line_lower or "leaving" in line_lower):
                color = COLOR_YELLOW

            self.append_colored_line(line, color)

    @Slot(int, QProcess.ExitStatus)
    def build_process_finished(self, exitCode, exitStatus):
        if exitCode != 0:
            self.append_colored_line(f"\n!!! Command Failed (Code: {exitCode}) !!!", COLOR_RED)
            self.set_buttons_enabled(True)
        else:
            self.execute_next_command()
    
    def cleanup(self):
        if self.build_process.state() != QProcess.NotRunning:
            self.build_process.terminate()