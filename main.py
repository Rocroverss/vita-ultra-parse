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

# ==========================================
# THEME SYSTEM (icons + palette from THEMES/<theme>/theme.txt)
# ==========================================

THEMES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "THEMES")


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
            # battery icons etc. are available if needed
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
# SVG CONSTANTS & UTILITY (fallback icons)
# ==========================================

SETTINGS_SVG = """<?xml version="1.0" encoding="utf-8"?>
<svg width="800px" height="800px" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<g id="Interface / Settings">
<g id="Vector">
<path d="M20.3499 8.92293L19.9837 8.7192C19.9269 8.68756 19.8989 8.67169 19.8714 8.65524C19.5983 8.49165 19.3682 8.26564 19.2002 7.99523C19.1833 7.96802 19.1674 7.93949 19.1348 7.8831C19.1023 7.82677 19.0858 7.79823 19.0706 7.76998C18.92 7.48866 18.8385 7.17515 18.8336 6.85606C18.8331 6.82398 18.8332 6.79121 18.8343 6.72604L18.8415 6.30078C18.8529 5.62025 18.8587 5.27894 18.763 4.97262C18.6781 4.70053 18.536 4.44993 18.3462 4.23725C18.1317 3.99685 17.8347 3.82534 17.2402 3.48276L16.7464 3.1982C16.1536 2.85658 15.8571 2.68571 15.5423 2.62057C15.2639 2.56294 14.9765 2.56561 14.6991 2.62789C14.3859 2.69819 14.0931 2.87351 13.5079 3.22396L13.5045 3.22555L13.1507 3.43741C13.0948 3.47091 13.0665 3.48779 13.0384 3.50338C12.7601 3.6581 12.4495 3.74365 12.1312 3.75387C12.0992 3.7549 12.0665 3.7549 12.0013 3.7549C11.9365 3.7549 11.9024 3.7549 11.8704 3.75387C11.5515 3.74361 11.2402 3.65759 10.9615 3.50224C10.9334 3.48658 10.9056 3.46956 10.8496 3.4359L10.4935 3.22213C9.90422 2.86836 9.60915 2.69121 9.29427 2.62057C9.0157 2.55807 8.72737 2.55634 8.44791 2.61471C8.13236 2.68062 7.83577 2.85276 7.24258 3.19703L7.23994 3.1982L6.75228 3.48124L6.74688 3.48454C6.15904 3.82572 5.86441 3.99672 5.6517 4.23614C5.46294 4.4486 5.32185 4.69881 5.2374 4.97018C5.14194 5.27691 5.14703 5.61896 5.15853 6.3027L5.16568 6.72736C5.16676 6.79166 5.16864 6.82362 5.16817 6.85525C5.16343 7.17499 5.08086 7.48914 4.92974 7.77096C4.9148 7.79883 4.8987 7.8267 4.86654 7.88237C4.83436 7.93809 4.81877 7.96579 4.80209 7.99268C4.63336 8.26452 4.40214 8.49186 4.12733 8.65572C4.10015 8.67193 4.0715 8.68752 4.01521 8.71871L3.65365 8.91908C3.05208 9.25245 2.75137 9.41928 2.53256 9.65669C2.33898 9.86672 2.19275 10.1158 2.10349 10.3872C2.00259 10.6939 2.00267 11.0378 2.00424 11.7255L2.00551 12.2877C2.00706 12.9708 2.00919 13.3122 2.11032 13.6168C2.19979 13.8863 2.34495 14.134 2.53744 14.3427C2.75502 14.5787 3.05274 14.7445 3.64974 15.0766L4.00808 15.276C4.06907 15.3099 4.09976 15.3266 4.12917 15.3444C4.40148 15.5083 4.63089 15.735 4.79818 16.0053C4.81625 16.0345 4.8336 16.0648 4.8683 16.1255C4.90256 16.1853 4.92009 16.2152 4.93594 16.2452C5.08261 16.5229 5.16114 16.8315 5.16649 17.1455C5.16707 17.1794 5.16658 17.2137 5.16541 17.2827L5.15853 17.6902C5.14695 18.3763 5.1419 18.7197 5.23792 19.0273C5.32287 19.2994 5.46484 19.55 5.65463 19.7627C5.86915 20.0031 6.16655 20.1745 6.76107 20.5171L7.25478 20.8015C7.84763 21.1432 8.14395 21.3138 8.45869 21.379C8.73714 21.4366 9.02464 21.4344 9.30209 21.3721C9.61567 21.3017 9.90948 21.1258 10.4964 20.7743L10.8502 20.5625C10.9062 20.5289 10.9346 20.5121 10.9626 20.4965C11.2409 20.3418 11.5512 20.2558 11.8695 20.2456C11.9015 20.2446 11.9342 20.2446 11.9994 20.2446C12.0648 20.2446 12.0974 20.2446 12.1295 20.2456C12.4484 20.2559 12.7607 20.3422 13.0394 20.4975C13.0639 20.5112 13.0885 20.526 13.1316 20.5519L13.5078 20.7777C14.0971 21.1315 14.3916 21.3081 14.7065 21.3788C14.985 21.4413 15.2736 21.4438 15.5531 21.3855C15.8685 21.3196 16.1657 21.1471 16.7586 20.803L17.2536 20.5157C17.8418 20.1743 18.1367 20.0031 18.3495 19.7636C18.5383 19.5512 18.6796 19.3011 18.764 19.0297C18.8588 18.7252 18.8531 18.3858 18.8417 17.7119L18.8343 17.2724C18.8332 17.2081 18.8331 17.1761 18.8336 17.1445C18.8383 16.8247 18.9195 16.5104 19.0706 16.2286C19.0856 16.2007 19.1018 16.1726 19.1338 16.1171C19.166 16.0615 19.1827 16.0337 19.1994 16.0068C19.3681 15.7349 19.5995 15.5074 19.8744 15.3435C19.9012 15.3275 19.9289 15.3122 19.9838 15.2818L19.9857 15.2809L20.3472 15.0805C20.9488 14.7472 21.2501 14.5801 21.4689 14.3427C21.6625 14.1327 21.8085 13.8839 21.8978 13.6126C21.9981 13.3077 21.9973 12.9658 21.9958 12.2861L21.9945 11.7119C21.9929 11.0287 21.9921 10.6874 21.891 10.3828C21.8015 10.1133 21.6555 9.86561 21.463 9.65685C21.2457 9.42111 20.9475 9.25526 20.3517 8.92378L20.3499 8.92293Z" stroke="#000000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M8.00033 12C8.00033 14.2091 9.79119 16 12.0003 16C14.2095 16 16.0003 14.2091 16.0003 12C16.0003 9.79082 14.2095 7.99996 12.0003 7.99996C9.79119 7.99996 8.00033 9.79082 8.00033 12Z" stroke="#000000" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
</g>
</g>
</svg>"""

INFO_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg width="800px" height="800px" viewBox="0 0 24 24" version="1.1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
    <title>information_fill</title>
    <g id="页面-1" stroke="none" stroke-width="1" fill="none" fill-rule="evenodd">
        <g id="System" transform="translate(-672.000000, -48.000000)" fill-rule="nonzero">
            <g id="information_fill" transform="translate(672.000000, 48.000000)">
                <path d="M24,0 L24,24 L0,24 L0,0 L24,0 Z M12.5934901,23.257841 L12.5819402,23.2595131 L12.5108777,23.2950439 L12.4918791,23.2987469 L12.4918791,23.2987469 L12.4767152,23.2950439 L12.4056548,23.2595131 C12.3958229,23.2563662 12.3870493,23.2590235 12.3821421,23.2649074 L12.3780323,23.275831 L12.360941,23.7031097 L12.3658947,23.7234994 L12.3769048,23.7357139 L12.4804777,23.8096931 L12.4953491,23.8136134 L12.4953491,23.8136134 L12.5071152,23.8096931 L12.6106902,23.7357139 L12.6232938,23.7196733 L12.6232938,23.7196733 L12.6266527,23.7031097 L12.609561,23.275831 C12.6075724,23.2657013 12.6010112,23.2592993 12.5934901,23.257841 L12.5934901,23.257841 Z M12.8583906,23.1452862 L12.8445485,23.1473072 L12.6598443,23.2396597 L12.6498822,23.2499052 L12.6498822,23.2499052 L12.6471943,23.2611114 L12.6650943,23.6906389 L12.6699349,23.7034178 L12.6699349,23.7034178 L12.678386,23.7104931 L12.8793402,23.8032389 C12.8914285,23.8068999 12.9022333,23.8029875 12.9078286,23.7952264 L12.9118235,23.7811639 L12.8776777,23.1665331 C12.8752882,23.1545897 12.8674102,23.1470016 12.8583906,23.1452862 L12.8583906,23.1452862 Z M12.1430473,23.1473072 C12.1332178,23.1423925 12.1221763,23.1452606 12.1156365,23.1525954 L12.1099173,23.1665331 L12.0757714,23.7811639 C12.0751323,23.7926639 12.0828099,23.8018602 12.0926481,23.8045676 L12.108256,23.8032389 L12.3092106,23.7104931 L12.3186497,23.7024347 L12.3186497,23.7024347 L12.3225043,23.6906389 L12.340401,23.2611114 L12.337245,23.2485176 L12.337245,23.2485176 L12.3277531,23.2396597 L12.1430473,23.1473072 Z" id="MingCute" fill-rule="nonzero"></path>
                <path d="M12,2 C17.5228,2 22,6.47715 22,12 C22,17.5228 17.5228,22 12,22 C6.47715,22 2,17.5228 2,12 C2,6.47715 6.47715,2 12,2 Z M11.99,10 L11,10 C10.4477,10 10,10.4477 10,11 C10,11.51285 10.386027,11.9355092 10.8833761,11.9932725 L11,12 L11,16.99 C11,17.5106133 11.3938293,17.9392373 11.8999333,17.9940734 L12.01,18 L12.5,18 C13.0523,18 13.5,17.5523 13.5,17 C13.5,16.6710222 13.3411062,16.3791012 13.0958694,16.1968582 L13,16.1338 L13,11.01 C13,10.4893867 12.6060836,10.0607627 12.1000493,10.0059266 L11.99,10 Z M12,7 C11.4477,7 11,7.44772 11,8 C11,8.55228 11.4477,9 12,9 C12.5523,9 13,8.55228 13,8 C13,7.44772 12.5523,7 12,7 Z" id="形状" fill="#09244B"></path>
            </g>
        </g>
    </g>
</svg>"""

SAVE_SVG = """<?xml version="1.0" encoding="utf-8"?>
<svg width="800px" height="800px" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<path fill-rule="evenodd" clip-rule="evenodd" d="M18.1716 1C18.702 1 19.2107 1.21071 19.5858 1.58579L22.4142 4.41421C22.7893 4.78929 23 5.29799 23 5.82843V20C23 21.6569 21.6569 23 20 23H4C2.34315 23 1 21.6569 1 20V4C1 2.34315 2.34315 1 4 1H18.1716ZM4 3C3.44772 3 3 3.44772 3 4V20C3 20.5523 3.44772 21 4 21L5 21L5 15C5 13.3431 6.34315 12 8 12L16 12C17.6569 12 19 13.3431 19 15V21H20C20.5523 21 21 20.5523 21 20V6.82843C21 6.29799 20.7893 5.78929 20.4142 5.41421L18.5858 3.58579C18.2107 3.21071 17.702 3 17.1716 3H17V5C17 6.65685 15.6569 8 14 8H10C8.34315 8 7 6.65685 7 5V3H4ZM17 21V15C17 14.4477 16.5523 14 16 14L8 14C7.44772 14 7 14.4477 7 15L7 21L17 21ZM9 3H15V5C15 5.55228 14.5523 6 14 6H10C9.44772 6 9 5.55228 9 5V3Z" fill="#0F0F0F"/>
</svg>"""


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
            "MyHomebrewProject": {
                "log_font_size": 11,
                "vita_ip": "192.168.0.21",
                "sdk_path": "/home/user/project_sdk",
                "last_build_dir": "/home/user/project_build",
                "log_port": 8081,
                "exec_path": "/home/user/project_build/eboot.bin",
                "target_app_id": "NCSJROCRO",
                "launch_title_id": "NCSJROCRO",
                "dump_folder": "C:\\vita-parse",
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
                self.command_output_signal.emit(
                    f"Cmd: {command} -> {response}", "#3ecf4c"
                )
        except Exception as e:
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
        PD94bWwgdmVyc2lvbj0iMS4wIiA/Pgo8c3ZnIGZpbGw9IiNEQ0RDREMiIHdpZHRoPSI4MDBweCIgaGVpZ2h0PSI4MDBweCIgdmlld0JveD0iMCAwIDk2IDk2IiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPgo8dGl0bGUvPgo8Zz4KPHBhdGggZD0iTTk0LjI0MjIsMzcuNzU3OGE1Ljk5NzksNS45OTc5LDAsMCwwLTguNDg0NCwwbC0yLjYxLDIuNjFBMzYuMDM0NywzNi4wMzQ3LDAsMCwwLDQ4LDEyYTM1LjU1LDM1LjU1LDAsMCwwLTIxLjYyMTEsNy4zNTk0LDUuOTk3Nyw1Ljk5NzcsMCwwLDAsNy4yNDIyLDkuNTYyNUEyMy42Njc3LDIzLjY2NzcsMCwwLDEsNDgsMjQsMjMuOTU3LDIzLjA0MjksMCwwLDEsNzAuNjcyOSw0MC40NzY2bC0zLjk3LTMuMTY0MWE1Ljk5NTYsNS45OTU2LDAsMSwwLTcuNDc2NSw5LjM3NWwxNS4wMzUxLDEyYTUuOTksNS45OSwwLDAsMCw3Ljk4LC0wLjQ0NTNsMTItMTJBNS45OTc5LDUuOTk3OSwwLDAsMCw5NC4yNDIyLDM3Ljc1NzhaIi8+CjxwYXRoIGQ9Ik02Mi4zNzg5LDY3LjA3ODFBMjMuNjY3NSwyMy42Njc1LDAsMCwxLDQ4LDcyLDIzLjE2LDIzLjE2LDAsMCwxLDM1Ljc1NzgsNjcuMDc4MSw1Ljk5NzcsNS45OTc3LDAsMSwwLDI4LjUxNTYsNzYuNDg0NEEzNi4wMzQ3LDM2LjAzNDcsMCwwLDAsNDgsODRhMzUuNTUsMzUuNTUsMCwwLDAsMjEuNjIxMS03LjM1OTQsNS45OTc3LDUuOTk3NywwLDEsMC03LjI0MjItOS41NjI1WiIvPgo8L2c+Cjwvc3ZnPg==
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
        """
        if "terminal" in current_theme.icons and os.path.exists(current_theme.icons["terminal"]):
            self.tabs.setTabIcon(self.idx_logging, qicon_from_svg_file(current_theme.icons["terminal"], size=16))
        if "folder" in current_theme.icons and os.path.exists(current_theme.icons["folder"]):
            self.tabs.setTabIcon(self.idx_transfer, qicon_from_svg_file(current_theme.icons["folder"], size=16))
        """

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

    # ---- launch-after-upload ----
    @Slot(str)
    def check_launch_queue(self, status_msg):
        if self._pending_app_launch and (
            status_msg == "Idle" or "Success" in status_msg
        ):
            app_id = self._pending_app_launch
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
            btn_reconnect.clicked.connect(self.tab_transfer.connect_ftp)
        else:
            btn_reconnect.setEnabled(False)
        ip_layout.addWidget(btn_reconnect)

        layout.addWidget(grp_ip)

    def setup_core_dump_group(self, layout):
        grp_core = QGroupBox("Core Dumps Quick Actions")
        core_layout = QVBoxLayout(grp_core)

        btn_fetch_parse = QPushButton("Fetch and parse last crash")
        if hasattr(self.tab_core, "fetch_and_parse_last_crash"):
            btn_fetch_parse.clicked.connect(self.tab_core.fetch_and_parse_last_crash)
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
        # Switch to Logging tab (again, index of logging)
        self.tabs.setCurrentIndex(self.idx_logging)

    # ------------------------------
    # Status bar / local IP
    # ------------------------------
    def setup_local_ip_status(self, layout):
        inactive = self.theme_color("status_inactive", "#777")

        self.local_ip_dot = ColorDot(inactive, size=12)
        layout.addWidget(self.local_ip_dot)

        self.local_ip_label = QLabel("Local IP: N/A")
        self.local_ip_label.setStyleSheet(f"color: {inactive};")
        layout.addWidget(self.local_ip_label)

        self.btn_refresh_ip = QPushButton()
        # Use themed refresh icon (falls back to embedded SVG)
        self.btn_refresh_ip.setIcon(self._get_refresh_icon())
        self.btn_refresh_ip.setIconSize(QSize(16, 16))
        self.btn_refresh_ip.setFixedSize(QSize(28, 28))
        self.btn_refresh_ip.setToolTip("Refresh Local IP & Network Status")
        self.btn_refresh_ip.clicked.connect(
            lambda: self.update_local_ip_status(initial=False, force_refresh=True)
        )
        layout.addWidget(self.btn_refresh_ip)

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

    def setup_status_bar(self, layout):
        status_bar_layout = QHBoxLayout()
        status_bar_layout.setContentsMargins(12, 4, 12, 4)

        inactive = self.theme_color("status_inactive", "#777")

        self.conn_dot = ColorDot(inactive, size=12)
        status_bar_layout.addWidget(self.conn_dot)
        self.conn_label = QLabel("Not connected")
        self.conn_label.setStyleSheet(f"color: {inactive};")
        status_bar_layout.addWidget(self.conn_label)

        status_bar_layout.addSpacing(20)

        self.transfer_dot = ColorDot(inactive, size=12)
        status_bar_layout.addWidget(self.transfer_dot)
        self.transfer_label = QLabel("Not transfer file in progress")
        self.transfer_label.setStyleSheet(f"color: {inactive};")
        status_bar_layout.addWidget(self.transfer_label)

        status_bar_layout.addStretch()

        self.setup_local_ip_status(status_bar_layout)
        layout.addLayout(status_bar_layout)

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
