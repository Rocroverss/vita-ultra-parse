import sys
import os
import site
import socket
import threading
import re
import base64
import time
import inspect
import importlib.util
import subprocess
from pathlib import Path
from typing import Optional, Any, Dict, List, Tuple

"""Components"""
from components.android_so_analysis import *  # noqa: F401,F403
from components.build import *  # noqa: F401,F403
from components.config import *  # noqa: F401,F403
from components.core_dump import *  # noqa: F401,F403
from components.file_transfer import *  # noqa: F401,F403
from components.logging import *  # noqa: F401,F403
from components.sdk_installation import *  # noqa: F401,F403
from components.theme_manager import *  # noqa: F401,F403


user_site_packages = site.getusersitepackages()
if user_site_packages not in sys.path:
    sys.path.append(user_site_packages)

from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel, QLineEdit, QTabWidget,
    QGroupBox, QMessageBox, QFrame, QFileDialog, QStyle,
    QTextEdit, QSpinBox, QListWidget, QListWidgetItem,
    QInputDialog, QComboBox, QSlider, QSplitter,
    QTextBrowser  
)
from PySide6.QtGui import (
    QColor, QPainter, QFont, QIntValidator, QIcon, QPixmap, 
    QDesktopServices, QTextCursor, QTextCharFormat
)
from PySide6.QtCore import (
    Qt, QThread, Signal, Slot, QTimer, QSize, 
    QByteArray, QUrl, QEvent, QRect
)
from PySide6.QtSvg import QSvgRenderer

HAS_ELFTOOLS = False
HAS_CAPSTONE = False
DEPENDENCIES_MET = True
DEPENDENCY_ERROR = None

try:
    from elftools.elf.elffile import ELFFile
    _HAS_PYELFTOOLS = True
except Exception:
    ELFFile = None
    _HAS_PYELFTOOLS = False

if _HAS_PYELFTOOLS:
    try:
        from elftools.elf.sections import SymbolTableSection
    except Exception:
        SymbolTableSection = None

try:
    from capstone import (
        Cs, CS_ARCH_ARM, CS_ARCH_ARM64, CS_ARCH_X86,
        CS_MODE_ARM, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN,
        CS_MODE_32, CS_MODE_64
    )
    HAS_CAPSTONE = True
except ImportError as e:
    HAS_CAPSTONE = False
    DEPENDENCIES_MET = False
    DEPENDENCY_ERROR = str(e)
    print(f"Warning: capstone not found. Disassembly disabled: {e}")

try:
    import cxxfilt
except ImportError:
    cxxfilt = None

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__))) 

# Define the folder where screenshots are stored. It will be created if it doesn't exist.
SCREENSHOTS_DIR = BASE_DIR / "screenshots"

# ==========================================
# THEME SYSTEM
# ==========================================
THEMES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "THEMES")
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

ComponentTheme = None
current_theme: Optional[Any] = None

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


def load_theme(theme_name: str, base_dir: Optional[Path] = None) -> Optional[Any]:
    global THEMES_DIR, current_theme
    
    if base_dir:
        theme_path = base_dir
    else:
        theme_path = Path(THEMES_DIR) / theme_name  
    theme_file = theme_path / "theme.txt"

    if not theme_file.exists():
        if theme_name != "default":
            print(f"Warning: theme '{theme_name}' not found at {theme_path}. Falling back to default.")

        theme_name = "default"
        theme_path = Path(THEMES_DIR) / "default"
        theme_file = theme_path / "theme.txt"

        if not theme_file.exists():
            print(f"CRITICAL ERROR: Default theme file not found: {theme_file}")
            return None 

    parsed_sections = {}
    current_section = None

    try:
        with theme_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                if line.startswith("# ===== ") and line.endswith(" ====="):
                    # Extract the section name
                    section_name = line.strip("#= ") 
                    current_section = section_name
                    parsed_sections[current_section] = {}
                    continue

                if current_section and "=" in line:
                    key, value = line.split("=", 1)
                    parsed_sections[current_section][key.strip()] = value.strip()
                    
    except Exception as e:
        print(f"Error parsing theme file {theme_file}: {e}")
        if theme_name != "default":
            print("Attempting to load default theme instead.")
            return load_theme("default")
        return None
    
    
    if ComponentTheme is None:
        print("CRITICAL ERROR: Theme component not available.")
        return None

    try:
        theme = ComponentTheme(theme_name, theme_path, parsed_sections)
        theme.load()
        current_theme = theme
        return theme
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to create Theme object with valid data: {e}")
        return None
    
# ==========================================
# REAL MODULES OR MOCK FALLBACKS
# ==========================================

try:
    from utils import settings
    from components.logging import LoggingTab
    from components.core_dump import CoreDumpTab
    from components.build import BuildTab
    from components.file_transfer import FileTransferTab
    from components.sdk_installation import SdkInstallationTab
    from components.essential import (
        AndroidSoAnalysisTab as ComponentAndroidSoAnalysisTab,
        ColorDot as ComponentColorDot,
        WorkspaceTab as ComponentWorkspaceTab,
        HelpTab as ComponentHelpTab,
        SettingsTab as ComponentSettingsTab,
        CommandWorker as ComponentCommandWorker,
        RazorTab as ComponentRazorTab,
        ProfilingTab as ComponentProfilingTab,
        ScreenshotsTab as ComponentScreenshotsTab,
        BatteryWidget as ComponentBatteryWidget,
        Theme as ComponentTheme,
    )

    if not hasattr(settings, "DEFAULT_WORKSPACE_NAME"):
        settings.DEFAULT_WORKSPACE_NAME = "Default"

    if not hasattr(settings, "get_workspaces"):
        def _get_workspaces():
            return [settings.DEFAULT_WORKSPACE_NAME]
        settings.get_workspaces = _get_workspaces

    if not hasattr(settings, "get_current_workspace_name"):
        def _get_current_workspace_name():
            return settings.DEFAULT_WORKSPACE_NAME
        settings.get_current_workspace_name = _get_current_workspace_name

    if not hasattr(settings, "load_workspace"):
        def _load_workspace(name: str) -> bool:
            return True
        settings.load_workspace = _load_workspace

    if not hasattr(settings, "create_workspace"):
        def _create_workspace(name: str) -> bool:
            return False
        settings.create_workspace = _create_workspace

    if not hasattr(settings, "delete_workspace"):
        def _delete_workspace(name: str) -> bool:
            return False
        settings.delete_workspace = _delete_workspace

except ImportError as e:
    print(f"WARNING: Local module imports failed: {e}. Running in MOCK mode.")

    ComponentAndroidSoAnalysisTab = None
    ComponentColorDot = None
    ComponentWorkspaceTab = None
    ComponentHelpTab = None
    ComponentSettingsTab = None
    ComponentCommandWorker = None
    ComponentRazorTab = None
    ComponentProfilingTab = None
    ComponentScreenshotsTab = None
    ComponentBatteryWidget = None
    ComponentTheme = None

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
                "window_opacity": 1.0,
                "background_image_opacity": 1.0,
                "background_aspect_mode": "keep",
                "ui_elements_opacity": 1.0,
                "component_toggles": {
                    "workspace": True,
                    "help": True,
                    "logging": True,
                    "core_dump": True,
                    "razor": True,
                    "profiling": True,
                    "android": True,
                    "screenshots": True,
                    "build": True,
                    "sdk": True,
                    "file_transfer": True,
                },
                "component_order": [
                    "workspace",
                    "help",
                    "logging",
                    "core_dump",
                    "razor",
                    "profiling",
                    "android",
                    "screenshots",
                    "build",
                    "sdk",
                    "file_transfer",
                ],
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

    settings = MockSettings()

    class MockTab(QWidget):
        def __init__(self, *args, **kwargs): 
            super().__init__()
            layout = QVBoxLayout(self)
            label = QLabel("Mock Tab (real module not found)")
            layout.addWidget(label)
            layout.addStretch()

        def cleanup(self):
            pass

    class LoggingTab(MockTab):
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

    class FileTransferTab(MockTab):
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

    class CoreDumpTab(MockTab):
        @Slot()
        def fetch_and_parse_last_crash(self):
            QMessageBox.information(
                self,
                "Core Dump",
                "Mock: fetching and parsing last crash (not implemented).",
            )

    class BuildTab(MockTab):
        pass

    class SdkInstallationTab(MockTab):  
        sdk_path_changed = Signal(str)
        managed_libraries_changed = Signal(list)

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.layout().addWidget(QLabel("SDK Tab (Mock - Real module missing)"))

# ==========================================
# EXTRACTED UI CLASSES
# ==========================================

if any(x is None for x in (
    ComponentAndroidSoAnalysisTab,
    ComponentColorDot,
    ComponentWorkspaceTab,
    ComponentHelpTab,
    ComponentSettingsTab,
    ComponentCommandWorker,
    ComponentRazorTab,
    ComponentProfilingTab,
    ComponentScreenshotsTab,
    ComponentBatteryWidget,
    ComponentTheme,
)):
    raise RuntimeError("Essential components failed to import from components/essential.")

# ==========================================
# MAIN WINDOW (VitaDeckModern)
# ==========================================

class VitaDeckModern(QWidget):
    # Base64 encoded SVG
    REFRESH_SVG_B64 = """
        PD94bWwgdmVyc2lvbj0iMS4wIiA/Pgo8c3ZnIGZpbGw9IiNEQ0RDREMiIHdpZHRoPSI4MDBweCIgaGVpZ2h0PSI4MDBweCIgdmlld0JveD0iMCAwIDk2IDk2IiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPgo8dGl0bGUvPgo8Zz4KPHBhdGggZD0iTTk0LjI0MjIsMzcuNzU3OGE1Ljk5NzksNS45OTc5LDAsMCwwLTguNDg0NCwwbC0yLjYxLDIuNjFBMzYuMDM0NywzNi4wMzQ3LDAsMCwwLDQ4LDEyYTM1LjU1LDM1LjU1LDAsMCwwLTIxLjYyMTEsNy4zNTk0LDUuOTk3Nyw1Ljk5NzcsMCwwLDAsNy4yNDIyLDkuNTYyNUEyMy42Njc3LDIzLjY2NzcsMCwwLDEsNDgsMjQsMjMuOTU3LDIzLjA0MjksMCwwLDEsNzAuNjcyOSw0MC40NzY2bC0zLjk3LTMuMTY0MWE1Ljk5NTYsNS45OTU2LDAsMSwwLTcuNDc2NSw5LjM3NWwxNS4wMzUxLDEyYTUuOTksNS45OTwwLDAsMCw3Ljk4LC0wLjQ0NTNsMTItMTJBNS45OTc5LDUuOTk3OSwwLDAsMCw5NC4yNDIyLDM3Ljc1NzhaIi8+CjxwYXRoIGQ9Ik02Mi4zNzg5LDY3LjA3ODFBMjMuNjY3NSwyMy42Njc1LDAsMCwxLDQ4LDcyLDIzLjE2LDIzLjE2LDAsMCwxLDM1Ljc1NzgsNjcuMDc4MSw1Ljk5NzcsNS45OTc3LDAsMSwwLDI4LjUxNTYsNzYuNDg0NEEzNi4wMzQ3LDM1LjAzNDcsMCwwLDAsNDgsODRhMzUuNTUsMzUuNTUsMCwwLDAsMjEuNjIxMS03LjM1OTQsNS45OTc3LDUuOTk3Nyw1Ljk5NzcsMCwxLDAtNy4yNDIyLTkuNTYyNVWiIvPgo8L2c+Cjwvc3ZnPg==
    """

    IPV4_PATTERN = re.compile(
        r"^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
        r"(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
    )

    COMPONENT_TOGGLE_DEFAULTS: Dict[str, bool] = {
        "workspace": True,
        "help": True,
        "logging": True,
        "core_dump": True,
        "razor": True,
        "profiling": True,
        "android": True,
        "screenshots": True,
        "build": True,
        "sdk": True,
        "file_transfer": True,
    }
    COMPONENT_LABELS: Dict[str, str] = {
        "workspace": "Workspace",
        "help": "Help",
        "logging": "Logging",
        "core_dump": "Core Dump",
        "razor": "Razor",
        "profiling": "Profiling",
        "android": "Android",
        "screenshots": "Screenshots",
        "build": "Build",
        "sdk": "SDK",
        "file_transfer": "File Transfer",
    }
    COMPONENT_MODULE_EXCLUDE = {
        "__init__",
        "android_so_analysis",
        "build",
        "config",
        "core_dump",
        "file_transfer",
        "icon_utils",
        "logging",
        "sdk_installation",
        "theme_manager",
        "ui_misc_tabs",
        "utils",
    }
    COMPONENT_DEFAULT_ORDER: List[str] = list(COMPONENT_TOGGLE_DEFAULTS.keys())

    def _get_component_toggles(self) -> Dict[str, bool]:
        raw = settings.get("component_toggles", {})
        if not isinstance(raw, dict):
            raw = {}
        merged = {
            key: bool(raw.get(key, default))
            for key, default in self.component_toggle_defaults.items()
        }
        settings.set("component_toggles", merged)
        return merged

    def _get_component_order(self) -> List[str]:
        raw = settings.get("component_order", [])
        if not isinstance(raw, list):
            raw = []
        seen = set()
        ordered = []
        for key in raw:
            if key in self.component_toggle_defaults and key not in seen:
                ordered.append(key)
                seen.add(key)
        for key in self.component_default_order:
            if key not in seen:
                ordered.append(key)
        settings.set("component_order", ordered)
        return ordered

    def _component_enabled(self, key: str) -> bool:
        return bool(self.component_toggles.get(key, self.component_toggle_defaults.get(key, True)))

    @staticmethod
    def _camel_case_name(stem: str) -> str:
        return "".join(part.capitalize() for part in stem.replace("-", "_").split("_") if part)

    def _custom_component_paths(self) -> List[Path]:
        components_dir = BASE_DIR / "components"
        custom_dir = components_dir / "custom"
        discovered: List[Path] = []
        seen: set[str] = set()

        for folder in (custom_dir, components_dir):
            if not folder.exists() or not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.py")):
                stem = path.stem
                if stem.startswith("_") or stem in self.COMPONENT_MODULE_EXCLUDE:
                    continue
                key = str(path.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)
                discovered.append(path)

        return discovered

    def _resolve_custom_component_factory(self, module: Any, stem: str):
        factory = getattr(module, "create_component", None)
        if callable(factory):
            return factory

        component_class = getattr(module, "COMPONENT_CLASS", None)
        if isinstance(component_class, str):
            component_class = getattr(module, component_class, None)
        if inspect.isclass(component_class) and issubclass(component_class, QWidget):
            return component_class

        preferred_names = [
            f"{self._camel_case_name(stem)}Tab",
            "ComponentTab",
            "CustomComponent",
        ]
        for name in preferred_names:
            candidate = getattr(module, name, None)
            if inspect.isclass(candidate) and issubclass(candidate, QWidget):
                return candidate

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__:
                continue
            if issubclass(obj, QWidget):
                return obj

        return None

    def _invoke_component_factory(self, factory) -> QWidget:
        try:
            signature = inspect.signature(factory)
        except (TypeError, ValueError):
            signature = None
        kwargs: Dict[str, Any] = {}
        if signature is not None:
            for name, param in signature.parameters.items():
                if param.kind not in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                ):
                    continue
                if name in ("settings", "settings_instance"):
                    kwargs[name] = settings
                elif name == "cmd_thread":
                    kwargs[name] = self.cmd_thread
                elif name == "parent":
                    kwargs[name] = self
                elif name == "project_root":
                    kwargs[name] = BASE_DIR
                elif name == "screenshots_dir":
                    kwargs[name] = SCREENSHOTS_DIR

        widget = factory(**kwargs) if kwargs else factory()
        if not isinstance(widget, QWidget):
            raise TypeError("Factory did not return a QWidget instance.")
        return widget

    def _discover_custom_components(self) -> Dict[str, Dict[str, Any]]:
        specs: Dict[str, Dict[str, Any]] = {}

        custom_dir = BASE_DIR / "components" / "custom"
        if not custom_dir.exists():
            try:
                custom_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                print(f"Warning: could not create custom component folder '{custom_dir}': {e}")

        for path in self._custom_component_paths():
            stem = path.stem
            module_name = f"vitadeck_custom_{stem}_{abs(hash(str(path.resolve())))}"

            try:
                spec = importlib.util.spec_from_file_location(module_name, str(path))
                if spec is None or spec.loader is None:
                    print(f"Warning: failed to build module spec for custom component: {path}")
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception as e:
                print(f"Warning: failed loading custom component '{path.name}': {e}")
                continue

            factory = self._resolve_custom_component_factory(module, stem)
            if factory is None:
                print(
                    f"Warning: custom component '{path.name}' missing QWidget class or create_component()."
                )
                continue

            key = getattr(module, "COMPONENT_KEY", stem)
            if not isinstance(key, str):
                key = str(key)
            key = key.strip().lower().replace(" ", "_")
            if not key:
                key = stem.lower()
            if key in self.COMPONENT_TOGGLE_DEFAULTS:
                key = f"custom_{key}"
            if key in specs:
                print(
                    f"Warning: duplicate custom component key '{key}' in '{path.name}', "
                    "skipping duplicate."
                )
                continue

            label = getattr(module, "COMPONENT_LABEL", stem.replace("_", " ").title())
            if not isinstance(label, str):
                label = str(label)
            label = label.strip() or stem.replace("_", " ").title()

            specs[key] = {
                "key": key,
                "label": label,
                "factory": factory,
                "path": path,
            }

        return specs

    def _safe_set_tab_visible(self, tab_index: Optional[int], visible: bool):
        if tab_index is None:
            return
        tab_bar = self.tabs.tabBar()
        tab_bar.setTabVisible(tab_index, visible)

    def _apply_background_settings(self):
        """Applies theme/window opacity and refreshes cached background rendering state."""
        if not current_theme:
            self.setWindowOpacity(1.0)
            self._background_enabled = False
            self.update()
            return

        bg_settings = getattr(current_theme, "background_settings", {})
        try:
            opacity = float(bg_settings.get("opacity", 1.0))
            self.setWindowOpacity(opacity)
        except ValueError:
            self.setWindowOpacity(1.0)
        self._refresh_background_state()
        self.update()

    def _background_image_opacity(self) -> float:
        theme_default = 1.0
        if current_theme is not None:
            try:
                theme_default = float(getattr(current_theme, "image_opacity", 1.0))
            except Exception:
                theme_default = 1.0

        raw = settings.get("background_image_opacity", theme_default)
        try:
            val = float(raw)
        except (TypeError, ValueError):
            val = theme_default
        return max(0.0, min(1.0, val))

    def _ui_elements_opacity(self) -> float:
        raw = settings.get("ui_elements_opacity", 1.0)
        try:
            val = float(raw)
        except (TypeError, ValueError):
            val = 1.0
        return max(0.1, min(1.0, val))

    @staticmethod
    def _color_with_alpha(color_value: str, alpha: float, fallback: str) -> str:
        if isinstance(color_value, str) and color_value.strip().lower() == "transparent":
            return "transparent"
        c = QColor(color_value)
        if not c.isValid():
            c = QColor(fallback)
        if not c.isValid():
            c = QColor("#000000")
        a = max(0.0, min(1.0, float(alpha)))
        return f"rgba({c.red()}, {c.green()}, {c.blue()}, {a:.3f})"

    def _refresh_background_state(self):
        self._background_enabled = False
        self._background_pixmap = QPixmap()
        self._background_aspect_mode = "keep"
        self._background_opacity = self._background_image_opacity()

        if not current_theme:
            return

        image_location = getattr(current_theme, "image_location", None)
        if not image_location or str(image_location).lower() == "none":
            return

        image_path = current_theme.theme_dir / str(image_location)
        if not image_path.is_file():
            return

        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            print(f"Warning: Failed to load background image at {image_path}")
            return

        self._background_pixmap = pixmap
        mode = str(settings.get("background_aspect_mode", "")).lower().strip()
        if not mode:
            mode = str(getattr(current_theme, "aspect_ratio_mode", "keep")).lower().strip()
        mode_map = {
            "scale": "stretch",
            "stretch": "stretch",
            "cut": "cut",
            "cover": "cut",
            "keep": "keep",
            "contain": "keep",
            "none": "keep",
        }
        mode = mode_map.get(mode, "keep")
        self._background_aspect_mode = mode
        self._background_enabled = True

    @Slot(float)
    def on_background_image_opacity_changed(self, opacity: float):
        settings.set("background_image_opacity", max(0.0, min(1.0, float(opacity))))
        self._background_opacity = self._background_image_opacity()
        self.update()

    @Slot(str)
    def on_background_mode_changed(self, mode: str):
        mode = str(mode or "keep").lower().strip()
        if mode not in ("keep", "cut", "stretch"):
            mode = "keep"
        settings.set("background_aspect_mode", mode)
        self._refresh_background_state()
        self.update()

    @Slot(float)
    def on_ui_elements_opacity_changed(self, opacity: float):
        settings.set("ui_elements_opacity", max(0.1, min(1.0, float(opacity))))
        self.apply_style(initial=False)


    @Slot(str)
    def on_sdk_path_changed(self, new_path: str):
        """Saves the new SDK path to the current workspace settings."""
        settings.set("sdk_path", new_path)
        if hasattr(settings, "save"):
            settings.save()

    @Slot(list)
    def on_managed_libraries_changed(self, new_libs: list):
        """Saves the updated list of managed libraries to the current workspace settings."""
        settings.set("managed_libraries", new_libs)
        if hasattr(settings, "save"):
            settings.save()
            
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

    def _sdk_tab_settings_from_workspace(self) -> Dict[str, Any]:
        """Builds a settings snapshot for the SDK tab from the active workspace."""
        managed_libraries = settings.get("managed_libraries", [])
        if not isinstance(managed_libraries, list):
            managed_libraries = []

        normalized_managed_libraries = []
        for item in managed_libraries:
            normalized_managed_libraries.append(dict(item) if isinstance(item, dict) else {})

        return {
            "sdk_path": settings.get("sdk_path", "$HOME/vitasdk"),
            "managed_libraries": normalized_managed_libraries,
        }

    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vitadeck - Manager & Debugger")
        self.resize(1300, 700)
        self.setObjectName("VitaDeckModern")
        
        self._pending_app_launch = None
        self._local_ip_cache = self.get_local_ip()
        self._background_enabled = False
        self._background_pixmap = QPixmap()
        self._background_aspect_mode = "keep"
        self._background_opacity = 1.0
        self.custom_component_specs = self._discover_custom_components()
        self.custom_component_widgets: Dict[str, QWidget] = {}
        self.custom_component_indices: Dict[str, int] = {}
        self.component_labels = dict(self.COMPONENT_LABELS)
        self.component_toggle_defaults = dict(self.COMPONENT_TOGGLE_DEFAULTS)
        self.component_default_order = list(self.COMPONENT_DEFAULT_ORDER)
        for key, spec in self.custom_component_specs.items():
            self.component_labels[key] = spec["label"]
            self.component_toggle_defaults[key] = True
            if key not in self.component_default_order:
                self.component_default_order.append(key)
        self.component_toggles = self._get_component_toggles()
        self.component_order = self._get_component_order()
        sdk_tab_settings = self._sdk_tab_settings_from_workspace()
        self.cmd_thread = ComponentCommandWorker(settings)

        main_layout = QVBoxLayout(self)
        content_and_sidebar = QHBoxLayout()

        self.tabs = QTabWidget()
        self.tabs.setFont(QFont("Arial", settings.get("base_font_size", 10)))

        self.tab_workspace = None
        self.tab_logging = None
        self.tab_core = None
        self.tab_razor = None
        self.tab_profiling = None
        self.tab_android_so = None
        self.tab_screenshots = None
        self.tab_build = None
        self.tab_sdk = None
        self.tab_transfer = None
        self.tab_help = None
        self.tab_settings = None

        self.idx_workspace = None
        self.idx_logging = None
        self.idx_core = None
        self.idx_razor = None
        self.idx_profiling = None
        self.idx_android = None
        self.idx_screenshots = None
        self.idx_build = None
        self.idx_sdk = None
        self.idx_transfer = None
        self.idx_help = None
        self.idx_settings = None
        for component_key in self.component_order:
            if not self._component_enabled(component_key):
                continue

            if component_key == "workspace":
                self.tab_workspace = ComponentWorkspaceTab(settings)
                self.tab_workspace.workspace_changed.connect(self.apply_workspace_settings)
                self.idx_workspace = self.tabs.addTab(self.tab_workspace, "Workspaces")
            elif component_key == "core_dump":
                self.tab_core = CoreDumpTab()
                self.idx_core = self.tabs.addTab(self.tab_core, "Core Dump")
            elif component_key == "razor":
                self.tab_razor = ComponentRazorTab()
                self.idx_razor = self.tabs.addTab(self.tab_razor, "Razor")
            elif component_key == "profiling":
                self.tab_profiling = ComponentProfilingTab()
                self.idx_profiling = self.tabs.addTab(self.tab_profiling, "Profiling")
            elif component_key == "android":
                self.tab_android_so = ComponentAndroidSoAnalysisTab(settings, self.cmd_thread)
                self.idx_android = self.tabs.addTab(self.tab_android_so, "Android")
            elif component_key == "screenshots":
                self.tab_screenshots = ComponentScreenshotsTab(SCREENSHOTS_DIR)
                self.idx_screenshots = self.tabs.addTab(self.tab_screenshots, "Screenshots")
            elif component_key == "build":
                self.tab_build = BuildTab()
                self.idx_build = self.tabs.addTab(self.tab_build, "Build")
            elif component_key == "sdk":
                self.tab_sdk = SdkInstallationTab(sdk_tab_settings)
                self.tab_sdk.sdk_path_changed.connect(self.on_sdk_path_changed)
                self.tab_sdk.managed_libraries_changed.connect(self.on_managed_libraries_changed)
                self.idx_sdk = self.tabs.addTab(self.tab_sdk, "SDK")
            elif component_key == "file_transfer":
                self.tab_transfer = FileTransferTab()
                if hasattr(self.tab_transfer, "ftp_thread"):
                    ftp_thread = self.tab_transfer.ftp_thread
                    if hasattr(ftp_thread, "status_signal"):
                        ftp_thread.status_signal.connect(self.update_connection_status)
                    if hasattr(ftp_thread, "progress_signal"):
                        ftp_thread.progress_signal.connect(self.update_transfer_status)
                        ftp_thread.progress_signal.connect(self.check_launch_queue)
                self.idx_transfer = self.tabs.addTab(self.tab_transfer, "File Transfer")
            elif component_key == "logging":
                self.tab_logging = LoggingTab()
                self.cmd_thread.command_output_signal.connect(self.tab_logging.append_log)
                self.idx_logging = self.tabs.addTab(self.tab_logging, "Logging")
            elif component_key == "help":
                self.tab_help = ComponentHelpTab()
                self.idx_help = self.tabs.addTab(self.tab_help, "Help")
            elif component_key in self.custom_component_specs:
                spec = self.custom_component_specs[component_key]
                try:
                    widget = self._invoke_component_factory(spec["factory"])
                except Exception as e:
                    print(
                        f"Warning: failed to initialize custom component '{spec['label']}' "
                        f"from {spec['path']}: {e}"
                    )
                    continue
                self.custom_component_widgets[component_key] = widget
                idx = self.tabs.addTab(widget, spec["label"])
                self.custom_component_indices[component_key] = idx

        self.tab_settings = ComponentSettingsTab(
            settings,
            THEMES_DIR,
            self.component_toggle_defaults,
            self.component_labels,
        )
        self.tab_settings.restart_log_server_signal.connect(self.restart_logging_server)
        self.tab_settings.apply_style_signal.connect(self.apply_style)
        self.tab_settings.theme_changed.connect(self.change_theme)
        if hasattr(self.tab_settings, "component_config_changed"):
            self.tab_settings.component_config_changed.connect(self.on_component_config_changed)
        elif hasattr(self.tab_settings, "component_toggles_changed"):
            self.tab_settings.component_toggles_changed.connect(self.on_component_toggles_changed)
        self.idx_settings = self.tabs.addTab(self.tab_settings, "Settings")
        self.tab_settings.opacity_changed.connect(self.set_window_opacity)
        if hasattr(self.tab_settings, "background_image_opacity_changed"):
            self.tab_settings.background_image_opacity_changed.connect(
                self.on_background_image_opacity_changed
            )
        if hasattr(self.tab_settings, "background_mode_changed"):
            self.tab_settings.background_mode_changed.connect(self.on_background_mode_changed)
        if hasattr(self.tab_settings, "ui_elements_opacity_changed"):
            self.tab_settings.ui_elements_opacity_changed.connect(
                self.on_ui_elements_opacity_changed
            )

        self.setup_tab_icons()

        self._safe_set_tab_visible(self.idx_workspace, False)
        self._safe_set_tab_visible(self.idx_help, False)
        self._safe_set_tab_visible(self.idx_settings, False)

        content_and_sidebar.addWidget(self.tabs, stretch=4)

        self.setup_sidebar(content_and_sidebar)
        main_layout.addLayout(content_and_sidebar)

        self.setup_status_bar(main_layout)

        self.apply_workspace_settings(initial=True)
        self._apply_tab_icons_from_theme()

        if current_theme:
            self._apply_background_settings()

        if type(settings).__name__ == "MockSettings":
            QMessageBox.warning(
                self,
                "Warning",
                "Running in MOCK mode. Some features may not work as expected because external modules are missing.",
            )
        self.set_window_opacity() #
        self.cmd_thread.start()
        
    @Slot(float)
    def set_window_opacity(self, opacity: float = None):
        """Applies the current workspace opacity setting to the window."""
        if opacity is None:
            opacity = settings.get("window_opacity", 1.0)

        opacity = max(0.0, min(1.0, opacity))
        self.setWindowOpacity(opacity)

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
                return qicon_from_svg_file(path, size=20)
        svg_content = base64.b64decode(self.REFRESH_SVG_B64).decode("utf-8")
        return svg_to_qicon(svg_content, size=20)

    def _apply_tab_icons_from_theme(self):
        if not current_theme:
            return

    def _refresh_tab_theme_icons(self):
        tabs_to_refresh = [
            self.tab_logging,
            self.tab_core,
            self.tab_build,
            self.tab_sdk,
            self.tab_android_so,
        ]
        tabs_to_refresh.extend(self.custom_component_widgets.values())
        for tab in tabs_to_refresh:
            if tab is None:
                continue
            fn = getattr(tab, "apply_theme_icons", None)
            if callable(fn):
                try:
                    fn()
                except Exception as e:
                    print(f"Warning: failed to refresh tab icons for '{type(tab).__name__}': {e}")

    def setup_tab_icons(self):
        old_corner_widget = self.tabs.cornerWidget(Qt.TopRightCorner)
        if old_corner_widget:
            old_corner_widget.deleteLater()
            self.tabs.setCornerWidget(None, Qt.TopRightCorner)

        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 8, 0)
        corner_layout.setSpacing(4)
        
        icon_tabs = []
        if self._component_enabled("workspace") and self.idx_workspace is not None:
            icon_tabs.append(("Workspace", self.idx_workspace, "workspace", SAVE_SVG))
        if self.idx_settings is not None:
            icon_tabs.append(("Settings", self.idx_settings, "settings", SETTINGS_SVG))
        if self._component_enabled("help") and self.idx_help is not None:
            icon_tabs.append(("Help", self.idx_help, "help", INFO_SVG))

        if not hasattr(self, 'icon_buttons'):
            self.icon_buttons = []
        else:
            self.icon_buttons.clear()


        for name, tab_index, icon_key, fallback_svg in icon_tabs:
            btn = QPushButton()
            btn.setFlat(True)
            
            icon = self._get_themed_icon(icon_key, fallback_svg, size=20)
            btn.setIcon(icon)
            btn.setIconSize(QSize(20, 20))
            btn.setFixedSize(28, 28)
            btn.setToolTip(name)
            
            btn.clicked.connect(lambda checked=False, idx=tab_index: self.tabs.setCurrentIndex(idx))
            
            corner_layout.addWidget(btn)
            self.icon_buttons.append(btn)

        corner_layout.addStretch()
        
        self.tabs.setCornerWidget(corner_widget, Qt.TopRightCorner)
        corner_widget.show()

    def _component_widget_map(self) -> Dict[str, Optional[QWidget]]:
        widget_map: Dict[str, Optional[QWidget]] = {
            "workspace": self.tab_workspace,
            "help": self.tab_help,
            "logging": self.tab_logging,
            "core_dump": self.tab_core,
            "razor": self.tab_razor,
            "profiling": self.tab_profiling,
            "android": self.tab_android_so,
            "screenshots": self.tab_screenshots,
            "build": self.tab_build,
            "sdk": self.tab_sdk,
            "file_transfer": self.tab_transfer,
        }
        for key, widget in self.custom_component_widgets.items():
            widget_map[key] = widget
        return widget_map

    def _refresh_component_indices(self):
        widget_map = self._component_widget_map()
        self.idx_workspace = self.tabs.indexOf(widget_map["workspace"]) if widget_map["workspace"] else None
        self.idx_help = self.tabs.indexOf(widget_map["help"]) if widget_map["help"] else None
        self.idx_logging = self.tabs.indexOf(widget_map["logging"]) if widget_map["logging"] else None
        self.idx_core = self.tabs.indexOf(widget_map["core_dump"]) if widget_map["core_dump"] else None
        self.idx_razor = self.tabs.indexOf(widget_map["razor"]) if widget_map["razor"] else None
        self.idx_profiling = self.tabs.indexOf(widget_map["profiling"]) if widget_map["profiling"] else None
        self.idx_android = self.tabs.indexOf(widget_map["android"]) if widget_map["android"] else None
        self.idx_screenshots = self.tabs.indexOf(widget_map["screenshots"]) if widget_map["screenshots"] else None
        self.idx_build = self.tabs.indexOf(widget_map["build"]) if widget_map["build"] else None
        self.idx_sdk = self.tabs.indexOf(widget_map["sdk"]) if widget_map["sdk"] else None
        self.idx_transfer = self.tabs.indexOf(widget_map["file_transfer"]) if widget_map["file_transfer"] else None
        self.custom_component_indices = {}
        for key, widget in self.custom_component_widgets.items():
            idx = self.tabs.indexOf(widget) if widget else -1
            if idx >= 0:
                self.custom_component_indices[key] = idx

    def _apply_component_order(self):
        widget_map = self._component_widget_map()
        target_position = 0
        tab_bar = self.tabs.tabBar()
        for key in self.component_order:
            widget = widget_map.get(key)
            if widget is None:
                continue
            current_index = self.tabs.indexOf(widget)
            if current_index < 0:
                continue
            if current_index != target_position:
                tab_bar.moveTab(current_index, target_position)
            target_position += 1
        self._refresh_component_indices()

    @Slot(dict, list)
    def on_component_config_changed(self, toggles: dict, order: list):
        self.component_order = self._get_component_order()
        if isinstance(order, list):
            seen = set()
            ordered = []
            for key in order:
                if key in self.component_toggle_defaults and key not in seen:
                    ordered.append(key)
                    seen.add(key)
            for key in self.component_default_order:
                if key not in seen:
                    ordered.append(key)
            self.component_order = ordered
            settings.set("component_order", ordered)
        self.on_component_toggles_changed(toggles)
        self._apply_component_order()
        self._safe_set_tab_visible(self.idx_workspace, False)
        self._safe_set_tab_visible(self.idx_help, False)
        self._safe_set_tab_visible(self.idx_settings, False)
        self.setup_tab_icons()

    @Slot(dict)
    def on_component_toggles_changed(self, toggles: dict):
        self.component_toggles = {
            key: bool(toggles.get(key, default))
            for key, default in self.component_toggle_defaults.items()
        }

        if self.idx_logging is not None:
            self._safe_set_tab_visible(self.idx_logging, self._component_enabled("logging"))
        if self.idx_core is not None:
            self._safe_set_tab_visible(self.idx_core, self._component_enabled("core_dump"))
        if self.idx_razor is not None:
            self._safe_set_tab_visible(self.idx_razor, self._component_enabled("razor"))
        if self.idx_profiling is not None:
            self._safe_set_tab_visible(self.idx_profiling, self._component_enabled("profiling"))
        if self.idx_android is not None:
            self._safe_set_tab_visible(self.idx_android, self._component_enabled("android"))
        if self.idx_screenshots is not None:
            self._safe_set_tab_visible(self.idx_screenshots, self._component_enabled("screenshots"))
        if self.idx_build is not None:
            self._safe_set_tab_visible(self.idx_build, self._component_enabled("build"))
        if self.idx_sdk is not None:
            self._safe_set_tab_visible(self.idx_sdk, self._component_enabled("sdk"))
        if self.idx_transfer is not None:
            self._safe_set_tab_visible(self.idx_transfer, self._component_enabled("file_transfer"))
        for key, idx in self.custom_component_indices.items():
            self._safe_set_tab_visible(idx, self._component_enabled(key))

        self._safe_set_tab_visible(self.idx_workspace, False)
        self._safe_set_tab_visible(self.idx_help, False)
        self._safe_set_tab_visible(self.idx_settings, False)
        self.setup_tab_icons()

        current_idx = self.tabs.currentIndex()
        tab_bar = self.tabs.tabBar()
        if current_idx >= 0 and not tab_bar.isTabVisible(current_idx):
            switched = False
            for i in range(self.tabs.count()):
                if tab_bar.isTabVisible(i):
                    self.tabs.setCurrentIndex(i)
                    switched = True
                    break
            if not switched and self.idx_settings is not None:
                self.tabs.setCurrentIndex(self.idx_settings)

        restart_needed = []
        if self._component_enabled("workspace") and self.idx_workspace is None:
            restart_needed.append("Workspace")
        if self._component_enabled("help") and self.idx_help is None:
            restart_needed.append("Help")
        if self._component_enabled("logging") and self.idx_logging is None:
            restart_needed.append("Logging")
        if self._component_enabled("core_dump") and self.idx_core is None:
            restart_needed.append("Core Dump")
        if self._component_enabled("razor") and self.idx_razor is None:
            restart_needed.append("Razor")
        if self._component_enabled("profiling") and self.idx_profiling is None:
            restart_needed.append("Profiling")
        if self._component_enabled("android") and self.idx_android is None:
            restart_needed.append("Android")
        if self._component_enabled("screenshots") and self.idx_screenshots is None:
            restart_needed.append("Screenshots")
        if self._component_enabled("build") and self.idx_build is None:
            restart_needed.append("Build")
        if self._component_enabled("sdk") and self.idx_sdk is None:
            restart_needed.append("SDK")
        if self._component_enabled("file_transfer") and self.idx_transfer is None:
            restart_needed.append("File Transfer")
        for key, spec in self.custom_component_specs.items():
            if self._component_enabled(key) and key not in self.custom_component_indices:
                restart_needed.append(spec["label"])

        if restart_needed:
            QMessageBox.information(
                self,
                "Restart Required",
                "Enabled components that were not loaded at startup. Restart the app to load: "
                + ", ".join(restart_needed),
            )

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

        if hasattr(self.tab_logging, "sync_with_settings"):
            self.tab_logging.sync_with_settings()
        if hasattr(self.tab_build, "sync_with_settings"):
            self.tab_build.sync_with_settings()
        if hasattr(self.tab_transfer, "sync_with_settings"):
            self.tab_transfer.sync_with_settings()
        if hasattr(self.tab_core, "sync_with_settings"):
            self.tab_core.sync_with_settings()
        if hasattr(self.tab_sdk, "sync_with_settings"):
            self.tab_sdk.sync_with_settings(self._sdk_tab_settings_from_workspace())
        for widget in self.custom_component_widgets.values():
            sync_fn = getattr(widget, "sync_with_settings", None)
            if not callable(sync_fn):
                continue
            try:
                sync_fn()
            except TypeError:
                try:
                    sync_fn(settings)
                except Exception as e:
                    print(f"Warning: custom component sync failed: {e}")
            except Exception as e:
                print(f"Warning: custom component sync failed: {e}")

        self.tab_settings.set_settings_values()
        self.apply_style(initial=initial)

        self.cmd_thread.set_host(vita_ip)
        self.update_local_ip_status(initial=initial)

        if self.tab_workspace and hasattr(self.tab_workspace, "refresh_list"):
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
        self.set_window_opacity()
        self._apply_background_settings() 
        self.setup_tab_icons()
        if hasattr(self, "btn_refresh_ip"):
            self.btn_refresh_ip.setIcon(self._get_refresh_icon())
        if hasattr(self, 'battery_widget') and current_theme:
            self.battery_widget.update_theme_path(current_theme.base_dir)
        self._refresh_tab_theme_icons()

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

    @Slot(int)
    def restart_logging_server(self, port):
        if hasattr(self.tab_logging, "restart_server"):
            self.tab_logging.restart_server(port)
    @Slot(str)
    def handle_theme_change(self, theme_name: str):
        """Loads the theme and reapplies the application's style sheet."""
        load_theme(theme_name)
        self.apply_style()
        if current_theme:
            self.battery_widget.update_theme_path(current_theme.base_dir)

    def _get_style_sheet(self, base_font_size: int, log_font_size: int) -> str:
        """Generates the full QSS string, including background image rules."""
        global current_theme
        
        if not current_theme:
            return ""
        
        qss_parts = []
        theme_file = current_theme.theme_dir / "theme.txt"
        
        if not theme_file.exists():
            print(f"Warning: theme.txt not found at {theme_file}")
            return ""
        
        variables = {}
        qss_lines = []
        in_qss = False
        
        try:
            with open(theme_file, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped == "# ===== QSS START =====":
                        in_qss = True
                        continue
                    if not in_qss:
                        if not stripped or stripped.startswith("#") or "=" not in stripped:
                            continue
                        k, v = stripped.split("=", 1)
                        variables[k.strip()] = v.strip()
                    else:
                        qss_lines.append(line.rstrip("\n"))
        
        except Exception as e:
            print(f"Error reading theme file: {e}")
            return ""
        
        variables["base_font_size"] = str(base_font_size)
        variables["log_font_size"] = str(log_font_size)
        
        qss = "\n".join(qss_lines)
        try:
            qss = qss.format(**variables)
        except KeyError as e:
            print(f"Warning: Missing variable in theme: {e}")
        
        qss_parts.append(qss)

        log_bg = self.theme_color("log_bg", "#111")
        log_border = self.theme_color("log_border", "#333")
        log_text = self.theme_color("log_text", "#c0c0c0")
        button_hover_bg = self.theme_color("button_hover_bg", "#3a668a")
        button_pressed_bg = self.theme_color("button_pressed_bg", "#2a5975")
        icon_button_bg = "rgba(140, 140, 140, 0.35)"
        icon_button_border = "rgba(220, 220, 220, 0.35)"
        log_radius = "12px"
        icon_button_radius = log_radius
        radius_match = re.search(
            r"QTextEdit#logOutput,\s*QPlainTextEdit#logOutput\s*\{[^}]*border-radius:\s*([^;]+);",
            qss,
            re.IGNORECASE | re.DOTALL,
        )
        if radius_match:
            log_radius = radius_match.group(1).strip()
            icon_button_radius = log_radius
        button_radius_match = re.search(
            r"QPushButton\s*\{[^}]*border-radius:\s*([^;]+);",
            qss,
            re.IGNORECASE | re.DOTALL,
        )
        if button_radius_match:
            icon_button_radius = button_radius_match.group(1).strip()

        embedded_console_qss = f"""
#logOutputContainer {{
    background-color: {log_bg};
    border: 1px solid {log_border};
    border-radius: {log_radius};
}}

#logOutputContainer QTextEdit#logOutput,
#logOutputContainer QPlainTextEdit#logOutput {{
    background: transparent;
    border: none;
    border-radius: 0px;
    color: {log_text};
}}

#logOutputContainer QLabel {{
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
}}

#logOutputContainer QPushButton {{
    background-color: {icon_button_bg};
    border: 1px solid {icon_button_border};
    border-radius: {icon_button_radius};
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    padding: 0;
}}

#logOutputContainer QPushButton:hover {{
    background-color: {button_hover_bg};
}}

#logOutputContainer QPushButton:pressed {{
    background-color: {button_pressed_bg};
}}
"""
        qss_parts.append(embedded_console_qss)

        ui_alpha = self._ui_elements_opacity()
        if ui_alpha < 0.999:
            bg_alpha = self._color_with_alpha(self.theme_color("background", "#1e1e1e"), ui_alpha, "#1e1e1e")
            group_bg_alpha = self._color_with_alpha(self.theme_color("group_bg", "#1e1e1e"), ui_alpha, "#1e1e1e")
            sidebar_bg_alpha = self._color_with_alpha(self.theme_color("sidebar_bg", "#252525"), ui_alpha, "#252525")
            input_bg_alpha = self._color_with_alpha(self.theme_color("input_bg", "#2d2d2d"), ui_alpha, "#2d2d2d")
            button_bg_alpha = self._color_with_alpha(self.theme_color("button_bg", "#2f4f6f"), ui_alpha, "#2f4f6f")
            button_hover_alpha = self._color_with_alpha(self.theme_color("button_hover_bg", "#3a668a"), ui_alpha, "#3a668a")
            button_pressed_alpha = self._color_with_alpha(self.theme_color("button_pressed_bg", "#2a5975"), ui_alpha, "#2a5975")
            tab_pane_bg_alpha = self._color_with_alpha(self.theme_color("tab_pane_bg", "#1e1e1e"), ui_alpha, "#1e1e1e")
            tab_bg_alpha = self._color_with_alpha(self.theme_color("tab_bg", "#2a2a2a"), ui_alpha, "#2a2a2a")
            tab_selected_bg_alpha = self._color_with_alpha(self.theme_color("tab_selected_bg", "#2f4f6f"), ui_alpha, "#2f4f6f")
            tab_hover_bg_alpha = self._color_with_alpha(self.theme_color("tab_hover_bg", "#3a3a3a"), ui_alpha, "#3a3a3a")
            log_bg_alpha = self._color_with_alpha(self.theme_color("log_bg", "#111"), ui_alpha, "#111")
            status_bg_alpha = self._color_with_alpha(self.theme_color("status_bar_bg", "#252525"), ui_alpha, "#252525")

            ui_alpha_qss = f"""
QWidget {{
    background-color: {bg_alpha};
}}

QGroupBox {{
    background-color: {group_bg_alpha};
}}

#sidebar {{
    background-color: {sidebar_bg_alpha};
}}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QListWidget, QComboBox {{
    background-color: {input_bg_alpha};
}}

QPushButton {{
    background-color: {button_bg_alpha};
}}

QPushButton:hover {{
    background-color: {button_hover_alpha};
}}

QPushButton:pressed {{
    background-color: {button_pressed_alpha};
}}

QTabWidget::pane {{
    background: {tab_pane_bg_alpha};
}}

QTabBar::tab {{
    background: {tab_bg_alpha};
}}

QTabBar::tab:selected {{
    background: {tab_selected_bg_alpha};
}}

QTabBar::tab:hover {{
    background: {tab_hover_bg_alpha};
}}

QTextEdit#logOutput, QPlainTextEdit#logOutput {{
    background-color: {log_bg_alpha};
}}

#statusBarFrame {{
    background-color: {status_bg_alpha};
}}

#logOutputContainer {{
    background-color: {log_bg_alpha};
}}
"""
            qss_parts.append(ui_alpha_qss)
        
        return "\n".join(qss_parts)

    @Slot()
    def apply_style(self, initial=False):
        self.set_window_opacity()
        """Applies the style sheet to the entire QApplication instance."""
        global current_theme
        
        if not current_theme: 
            print("Warning: Attempted to apply style, but no theme is currently loaded.")
            return
        base_font_size = settings.get("base_font_size", 10) 
        log_font_size = settings.get("log_font_size", 13)
        qss_content = self._get_style_sheet(base_font_size, log_font_size)
        
        if qss_content:
            QApplication.instance().setStyleSheet(qss_content)
        else:
            print("Warning: No QSS content generated")
        self._refresh_background_state()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        dominant_color = self._dominant_theme_color()
        painter.fillRect(self.rect(), dominant_color)

        if self._background_enabled and not self._background_pixmap.isNull() and self._background_opacity > 0.0:
            painter.save()
            painter.setOpacity(self._background_opacity)
            pixmap = self._background_pixmap
            mode = self._background_aspect_mode

            if mode == "stretch":
                painter.drawPixmap(self.rect(), pixmap)
            elif mode == "cut":
                scaled = pixmap.scaled(
                    self.size(),
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                )
                src_x = max(0, (scaled.width() - self.width()) // 2)
                src_y = max(0, (scaled.height() - self.height()) // 2)
                src_rect = QRect(src_x, src_y, self.width(), self.height())
                painter.drawPixmap(self.rect(), scaled, src_rect)
            elif mode == "keep":
                scaled = pixmap.scaled(
                    self.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                x = (self.width() - scaled.width()) // 2
                y = (self.height() - scaled.height()) // 2
                painter.drawPixmap(QRect(x, y, scaled.width(), scaled.height()), scaled)
            else:
                x = (self.width() - pixmap.width()) // 2
                y = (self.height() - pixmap.height()) // 2
                painter.drawPixmap(QRect(x, y, pixmap.width(), pixmap.height()), pixmap)
            painter.restore()

    def _dominant_theme_color(self) -> QColor:
        color = QColor(self.theme_color("background", "#1e1e1e"))
        if not color.isValid():
            color = QColor("#1e1e1e")
        return color

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

    def download_latest_file_async(self, remote_path: str, local_path: Path, file_pattern: str, is_recursive: bool):
        """
        Public method called by VitaDeckModern to enqueue a recursive download command.
        """        
        self.ftp_thread.add_command(
            'download_latest', 
            remote_path, 
            local_path, 
            file_pattern, 
            is_recursive
        )

    def trigger_and_fetch_screenshot(self):
        """
        1. Triggers a system screenshot on the Vita via the cmd_thread.
        2. Uses QTimer for a non-blocking 2-second wait.
        3. Initiates the download of the latest screenshot after the wait.
        """
        self.send_command("screenshot")
        
        if hasattr(self, 'log_message'):
            self.log_message("Screenshot triggered. Waiting 2s for file to save on Vita before fetching...", level='warn')

        QTimer.singleShot(4000, self._initiate_screenshot_download)

    def _initiate_screenshot_download(self):
        """Initiates the FTP download command after the screenshot has been triggered and saved."""
        # 3. Define remote path and pattern
        REMOTE_SCREENSHOT_DIR = "ux0:/picture/SCREENSHOT/"
        # The file pattern is for names like: 2025-12-11_10-50-00.jpg
        SCREENSHOT_FILE_PATTERN = r'\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.jpg'
        
        # FIX START: Robustly determine the local download folder to handle cross-OS path issues.
        configured_path = settings.get("dump_folder")
        
        # Define a robust default path
        # NOTE: Using a subdirectory 'VitaDeck_Screenshots' in Downloads for cleanliness.
        default_local_dir = Path.home() / "Downloads" / "VitaDeck_Screenshots" 

        if configured_path:
            # Check if running on non-Windows OS but loaded a Windows-style absolute path (e.g., 'C:\...')
            # os.name == 'nt' is True on Windows. We use Path.home() as the absolute path fallback.
            is_cross_os_path = os.name != 'nt' and configured_path.strip().startswith(('C:', 'D:', 'E:'))
            
            if is_cross_os_path:
                # Use the default path if the configured path is foreign
                local_dir = default_local_dir
                if hasattr(self, 'log_message'):
                    self.log_message(
                        f"Warning: Configured dump folder '{configured_path}' appears invalid for this OS. Using default: {local_dir.resolve()}", 
                        level='warn'
                    )
            else:
                # Use the configured path
                local_dir = Path(configured_path)
        else:
            # Use the default path if nothing is configured
            local_dir = default_local_dir

        # Resolve to an absolute path and create the directory
        local_dir = local_dir.resolve()
        local_dir.mkdir(parents=True, exist_ok=True) # Ensure folder exists
        # FIX END

        if hasattr(self.tab_transfer, "download_latest_file_async"):
            # This function call in file_transfer.py will handle disconnect/reconnect
            self.tab_transfer.download_latest_file_async(
                remote_path=REMOTE_SCREENSHOT_DIR,
                local_path=local_dir,
                file_pattern=SCREENSHOT_FILE_PATTERN,
                is_recursive=False # Screenshots are not recursive
            )
        else:
            if hasattr(self.tab_logging, "append_log"):
                self.tab_logging.append_log("File Transfer Tab not ready or missing required method.", "red")



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
        self.btn_upload_launch.setObjectName("btnUploadLaunch") # ID for styling
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

        btn_screenshot = QPushButton("Take screenshot")
        btn_screenshot.clicked.connect(self.trigger_and_fetch_screenshot)
        quick_layout.addWidget(btn_screenshot)

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

        if self.idx_logging is not None and self._component_enabled("logging"):
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
        
        if self.idx_logging is not None and self._component_enabled("logging"):
            self.tabs.setCurrentIndex(self.idx_logging)

    # ------------------------------
    # Status bar / local IP
    # ------------------------------ 
    def setup_local_ip_status(self, layout):
        inactive = self.theme_color("status_inactive", "#777")
        self.local_ip_dot = ComponentColorDot(inactive, size=12)
        layout.addWidget(self.local_ip_dot, 0, Qt.AlignVCenter)
        self.local_ip_label = QLabel("Local IP: N/A")
        self.local_ip_label.setStyleSheet(f"color: {inactive};")
        layout.addWidget(self.local_ip_label, 0, Qt.AlignVCenter)

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
        layout.addWidget(self.btn_refresh_ip, 0, Qt.AlignVCenter)

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
        self.status_frame = QFrame()
        self.status_frame.setObjectName("statusBarFrame") 
        status_bar_layout = QHBoxLayout(self.status_frame)
        status_bar_layout.setContentsMargins(12, 8, 12, 8) 
        status_bar_layout.setSpacing(8)
        status_bar_layout.setAlignment(Qt.AlignVCenter)
        inactive = self.theme_color("status_inactive", "#777")
        theme_path = os.path.join(THEMES_DIR, settings.get("theme_name", "default"))
        self.battery_widget = ComponentBatteryWidget(theme_path)
        status_bar_layout.addWidget(self.battery_widget, 0, Qt.AlignVCenter)
        self.cmd_thread.battery_signal.connect(self.battery_widget.update_battery)
        status_bar_layout.addSpacing(20)
        self.conn_dot = ComponentColorDot(inactive, size=12)
        status_bar_layout.addWidget(self.conn_dot, 0, Qt.AlignVCenter)
        self.conn_label = QLabel("Not connected")
        self.conn_label.setStyleSheet(f"color: {inactive};")
        status_bar_layout.addWidget(self.conn_label, 0, Qt.AlignVCenter)
        status_bar_layout.addSpacing(20)
        self.transfer_dot = ComponentColorDot(inactive, size=12)
        status_bar_layout.addWidget(self.transfer_dot, 0, Qt.AlignVCenter)
        self.transfer_label = QLabel("File transfer idle")
        self.transfer_label.setStyleSheet(f"color: {inactive};")
        status_bar_layout.addWidget(self.transfer_label, 0, Qt.AlignVCenter)
        status_bar_layout.addStretch()
        self.setup_local_ip_status(status_bar_layout)
        layout.addWidget(self.status_frame)


    @Slot(str, str)
    def update_connection_status(self, message, color):
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
    theme_name = settings.get("theme_name", "default")
    load_theme(theme_name)

    window = VitaDeckModern()
    window.show()

    sys.exit(app.exec())


