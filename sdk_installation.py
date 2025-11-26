from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QLabel, QPushButton
from PySide6.QtCore import Qt 

class SdkInstallationTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)
        
        grp = QGroupBox("Vita SDK Installer")
        vbox = QVBoxLayout(grp)
        vbox.addWidget(QLabel("SDK Installation features will be implemented here later."))
        vbox.addWidget(QPushButton("Start SDK Installation (Future Feature)"))
        
        layout.addWidget(grp)
        layout.addStretch()