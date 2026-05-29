from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

try:
    from utils import settings
except Exception:
    settings = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
THEMES_DIR = PROJECT_ROOT / "THEMES"


def _load_theme_foreground() -> QColor:
    theme_name = "default"
    if settings is not None and hasattr(settings, "get"):
        try:
            theme_name = settings.get("theme_name", "default")
        except Exception:
            theme_name = "default"

    for candidate_theme in (theme_name, "default"):
        theme_file = THEMES_DIR / candidate_theme / "theme.txt"
        if not theme_file.exists():
            continue
        try:
            for raw_line in theme_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() != "foreground":
                    continue
                color = QColor(value.strip())
                if color.isValid():
                    return color
        except Exception:
            continue

    app = QApplication.instance()
    if app is not None:
        palette_color = app.palette().buttonText().color()
        if palette_color.isValid():
            return palette_color

    return QColor("#dcdcdc")


def _render_svg_to_pixmap(renderer: QSvgRenderer, size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def _tint_pixmap(pixmap: QPixmap, color: QColor) -> QPixmap:
    if pixmap.isNull() or not color.isValid():
        return pixmap

    tinted = QPixmap(pixmap.size())
    tinted.fill(Qt.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), color)
    painter.end()
    return tinted


def themed_svg_icon_from_path(path: str, size: int = 20) -> QIcon:
    if not path or not Path(path).exists():
        return QIcon()
    renderer = QSvgRenderer(str(path))
    base_pixmap = _render_svg_to_pixmap(renderer, size)
    return QIcon(_tint_pixmap(base_pixmap, _load_theme_foreground()))


def themed_svg_icon_from_content(svg_content: str, size: int = 20) -> QIcon:
    if not svg_content:
        return QIcon()
    renderer = QSvgRenderer(QByteArray(svg_content.encode("utf-8")))
    base_pixmap = _render_svg_to_pixmap(renderer, size)
    return QIcon(_tint_pixmap(base_pixmap, _load_theme_foreground()))


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
        return themed_svg_icon_from_path(str(path), size=size)

    return QIcon()
