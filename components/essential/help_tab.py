from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QStyle, QTextEdit, QVBoxLayout, QWidget, QHBoxLayout


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
