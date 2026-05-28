from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class ColorDot(QWidget):
    """Small colored circle widget."""

    def __init__(self, color="#777", size=10):
        super().__init__()
        self._color = QColor(color)
        self._size = size
        self.setFixedSize(size, size)

    def sizeHint(self):
        return QSize(self._size, self._size)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self._color)
        painter.setPen(Qt.NoPen)
        diameter = max(2.0, min(self.width(), self.height()) - 2.0)
        x = (self.width() - diameter) / 2.0
        y = (self.height() - diameter) / 2.0
        painter.drawEllipse(x, y, diameter, diameter)
