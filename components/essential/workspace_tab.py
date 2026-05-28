from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class WorkspaceTab(QWidget):
    workspace_changed = Signal()

    def __init__(self, settings_instance):
        super().__init__()
        self.settings = settings_instance

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)

        self.current_label = QLabel(
            f"<b>Current Workspace:</b> {self.settings.get_current_workspace_name()}"
        )
        self.current_label.setFont(QFont("Arial", 12))
        layout.addWidget(self.current_label)
        layout.addSpacing(10)

        list_grp = QGroupBox("Available Workspaces")
        list_layout = QVBoxLayout(list_grp)

        self.workspace_list = QListWidget()
        self.workspace_list.setMinimumHeight(200)
        self.workspace_list.setStyleSheet(
            "background-color: #2d2d2d; border-radius: 4px; padding: 4px;"
        )
        self.workspace_list.itemDoubleClicked.connect(self.load_selected)
        list_layout.addWidget(self.workspace_list)

        hbox_actions = QHBoxLayout()
        self.btn_load = QPushButton("Load Selected")
        self.btn_load.clicked.connect(self.load_selected)
        hbox_actions.addWidget(self.btn_load)

        self.btn_delete = QPushButton("Delete Selected")
        self.btn_delete.setStyleSheet("background-color: #8B0000;")
        self.btn_delete.clicked.connect(self.delete_selected)
        hbox_actions.addWidget(self.btn_delete)

        list_layout.addLayout(hbox_actions)
        layout.addWidget(list_grp)
        layout.addSpacing(10)

        create_grp = QGroupBox("Create New Workspace")
        create_layout = QVBoxLayout(create_grp)

        self.btn_create = QPushButton("Create Workspace from Current Settings")
        self.btn_create.clicked.connect(self.create_new)
        create_layout.addWidget(self.btn_create)

        layout.addWidget(create_grp)
        layout.addStretch()

        self.refresh_list()

    @Slot()
    def refresh_list(self):
        self.workspace_list.clear()
        current_name = self.settings.get_current_workspace_name()
        try:
            workspaces = self.settings.get_workspaces()
        except AttributeError:
            workspaces = [getattr(self.settings, "DEFAULT_WORKSPACE_NAME", "Default")]

        for name in workspaces:
            item = QListWidgetItem(name)
            if name == current_name:
                item.setFont(QFont("Arial", 10, QFont.Bold))
                item.setText(f"{name} (ACTIVE)")
                item.setForeground(QColor("#3ecf4c"))
            self.workspace_list.addItem(item)

        self.current_label.setText(f"<b>Current Workspace:</b> {current_name}")

    @Slot()
    def load_selected(self):
        items = self.workspace_list.selectedItems()
        if not items:
            QMessageBox.warning(self, "Load Error", "Please select a workspace.")
            return

        name = items[0].text().replace(" (ACTIVE)", "")
        if name == self.settings.get_current_workspace_name():
            QMessageBox.information(
                self, "Load Info", f"Workspace '{name}' is already active."
            )
            return

        if self.settings.load_workspace(name):
            self.refresh_list()
            self.workspace_changed.emit()
            QMessageBox.information(
                self, "Load Success", f"Workspace '{name}' loaded successfully."
            )
        else:
            QMessageBox.critical(
                self, "Load Error", f"Could not load workspace '{name}'."
            )

    @Slot()
    def delete_selected(self):
        items = self.workspace_list.selectedItems()
        if not items:
            QMessageBox.warning(
                self, "Delete Error", "Please select a workspace to delete."
            )
            return

        name = items[0].text().replace(" (ACTIVE)", "")

        if name == getattr(self.settings, "DEFAULT_WORKSPACE_NAME", "Default"):
            QMessageBox.critical(
                self, "Delete Error", "Cannot delete the default workspace."
            )
            return

        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to permanently delete workspace '{name}'? This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.No:
            return

        if self.settings.delete_workspace(name):
            self.refresh_list()
            self.workspace_changed.emit()
            QMessageBox.information(
                self, "Delete Success", f"Workspace '{name}' deleted."
            )
        else:
            QMessageBox.critical(
                self, "Delete Error", f"Could not delete workspace '{name}'."
            )

    @Slot()
    def create_new(self):
        name, ok = QInputDialog.getText(
            self,
            "Create New Workspace",
            "Enter a name for the new workspace (based on current settings):",
            QLineEdit.Normal,
            "New Project",
        )
        if not ok or not name:
            return

        name = name.strip()
        if self.settings.create_workspace(name):
            self.refresh_list()
            self.workspace_changed.emit()
            QMessageBox.information(
                self,
                "Create Success",
                f"Workspace '{name}' created and set as active.",
            )
        else:
            QMessageBox.warning(
                self,
                "Create Error",
                f"Workspace name '{name}' already exists or is invalid.",
            )
