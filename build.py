import os
import sys
import shutil
import subprocess
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QLabel, QLineEdit, QGroupBox, QPlainTextEdit, 
                               QFileDialog, QMessageBox, QApplication)
from PySide6.QtCore import QProcess, Slot, QByteArray, Qt, QTimer
from PySide6.QtGui import QTextCursor, QColor, QTextCharFormat, QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from utils import settings
import re

# --- COLOR DEFINITIONS ---
COLOR_RED = "#F44747"         # For errors
COLOR_YELLOW = "#FFD700"      # Standard make messages
COLOR_GREY = "#D4D4D4"        # Default text (explicitly used for file paths)
COLOR_BLUE = "#569CD6"        
COLOR_DARK_BLUE = "#007ACC"   # Dark blue for progress % and built targets
COLOR_TEAL = "#00FFFF"        # Turquoise for notes (ANSI 36)
COLOR_PURPLE = "#C586C0"      # Purple for warnings (ANSI 35)
COLOR_LIGHT_GREEN = "#85C664" # Light Green for "Copying raw ELF..."
COLOR_DARK_GREEN = "#487C39"  # Dark Green for final 100% build complete and Build Complete message
COLOR_THREAD_NAME = "#4EC9B0" # Running command headers
COLOR_BACKGROUND = "#1E1E1E" 
COLOR_BTN_BG = "#2d2d2d"      

# Mapping common ANSI codes to YOUR new defined colors
ANSI_COLOR_MAP = {
    '31': COLOR_RED,        # Errors
    '32': COLOR_LIGHT_GREEN, 
    '33': COLOR_YELLOW,
    '34': COLOR_BLUE,
    '35': COLOR_PURPLE,     # Warnings (Magenta/Purple)
    '36': COLOR_TEAL,       # Notes (Cyan/Turquoise)
    '0': COLOR_GREY,        # Reset
}

# The regular expression to find ANSI escape sequences
ANSI_ESCAPE = re.compile(r'(\x1B\[[\d;]*[mK])')

# REGEX to find file paths, lines, and columns: 
# Looks for /path/to/file.(c|cpp|h|...) followed by :line:column:
FILE_PATH_REGEX = re.compile(r'((?:/[^:]+)+\.[a-z]+:\d+:\d+:)', re.IGNORECASE)

# --- COPY ICON SVG (RESTORED) ---
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
        
        # --- Button layout on the same row ---
        button_row = QHBoxLayout()
        
        btn_open_folder = QPushButton("Open Build Directory") 
        btn_open_folder.clicked.connect(self.open_build_folder) 
        
        btn_term = QPushButton("Open Terminal in Build Directory")
        btn_term.clicked.connect(self.open_terminal_in_build_dir)
        
        button_row.addWidget(btn_open_folder)
        button_row.addWidget(btn_term)
        # --- END Button layout fix ---
        
        dir_layout.addLayout(path_row)
        dir_layout.addLayout(button_row)
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

        # --- OUTPUT HEADER WITH COPY BUTTON (RESTORED) ---
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
                background-color: {COLOR_BLUE};
            }}
        """)
        self.btn_copy.clicked.connect(self.copy_output_to_clipboard)
        header_layout.addWidget(self.btn_copy)

        layout.addLayout(header_layout) # ADDED BACK TO LAYOUT

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

    def open_build_folder(self):
            """Opens the current build directory in the system's default file explorer."""
            current_dir = self.build_dir
            if not os.path.isdir(current_dir):
                QMessageBox.warning(self, "Error", "Invalid build directory.")
                return

            if sys.platform == "win32":
                subprocess.Popen(['explorer', current_dir])
            elif sys.platform == "darwin":
                subprocess.Popen(['open', current_dir])
            else:
                try:
                    subprocess.Popen(['xdg-open', current_dir])
                except FileNotFoundError:
                    QMessageBox.warning(self, "Error", "Could not find 'xdg-open'.")

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
                background-color: {COLOR_LIGHT_GREEN};
                border-radius: 6px;
            }}
        """)
        # Reset style after 200ms
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
            QMessageBox.warning(self, "Error", "Invalid build directory.")
            return
        if sys.platform == "win32":
            subprocess.Popen(['start', 'cmd', '/K', 'cd', '/D', current_dir], shell=True)
        elif sys.platform == "darwin":
            subprocess.Popen(['open', '-a', 'Terminal', current_dir])
        else:
            # FIX: Robust command for Linux terminal working directory
            try:
                cd_command = f'bash -c "cd \\"{current_dir}\\" && exec bash"'
                
                terminal_cmds = [
                    ['x-terminal-emulator', '-e', cd_command],
                    ['gnome-terminal', '--command', cd_command],
                    ['konsole', '--separate', '-e', cd_command],
                ]

                for cmd in terminal_cmds:
                    try:
                        subprocess.Popen(cmd)
                        return
                    except FileNotFoundError:
                        continue
                
                QMessageBox.warning(self, "Error", "Could not find a working terminal emulator.")
            
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Error opening terminal: {e}")

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
            # FIX: Ensure 'python_cleanup' has a second, empty argument list to prevent IndexError.
            self.build_queue = [['python_cleanup', []], ['cmake', ['..']], ['make', []]]
        
        self.execute_next_command()

    def execute_next_command(self):
        if not self.build_queue:
            self.append_colored_line("--- Build Complete ---", COLOR_DARK_GREEN)
            self.set_buttons_enabled(True)
            return

        # cmd_info is guaranteed to have 2 elements now: [command, [args]]
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
        cursor.insertText(text)
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

        parts = ANSI_ESCAPE.split(text_chunk)
        current_color = COLOR_GREY 

        for part in parts:
            if not part:
                continue
            
            # 1. Update current_color based on ANSI codes from the compiler
            if ANSI_ESCAPE.match(part):
                code_str = part[2:-1] 
                codes = code_str.split(';')
                for code in codes:
                    if code in ANSI_COLOR_MAP:
                        current_color = ANSI_COLOR_MAP[code]
                    elif code == '0': 
                        current_color = COLOR_GREY
            
            # 2. Process actual text and apply custom overrides
            else:
                lines = part.split('\n')
                for i, line in enumerate(lines):
                    
                    output_line = line
                    output_color = current_color
                    line_lower = output_line.lower()
                    
                    # --- Custom Color Override Logic ---
                    
                    # A. File Path Color Fix (MUST RUN FIRST to apply grey to paths)
                    match = FILE_PATH_REGEX.search(output_line)
                    if match:
                        path_text = match.group(1)
                        # Split the line into three parts: before path, path, and after path
                        pre_path = output_line[:match.start()]
                        post_path = output_line[match.end():]
                        
                        # Apply original color to text before path
                        if pre_path:
                            self.append_colored_line(pre_path, output_color)
                            
                        # Apply GREY to the path itself
                        self.append_colored_line(path_text, COLOR_GREY)
                        
                        # Update output_line to be the remainder after the path
                        output_line = post_path
                        
                        # Skip the rest of the standard logic for this loop, continue with remaining text below
                        if output_line:
                            self.append_colored_line(output_line, output_color)
                        
                        if i < len(lines) - 1:
                            self.append_colored_line('\n', COLOR_GREY)
                        continue # Move to the next line/part
                        

                    # B. Progress % and Built Target (Dark Blue)
                    if re.match(r'\[\s*\d+%\]', line):
                        output_color = COLOR_DARK_BLUE
                    
                    # C. Final 100% Build Completion (Dark Green)
                    if line_lower.startswith("[100%]") and ("building vpk" in line_lower or "built target ncsj.vpk" in line_lower):
                        output_color = COLOR_DARK_GREEN

                    # D. Copying raw ELF (Light Green)
                    if "copying raw elf" in line_lower:
                        output_color = COLOR_LIGHT_GREEN
                        
                    # E. Errors (Red)
                    if 'error:' in line_lower or 'failed' in line_lower or 'fatal' in line_lower:
                        output_color = COLOR_RED
                    
                    # F. Warnings (Purple) and Notes (Teal) are handled by the ANSI parser setting current_color (35/36).
                    
                    # --- End Custom Color Override Logic ---
                    
                    # Append the whole line with the determined color
                    if line:
                        self.append_colored_line(output_line, output_color)
                    
                    if i < len(lines) - 1:
                        self.append_colored_line('\n', COLOR_GREY)

    @Slot(int, QProcess.ExitStatus)
    def build_process_finished(self, exitCode, exitStatus):
        if exitCode != 0:
            self.append_colored_line(f"\n!!! Command Failed (Code: {exitCode}) !!!\n", COLOR_RED)
            self.set_buttons_enabled(True)
        else:
            self.execute_next_command()
    
    def cleanup(self):
        if self.build_process.state() != QProcess.NotRunning:
            self.build_process.terminate()