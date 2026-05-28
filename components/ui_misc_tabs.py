import os
import re
import socket
import threading
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QEvent, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIntValidator, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ColorDot(QWidget):
    """Small colored circle widget."""

    def __init__(self, color="#777", size=10):
        super().__init__()
        self._color = QColor(color)
        self._size = size
        self.setFixedSize(size, size)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self._color)
        painter.setPen(Qt.NoPen)
        rect = self.rect()
        diameter = min(rect.width(), rect.height()) * 0.8
        painter.drawEllipse(
            rect.center().x() - diameter / 2,
            rect.center().y() - diameter / 2,
            diameter,
            diameter,
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


class SettingsTab(QWidget):
    restart_log_server_signal = Signal(int)
    apply_style_signal = Signal()
    theme_changed = Signal(str)
    opacity_changed = Signal(float)
    component_toggles_changed = Signal(dict)
    component_config_changed = Signal(dict, list)

    COMPONENT_LABELS = {
        "workspace": "Workspace",
        "help": "Help",
        "logging": "Logging",
        "core_dump": "Core Dump",
        "razor": "Razor",
        "profiling": "Profiling",
        "android": "Android",
        "screenshots": "Screenshots",
        "build": "Build",
        "sdk": "SDK",
        "file_transfer": "File Transfer",
    }

    def __init__(self, settings_instance, themes_dir: str, component_defaults: Dict[str, bool]):
        super().__init__()
        self.settings = settings_instance
        self.themes_dir = themes_dir
        self.component_defaults = dict(component_defaults)
        self._loading_components = False

        root_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_container = QWidget()
        layout = QVBoxLayout(scroll_container)
        layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(scroll_container)
        root_layout.addWidget(scroll)

        grp_sdk = QGroupBox("VitaSDK & Build Configuration")
        lay_sdk = QVBoxLayout(grp_sdk)

        lay_sdk.addWidget(QLabel("VitaSDK Path:"))
        hbox_sdk = QHBoxLayout()
        self.sdk_input = QLineEdit()
        self.btn_sdk = QPushButton("Browse SDK Root")
        self.btn_sdk.clicked.connect(
            lambda: self.browse_folder(self.sdk_input, "sdk_path", is_file=False)
        )
        hbox_sdk.addWidget(self.sdk_input)
        hbox_sdk.addWidget(self.btn_sdk)
        lay_sdk.addLayout(hbox_sdk)

        lay_sdk.addWidget(QLabel("Default Build Folder:"))
        hbox_build = QHBoxLayout()
        self.build_input = QLineEdit()
        self.btn_build = QPushButton("Browse Build Folder")
        self.btn_build.clicked.connect(
            lambda: self.browse_folder(self.build_input, "last_build_dir", is_file=False)
        )
        hbox_build.addWidget(self.build_input)
        hbox_build.addWidget(self.btn_build)
        lay_sdk.addLayout(hbox_build)

        self.sdk_input.textChanged.connect(lambda t: self.settings.set("sdk_path", t))
        self.build_input.textChanged.connect(
            lambda t: self.settings.set("last_build_dir", t)
        )
        layout.addWidget(grp_sdk)

        grp_log = QGroupBox("Logging Server Configuration")
        lay_log = QVBoxLayout(grp_log)

        lay_log.addWidget(QLabel("Log Server Port (Requires Restart):"))
        hbox_port = QHBoxLayout()
        self.log_port_input = QLineEdit()
        self.log_port_input.setValidator(QIntValidator(1024, 65535))
        btn_port = QPushButton("Apply Port & Restart Server")
        btn_port.clicked.connect(self.apply_port_and_restart)
        hbox_port.addWidget(self.log_port_input)
        hbox_port.addWidget(btn_port)
        lay_log.addLayout(hbox_port)

        self.log_port_input.textChanged.connect(self.update_log_port_setting)
        layout.addWidget(grp_log)

        grp_appearance = QGroupBox("Log/Terminal Appearance")
        lay_appearance = QVBoxLayout(grp_appearance)

        lay_appearance.addWidget(QLabel("Log Output Font Size (pt):"))
        hbox_font = QHBoxLayout()
        self.font_size_spinbox = QSpinBox()
        self.font_size_spinbox.setRange(8, 30)
        self.font_size_spinbox.valueChanged.connect(
            lambda v: self.settings.set("log_font_size", v)
        )
        btn_apply_font = QPushButton("Apply Style Changes")
        btn_apply_font.clicked.connect(self.apply_style_signal.emit)
        hbox_font.addWidget(self.font_size_spinbox)
        hbox_font.addWidget(btn_apply_font)
        lay_appearance.addLayout(hbox_font)

        layout.addWidget(grp_appearance)

        grp_window = QGroupBox("Window Appearance")
        lay_window = QVBoxLayout(grp_window)
        lay_window.addWidget(QLabel("Window Opacity:"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setSingleStep(1)
        self.opacity_slider.setPageStep(10)
        self.opacity_slider.setTickInterval(10)
        self.opacity_slider.setTickPosition(QSlider.TicksBelow)

        hbox_opacity = QHBoxLayout()
        self.opacity_label = QLabel("100%")
        hbox_opacity.addWidget(QLabel("10%"))
        hbox_opacity.addWidget(self.opacity_slider)
        hbox_opacity.addWidget(QLabel("100%"))

        lay_window.addLayout(hbox_opacity)
        lay_window.addWidget(self.opacity_label, alignment=Qt.AlignCenter)
        self.opacity_slider.valueChanged.connect(self.on_opacity_changed)
        layout.addWidget(grp_window)

        grp_theme = QGroupBox("Theme")
        lay_theme = QVBoxLayout(grp_theme)
        lay_theme.addWidget(QLabel("Select UI Theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(self.discover_themes())

        current_theme_name = self.settings.get("theme_name", "default")
        idx = self.theme_combo.findText(current_theme_name)
        if idx != -1:
            self.theme_combo.setCurrentIndex(idx)

        self.theme_combo.currentTextChanged.connect(self.on_theme_changed)
        lay_theme.addWidget(self.theme_combo)
        layout.addWidget(grp_theme)

        grp_components = QGroupBox("Component Loading")
        lay_components = QVBoxLayout(grp_components)
        lay_components.addWidget(
            QLabel("Click-hold and drag to reorder components. Check/uncheck to enable or disable.")
        )

        self.component_list = QListWidget()
        self.component_list.setSelectionMode(QListWidget.SingleSelection)
        self.component_list.setDragDropMode(QListWidget.InternalMove)
        self.component_list.setDefaultDropAction(Qt.MoveAction)
        self.component_list.setDragEnabled(True)
        self.component_list.setAcceptDrops(True)
        self.component_list.viewport().setAcceptDrops(True)
        self.component_list.setDropIndicatorShown(True)
        self.component_list.itemChanged.connect(self._persist_component_config)
        self.component_list.model().rowsMoved.connect(self._persist_component_config)
        lay_components.addWidget(self.component_list)

        layout.addWidget(grp_components)
        layout.addStretch()
        self.set_settings_values()

    def _normalized_component_toggles(self) -> Dict[str, bool]:
        raw = self.settings.get("component_toggles", {})
        if not isinstance(raw, dict):
            raw = {}
        return {
            key: bool(raw.get(key, default))
            for key, default in self.component_defaults.items()
        }

    def _normalized_component_order(self) -> list:
        raw = self.settings.get("component_order", [])
        if not isinstance(raw, list):
            raw = []
        seen = set()
        ordered = []
        for key in raw:
            if key in self.component_defaults and key not in seen:
                ordered.append(key)
                seen.add(key)
        for key in self.component_defaults:
            if key not in seen:
                ordered.append(key)
        return ordered

    def _persist_component_config(self, *args):
        if self._loading_components:
            return
        toggles = {}
        order = []
        for i in range(self.component_list.count()):
            item = self.component_list.item(i)
            key = item.data(Qt.UserRole)
            if not key:
                continue
            order.append(key)
            toggles[key] = item.checkState() == Qt.Checked
        self.settings.set("component_toggles", toggles)
        self.settings.set("component_order", order)
        self.component_toggles_changed.emit(toggles)
        self.component_config_changed.emit(toggles, order)

    def discover_themes(self):
        themes = []
        if os.path.isdir(self.themes_dir):
            for entry in sorted(os.listdir(self.themes_dir)):
                full = os.path.join(self.themes_dir, entry)
                if os.path.isdir(full):
                    themes.append(entry)
        if not themes:
            themes = ["default"]
        return themes

    def on_theme_changed(self, name: str):
        self.settings.set("theme_name", name)
        self.theme_changed.emit(name)

    def update_log_port_setting(self, text):
        try:
            port = int(text)
            self.settings.set("log_port", port)
        except ValueError:
            pass

    def browse_folder(self, line_edit, setting_key, is_file=False):
        current_path = self.settings.get(setting_key, os.getcwd())
        if is_file:
            d, _ = QFileDialog.getOpenFileName(self, "Select File", current_path)
        else:
            d = QFileDialog.getExistingDirectory(self, "Select Folder", current_path)
        if d:
            line_edit.setText(d)
            self.settings.set(setting_key, d)

    @Slot(int)
    def on_opacity_changed(self, value):
        self.opacity_label.setText(f"{value}%")
        float_opacity = value / 100.0
        self.settings.set("window_opacity", float_opacity)
        self.opacity_changed.emit(float_opacity)

    def set_settings_values(self):
        self.sdk_input.setText(self.settings.get("sdk_path", ""))
        self.build_input.setText(self.settings.get("last_build_dir", os.getcwd()))
        current_port = self.settings.get("log_port", 8080)
        self.log_port_input.blockSignals(True)
        self.log_port_input.setText(str(current_port))
        self.log_port_input.blockSignals(False)
        self.font_size_spinbox.setValue(self.settings.get("log_font_size", 13))

        theme_name = self.settings.get("theme_name", "default")
        idx = self.theme_combo.findText(theme_name)
        if idx != -1:
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(idx)
            self.theme_combo.blockSignals(False)

        current_opacity = self.settings.get("window_opacity", 1.0)
        slider_value = int(current_opacity * 100)
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(slider_value)
        self.opacity_slider.blockSignals(False)
        self.opacity_label.setText(f"{slider_value}%")
        self.on_opacity_changed(slider_value)

        toggles = self._normalized_component_toggles()
        order = self._normalized_component_order()
        self._loading_components = True
        self.component_list.clear()
        for key in order:
            label = self.COMPONENT_LABELS.get(key, key.replace("_", " ").title())
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            item.setFlags(
                Qt.ItemIsEnabled
                | Qt.ItemIsSelectable
                | Qt.ItemIsDragEnabled
                | Qt.ItemIsUserCheckable
            )
            item.setCheckState(Qt.Checked if toggles.get(key, True) else Qt.Unchecked)
            self.component_list.addItem(item)
        self._loading_components = False

    def apply_port_and_restart(self):
        try:
            port = int(self.log_port_input.text())
        except ValueError:
            QMessageBox.critical(self, "Input Error", "Invalid port number.")
            return

        if port < 1024 or port > 65535:
            QMessageBox.warning(
                self, "Port Error", "Port must be between 1024 and 65535."
            )
            return

        self.settings.set("log_port", port)
        self.restart_log_server_signal.emit(port)


class CommandWorker(QThread):
    command_output_signal = Signal(str, str)
    battery_signal = Signal(int, bool)

    def __init__(self, settings_instance):
        super().__init__()
        self.settings = settings_instance
        self.host = self.settings.get("vita_ip", "192.168.1.100")
        self.port = 1338
        self.command_queue = []
        self.running = True
        self.mutex = threading.Lock()

    def add_command(self, cmd_string):
        with self.mutex:
            self.command_queue.append(cmd_string)

    def set_host(self, host):
        self.host = host

    def run(self):
        while self.running:
            if self.command_queue:
                with self.mutex:
                    command = self.command_queue.pop(0)
                self._do_send_command(command)
            self.msleep(100)

    def _do_send_command(self, command):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                if command != "battery":
                    self.command_output_signal.emit(
                        f"Attempting to send command: '{command}'", "orange"
                    )

                s.connect((self.host, self.port))
                s.sendall(f"{command}\n".encode("utf-8"))
                response = s.recv(1024).decode("utf-8", errors="ignore").strip()

                if command == "battery":
                    match = re.search(r"Battery:\s*(\d+)%\s*\((.*)\)", response)
                    if match:
                        level = int(match.group(1))
                        status_text = match.group(2).lower()
                        is_charging = "not charging" not in status_text
                        self.battery_signal.emit(level, is_charging)
                    return

                self.command_output_signal.emit(
                    f"Cmd: {command} -> {response}", "#3ecf4c"
                )
        except Exception as e:
            if command != "battery":
                self.command_output_signal.emit(f"Cmd Error: {e}", "red")

    def stop(self):
        self.running = False
        self.wait()


class RazorTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        label = QLabel("Razor: Functionality to be implemented in the future.")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        layout.addStretch()


class ProfilingTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        label = QLabel("Profiling: Functionality to be implemented in the future.")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        layout.addStretch()


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
