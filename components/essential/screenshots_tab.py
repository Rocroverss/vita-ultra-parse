import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ScreenshotsTab(QWidget):
    def __init__(self, screenshots_dir: Path):
        super().__init__()
        self.screenshots_dir = Path(screenshots_dir)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        main_layout = QHBoxLayout(self)
        left_panel = QVBoxLayout()

        self.screenshot_list = QListWidget()
        self.screenshot_list.setSelectionMode(QListWidget.SingleSelection)
        self.screenshot_list.currentItemChanged.connect(self.display_selected_image)
        self.screenshot_list.itemDoubleClicked.connect(self.open_selected_file)
        left_panel.addWidget(self.screenshot_list)

        hbox = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh List")
        self.btn_refresh.clicked.connect(self.refresh_list)
        hbox.addWidget(self.btn_refresh)

        self.btn_open_folder = QPushButton("Open Folder")
        self.btn_open_folder.clicked.connect(self.open_folder)
        hbox.addWidget(self.btn_open_folder)

        self.btn_open_selected = QPushButton("Open Selected")
        self.btn_open_selected.clicked.connect(self.open_selected_file)
        hbox.addWidget(self.btn_open_selected)

        self.btn_delete_selected = QPushButton("Delete Selected")
        self.btn_delete_selected.setStyleSheet("background-color: #8B0000;")
        self.btn_delete_selected.clicked.connect(self.delete_selected_file)
        hbox.addWidget(self.btn_delete_selected)

        left_panel.addLayout(hbox)
        main_layout.addLayout(left_panel, 2)

        self.image_display = QLabel("Select a screenshot to view it here.")
        self.image_display.setAlignment(Qt.AlignCenter)
        self.image_display.setStyleSheet("border: 1px solid #333;")
        self.image_display.setMinimumSize(200, 200)

        right_panel = QVBoxLayout()
        right_panel.addWidget(self.image_display)
        right_panel.addStretch()
        main_layout.addLayout(right_panel, 3)

        self.image_display.installEventFilter(self)
        self.refresh_list()

    def eventFilter(self, source, event):
        if source == self.image_display and event.type() == QEvent.Type.Resize:
            self.display_selected_image(self.screenshot_list.currentItem(), None)
        return super().eventFilter(source, event)

    def _get_selected_path(self) -> Optional[Path]:
        selected_items = self.screenshot_list.selectedItems()
        if not selected_items:
            return None
        filename = selected_items[0].text()
        return self.screenshots_dir / filename

    @Slot(QListWidgetItem, QListWidgetItem)
    def display_selected_image(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current is None or current.text() == "No screenshots found.":
            self.image_display.clear()
            self.image_display.setText("Select a screenshot to view it here.")
            return

        file_path = self.screenshots_dir / current.text()
        if file_path.is_file():
            pixmap = QPixmap(str(file_path))
            if pixmap.isNull():
                self.image_display.setText(f"Could not load image file: {file_path.name}")
                return

            scaled_pixmap = pixmap.scaled(
                self.image_display.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.image_display.setPixmap(scaled_pixmap)
            self.image_display.setAlignment(Qt.AlignCenter)
        else:
            self.image_display.clear()
            self.image_display.setText("File not found.")

    @Slot()
    def refresh_list(self):
        self.screenshot_list.clear()
        files = sorted(
            [f for f in self.screenshots_dir.iterdir() if f.is_file()],
            key=os.path.getmtime,
            reverse=True,
        )

        if not files:
            self.screenshot_list.addItem("No screenshots found.")
            self.image_display.clear()
            self.image_display.setText("Select a screenshot to view it here.")
            return

        for file_path in files:
            self.screenshot_list.addItem(file_path.name)

        if self.screenshot_list.count() > 0 and self.screenshot_list.item(0).text() != "No screenshots found.":
            self.screenshot_list.setCurrentRow(0)

    @Slot()
    def open_folder(self):
        url = QUrl.fromLocalFile(str(self.screenshots_dir))
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                self,
                "Open Folder Error",
                f"Could not open folder: {self.screenshots_dir.resolve()}.",
            )

    @Slot()
    def open_selected_file(self):
        file_path = self._get_selected_path()
        if not file_path:
            if self.screenshot_list.count() == 1 and self.screenshot_list.item(0).text() == "No screenshots found.":
                QMessageBox.information(self, "Selection Info", "No screenshots to open.")
            else:
                QMessageBox.warning(self, "Selection Error", "Please select a screenshot file first.")
            return

        url = QUrl.fromLocalFile(str(file_path))
        if not QDesktopServices.openUrl(url):
            QMessageBox.critical(self, "Open File Error", f"Could not open file: {file_path.name}")

    @Slot()
    def delete_selected_file(self):
        file_path = self._get_selected_path()
        if not file_path:
            QMessageBox.warning(self, "Selection Error", "Please select a screenshot file to delete.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to permanently delete '{file_path.name}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.No:
            return

        try:
            os.remove(file_path)
            self.refresh_list()
            QMessageBox.information(
                self, "Delete Success", f"Screenshot '{file_path.name}' deleted."
            )
        except Exception as e:
            QMessageBox.critical(self, "Delete Error", f"Failed to delete file: {e}")
