import os
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


PROJECT_ROOT = Path(__file__).resolve().parents[2]
THEMES_DIR = str(PROJECT_ROOT / "THEMES")
THEME_DIR = Path(THEMES_DIR) / "default"


def _load_svg(filename: str, fallback: str) -> str:
    file_path = THEME_DIR / filename
    try:
        if file_path.exists():
            return file_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"SVG load error for {filename}: {e}")
    return fallback


BATTERY_SVGS_FALLBACK = {
    "alt-battery-1.svg": """<svg>...</svg>""",
    "alt-battery-2.svg": """<svg>...</svg>""",
    "alt-battery-3.svg": """<svg>...</svg>""",
    "alt-battery-4.svg": """<svg>...</svg>""",
    "alt-battery-5.svg": """<svg>...</svg>""",
    "alt-charge-battery.svg": """<svg>...</svg>""",
}

BATTERY_SVGS = {
    name: _load_svg(name, fallback)
    for name, fallback in BATTERY_SVGS_FALLBACK.items()
}


class BatteryWidget(QWidget):
    def __init__(
        self,
        theme_path: str,
        parent=None,
        themes_dir: Optional[str] = None,
        battery_svgs: Optional[Dict[str, str]] = None,
    ):
        super().__init__(parent)
        self.theme_path = theme_path
        self.themes_dir = themes_dir or THEMES_DIR
        self.battery_svgs = dict(battery_svgs) if battery_svgs else dict(BATTERY_SVGS)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.setLayout(layout)

        self.lbl_text = QLabel("--%")
        self.lbl_text.setStyleSheet("font-weight: bold; color: #888;")

        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(24, 24)
        self.lbl_icon.setScaledContents(True)

        layout.addWidget(self.lbl_text)
        layout.addWidget(self.lbl_icon)

        self.update_battery(0, is_charging=False, connected=False)

    def update_theme_path(self, new_path):
        self.theme_path = new_path

    def update_battery(self, level: int, is_charging: bool = False, connected: bool = True):
        if not connected:
            self.lbl_text.setText("--%")
            self.lbl_icon.clear()
            return

        self.lbl_text.setText(f"{level}%")

        icon_name = ""
        color = ""

        if is_charging:
            icon_name = "alt-charge-battery.svg"
            color = "#3ecf4c"
        else:
            if level < 20:
                icon_name = "alt-battery-1.svg"
                color = "#ff3333"
            elif 20 <= level < 40:
                icon_name = "alt-battery-2.svg"
                color = "orange"
            elif 40 <= level < 60:
                icon_name = "alt-battery-3.svg"
                color = "#3ecf4c"
            elif 60 <= level < 80:
                icon_name = "alt-battery-4.svg"
                color = "#3ecf4c"
            else:
                icon_name = "alt-battery-5.svg"
                color = "#3ecf4c"

        pixmap = QPixmap()
        loaded = False

        full_path = os.path.join(self.theme_path, "icons", icon_name)
        if not os.path.exists(full_path):
            default_path = os.path.join(self.themes_dir, "default", "icons", icon_name)
            if os.path.exists(default_path):
                full_path = default_path

        if os.path.exists(full_path):
            pixmap.load(full_path)
            loaded = True

        if not loaded and icon_name in self.battery_svgs:
            renderer = QSvgRenderer(QByteArray(self.battery_svgs[icon_name].encode("utf-8")))
            pixmap = QPixmap(24, 24)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            loaded = True

        if loaded and not pixmap.isNull():
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), QColor(color))
            painter.end()
            self.lbl_icon.setPixmap(pixmap)
        else:
            print(f"Battery Icon missing: {icon_name}")
