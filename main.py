import sys
import os
import socket
import threading
import re
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QLineEdit, QTabWidget,
    QGroupBox, QMessageBox, QFrame, QFileDialog, QStyle,
    QTextEdit, QSpinBox, QListWidget, QListWidgetItem,
    QInputDialog, QComboBox
)
from PySide6.QtGui import QColor, QPainter, QFont, QIntValidator, QIcon, QPixmap
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer, QSize, QByteArray
from PySide6.QtSvg import QSvgRenderer
from pathlib import Path
# ==========================================
# THEME SYSTEM (icons + palette from THEMES/<theme>/theme.txt)
# ==========================================

THEMES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "THEMES")

# ==========================================
# SVG CONSTANTS & UTILITY (fallback icons)
# ==========================================

THEME_DIR = Path("THEMES") / "default"

from pathlib import Path

THEME_DIR = Path("THEMES") / "default"

def load_svg(filename: str, fallback: str) -> str:
    file_path = THEME_DIR / filename
    try:
        if file_path.exists():
            return file_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"SVG load error for {filename}: {e}")

    return fallback

SETTINGS_SVG_FALLBACK = """<svg>...</svg>"""
INFO_SVG_FALLBACK = """<svg>...</svg>"""
SAVE_SVG_FALLBACK = """<svg>...</svg>"""


SETTINGS_SVG = load_svg("settings.svg", SETTINGS_SVG_FALLBACK)
INFO_SVG     = load_svg("info.svg", INFO_SVG_FALLBACK)
SAVE_SVG     = load_svg("save.svg", SAVE_SVG_FALLBACK)


BATTERY_SVGS_FALLBACK = {
    "alt-battery-1.svg": """<svg>...</svg>""",
    "alt-battery-2.svg": """<svg>...</svg>""",
    "alt-battery-3.svg": """<svg>...</svg>""",
    "alt-battery-4.svg": """<svg>...</svg>""",
    "alt-battery-5.svg": """<svg>...</svg>""",
    "alt-charge-battery.svg": """<svg>...</svg>""",
}

BATTERY_SVGS = {
    name: load_svg(name, fallback)
    for name, fallback in BATTERY_SVGS_FALLBACK.items()
}


def svg_to_qicon(svg_content: str, size: int = 24) -> QIcon:
    """Converts an SVG string into a QIcon."""
    renderer = QSvgRenderer(QByteArray(svg_content.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def qicon_from_svg_file(path: str, size: int = 24) -> QIcon:
    """Converts an SVG file on disk into a QIcon."""
    if not os.path.exists(path):
        return QIcon()
    renderer = QSvgRenderer(path)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


class BatteryWidget(QWidget):
    def __init__(self, theme_path, parent=None):
        super().__init__(parent)
        self.theme_path = theme_path
        
        # Layout
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.setLayout(layout)

        # Percentage Label
        self.lbl_text = QLabel("--%")
        # Use a generic style, will be overridden by main window CSS if needed, 
        # but here we ensure it's visible
        self.lbl_text.setStyleSheet("font-weight: bold; color: #888;")
        
        # Icon Label
        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(24, 24)
        self.lbl_icon.setScaledContents(True)

        layout.addWidget(self.lbl_text)
        layout.addWidget(self.lbl_icon)
        
        # Default state
        self.update_battery(0, is_charging=False, connected=False)

    def update_theme_path(self, new_path):
        self.theme_path = new_path
        # Force refresh with last known values if we had storage, 
        # for now just reset or wait for next update

    def update_battery(self, level: int, is_charging: bool = False, connected: bool = True):
        """
        Updates the battery icon and color based on level.
        """
        if not connected:
            self.lbl_text.setText("--%")
            self.lbl_icon.clear()
            return

        self.lbl_text.setText(f"{level}%")
        
        icon_name = ""
        color = ""

        # Logic per requirements
        if is_charging:
            icon_name = "alt-charge-battery.svg"
            color = "#3ecf4c"# Green
        else:
            if level < 20:
                icon_name = "alt-battery-1.svg"
                color = "#ff3333" # Red
            elif 20 <= level < 40:
                icon_name = "alt-battery-2.svg"
                color = "orange" # Orange
            elif 40 <= level < 60:
                icon_name = "alt-battery-3.svg"
                color = "#3ecf4c" # Green
            elif 60 <= level < 80:
                icon_name = "alt-battery-4.svg"
                color = "#3ecf4c" # Green
            else: # 80 - 100
                icon_name = "alt-battery-5.svg"
                color = "#3ecf4c" # Green

        # Load and Tint Pixmap
        pixmap = QPixmap()
        loaded = False
        
        # 1. Try to load from file (Theme path -> Default path)
        full_path = os.path.join(self.theme_path, "icons", icon_name)
        if not os.path.exists(full_path):
            default_path = os.path.join(THEMES_DIR, "default", "icons", icon_name)
            if os.path.exists(default_path):
                full_path = default_path
            
        if os.path.exists(full_path):
            pixmap.load(full_path)
            loaded = True
        
        # 2. Fallback to embedded SVG if file not found
        if not loaded and icon_name in BATTERY_SVGS:
            renderer = QSvgRenderer(QByteArray(BATTERY_SVGS[icon_name].encode("utf-8")))
            pixmap = QPixmap(24, 24)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            loaded = True

        if loaded and not pixmap.isNull():
            # Apply Color Overlay
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), QColor(color))
            painter.end()
            self.lbl_icon.setPixmap(pixmap)
        else:
            print(f"Battery Icon missing: {icon_name}")


class Theme:
    def __init__(self, name: str, base_dir: str):
        self.name = name
        self.base_dir = base_dir
        self.palette: dict[str, str] = {}
        self.icons: dict[str, str] = {}

    def load(self):
        self._load_palette()
        self._load_icons()

    def _load_palette(self):
        """Parse theme.txt as simple key=value or key: value lines."""
        theme_file = os.path.join(self.base_dir, "theme.txt")
        palette: dict[str, str] = {}
        if os.path.exists(theme_file):
            try:
                with open(theme_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or line.startswith("//"):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                        elif ":" in line:
                            key, val = line.split(":", 1)
                        else:
                            continue
                        palette[key.strip()] = val.strip()
            except Exception as e:
                print(f"Warning: failed to read theme file '{theme_file}': {e}")
        self.palette = palette

    def _load_icons(self):
        """Map logical icon keys to SVG files inside the theme folder."""
        def icon_path(filename: str) -> str:
            return os.path.join(self.base_dir, filename)

        self.icons = {
            "workspace": icon_path("alt-workspace.svg"),
            "settings": icon_path("alt-setting.svg"),
            "help": icon_path("alt-info.svg"),
            "refresh": icon_path("alt-refresh.svg"),
            "terminal": icon_path("alt-terminal.svg"),
            "folder": icon_path("alt-folder.svg"),
            "save": icon_path("alt-save-floppy.svg"),
            "search": icon_path("alt-search.svg"),
            "trash": icon_path("alt-trash.svg"),
        }


current_theme: Optional[Theme] = None


def load_theme(theme_name: str = "default") -> Theme:
    """Create and load a Theme instance from THEMES/<theme_name>."""
    global current_theme

    base_dir = os.path.join(THEMES_DIR, theme_name)
    if not os.path.isdir(base_dir):
        if theme_name != "default":
            print(f"Warning: theme '{theme_name}' not found, falling back to 'default'")
        base_dir = os.path.join(THEMES_DIR, "default")

    theme = Theme(theme_name, base_dir)
    theme.load()
    current_theme = theme
    return theme


# ==========================================
# REAL MODULES OR MOCK FALLBACKS
# ==========================================

try:
    from utils import settings  # real settings
    from logging import LoggingTab  # type: ignore
    from core_dump import CoreDumpTab  # type: ignore
    from build import BuildTab  # type: ignore
    from file_transfer import FileTransferTab  # type: ignore
    from sdk_installation import SdkInstallationTab  # type: ignore

    # Make sure workspace API exists
    if not hasattr(settings, "DEFAULT_WORKSPACE_NAME"):
        settings.DEFAULT_WORKSPACE_NAME = "Default"

    if not hasattr(settings, "get_workspaces"):
        def _get_workspaces():
            return [settings.DEFAULT_WORKSPACE_NAME]
        settings.get_workspaces = _get_workspaces  # type: ignore[attr-defined]

    if not hasattr(settings, "get_current_workspace_name"):
        def _get_current_workspace_name():
            return settings.DEFAULT_WORKSPACE_NAME
        settings.get_current_workspace_name = _get_current_workspace_name  # type: ignore[attr-defined]

    if not hasattr(settings, "load_workspace"):
        def _load_workspace(name: str) -> bool:
            return True
        settings.load_workspace = _load_workspace  # type: ignore[attr-defined]

    if not hasattr(settings, "create_workspace"):
        def _create_workspace(name: str) -> bool:
            return False
        settings.create_workspace = _create_workspace  # type: ignore[attr-defined]

    if not hasattr(settings, "delete_workspace"):
        def _delete_workspace(name: str) -> bool:
            return False
        settings.delete_workspace = _delete_workspace  # type: ignore[attr-defined]

except ImportError as e:
    print(f"WARNING: Local module imports failed: {e}. Running in MOCK mode.")

    class MockSettings:
        DEFAULT_WORKSPACE_NAME = "Default"

        _all_workspaces = {
            DEFAULT_WORKSPACE_NAME: {
                "log_font_size": 13,
                "vita_ip": "192.168.1.100",
                "sdk_path": "/path/to/vitasdk",
                "last_build_dir": os.getcwd(),
                "log_port": 8080,
                "exec_path": "",
                "target_app_id": "PCSG00000",
                "launch_title_id": "VHBB00001",
                "dump_folder": "",
                "vita_port": 1337,
                "base_font_size": 10,
                "theme_name": "default",
            },
        }
        _current_workspace_name = DEFAULT_WORKSPACE_NAME

        def __init__(self):
            self._current_data = self._all_workspaces.get(
                self._current_workspace_name,
                self._all_workspaces[self.DEFAULT_WORKSPACE_NAME],
            )

        def get_workspaces(self):
            return list(self._all_workspaces.keys())

        def get_current_workspace_name(self):
            return self._current_workspace_name

        def load_workspace(self, name: str) -> bool:
            if name in self._all_workspaces:
                self._current_workspace_name = name
                self._current_data = self._all_workspaces[name]
                return True
            return False

        def create_workspace(self, name: str) -> bool:
            name = name.strip()
            if not name or name in self._all_workspaces:
                return False
            self._all_workspaces[name] = self._current_data.copy()
            self.load_workspace(name)
            return True

        def delete_workspace(self, name: str) -> bool:
            if name == self.DEFAULT_WORKSPACE_NAME:
                return False
            if name in self._all_workspaces:
                del self._all_workspaces[name]
                if self._current_workspace_name == name:
                    self.load_workspace(self.DEFAULT_WORKSPACE_NAME)
                return True
            return False

        def get(self, key, default=None):
            return self._current_data.get(key, default)

        def set(self, key, value):
            self._current_data[key] = value

        def save(self):
            print(
                f"Mock Save: Current workspace '{self._current_workspace_name}' and all others saved."
            )

    settings = MockSettings()  # type: ignore[assignment]

    class MockTab(QWidget):
        def __init__(self):
            super().__init__()
            layout = QVBoxLayout(self)
            label = QLabel("Mock Tab (real module not found)")
            layout.addWidget(label)
            layout.addStretch()

        def cleanup(self):
            pass

    class LoggingTab(MockTab):  # type: ignore[no-redef]
        def __init__(self):
            super().__init__()
            self.log_output = QTextEdit()
            self.log_output.setObjectName("logOutput")
            self.layout().addWidget(self.log_output)

        def append_log(self, message, color):
            self.log_output.append(
                f'<span style="color: {color};">{message}</span>'
            )

        def restart_server(self, port):
            QMessageBox.information(
                self, "Server", f"Log Server Restarted on port {port}"
            )

    class FileTransferTab(MockTab):  # type: ignore[no-redef]
        class MockFTPThread(QThread):
            status_signal = Signal(str, str)
            progress_signal = Signal(str)

            def run(self):
                self.status_signal.emit("Connected (FTP Mock)", "#3ecf4c")
                self.progress_signal.emit("Idle")
                self.exec()

            def add_command(self, cmd, *args):
                if cmd == "upload":
                    self.progress_signal.emit("Uploading eboot.bin...")
                    QTimer.singleShot(
                        2000, lambda: self.progress_signal.emit("Idle")
                    )

        def __init__(self):
            super().__init__()
            self.ftp_thread = self.MockFTPThread()
            self.ftp_thread.start()

        def connect_ftp(self):
            QMessageBox.information(self, "FTP", "Connecting FTP (Mock)...")
            self.ftp_thread.status_signal.emit("Connecting...", "orange")
            QTimer.singleShot(
                1000,
                lambda: self.ftp_thread.status_signal.emit(
                    "Connected (FTP Mock)", "#3ecf4c"
                ),
            )

    class CoreDumpTab(MockTab):  # type: ignore[no-redef]
        @Slot()
        def fetch_and_parse_last_crash(self):
            QMessageBox.information(
                self,
                "Core Dump",
                "Mock: fetching and parsing last crash (not implemented).",
            )

    class BuildTab(MockTab):  # type: ignore[no-redef]
        pass

    class SdkInstallationTab(MockTab):  # type: ignore[no-redef]
        pass


# ==========================================
# STATUS DOT
# ==========================================

class ColorDot(QWidget):
    """Small colored circle widget."""
    def __init__(self, color="#777", size=10):
        super().__init__()
        self._color = QColor(color)
        self._size = size
        self.setFixedSize(size, size)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self._color)
        painter.setPen(Qt.NoPen)
        rect = self.rect()
        diameter = min(rect.width(), rect.height()) * 0.8
        painter.drawEllipse(
            rect.center().x() - diameter / 2,
            rect.center().y() - diameter / 2,
            diameter,
            diameter,
        )


# ==========================================
# WORKSPACE TAB
# ==========================================

class WorkspaceTab(QWidget):
    workspace_changed = Signal()

    def __init__(self, settings_instance):
        super().__init__()
        self.settings = settings_instance

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        self.current_label = QLabel(
            f"<b>Current Workspace:</b> {self.settings.get_current_workspace_name()}"
        )
        self.current_label.setFont(QFont("Arial", 12))
        layout.addWidget(self.current_label)
        layout.addSpacing(10)

        list_grp = QGroupBox("Available Workspaces")
        list_layout = QVBoxLayout(list_grp)

        self.workspace_list = QListWidget()
        self.workspace_list.setMinimumHeight(200)
        self.workspace_list.setStyleSheet(
            "background-color: #2d2d2d; border-radius: 4px; padding: 4px;"
        )
        self.workspace_list.itemDoubleClicked.connect(self.load_selected)
        list_layout.addWidget(self.workspace_list)

        hbox_actions = QHBoxLayout()
        self.btn_load = QPushButton("Load Selected")
        self.btn_load.clicked.connect(self.load_selected)
        hbox_actions.addWidget(self.btn_load)

        self.btn_delete = QPushButton("Delete Selected")
        self.btn_delete.setStyleSheet("background-color: #8B0000;")
        self.btn_delete.clicked.connect(self.delete_selected)
        hbox_actions.addWidget(self.btn_delete)

        list_layout.addLayout(hbox_actions)
        layout.addWidget(list_grp)
        layout.addSpacing(10)

        create_grp = QGroupBox("Create New Workspace")
        create_layout = QVBoxLayout(create_grp)

        self.btn_create = QPushButton("Create Workspace from Current Settings")
        self.btn_create.clicked.connect(self.create_new)
        create_layout.addWidget(self.btn_create)

        layout.addWidget(create_grp)
        layout.addStretch()

        self.refresh_list()

    @Slot()
    def refresh_list(self):
        self.workspace_list.clear()
        current_name = self.settings.get_current_workspace_name()
        try:
            workspaces = self.settings.get_workspaces()
        except AttributeError:
            workspaces = [getattr(self.settings, "DEFAULT_WORKSPACE_NAME", "Default")]

        for name in workspaces:
            item = QListWidgetItem(name)
            if name == current_name:
                item.setFont(QFont("Arial", 10, QFont.Bold))
                item.setText(f"{name} (ACTIVE)")
                item.setForeground(QColor("#3ecf4c"))
            self.workspace_list.addItem(item)

        self.current_label.setText(f"<b>Current Workspace:</b> {current_name}")

    @Slot()
    def load_selected(self):
        items = self.workspace_list.selectedItems()
        if not items:
            QMessageBox.warning(self, "Load Error", "Please select a workspace.")
            return

        name = items[0].text().replace(" (ACTIVE)", "")
        if name == self.settings.get_current_workspace_name():
            QMessageBox.information(
                self, "Load Info", f"Workspace '{name}' is already active."
            )
            return

        if self.settings.load_workspace(name):
            self.refresh_list()
            self.workspace_changed.emit()
            QMessageBox.information(
                self, "Load Success", f"Workspace '{name}' loaded successfully."
            )
        else:
            QMessageBox.critical(
                self, "Load Error", f"Could not load workspace '{name}'."
            )

    @Slot()
    def delete_selected(self):
        items = self.workspace_list.selectedItems()
        if not items:
            QMessageBox.warning(
                self, "Delete Error", "Please select a workspace to delete."
            )
            return

        name = items[0].text().replace(" (ACTIVE)", "")

        if name == getattr(self.settings, "DEFAULT_WORKSPACE_NAME", "Default"):
            QMessageBox.critical(
                self, "Delete Error", "Cannot delete the default workspace."
            )
            return

        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to permanently delete workspace '{name}'? This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.No:
            return

        if self.settings.delete_workspace(name):
            self.refresh_list()
            self.workspace_changed.emit()
            QMessageBox.information(
                self, "Delete Success", f"Workspace '{name}' deleted."
            )
        else:
            QMessageBox.critical(
                self, "Delete Error", f"Could not delete workspace '{name}'."
            )

    @Slot()
    def create_new(self):
        name, ok = QInputDialog.getText(
            self,
            "Create New Workspace",
            "Enter a name for the new workspace (based on current settings):",
            QLineEdit.Normal,
            "New Project",
        )
        if not ok or not name:
            return

        name = name.strip()
        if self.settings.create_workspace(name):
            self.refresh_list()
            self.workspace_changed.emit()
            QMessageBox.information(
                self,
                "Create Success",
                f"Workspace '{name}' created and set as active.",
            )
        else:
            QMessageBox.warning(
                self,
                "Create Error",
                f"Workspace name '{name}' already exists or is invalid.",
            )


# ==========================================
# HELP TAB
# ==========================================

class HelpTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        info_icon = QWidget().style().standardIcon(QStyle.SP_MessageBoxInformation)
        icon_label = QLabel()
        icon_label.setPixmap(info_icon.pixmap(24, 24))

        title_label = QLabel("<b>Vitadeck Manager & Debugger Help</b>")
        title_label.setFont(QFont("Arial", 16, QFont.Bold))

        title_hbox = QHBoxLayout()
        title_hbox.addWidget(icon_label)
        title_hbox.addWidget(title_label)
        title_hbox.addStretch()
        layout.addLayout(title_hbox)

        help_text = QTextEdit()
        help_text.setReadOnly(True)
        help_text.setHtml(
            """
            <p><b>PS Vita Debugging Tool Suite</b></p>
            <hr>
            <p><b>How to use the application:</b></p>
            <ul>
                <li>Connect your PS Vita using <b>VitaCompanion</b> and make sure ports 1337 (FTP) and 1338 (Commands) are accessible.</li>
                <li>Use the <b>File Transfer</b> tab to manage files through FTP.</li>
                <li>Use <b>Quick Commands</b> or <b>Upload & Launch</b> to send commands or upload/launch homebrew apps.</li>
                <li>For core dump analysis, configure the paths to <b>VitaSDK/devkitARM</b> in the <b>Settings</b> tab.</li>
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
            """
        )
        layout.addWidget(help_text)


# ==========================================
# SETTINGS TAB (THEME-AWARE)
# ==========================================

class SettingsTab(QWidget):
    restart_log_server_signal = Signal(int)
    apply_style_signal = Signal()
    theme_changed = Signal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        # SDK configuration
        grp_sdk = QGroupBox("VitaSDK & Build Configuration")
        lay_sdk = QVBoxLayout(grp_sdk)

        lay_sdk.addWidget(QLabel("VitaSDK Path:"))
        hbox_sdk = QHBoxLayout()
        self.sdk_input = QLineEdit()
        self.btn_sdk = QPushButton("Browse SDK Root")
        self.btn_sdk.clicked.connect(
            lambda: self.browse_folder(self.sdk_input, "sdk_path", is_file=False)
        )
        hbox_sdk.addWidget(self.sdk_input)
        hbox_sdk.addWidget(self.btn_sdk)
        lay_sdk.addLayout(hbox_sdk)

        lay_sdk.addWidget(QLabel("Default Build Folder:"))
        hbox_build = QHBoxLayout()
        self.build_input = QLineEdit()
        self.btn_build = QPushButton("Browse Build Folder")
        self.btn_build.clicked.connect(
            lambda: self.browse_folder(self.build_input, "last_build_dir", is_file=False)
        )
        hbox_build.addWidget(self.build_input)
        hbox_build.addWidget(self.btn_build)
        lay_sdk.addLayout(hbox_build)

        self.sdk_input.textChanged.connect(lambda t: settings.set("sdk_path", t))
        self.build_input.textChanged.connect(
            lambda t: settings.set("last_build_dir", t)
        )
        layout.addWidget(grp_sdk)

        # Logging server configuration
        grp_log = QGroupBox("Logging Server Configuration")
        lay_log = QVBoxLayout(grp_log)

        lay_log.addWidget(QLabel("Log Server Port (Requires Restart):"))
        hbox_port = QHBoxLayout()
        self.log_port_input = QLineEdit()
        self.log_port_input.setValidator(QIntValidator(1024, 65535))
        btn_port = QPushButton("Apply Port & Restart Server")
        btn_port.clicked.connect(self.apply_port_and_restart)
        hbox_port.addWidget(self.log_port_input)
        hbox_port.addWidget(btn_port)
        lay_log.addLayout(hbox_port)

        self.log_port_input.textChanged.connect(self.update_log_port_setting)
        layout.addWidget(grp_log)

        # Log appearance
        grp_appearance = QGroupBox("Log/Terminal Appearance")
        lay_appearance = QVBoxLayout(grp_appearance)

        lay_appearance.addWidget(QLabel("Log Output Font Size (pt):"))
        hbox_font = QHBoxLayout()
        self.font_size_spinbox = QSpinBox()
        self.font_size_spinbox.setRange(8, 30)
        self.font_size_spinbox.valueChanged.connect(
            lambda v: settings.set("log_font_size", v)
        )
        btn_apply_font = QPushButton("Apply Style Changes")
        btn_apply_font.clicked.connect(self.apply_style_signal.emit)
        hbox_font.addWidget(self.font_size_spinbox)
        hbox_font.addWidget(btn_apply_font)
        lay_appearance.addLayout(hbox_font)

        layout.addWidget(grp_appearance)

        # Theme selection
        grp_theme = QGroupBox("Theme")
        lay_theme = QVBoxLayout(grp_theme)

        lay_theme.addWidget(QLabel("Select UI Theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(self.discover_themes())

        current_theme_name = settings.get("theme_name", "default")
        idx = self.theme_combo.findText(current_theme_name)
        if idx != -1:
            self.theme_combo.setCurrentIndex(idx)

        self.theme_combo.currentTextChanged.connect(self.on_theme_changed)

        lay_theme.addWidget(self.theme_combo)
        layout.addWidget(grp_theme)

        layout.addStretch()

    def discover_themes(self):
        themes = []
        if os.path.isdir(THEMES_DIR):
            for entry in sorted(os.listdir(THEMES_DIR)):
                full = os.path.join(THEMES_DIR, entry)
                if os.path.isdir(full):
                    themes.append(entry)
        if not themes:
            themes = ["default"]
        return themes

    def on_theme_changed(self, name: str):
        settings.set("theme_name", name)
        self.theme_changed.emit(name)

    def update_log_port_setting(self, text):
        try:
            port = int(text)
            settings.set("log_port", port)
        except ValueError:
            pass

    def browse_folder(self, line_edit, setting_key, is_file=False):
        current_path = settings.get(setting_key, os.getcwd())
        if is_file:
            d, _ = QFileDialog.getOpenFileName(self, "Select File", current_path)
        else:
            d = QFileDialog.getExistingDirectory(self, "Select Folder", current_path)
        if d:
            line_edit.setText(d)
            settings.set(setting_key, d)

    def set_settings_values(self):
        self.sdk_input.setText(settings.get("sdk_path", ""))
        self.build_input.setText(settings.get("last_build_dir", os.getcwd()))

        current_port = settings.get("log_port", 8080)
        self.log_port_input.blockSignals(True)
        self.log_port_input.setText(str(current_port))
        self.log_port_input.blockSignals(False)

        self.font_size_spinbox.setValue(settings.get("log_font_size", 13))

        theme_name = settings.get("theme_name", "default")
        idx = self.theme_combo.findText(theme_name)
        if idx != -1:
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(idx)
            self.theme_combo.blockSignals(False)

    def apply_port_and_restart(self):
        try:
            port = int(self.log_port_input.text())
        except ValueError:
            QMessageBox.critical(self, "Input Error", "Invalid port number.")
            return

        if port < 1024 or port > 65535:
            QMessageBox.warning(
                self, "Port Error", "Port must be between 1024 and 65535."
            )
            return

        settings.set("log_port", port)
        self.restart_log_server_signal.emit(port)


# ==========================================
# COMMAND WORKER
# ==========================================

class CommandWorker(QThread):
    command_output_signal = Signal(str, str)
    battery_signal = Signal(int, bool) # Signal for battery updates: (level, is_charging)

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
                # Don't log the 'battery' polling to keep logs clean, unless it fails
                if command != "battery":
                    self.command_output_signal.emit(
                        f"Attempting to send command: '{command}'", "orange"
                    )
                
                s.connect((self.host, self.port))
                s.sendall(f"{command}\n".encode("utf-8"))
                response = (
                    s.recv(1024)
                    .decode("utf-8", errors="ignore")
                    .strip()
                )
                
                # Special handling for battery command
                if command == "battery":
                    # Expected format: Battery: 54% (Not charging)
                    # Regex to capture digits and status text inside parens
                    match = re.search(r"Battery:\s*(\d+)%\s*\((.*)\)", response)
                    if match:
                        level = int(match.group(1))
                        status_text = match.group(2).lower()
                        # Determine if charging. 
                        # Assuming "Not charging" means False. Anything else might be True.
                        # Adjust logic if "Charging" string is different.
                        is_charging = "not charging" not in status_text
                        self.battery_signal.emit(level, is_charging)
                    return # Exit without logging to console

                self.command_output_signal.emit(
                    f"Cmd: {command} -> {response}", "#3ecf4c"
                )
        except Exception as e:
            # Only log errors for non-battery commands to avoid spam if device is offline
            if command != "battery":
                self.command_output_signal.emit(f"Cmd Error: {e}", "red")

    def stop(self):
        self.running = False
        self.wait()


# ==========================================
# MAIN WINDOW (VitaDeckModern)
# ==========================================

class VitaDeckModern(QWidget):
    # Base64 encoded SVG for the refresh button icon (fallback)
    REFRESH_SVG_B64 = """
        PD94bWwgdmVyc2lvbj0iMS4wIiA/Pgo8c3ZnIGZpbGw9IiNEQ0RDREMiIHdpZHRoPSI4MDBweCIgaGVpZ2h0PSI4MDBweCIgdmlld0JveD0iMCAwIDk2IDk2IiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPgo8dGl0bGUvPgo8Zz4KPHBhdGggZD0iTTk0LjI0MjIsMzcuNzU3OGE1Ljk5NzksNS45OTc5LDAsMCwwLTguNDg0NCwwbC0yLjYxLDIuNjFBMzYuMDM0NywzNi4wMzQ3LDAsMCwwLDQ4LDEyYTM1LjU1LDM1LjU1LDAsMCwwLTIxLjYyMTEsNy4zNTk0LDUuOTk3Nyw1Ljk5NzcsMCwwLDAsNy4yNDIyLDkuNTYyNUEyMy42Njc3LDIzLjY2NzcsMCwwLDEsNDgsMjQsMjMuOTU3LDIzLjA0MjksMCwwLDEsNzAuNjcyOSw0MC40NzY2bC0zLjk3LTMuMTY0MWE1Ljk5NTYsNS45OTU2LDAsMSwwLTcuNDc2NSw5LjM3NWwxNS4wMzUxLDEyYTUuOTksNS45OTwwLDAsMCw3Ljk4LC0wLjQ0NTNsMTItMTJBNS45OTc5LDUuOTk3OSwwLDAsMCw5NC4yNDIyLDM3Ljc1NzhaIi8+CjxwYXRoIGQ9Ik02Mi4zNzg5LDY3LjA3ODFBMjMuNjY3NSwyMy42Njc1LDAsMCwxLDQ4LDcyLDIzLjE2LDIzLjE2LDAsMCwxLDM1Ljc1NzgsNjcuMDc4MSw1Ljk5NzcsNS45OTc3LDAsMSwwLDI4LjUxNTYsNzYuNDg0NEEzNi4wMzQ3LDM1LjAzNDcsMCwwLDAsNDgsODRhMzUuNTUsMzUuNTUsMCwwLDAsMjEuNjIxMS03LjM1OTQsNS45OTc3LDUuOTk3Nyw1Ljk5NzcsMCwxLDAtNy4yNDIyLTkuNTYyNVWiIvPgo8L2c+Cjwvc3ZnPg==
    """

    IPV4_PATTERN = re.compile(
        r"^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
        r"(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
    )

    @staticmethod
    def get_local_ip():
        local_ip = "127.0.0.1"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            if local_ip not in ("0.0.0.0", "127.0.0.1"):
                return local_ip
        except Exception:
            pass

        try:
            local_ip = socket.gethostbyname(socket.gethostname())
            if local_ip not in ("0.0.0.0", "127.0.0.1"):
                return local_ip
        except Exception:
            pass
        return local_ip

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vitadeck - Manager & Debugger")
        self.resize(1200, 700)

        self._pending_app_launch = None
        self._local_ip_cache = self.get_local_ip()
        
        # Command worker
        self.cmd_thread = CommandWorker()
        self.cmd_thread.start()

        main_layout = QVBoxLayout(self)
        content_and_sidebar = QHBoxLayout()

        # --- Main QTabWidget (feature tabs) ---
        self.tabs = QTabWidget()
        self.tabs.setFont(QFont("Arial", settings.get("base_font_size", 10)))

        # Workspace tab (hidden in tab bar, accessed via icon)
        self.tab_workspace = WorkspaceTab(settings)
        self.tab_workspace.workspace_changed.connect(self.apply_workspace_settings)
        self.idx_workspace = self.tabs.addTab(self.tab_workspace, "Workspaces")

        # Logging tab (visible)
        self.tab_logging = LoggingTab()
        self.cmd_thread.command_output_signal.connect(self.tab_logging.append_log)
        self.idx_logging = self.tabs.addTab(self.tab_logging, "Logging")

        # Core dump tab (visible)
        self.tab_core = CoreDumpTab()
        self.idx_core = self.tabs.addTab(self.tab_core, "Core Dump")

        # Build tab (visible)
        self.tab_build = BuildTab()
        self.idx_build = self.tabs.addTab(self.tab_build, "Build")

        # File transfer tab (visible)
        self.tab_transfer = FileTransferTab()
        if hasattr(self.tab_transfer, "ftp_thread"):
            ftp_thread = self.tab_transfer.ftp_thread
            if hasattr(ftp_thread, "status_signal"):
                ftp_thread.status_signal.connect(self.update_connection_status)
            if hasattr(ftp_thread, "progress_signal"):
                ftp_thread.progress_signal.connect(self.update_transfer_status)
                ftp_thread.progress_signal.connect(self.check_launch_queue)
        self.idx_transfer = self.tabs.addTab(self.tab_transfer, "File Transfer")

        # SDK installation tab (visible)
        self.tab_sdk = SdkInstallationTab()
        self.idx_sdk = self.tabs.addTab(self.tab_sdk, "SDK")

        # Help tab (hidden in tab bar, accessed via icon)
        self.tab_help = HelpTab()
        self.idx_help = self.tabs.addTab(self.tab_help, "ℹ️ Help")

        # Settings tab (hidden in tab bar, accessed via icon)
        self.tab_settings = SettingsTab()
        self.tab_settings.restart_log_server_signal.connect(self.restart_logging_server)
        self.tab_settings.apply_style_signal.connect(self.apply_style)
        self.tab_settings.theme_changed.connect(self.change_theme)
        self.idx_settings = self.tabs.addTab(self.tab_settings, "Settings")

        # Right-aligned SVG icon buttons in corner of the tab bar
        self.setup_tab_icons()

        # Hide Workspace / Help / Settings text tabs (icon-only)
        tab_bar = self.tabs.tabBar()
        tab_bar.setTabVisible(self.idx_workspace, False)
        tab_bar.setTabVisible(self.idx_help, False)
        tab_bar.setTabVisible(self.idx_settings, False)

        content_and_sidebar.addWidget(self.tabs, stretch=4)

        # Sidebar
        self.setup_sidebar(content_and_sidebar)
        main_layout.addLayout(content_and_sidebar)

        # Status bar
        self.setup_status_bar(main_layout)

        # Apply workspace settings & theme
        self.apply_workspace_settings(initial=True)
        self._apply_tab_icons_from_theme()

        if type(settings).__name__ == "MockSettings":
            QMessageBox.warning(
                self,
                "Warning",
                "Running in MOCK mode. Some features may not work as expected because external modules are missing.",
            )

    # ---- themed icon helpers ----
    def _get_themed_icon(self, key: str, fallback_svg: str, size: int = 20) -> QIcon:
        if current_theme and key in current_theme.icons:
            path = current_theme.icons[key]
            if os.path.exists(path):
                return qicon_from_svg_file(path, size=size)
        return svg_to_qicon(fallback_svg, size=size)

    def _get_refresh_icon(self) -> QIcon:
        if current_theme and "refresh" in current_theme.icons:
            path = current_theme.icons["refresh"]
            if os.path.exists(path):
                return qicon_from_svg_file(path, size=16)
        svg_data = QByteArray.fromBase64(self.REFRESH_SVG_B64.encode("utf-8"))
        renderer = QSvgRenderer(svg_data)
        pixmap = QPixmap(QSize(20, 20))
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)

    def _apply_tab_icons_from_theme(self):
        if not current_theme:
            return

    # ---- tab bar icons ----
    def setup_tab_icons(self):
        corner_widget = QWidget()

        # Normal margins; we'll instead create vertical space by moving the pane down.
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(4)

        icon_tabs = [
            ("Workspace", self.tab_workspace, "workspace", SAVE_SVG),
            ("Settings", self.tab_settings, "settings", SETTINGS_SVG),
            ("Help", self.tab_help, "help", INFO_SVG),
        ]

        self.icon_buttons = []

        for name, widget, icon_key, fallback_svg in icon_tabs:
            btn = QPushButton()
            btn.setFlat(True)
            btn.setIcon(self._get_themed_icon(icon_key, fallback_svg, size=20))
            btn.setIconSize(QSize(20, 20))
            btn.setFixedSize(28, 28)
            btn.setToolTip(name)
            btn.clicked.connect(
                lambda checked=False, w=widget: self.tabs.setCurrentWidget(w)
            )
            corner_layout.addWidget(btn)
            self.icon_buttons.append(btn)

        corner_layout.addStretch()
        self.tabs.setCornerWidget(corner_widget, Qt.TopRightCorner)


    # ---- workspace + theme ----
    @Slot()
    def apply_workspace_settings(self, initial=False):
        vita_ip = settings.get("vita_ip", "192.168.1.100")
        exec_path = settings.get("exec_path", os.path.join(os.getcwd(), "eboot.bin"))
        target_app_id = settings.get("target_app_id", "PCSG00000")
        launch_title_id = settings.get("launch_title_id", "VHBB00001")

        self.ip_entry.setText(vita_ip)
        self.exec_entry.setText(exec_path)
        self.appid_entry.setText(target_app_id)
        self.launch_id_entry.setText(launch_title_id)

        self.tab_settings.set_settings_values()
        self.apply_style(initial=initial)

        self.cmd_thread.set_host(vita_ip)
        self.update_local_ip_status(initial=initial)

        self.tab_workspace.refresh_list()

        theme_name = settings.get("theme_name", "default")
        self.change_theme(theme_name, from_workspace=True)

        if not initial:
            QMessageBox.information(
                self,
                "Workspace Loaded",
                f"Settings for workspace '{settings.get_current_workspace_name()}' applied.",
            )

    @Slot(str)
    def change_theme(self, theme_name: str, from_workspace: bool = False):
        load_theme(theme_name)
        self.apply_style(initial=False)
        self.setup_tab_icons()
        if hasattr(self, "btn_refresh_ip"):
            self.btn_refresh_ip.setIcon(self._get_refresh_icon())
        self._apply_tab_icons_from_theme()
        
        # Update Battery Widget theme
        if hasattr(self, 'battery_widget') and current_theme:
            self.battery_widget.update_theme_path(current_theme.base_dir)

    # ---- launch-after-upload ----
    @Slot(str)
    def check_launch_queue(self, status_msg):
        if self._pending_app_launch and (
            status_msg == "Idle" or "Success" in status_msg
        ):
            app_id = self._pending_app_launch
            # Delay launch command slightly
            QTimer.singleShot(
                500, lambda: self.send_command(f"launch {app_id}")
            )
            if hasattr(self.tab_logging, "append_log"):
                self.tab_logging.append_log(
                    f"Upload complete. Launching {app_id}...", "#3ecf4c"
                )
            self._pending_app_launch = None

    # ---- style ----
    @Slot(int)
    def restart_logging_server(self, port):
        if hasattr(self.tab_logging, "restart_server"):
            self.tab_logging.restart_server(port)

    @Slot()
    def apply_style(self, initial=False):
        log_font_size = settings.get("log_font_size", 13)
        base_font_size = settings.get("base_font_size", 10)

        self.setStyleSheet(self._get_style_sheet(base_font_size, log_font_size))

        if hasattr(self, "btn_refresh_ip"):
            self.btn_refresh_ip.setStyleSheet(
                """
                QPushButton {
                    background-color: #2d2d2d;
                    border: 1px solid #444;
                    border-radius: 4px;
                    padding: 2px;
                }
                QPushButton:hover {
                    background-color: #3a3a3a;
                    border: 1px solid #555;
                }
            """
            )

        if not initial:
            QMessageBox.information(
                self,
                "Style Applied",
                f"Application style applied. Log output font size: {log_font_size}pt.",
            )

    def _get_style_sheet(self, base_font_size, log_font_size):
        def p(key: str, default: str) -> str:
            if current_theme and current_theme.palette:
                return current_theme.palette.get(key, default)
            return default

        bg = p("background", "#1e1e1e")
        fg = p("foreground", "#dcdcdc")
        group_border = p("group_border", "#3c3c3c")
        group_title = p("group_title", "#aaa")
        group_bg = p("group_bg", "transparent")
        sidebar_bg = p("sidebar_bg", "#252525")
        sidebar_border = p("sidebar_border", "#3c3c3c")
        input_bg = p("input_bg", "#2d2d2d")
        input_border = p("input_border", "#444")
        input_fg = p("input_fg", "#e0e0e0")
        btn_bg = p("button_bg", "#2f4f6f")
        btn_border = p("button_border", "#3a5f80")
        btn_fg = p("button_fg", "#ffffff")
        btn_bg_hover = p("button_hover_bg", "#3a668a")
        btn_bg_pressed = p("button_pressed_bg", "#2a5975")
        btn_disabled_bg = p("button_disabled_bg", "#222")
        btn_disabled_fg = p("button_disabled_fg", "#555")
        btn_disabled_border = p("button_disabled_border", "#333")
        tab_pane_border = p("tab_pane_border", "#3c3c3c")
        tab_pane_bg = p("tab_pane_bg", "#1e1e1e")
        tab_bg = p("tab_bg", "#2a2a2a")
        tab_fg = p("tab_fg", "#dcdcdc")
        tab_selected_bg = p("tab_selected_bg", "#2f4f6f")
        tab_selected_border = p("tab_selected_border", "#3a5f80")
        tab_selected_fg = p("tab_selected_fg", "#ffffff")
        tab_hover_bg = p("tab_hover_bg", "#3a3a3a")
        log_bg = p("log_bg", "#111")
        log_border = p("log_border", "#333")
        log_text = p("log_text", "#c0c0c0")
        log_font = p("log_font_family", "Consolas, Monospace")
# THE FIX: Define the status bar colors
        status_bg = p("status_bar_bg", "#252525")
        status_border = p("status_bar_border", "#3c3c3c")
        return f"""
QWidget {{
    background-color: {bg};
    color: {fg};
    font-family: 'Segoe UI', sans-serif;
    font-size: {base_font_size}pt;
    border-radius: 10px;
}}

QGroupBox {{
    border: 1px solid {group_border};
    border-radius: 10px;
    margin-top: 20px;
    font-weight: bold;
    background-color: {group_bg};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {group_title};
}}

#sidebar {{
    background-color: {sidebar_bg};
    border: 1px solid {sidebar_border};
    border-radius: 12px;
    padding: 12px;
}}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QListWidget, QComboBox {{
    padding: 6px 8px;
    border-radius: 8px;
    background-color: {input_bg};
    border: 1px solid {input_border};
    color: {input_fg};
}}

QListWidget::item {{
    border-radius: 6px;
    padding: 4px;
}}

QListWidget::item:selected {{
    background: {tab_selected_bg};
    border-radius: 6px;
}}

QPushButton {{
    background-color: {btn_bg};
    border: 1px solid {btn_border};
    padding: 8px 12px;
    border-radius: 10px;
    color: {btn_fg};
}}

QPushButton:hover {{
    background-color: {btn_bg_hover};
}}

QPushButton:pressed {{
    background-color: {btn_bg_pressed};
}}

QPushButton:disabled {{
    background-color: {btn_disabled_bg};
    color: {btn_disabled_fg};
    border: 1px solid {btn_disabled_border};
}}

QTabWidget::pane {{
    border: 1px solid {tab_pane_border};
    border-radius: 12px;
    background: {tab_pane_bg};
    top: 6px;              /* move pane down so all tab buttons sit higher */
}}

QTabBar::tab {{
    padding: 8px 18px;
    background: {tab_bg};
    color: {tab_fg};
    border: 1px solid {tab_pane_border};
    border-bottom: none;
    border-radius: 10px 10px 0 0;
    margin-right: 4px;
}}

QTabBar::tab:selected {{
    background: {tab_selected_bg};
    border-color: {tab_selected_border};
    color: {tab_selected_fg};
}}

QTabBar::tab:hover {{
    background: {tab_hover_bg};
}}

QScrollArea {{
    border-radius: 12px;
    border: 1px solid {sidebar_border};
}}

QScrollBar:vertical, QScrollBar:horizontal {{
    background: transparent;
    border-radius: 6px;
    margin: 2px;
}}

QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {btn_bg_hover};
    border-radius: 6px;
}}

QMenu {{
    background: {group_bg};
    border-radius: 10px;
    padding: 5px;
}}

QMenu::item {{
    padding: 6px 10px;
    border-radius: 6px;
}}

QMenu::item:selected {{
    background: {tab_selected_bg};
    color: {tab_selected_fg};
}}

QTextEdit#logOutput, QPlainTextEdit#logOutput {{
    background-color: {log_bg};
    border: 1px solid {log_border};
    border-radius: 12px;
    padding: 10px;
    color: {log_text};
    font-family: {log_font};
    font-size: {log_font_size}pt;
}}

#statusBarFrame {{
    background-color: {status_bg};
    border: 1px solid {status_border};
    border-radius: 12px; /* Consistent with sidebar and tabs */
    margin-top: 5px;
}}


/* Add style for the icon button to ensure it's flat and inherits styles */
#statusBarFrame QPushButton {{
    background-color: transparent; /* Don't want a full background box */
    border: none;
    padding: 0;
}}

#statusBarFrame QPushButton:hover {{
    background-color: {btn_bg_hover};
    border: none;
}}

#statusBarFrame QPushButton:pressed {{
    background-color: {btn_bg_pressed};
    border: none;
}}

#statusBarFrame QLabel {{
    background-color: transparent;
    padding: 0;
    margin: 0;
}}
        

        """


    # ------------------------------
    # Sidebar
    # ------------------------------
    def theme_color(self, key: str, default: str) -> str:
        """Helper to get a color from the current theme palette, with a fallback."""
        if current_theme and current_theme.palette:
            return current_theme.palette.get(key, default)
        return default

    def setup_ip_group(self, layout):
        grp_ip = QGroupBox("PS Vita IP")
        ip_layout = QVBoxLayout(grp_ip)

        self.ip_entry = QLineEdit()
        self.ip_entry.textChanged.connect(lambda t: settings.set("vita_ip", t))
        self.ip_entry.textChanged.connect(self.update_command_worker_host)
        self.ip_entry.textChanged.connect(
            lambda: self.update_local_ip_status(initial=False)
        )
        ip_layout.addWidget(self.ip_entry)

        btn_reconnect = QPushButton("Reconnect FTP")
        if hasattr(self.tab_transfer, "connect_ftp"):
            # Also request battery update when reconnecting
            btn_reconnect.clicked.connect(lambda: (
                self.tab_transfer.connect_ftp(),
                self.request_battery_update()
            ))
        else:
            btn_reconnect.setEnabled(False)
        ip_layout.addWidget(btn_reconnect)

        layout.addWidget(grp_ip)

    def setup_core_dump_group(self, layout):
        grp_core = QGroupBox("Core Dumps Quick Actions")
        core_layout = QVBoxLayout(grp_core)

        btn_fetch_parse = QPushButton("Fetch and parse last crash")
        if hasattr(self.tab_core, "fetch_and_parse_last_crash"):
            # Also request battery update
            btn_fetch_parse.clicked.connect(lambda: (
                self.tab_core.fetch_and_parse_last_crash(),
                self.request_battery_update()
            ))
        else:
            btn_fetch_parse.setEnabled(False)
        core_layout.addWidget(btn_fetch_parse)

        layout.addWidget(grp_core)

    def setup_sidebar(self, layout):
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sb = QVBoxLayout(sidebar)

        self.setup_ip_group(sb)
        sb.addSpacing(12)

        self.setup_core_dump_group(sb)
        sb.addSpacing(12)

        self.setup_run_executable_sidebar(sb)
        sb.addSpacing(12)

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
        self.exec_entry = QLineEdit()
        self.exec_entry.setPlaceholderText("Path to eboot.bin or *.self")
        btn_browse_exec = QPushButton("Browse...")
        btn_browse_exec.clicked.connect(self.browse_exec_file)
        hbox_exec.addWidget(self.exec_entry)
        hbox_exec.addWidget(btn_browse_exec)
        run_exec_layout.addLayout(hbox_exec)

        run_exec_layout.addWidget(QLabel("Target App ID (e.g., PCSG00000):"))
        self.appid_entry = QLineEdit()
        self.appid_entry.textChanged.connect(
            lambda t: settings.set("target_app_id", t)
        )
        run_exec_layout.addWidget(self.appid_entry)

        self.btn_upload_launch = QPushButton("Upload and Launch")
        # Button color from theme (fallback to original)
        primary_bg = self.theme_color("button_primary_bg", "#2f4f6f")
        primary_fg = self.theme_color("button_primary_fg", "#ffffff")
        self.btn_upload_launch.setStyleSheet(
            f"background-color: {primary_bg}; color: {primary_fg};"
        )
        self.btn_upload_launch.clicked.connect(self.upload_and_launch)
        run_exec_layout.addWidget(self.btn_upload_launch)

        layout.addWidget(grp_run_exec)

    def setup_quick_commands_sidebar(self, layout):
        grp_quick = QGroupBox("Quick Commands")
        quick_layout = QVBoxLayout(grp_quick)

        btn_quit_all = QPushButton("Quit All Apps")
        btn_quit_all.clicked.connect(lambda: self.send_command("destroy"))
        quick_layout.addWidget(btn_quit_all)

        btn_reboot = QPushButton("Reboot Console")
        btn_reboot.clicked.connect(lambda: self.send_command("reboot"))
        quick_layout.addWidget(btn_reboot)

        hbox_screen = QHBoxLayout()
        btn_screen_on = QPushButton("Screen ON")
        btn_screen_on.clicked.connect(lambda: self.send_command("screen on"))
        btn_screen_off = QPushButton("Screen OFF")
        btn_screen_off.clicked.connect(lambda: self.send_command("screen off"))
        hbox_screen.addWidget(btn_screen_on)
        hbox_screen.addWidget(btn_screen_off)
        quick_layout.addLayout(hbox_screen)

        hbox_launch = QHBoxLayout()
        self.launch_id_entry = QLineEdit()
        self.launch_id_entry.setPlaceholderText("Enter Title ID")
        self.launch_id_entry.textChanged.connect(
            lambda t: settings.set("launch_title_id", t)
        )
        btn_launch_id = QPushButton("Launch Title ID")
        btn_launch_id.clicked.connect(self.launch_title_id)
        hbox_launch.addWidget(self.launch_id_entry)
        hbox_launch.addWidget(btn_launch_id)
        quick_layout.addLayout(hbox_launch)

        layout.addWidget(grp_quick)

    # ------------------------------
    # Sidebar actions
    # ------------------------------
    def browse_exec_file(self):
        current_path = settings.get("exec_path", os.getcwd())
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select eboot.bin/Self",
            current_path,
            "Executable Files (eboot.bin *.self);;All Files (*)",
        )
        if filename:
            self.exec_entry.setText(filename)
            settings.set("exec_path", filename)

    def upload_and_launch(self):
        local_path = self.exec_entry.text().strip()
        app_id = self.appid_entry.text().strip()

        if not os.path.isfile(local_path):
            QMessageBox.warning(
                self, "File Error", "Local executable file not found."
            )
            return
        if not app_id:
            QMessageBox.warning(
                self, "Input Error", "Please enter a target Application ID."
            )
            return

        if not hasattr(self.tab_transfer, "ftp_thread") or not hasattr(
            self.tab_transfer.ftp_thread, "add_command"
        ):
            QMessageBox.warning(
                self,
                "FTP Error",
                "File transfer backend is not available in this build.",
            )
            return

        remote_path = f"ux0:/app/{app_id}/eboot.bin"
        reply = QMessageBox.question(
            self,
            "Confirm Upload & Launch",
            f"Upload '{os.path.basename(local_path)}' to '{remote_path}' and launch '{app_id}'?\n\nNOTE: This will overwrite the existing eboot.bin!",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.No:
            return

        if hasattr(self.tab_logging, "append_log"):
            self.tab_logging.append_log(
                f"Queueing upload of {os.path.basename(local_path)}...", "orange"
            )

        self._pending_app_launch = app_id
        self.tab_transfer.ftp_thread.add_command(
            "upload", local_path, remote_path, True
        )
        
        # Trigger battery update
        self.request_battery_update()

        # Switch to Logging tab (use stored index instead of hard-coded 1)
        self.tabs.setCurrentIndex(self.idx_logging)

    def launch_title_id(self):
        title_id = self.launch_id_entry.text().strip()
        if not title_id:
            QMessageBox.warning(
                self, "Input Error", "Please enter a Title ID to launch."
            )
            return
        self.send_command(f"launch {title_id}")

    def request_battery_update(self):
        """Queues a battery status check."""
        self.cmd_thread.add_command("battery")

    def send_command(self, command):
        if command in ("destroy", "reboot"):
            reply = QMessageBox.question(
                self,
                "Confirm Command",
                f"Are you sure you want to run '{command}'? This may close apps or reboot your device.",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return

        self.cmd_thread.add_command(command)
        
        # Queue battery check after command
        self.request_battery_update()
        
        # Switch to Logging tab (again, index of logging)
        self.tabs.setCurrentIndex(self.idx_logging)

    # ------------------------------
    # Status bar / local IP
    # ------------------------------
# ... inside VitaDeckModern class ...
    
    def setup_local_ip_status(self, layout):
        inactive = self.theme_color("status_inactive", "#777")

        self.local_ip_dot = ColorDot(inactive, size=12)
        layout.addWidget(self.local_ip_dot)

        self.local_ip_label = QLabel("Local IP: N/A")
        self.local_ip_label.setStyleSheet(f"color: {inactive};")
        layout.addWidget(self.local_ip_label)

        # The refresh button will now adopt the normal QPushButton style
        self.btn_refresh_ip = QPushButton()
        self.btn_refresh_ip.setFlat(True) # Ensure it looks like an icon button
        self.btn_refresh_ip.setIcon(self._get_refresh_icon())
        self.btn_refresh_ip.setIconSize(QSize(20, 20)) # Match tab corner icons
        self.btn_refresh_ip.setFixedSize(QSize(28, 28)) # Match tab corner icons
        self.btn_refresh_ip.setToolTip("Refresh Local IP & Network Status")
        self.btn_refresh_ip.clicked.connect(
            lambda: self.update_local_ip_status(initial=False, force_refresh=True)
        )
        layout.addWidget(self.btn_refresh_ip)

    # ...

    def _apply_final_ip_status(self):
        self._local_ip_cache = self.get_local_ip()
        local_ip = self._local_ip_cache
        vita_ip = settings.get("vita_ip", "")

        inactive = self.theme_color("status_inactive", "#777")
        ok_color = self.theme_color("status_ok", "#3ecf4c")
        err_color = self.theme_color("status_error", "red")

        local_is_valid = (
            self.IPV4_PATTERN.match(local_ip)
            and local_ip not in ("0.0.0.0", "127.0.0.1")
        )
        vita_is_valid = self.IPV4_PATTERN.match(vita_ip)

        color = inactive
        display_text = "Local IP: N/A"

        if local_is_valid and vita_is_valid:
            local_subnet = local_ip.rsplit(".", 1)[0]
            vita_subnet = vita_ip.rsplit(".", 1)[0]
            if local_subnet == vita_subnet:
                color = ok_color
                status = "OK"
            else:
                color = err_color
                status = "Different Network"
            display_text = f"Local IP: {local_ip} ({status})"
        else:
            if not local_is_valid:
                display_text = "Local IP: N/A (Error/Localhost)"
            elif not vita_is_valid:
                display_text = f"Local IP: {local_ip} (Vita IP Invalid)"

        self.local_ip_dot.set_color(color)
        self.local_ip_label.setText(display_text)
        self.local_ip_label.setStyleSheet(f"color: {color};")

    @Slot(bool, bool)
    def update_local_ip_status(self, initial=False, force_refresh=False):
        warn_color = self.theme_color("status_warning", "orange")

        if force_refresh:
            self.local_ip_dot.set_color(warn_color)
            self.local_ip_label.setText("Local IP: Getting current IP...")
            self.local_ip_label.setStyleSheet(f"color: {warn_color};")
            QApplication.processEvents()
            QTimer.singleShot(500, self._apply_final_ip_status)
        else:
            self._apply_final_ip_status()

# ... inside VitaDeckModern class ...
    
    def setup_status_bar(self, layout):
        # 1. Create a QFrame to act as the rounded container for the status bar
        self.status_frame = QFrame()
        self.status_frame.setObjectName("statusBarFrame") 
        # Apply style sheet for rounded corners and border in _get_style_sheet
        
        status_bar_layout = QHBoxLayout(self.status_frame)
        status_bar_layout.setContentsMargins(12, 8, 12, 8) # Add vertical padding

        inactive = self.theme_color("status_inactive", "#777")
        
        # --- 1. Battery Widget (Left-most) ---
        theme_path = os.path.join(THEMES_DIR, settings.get("theme_name", "default"))
        self.battery_widget = BatteryWidget(theme_path)
        status_bar_layout.addWidget(self.battery_widget)
        # Connect battery signal
        self.cmd_thread.battery_signal.connect(self.battery_widget.update_battery)
        
        status_bar_layout.addSpacing(20)

        # --- 2. Connection Status (Dot + Label) ---
        self.conn_dot = ColorDot(inactive, size=12)
        status_bar_layout.addWidget(self.conn_dot)
        self.conn_label = QLabel("Not connected")
        self.conn_label.setStyleSheet(f"color: {inactive};")
        status_bar_layout.addWidget(self.conn_label)

        status_bar_layout.addSpacing(20)

        # --- 3. Transfer Status (Dot + Label) ---
        self.transfer_dot = ColorDot(inactive, size=12)
        status_bar_layout.addWidget(self.transfer_dot)
        self.transfer_label = QLabel("File transfer idle") # Changed default text
        self.transfer_label.setStyleSheet(f"color: {inactive};")
        status_bar_layout.addWidget(self.transfer_label)

        status_bar_layout.addStretch()
        
        # --- 4. Local IP Status (Right-most) ---
        self.setup_local_ip_status(status_bar_layout)
        
        # Add the frame to the main window layout
        layout.addWidget(self.status_frame)

    # ...

    @Slot(str, str)
    def update_connection_status(self, message, color):
        # color string comes from FTP thread; we use it directly
        self.conn_label.setStyleSheet(f"color: {color};")
        self.conn_label.setText(message)
        self.conn_dot.set_color(color)

    @Slot(str)
    def update_transfer_status(self, status_msg):
        inactive = self.theme_color("status_inactive", "#777")
        ok_color = self.theme_color("status_ok", "#3ecf4c")
        err_color = self.theme_color("status_error", "red")
        warn_color = self.theme_color("status_warning", "orange")

        color = inactive
        text = status_msg

        if status_msg.lower() == "idle":
            text = "File transfer idle"
            color = ok_color
        elif "error" in status_msg.lower():
            text = f"Transfer Error: {status_msg}"
            color = err_color
        elif status_msg.startswith(
            ("Uploading", "Downloading", "Renaming", "Deleting")
        ):
            color = warn_color
        else:
            text = "Not transfer file in progress"
            color = inactive

        self.transfer_label.setText(text)
        self.transfer_dot.set_color(color)
        self.transfer_label.setStyleSheet(f"color: {color};")

    # ------------------------------
    # Close event
    # ------------------------------
    def closeEvent(self, event):
        if hasattr(self.tab_logging, "cleanup"):
            self.tab_logging.cleanup()
        if hasattr(self.tab_transfer, "cleanup"):
            self.tab_transfer.cleanup()
        if hasattr(self.tab_build, "cleanup"):
            self.tab_build.cleanup()

        self.cmd_thread.stop()
        if hasattr(settings, "save"):
            settings.save()

        event.accept()



# ==========================================
# ENTRY POINT
# ==========================================

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Load saved or default theme BEFORE creating the window
    theme_name = settings.get("theme_name", "default")
    load_theme(theme_name)

    window = VitaDeckModern()
    window.show()

    sys.exit(app.exec())