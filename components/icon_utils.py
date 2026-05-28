from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

try:
    from utils import settings
except Exception:
    settings = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
THEMES_DIR = PROJECT_ROOT / "THEMES"


def themed_icon(svg_filename: str, size: int = 20) -> QIcon:
    theme_name = "default"
    if settings is not None and hasattr(settings, "get"):
        try:
            theme_name = settings.get("theme_name", "default")
        except Exception:
            theme_name = "default"

    candidates = [
        THEMES_DIR / theme_name / svg_filename,
        THEMES_DIR / "default" / svg_filename,
    ]

    for path in candidates:
        if not path.exists():
            continue
        renderer = QSvgRenderer(str(path))
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)

    return QIcon()
