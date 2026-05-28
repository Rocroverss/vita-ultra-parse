from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


COMPONENT_KEY = "example1"
COMPONENT_LABEL = "Example 1"


class Example1Tab(QWidget):
    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.settings = settings

        layout = QVBoxLayout(self)
        self.title = QLabel("Custom component loaded: Example 1")
        self.workspace_label = QLabel("")
        refresh_btn = QPushButton("Refresh Workspace Name")
        refresh_btn.clicked.connect(self.refresh_workspace_name)

        layout.addWidget(self.title)
        layout.addWidget(self.workspace_label)
        layout.addWidget(refresh_btn)
        layout.addStretch()

        self.refresh_workspace_name()

    def refresh_workspace_name(self):
        if self.settings and hasattr(self.settings, "get_current_workspace_name"):
            name = self.settings.get_current_workspace_name()
        else:
            name = "Unknown"
        self.workspace_label.setText(f"Active workspace: {name}")

    def sync_with_settings(self):
        self.refresh_workspace_name()


def create_component(settings=None, parent=None):
    return Example1Tab(settings=settings, parent=parent)
