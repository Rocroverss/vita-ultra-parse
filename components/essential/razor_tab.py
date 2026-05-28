from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class RazorTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        label = QLabel("Razor: Functionality to be implemented in the future.")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        layout.addStretch()
