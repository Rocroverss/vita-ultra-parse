import os
from pathlib import Path
from typing import Optional
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt, QByteArray
from PySide6.QtSvg import QSvgRenderer

THEMES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "THEMES")
DEFAULT_THEME_DIR = Path(THEMES_DIR) / "default"

# --- SVG Constants ---
SETTINGS_SVG_FALLBACK = """<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="#777"/></svg>"""
INFO_SVG_FALLBACK = """<svg viewBox="0 0 24 24"><rect x="2" y="2" width="20" height="20" fill="#777"/></svg>"""
SAVE_SVG_FALLBACK = """<svg viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" fill="#777"/></svg>"""

def load_svg(filename: str, fallback: str) -> str:
    file_path = DEFAULT_THEME_DIR / filename
    try:
        if file_path.exists():
            return file_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"SVG load error for {filename}: {e}")
    return fallback

SETTINGS_SVG = load_svg("settings.svg", SETTINGS_SVG_FALLBACK)
INFO_SVG = load_svg("info.svg", INFO_SVG_FALLBACK)
SAVE_SVG = load_svg("save.svg", SAVE_SVG_FALLBACK)

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
    renderer = QSvgRenderer(QByteArray(svg_content.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)

def qicon_from_svg_file(path: str, size: int = 24) -> QIcon:
    if not os.path.exists(path):
        return QIcon()
    renderer = QSvgRenderer(path)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)

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
        theme_file = os.path.join(self.base_dir, "theme.txt")
        if os.path.exists(theme_file):
            try:
                with open(theme_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith(("#", "//")):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                        elif ":" in line:
                            key, val = line.split(":", 1)
                        else:
                            continue
                        self.palette[key.strip()] = val.strip()
            except Exception as e:
                print(f"Warning: failed to read theme file '{theme_file}': {e}")

    def _load_icons(self):
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