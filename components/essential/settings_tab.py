import os
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from utils import normalize_path_for_storage
from .theme import Theme


class SettingsTab(QWidget):
    restart_log_server_signal = Signal(int)
    apply_style_signal = Signal()
    theme_changed = Signal(str)
    opacity_changed = Signal(float)
    background_image_opacity_changed = Signal(float)
    background_mode_changed = Signal(str)
    ui_elements_opacity_changed = Signal(float)
    background_image_path_changed = Signal(str)
    component_toggles_changed = Signal(dict)
    component_config_changed = Signal(dict, list)
    build_directory_change_requested = Signal(str)

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

    def __init__(
        self,
        settings_instance,
        themes_dir: str,
        component_defaults: Dict[str, bool],
        component_labels: Optional[Dict[str, str]] = None,
    ):
        super().__init__()
        self.settings = settings_instance
        self.themes_dir = themes_dir
        self.component_defaults = dict(component_defaults)
        self.component_labels = dict(self.COMPONENT_LABELS)
        if component_labels:
            self.component_labels.update(component_labels)
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
        self.build_input.editingFinished.connect(self._commit_build_directory_from_input)
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

        lay_window.addWidget(QLabel("Background Image Opacity:"))
        self.bg_opacity_slider = QSlider(Qt.Horizontal)
        self.bg_opacity_slider.setRange(0, 100)
        self.bg_opacity_slider.setSingleStep(1)
        self.bg_opacity_slider.setPageStep(10)
        self.bg_opacity_slider.setTickInterval(10)
        self.bg_opacity_slider.setTickPosition(QSlider.TicksBelow)

        hbox_bg_opacity = QHBoxLayout()
        self.bg_opacity_label = QLabel("100%")
        hbox_bg_opacity.addWidget(QLabel("0%"))
        hbox_bg_opacity.addWidget(self.bg_opacity_slider)
        hbox_bg_opacity.addWidget(QLabel("100%"))
        lay_window.addLayout(hbox_bg_opacity)
        lay_window.addWidget(self.bg_opacity_label, alignment=Qt.AlignCenter)
        self.bg_opacity_slider.valueChanged.connect(self.on_background_image_opacity_changed)

        lay_window.addWidget(QLabel("Background Image Mode:"))
        self.bg_mode_combo = QComboBox()
        self.bg_mode_combo.addItem("Keep Perspective", "keep")
        self.bg_mode_combo.addItem("Cut (Fill)", "cut")
        self.bg_mode_combo.addItem("Stretch", "stretch")
        self.bg_mode_combo.currentIndexChanged.connect(self.on_background_mode_changed)
        lay_window.addWidget(self.bg_mode_combo)

        lay_window.addWidget(QLabel("Custom Background Image:"))
        self.custom_background_label = QLabel()
        self.custom_background_label.setWordWrap(True)
        lay_window.addWidget(self.custom_background_label)

        bg_image_buttons = QHBoxLayout()
        self.btn_custom_background = QPushButton("Choose Background Image")
        self.btn_custom_background.clicked.connect(self.browse_custom_background_image)
        bg_image_buttons.addWidget(self.btn_custom_background)
        self.btn_clear_custom_background = QPushButton("Use Theme Background")
        self.btn_clear_custom_background.clicked.connect(self.clear_custom_background_image)
        bg_image_buttons.addWidget(self.btn_clear_custom_background)
        lay_window.addLayout(bg_image_buttons)

        lay_window.addWidget(QLabel("GUI Elements Opacity:"))
        self.ui_opacity_slider = QSlider(Qt.Horizontal)
        self.ui_opacity_slider.setRange(10, 100)
        self.ui_opacity_slider.setSingleStep(1)
        self.ui_opacity_slider.setPageStep(10)
        self.ui_opacity_slider.setTickInterval(10)
        self.ui_opacity_slider.setTickPosition(QSlider.TicksBelow)

        hbox_ui_opacity = QHBoxLayout()
        self.ui_opacity_label = QLabel("100%")
        hbox_ui_opacity.addWidget(QLabel("10%"))
        hbox_ui_opacity.addWidget(self.ui_opacity_slider)
        hbox_ui_opacity.addWidget(QLabel("100%"))
        lay_window.addLayout(hbox_ui_opacity)
        lay_window.addWidget(self.ui_opacity_label, alignment=Qt.AlignCenter)
        self.ui_opacity_slider.valueChanged.connect(self.on_ui_elements_opacity_changed)
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
        self.component_list.setMinimumHeight(400)
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

    def _theme_defaults(self) -> Dict[str, object]:
        theme_name = self.theme_combo.currentText().strip() or self.settings.get("theme_name", "default") or "default"
        theme_path = Path(self.themes_dir) / theme_name
        theme = Theme(theme_name, theme_path, {})

        mode_map = {
            "scale": "stretch",
            "stretch": "stretch",
            "cut": "cut",
            "cover": "cut",
            "keep": "keep",
            "contain": "keep",
            "none": "keep",
        }
        mode = mode_map.get(str(getattr(theme, "aspect_ratio_mode", "keep")).lower().strip(), "keep")

        theme_image_path = ""
        image_location = str(getattr(theme, "image_location", "none")).strip()
        if image_location and image_location.lower() != "none":
            candidate = theme_path / image_location
            if candidate.is_file():
                theme_image_path = str(candidate)

        try:
            window_opacity = float(getattr(theme, "opacity", 1.0))
        except (TypeError, ValueError):
            window_opacity = 1.0
        try:
            image_opacity = float(getattr(theme, "image_opacity", 1.0))
        except (TypeError, ValueError):
            image_opacity = 1.0
        try:
            ui_opacity = float(getattr(theme, "ui_elements_opacity", 1.0))
        except (TypeError, ValueError):
            ui_opacity = 1.0

        return {
            "window_opacity": max(0.0, min(1.0, window_opacity)),
            "background_image_opacity": max(0.0, min(1.0, image_opacity)),
            "background_aspect_mode": mode,
            "ui_elements_opacity": max(0.1, min(1.0, ui_opacity)),
            "theme_image_path": theme_image_path,
        }

    def _refresh_appearance_controls(self):
        theme_defaults = self._theme_defaults()

        raw_window_opacity = self.settings.get("window_opacity", None)
        try:
            current_opacity = float(raw_window_opacity)
        except (TypeError, ValueError):
            current_opacity = float(theme_defaults["window_opacity"])
        slider_value = int(max(0.0, min(1.0, current_opacity)) * 100)
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(slider_value)
        self.opacity_slider.blockSignals(False)
        self.opacity_label.setText(f"{slider_value}%")

        raw_bg_opacity = self.settings.get("background_image_opacity", None)
        try:
            current_bg_opacity = float(raw_bg_opacity)
        except (TypeError, ValueError):
            current_bg_opacity = float(theme_defaults["background_image_opacity"])
        bg_slider_value = int(max(0.0, min(1.0, current_bg_opacity)) * 100)
        self.bg_opacity_slider.blockSignals(True)
        self.bg_opacity_slider.setValue(bg_slider_value)
        self.bg_opacity_slider.blockSignals(False)
        self.bg_opacity_label.setText(f"{bg_slider_value}%")

        current_bg_mode = str(self.settings.get("background_aspect_mode", "") or "").lower().strip()
        if not current_bg_mode:
            current_bg_mode = str(theme_defaults["background_aspect_mode"])
        idx_mode = self.bg_mode_combo.findData(current_bg_mode)
        if idx_mode < 0:
            idx_mode = 0
        self.bg_mode_combo.blockSignals(True)
        self.bg_mode_combo.setCurrentIndex(idx_mode)
        self.bg_mode_combo.blockSignals(False)

        raw_ui_opacity = self.settings.get("ui_elements_opacity", None)
        try:
            current_ui_opacity = float(raw_ui_opacity)
        except (TypeError, ValueError):
            current_ui_opacity = float(theme_defaults["ui_elements_opacity"])
        ui_slider_value = int(max(0.1, min(1.0, current_ui_opacity)) * 100)
        self.ui_opacity_slider.blockSignals(True)
        self.ui_opacity_slider.setValue(ui_slider_value)
        self.ui_opacity_slider.blockSignals(False)
        self.ui_opacity_label.setText(f"{ui_slider_value}%")

        custom_background = normalize_path_for_storage(self.settings.get("custom_background_image", ""))
        theme_background = str(theme_defaults.get("theme_image_path", ""))
        if custom_background and os.path.isfile(custom_background):
            self.custom_background_label.setText(f"Custom background:\n{custom_background}")
        elif custom_background:
            if theme_background:
                self.custom_background_label.setText(
                    "Saved custom background is missing.\n"
                    f"Using theme background:\n{theme_background}"
                )
            else:
                self.custom_background_label.setText(
                    "Saved custom background is missing.\nNo theme background image is configured."
                )
        elif theme_background:
            self.custom_background_label.setText(f"Using theme background:\n{theme_background}")
        else:
            self.custom_background_label.setText("No background image configured.")
        self.btn_clear_custom_background.setEnabled(bool(custom_background))

    def on_theme_changed(self, name: str):
        self.settings.set("theme_name", name)
        self.theme_changed.emit(name)
        self._refresh_appearance_controls()

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
            if setting_key == "last_build_dir":
                self._request_build_directory_change(d)
            else:
                line_edit.setText(d)
                self.settings.set(setting_key, d)

    def _request_build_directory_change(self, new_path: str):
        normalized_path = normalize_path_for_storage(new_path)
        self.set_build_directory_value(normalized_path)
        self.build_directory_change_requested.emit(normalized_path)

    def _commit_build_directory_from_input(self):
        self._request_build_directory_change(self.build_input.text())

    def set_build_directory_value(self, value: str):
        normalized_value = normalize_path_for_storage(value)
        if self.build_input.text() == normalized_value:
            return
        self.build_input.blockSignals(True)
        self.build_input.setText(normalized_value)
        self.build_input.blockSignals(False)

    def browse_custom_background_image(self):
        start_path = self.settings.get("custom_background_image", "") or self.settings.get("dump_folder", os.getcwd())
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Background Image",
            start_path,
            "Image Files (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)",
        )
        if not filename:
            return

        normalized_path = normalize_path_for_storage(filename)
        self.settings.set("custom_background_image", normalized_path)
        self._refresh_appearance_controls()
        self.background_image_path_changed.emit(normalized_path)

    def clear_custom_background_image(self):
        self.settings.set("custom_background_image", "")
        self._refresh_appearance_controls()
        self.background_image_path_changed.emit("")

    @Slot(int)
    def on_opacity_changed(self, value):
        self.opacity_label.setText(f"{value}%")
        float_opacity = value / 100.0
        self.settings.set("window_opacity", float_opacity)
        self.opacity_changed.emit(float_opacity)

    @Slot(int)
    def on_background_image_opacity_changed(self, value):
        self.bg_opacity_label.setText(f"{value}%")
        float_opacity = value / 100.0
        self.settings.set("background_image_opacity", float_opacity)
        self.background_image_opacity_changed.emit(float_opacity)

    @Slot(int)
    def on_ui_elements_opacity_changed(self, value):
        self.ui_opacity_label.setText(f"{value}%")
        float_opacity = value / 100.0
        self.settings.set("ui_elements_opacity", float_opacity)
        self.ui_elements_opacity_changed.emit(float_opacity)

    @Slot(int)
    def on_background_mode_changed(self, _index: int):
        mode = self.bg_mode_combo.currentData()
        if not mode:
            mode = "keep"
        self.settings.set("background_aspect_mode", mode)
        self.background_mode_changed.emit(str(mode))

    def set_settings_values(self):
        self.sdk_input.setText(self.settings.get("sdk_path", ""))
        self.set_build_directory_value(self.settings.get("last_build_dir", os.getcwd()))
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

        self._refresh_appearance_controls()

        toggles = self._normalized_component_toggles()
        order = self._normalized_component_order()
        self._loading_components = True
        self.component_list.clear()
        for key in order:
            label = self.component_labels.get(key, key.replace("_", " ").title())
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
