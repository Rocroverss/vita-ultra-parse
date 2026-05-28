import sys
import shutil
import os
import re
from textwrap import dedent

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QLabel, QPushButton,
    QCheckBox, QHBoxLayout, QRadioButton, QLineEdit,
    QPlainTextEdit, QMessageBox, QFormLayout, QProgressBar,
    QListWidget, QListWidgetItem, QFileDialog, QSizePolicy,
    QFrame, QSplitter, QGridLayout, QApplication
)
from PySide6.QtCore import Qt, QProcess, Signal, Slot, QSize
from PySide6.QtGui import QTextCursor, QIcon, QColor, QTextCharFormat, QFont
from components.icon_utils import themed_icon

# --- COLOR DEFINITIONS (ANSI for Terminal Tools) ---
# NOTE: These colors are used for semantic highlighting within the QPlainTextEdit 
# (terminal log) and are generally intended to be fixed for consistency across themes, 
# mimicking ANSI escape codes. They are not widget styles.
COLOR_RED = "#F14C4C"         # Error
COLOR_YELLOW = "#CCA700"      # Warning
COLOR_GREY = "#CCCCCC"        # Standard text
COLOR_CMD = "#569CD6"         # Commands (Blue for focus/highlight)
COLOR_PROGRESS = "#C586C0"    # Progress
COLOR_SUCCESS = "#23D18B"     # Success
COLOR_CYAN = "#4EC9B0"        # Paths

# ANSI Escape Code Helper
ANSI_ESCAPE = re.compile(r'(\x1B\[[\d;]*[mK])')
ANSI_COLOR_MAP = {
    '30': "#000000", '31': COLOR_RED, '32': COLOR_SUCCESS, '33': COLOR_YELLOW,
    '34': COLOR_CMD, '35': COLOR_PROGRESS, '36': COLOR_CYAN, '37': COLOR_GREY,
    '0': COLOR_GREY
}

# --- Configuration Panel Widgets ---

class SdkConfigPanel(QWidget):
    """Configuration panel for global SDK settings and installation actions."""
    sdk_path_changed = Signal(str)
    
    def __init__(self, workspace_settings: dict, parent=None):
        super().__init__(parent)
        self.workspace_settings = workspace_settings
        self.parent_tab = parent 

        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignTop)

        # SDK Path setting
        path_box = QGroupBox("VitaSDK Installation Path")
        path_layout = QHBoxLayout(path_box)
        
        default_sdk_path = "$HOME/vitasdk"
        
        self.ed_vitasdk_path = QLineEdit(self.workspace_settings.get("sdk_path", default_sdk_path))
        self.ed_vitasdk_path.setPlaceholderText(default_sdk_path + " (default if empty)")
        self.ed_vitasdk_path.editingFinished.connect(self.on_sdk_path_edited)
        
        path_layout.addWidget(QLabel("Path:"))
        path_layout.addWidget(self.ed_vitasdk_path)
        main_layout.addWidget(path_box)

        # SDK Status and Help
        help_box = QGroupBox("SDK Status and Help")
        help_layout = QVBoxLayout(help_box)
        
        help_layout.addWidget(QLabel(
            "VitaSDK is managed through vdpm (Vita Package Manager).\n"
            "Use the buttons below to install, update, or check the status."
        ))
        
        # Status labels
        self.status_sdk_official = QLabel("Official SDK Status: Unknown")
        self.status_sdk_softfp = QLabel("SoftFP SDK Status: Unknown")
        help_layout.addWidget(self.status_sdk_official)
        help_layout.addWidget(self.status_sdk_softfp)
        
        main_layout.addWidget(help_box)

        # SDK Variant for Update
        sdk_mode_box = QGroupBox("SDK Variant for Update")
        sdk_mode_layout = QHBoxLayout(sdk_mode_box)
        self.rad_sdk_normal = QRadioButton("Official (Default 'vitasdk-update')")
        self.rad_sdk_softfp = QRadioButton("SoftFP Fork (Requires 'git pull' + re-install)")
        self.rad_sdk_normal.setChecked(True)
        sdk_mode_layout.addWidget(self.rad_sdk_normal)
        sdk_mode_layout.addWidget(self.rad_sdk_softfp)
        main_layout.addWidget(sdk_mode_box)

        # Buttons for SDK Actions
        btn_layout = QGridLayout()
        self.btn_install_sdk = QPushButton("Install Official SDK")
        self.btn_install_softfp = QPushButton("Install SoftFP SDK")
        self.btn_update = QPushButton("Update Current SDK")
        self.btn_uninstall = QPushButton("Uninstall VitaSDK (rm -rf)")
        
        self.btn_install_sdk.clicked.connect(lambda: self.parent_tab.on_install_sdk(False, self.ed_vitasdk_path.text()))
        self.btn_install_softfp.clicked.connect(lambda: self.parent_tab.on_install_sdk(True, self.ed_vitasdk_path.text()))
        self.btn_update.clicked.connect(lambda: self.parent_tab.on_update_sdk(self.rad_sdk_softfp.isChecked(), self.ed_vitasdk_path.text()))
        self.btn_uninstall.clicked.connect(self.on_uninstall_clicked)
        
        btn_layout.addWidget(self.btn_install_sdk, 0, 0)
        btn_layout.addWidget(self.btn_install_softfp, 0, 1)
        btn_layout.addWidget(self.btn_update, 1, 0)
        btn_layout.addWidget(self.btn_uninstall, 1, 1)
        
        main_layout.addLayout(btn_layout)
        main_layout.addStretch()

    @Slot()
    def on_sdk_path_edited(self):
        path = self.ed_vitasdk_path.text().strip()
        self.sdk_path_changed.emit(path)

    @Slot()
    def on_uninstall_clicked(self):
        vitasdk_path = self.ed_vitasdk_path.text().strip()
        if not vitasdk_path or vitasdk_path in ("$HOME/vitasdk", "/usr/local/vitasdk"):
            msg = f"You are about to permanently delete the VitaSDK installation directory: \n\n'{vitasdk_path}'\n\nThis action cannot be undone. Are you absolutely sure?"
        else:
            msg = f"You are about to permanently delete the custom VitaSDK installation directory: \n\n'{vitasdk_path}'\n\nThis action cannot be undone. Are you absolutely sure?"
            
        reply = QMessageBox.question(self, 'Confirm Uninstall',
            msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            self.parent_tab.on_uninstall_sdk(vitasdk_path)

    def set_buttons_enabled(self, enabled: bool):
        self.btn_install_sdk.setEnabled(enabled)
        self.btn_install_softfp.setEnabled(enabled)
        self.btn_update.setEnabled(enabled)
        self.btn_uninstall.setEnabled(enabled)
        self.ed_vitasdk_path.setEnabled(enabled)


class LibConfigPanel(QWidget):
    """Configuration panel for a single managed library/project."""
    lib_data_changed = Signal()

    def __init__(self, lib_data: dict, parent=None):
        super().__init__(parent)
        self.lib_data = dict(lib_data)
        self.parent_tab = parent 

        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignTop)

        # Path setting
        path_box = QGroupBox("Project Directory")
        path_layout = QHBoxLayout(path_box)
        
        self.ed_path = QLineEdit(self.lib_data.get("path", ""))
        self.ed_path.setPlaceholderText("Browse to your project's main directory")
        self.ed_path.editingFinished.connect(self.on_path_edited)

        self.btn_browse = QPushButton("Browse")
        self.btn_browse.clicked.connect(self.on_browse)

        path_layout.addWidget(self.ed_path, 1)
        path_layout.addWidget(self.btn_browse)
        main_layout.addWidget(path_box)

        # Configuration options (flags)
        config_box = QGroupBox("Compilation Flags")
        config_layout = QFormLayout(config_box)

        self.ed_make_flags = QLineEdit(self.lib_data.get("make_flags", ""))
        self.ed_make_flags.setPlaceholderText("Common make flags (e.g., SOFTFP_ABI=1)")
        self.ed_make_flags.editingFinished.connect(self.on_flags_edited)

        self.chk_debug = QCheckBox("Enable Debug Build")
        self.chk_debug.setChecked(self.lib_data.get("debug_enabled", False))
        self.chk_debug.stateChanged.connect(self.on_debug_toggled)

        self.ed_debug_flags = QLineEdit(self.lib_data.get("debug_flags", "DEBUG=1"))
        self.ed_debug_flags.setPlaceholderText("Debug flags (e.g., DEBUG=1 VGL_DEBUG=1)")
        self.ed_debug_flags.editingFinished.connect(self.on_flags_edited)
        
        self.ed_debug_flags.setEnabled(True) 

        config_layout.addRow("Base Make Flags:", self.ed_make_flags)
        config_layout.addRow(self.chk_debug)
        config_layout.addRow("Debug Override Flags:", self.ed_debug_flags)

        main_layout.addWidget(config_box)
        
        # Build button
        self.btn_build = QPushButton("Build This Project Now")
        self.btn_build.clicked.connect(self.on_build)
        main_layout.addWidget(self.btn_build)

        main_layout.addStretch()

    @Slot()
    def on_browse(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Project Directory", self.lib_data.get("path", os.path.expanduser("~")))
        if dir_path:
            self.lib_data["path"] = dir_path
            self.ed_path.setText(dir_path)
            self.lib_data_changed.emit()

    @Slot()
    def on_path_edited(self):
        self.lib_data["path"] = self.ed_path.text().strip()
        self.lib_data_changed.emit()

    @Slot()
    def on_flags_edited(self):
        self.lib_data["make_flags"] = self.ed_make_flags.text().strip()
        self.lib_data["debug_flags"] = self.ed_debug_flags.text().strip()
        self.lib_data_changed.emit()

    @Slot(int)
    def on_debug_toggled(self, state):
        is_checked = state == Qt.Checked
        self.lib_data["debug_enabled"] = is_checked
        self.lib_data_changed.emit()

    @Slot()
    def on_build(self):
        flags = self.lib_data["make_flags"]
        if self.lib_data.get("debug_enabled"):
            flags = f"{flags} {self.lib_data['debug_flags']}"

        build_config = {
            "path": self.lib_data["path"],
            "flags": flags.strip(),
            "lib_name": os.path.basename(self.lib_data["path"]) or "Library Project"
        }
        self.parent_tab.on_build_library(build_config)

    def set_data(self, lib_data: dict):
        self.lib_data = dict(lib_data)
        self.ed_path.setText(self.lib_data.get("path", ""))
        self.ed_make_flags.setText(self.lib_data.get("make_flags", ""))
        self.chk_debug.setChecked(self.lib_data.get("debug_enabled", False))
        self.ed_debug_flags.setText(self.lib_data.get("debug_flags", "DEBUG=1"))
        self.ed_debug_flags.setEnabled(True)
        
    def get_data(self) -> dict:
        return self.lib_data

    def set_buttons_enabled(self, enabled: bool):
        self.ed_path.setEnabled(enabled)
        self.btn_browse.setEnabled(enabled)
        self.ed_make_flags.setEnabled(enabled)
        self.chk_debug.setEnabled(enabled)
        self.ed_debug_flags.setEnabled(enabled)
        self.btn_build.setEnabled(enabled)


# --- List Item Widget ---

class LibListItemWidget(QWidget):
    """Custom widget for an item in the list of managed libraries."""
    delete_requested = Signal(dict)
    
    def __init__(self, lib_data: dict, parent=None):
        super().__init__(parent)
        self.lib_data = lib_data
        
        # Ensure widget does not draw an opaque background, allowing QListWidget 
        # selection/hover style to show through the entire item.
        self.setAutoFillBackground(False)
        
        h_layout = QHBoxLayout(self)
        # Increased vertical margins (5, 5) to "surround more the buttons" and text
        h_layout.setContentsMargins(5, 5, 5, 5) 
        h_layout.setSpacing(5)

        self.label = QLabel("")
        self.label.setAutoFillBackground(False) # Ensure label is also transparent
        
        # Load the trash icon
        self.btn_delete = QPushButton(themed_icon("alt-trash.svg", 16), "")
        self.btn_delete.setFixedSize(QSize(24, 24))
        self.btn_delete.setIconSize(QSize(16, 16))
        self.btn_delete.setFlat(False) 
        
        # Button style is now fully inherited from the application theme
        
        self.btn_delete.clicked.connect(self.on_delete)
        
        self.update_name(lib_data.get("path", ""))
        
        h_layout.addWidget(self.label, 1) 
        h_layout.addWidget(self.btn_delete)
        
    @Slot()
    def on_delete(self):
        self.delete_requested.emit(self.lib_data)

    def update_name(self, new_path: str):
        lib_name = os.path.basename(new_path) if new_path else "New Project" 
        self.label.setText(lib_name)
        self.btn_delete.setToolTip(f"Remove project '{lib_name}' from manager")

    def apply_theme_icons(self):
        self.btn_delete.setIcon(themed_icon("alt-trash.svg", 16))


# --- Main Sdk Installation Tab ---

class SdkInstallationTab(QWidget):
    sdk_path_changed = Signal(str)
    managed_libraries_changed = Signal(list)

    def __init__(self, workspace_settings: dict, parent=None):
        super().__init__(parent)

        self.process: QProcess | None = None
        self.workspace_settings = workspace_settings 
        
        if 'managed_libraries' not in self.workspace_settings:
            self.workspace_settings['managed_libraries'] = []

        main_layout = QVBoxLayout(self)
        
        # --- Splitter ---
        content_splitter = QSplitter(Qt.Horizontal)
        content_splitter.setHandleWidth(8)
        content_splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 1. Left Panel (List)
        list_widget_container = QWidget()
        list_widget_container.setMinimumWidth(150) 
        list_widget_container.setMaximumWidth(250)
        
        list_vbox = QVBoxLayout(list_widget_container)
        list_vbox.setContentsMargins(0, 0, 0, 0)
        
        self.list_widget = QListWidget()
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        
        # QListWidget style is now fully inherited from the application theme
        
        self.list_widget.currentItemChanged.connect(self.on_list_item_changed)
        list_vbox.addWidget(self.list_widget)
        
        self.btn_add_lib = QPushButton("Add Project")
        self.btn_add_lib.clicked.connect(self.on_add_library)
        
        btn_h_layout = QHBoxLayout()
        btn_h_layout.setContentsMargins(5, 5, 5, 5)
        btn_h_layout.addWidget(self.btn_add_lib)
        list_vbox.addLayout(btn_h_layout)

        content_splitter.addWidget(list_widget_container)

        # 2. Right Panel (Details)
        self.detail_frame = QFrame()
        self.detail_layout = QVBoxLayout(self.detail_frame)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        
        self.sdk_config_panel = SdkConfigPanel(self.workspace_settings, parent=self)
        self.sdk_config_panel.sdk_path_changed.connect(self.on_sdk_path_changed)
        
        initial_lib_data = self.workspace_settings['managed_libraries'][0] if self.workspace_settings['managed_libraries'] else {"path":""}
        self.lib_config_panel = LibConfigPanel(initial_lib_data, parent=self)
        self.lib_config_panel.lib_data_changed.connect(self.on_lib_data_updated)
        
        self.current_detail_widget = QWidget() 
        self.detail_layout.addWidget(self.current_detail_widget)
        
        content_splitter.addWidget(self.detail_frame)
        content_splitter.setSizes([1, 4]) 
        main_layout.addWidget(content_splitter)
        
        # --- Terminal Log ---
        log_group = QGroupBox("Terminal Output")
        log_vbox = QVBoxLayout(log_group)

        log_frame = QFrame()
        log_frame.setObjectName("logOutputContainer")
        log_frame_layout = QVBoxLayout(log_frame)
        log_frame_layout.setContentsMargins(6, 6, 6, 6)
        log_frame_layout.setSpacing(4)

        log_header = QHBoxLayout()
        log_header.setObjectName("logOutputToolbar")
        log_header.setContentsMargins(4, 2, 4, 2)
        log_header.addWidget(QLabel("Console:"))
        log_header.addStretch()

        self.btn_log_copy = QPushButton()
        self.btn_log_copy.setToolTip("Copy Console Output")
        self.btn_log_copy.setFixedSize(28, 28)
        self.btn_log_copy.clicked.connect(self.copy_log_to_clipboard)
        log_header.addWidget(self.btn_log_copy)

        self.btn_log_clear = QPushButton()
        self.btn_log_clear.setToolTip("Clear Console Output")
        self.btn_log_clear.setFixedSize(28, 28)
        self.btn_log_clear.clicked.connect(self.clear_log_output)
        log_header.addWidget(self.btn_log_clear)

        log_frame_layout.addLayout(log_header)
        
        self.log = QPlainTextEdit()
        self.log.setObjectName("logOutput") 
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 10))
        
        log_frame_layout.addWidget(self.log)
        log_vbox.addWidget(log_frame)
        
        # Progress Bar inside Log area
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(3) 
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.progress_bar.hide()
        # QProgressBar style is now fully inherited from the application theme
        
        log_vbox.addWidget(self.progress_bar)
        
        main_layout.addWidget(log_group)
        self.apply_theme_icons()

        self.load_list_items()

    # ========== List and Detail View Logic ==========

    def load_list_items(self):
        self.list_widget.clear()
        sdk_item = QListWidgetItem("SDK Configuration", self.list_widget)
        sdk_item.setData(Qt.UserRole, "SDK") 
        
        for lib_data in self.workspace_settings.get("managed_libraries", []):
            self._add_lib_item_to_list(lib_data)
            
        if self.list_widget.count() > 0:
             self.list_widget.setCurrentRow(0)

    def sync_with_settings(self, workspace_settings: dict):
        """
        Reloads the tab UI from the active workspace settings so this tab stays
        synchronized with workspace/project changes made in the main settings flow.
        """
        if self.process_is_running():
            return

        self.workspace_settings = dict(workspace_settings or {})
        if "managed_libraries" not in self.workspace_settings:
            self.workspace_settings["managed_libraries"] = []

        self.sdk_config_panel.workspace_settings = self.workspace_settings
        sdk_path = self.workspace_settings.get("sdk_path", "$HOME/vitasdk")
        if self.sdk_config_panel.ed_vitasdk_path.text() != sdk_path:
            self.sdk_config_panel.ed_vitasdk_path.setText(sdk_path)
        self.apply_theme_icons()

        self.load_list_items()
        
    def _add_lib_item_to_list(self, lib_data: dict):
        item = QListWidgetItem(self.list_widget)
        widget = LibListItemWidget(lib_data)
        widget.delete_requested.connect(self.on_delete_library)
        
        item.setSizeHint(widget.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, widget)
        item.setData(Qt.UserRole, lib_data) 

    @Slot(QListWidgetItem, QListWidgetItem)
    def on_list_item_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
        if not current: return

        if self.current_detail_widget is not None:
            self.detail_layout.removeWidget(self.current_detail_widget)
            self.current_detail_widget.hide()
            
        item_data = current.data(Qt.UserRole)

        if item_data == "SDK":
            self.current_detail_widget = self.sdk_config_panel
        elif isinstance(item_data, dict):
            self.lib_config_panel.set_data(item_data)
            self.current_detail_widget = self.lib_config_panel
        else:
            self.current_detail_widget = QWidget() 

        self.current_detail_widget.show()
        self.detail_layout.addWidget(self.current_detail_widget)
        self.detail_layout.addStretch()

    # ========== Persistence Handlers ==========

    @Slot(str)
    def on_sdk_path_changed(self, new_path: str):
        self.workspace_settings["sdk_path"] = new_path
        self.sdk_path_changed.emit(new_path)
        
    @Slot()
    def on_lib_data_updated(self):
        new_lib_data = self.lib_config_panel.get_data()
        current_item = self.list_widget.currentItem()
        
        if current_item:
            current_item.setData(Qt.UserRole, new_lib_data)
            item_widget: LibListItemWidget = self.list_widget.itemWidget(current_item)
            if item_widget:
                item_widget.lib_data = new_lib_data 
                item_widget.update_name(new_lib_data.get("path", ""))

        self.update_managed_libraries_list()
        
    def update_managed_libraries_list(self):
        managed_libraries = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            data = item.data(Qt.UserRole)
            if isinstance(data, dict):
                managed_libraries.append(data)
                
        self.workspace_settings["managed_libraries"] = managed_libraries
        self.managed_libraries_changed.emit(managed_libraries)

    # ========== UI handlers for Libraries ==========

    @Slot()
    def on_add_library(self):
        if self.process_is_running(): return
        
        new_lib = {
            "path": "",
            "make_flags": "",
            "debug_enabled": False,
            "debug_flags": "DEBUG=1"
        }
        self._add_lib_item_to_list(new_lib)
        
        new_item = self.list_widget.item(self.list_widget.count() - 1)
        self.list_widget.setCurrentItem(new_item)
        
        self.update_managed_libraries_list() 

    @Slot(dict)
    def on_delete_library(self, lib_data: dict):
        if self.process_is_running(): return

        lib_path = lib_data.get("path", "")
        lib_name = os.path.basename(lib_path) if lib_path else "New Project"
        
        reply_manager = QMessageBox.question(self, 'Confirm Removal',
            f"Are you sure you want to remove the project '{lib_name}' from the manager list? "
            "The files will remain on disk unless you choose to delete them in the next step.", 
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply_manager == QMessageBox.No: return

        item_to_delete = None
        row = -1
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item_data = item.data(Qt.UserRole)
            if isinstance(item_data, dict) and item_data == lib_data: 
                item_to_delete = item
                row = i
                break
        
        if item_to_delete:
            self.list_widget.takeItem(row) 
            del item_to_delete 

            self.update_managed_libraries_list() 

            if self.list_widget.count() > 0:
                new_current_row = max(0, min(row, self.list_widget.count() - 1))
                new_current_item = self.list_widget.item(new_current_row)
                self.list_widget.setCurrentItem(new_current_item)
            else:
                self.list_widget.setCurrentRow(-1) 
        else:
            QMessageBox.warning(self, "Error", "Could not find the library item to delete.")
            return

        if lib_path:
            reply_files = QMessageBox.question(self, 'Confirm File Deletion (DANGEROUS)',
                f"Do you also want to **permanently delete the project files** at: \n\n'{lib_path}'\n\nThis uses 'rm -rf' and cannot be undone.", 
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

            if reply_files == QMessageBox.Yes:
                script = self.build_delete_lib_script(lib_path)
                self.append_colored_line(f">>> Deleting project files for '{lib_name}' ({lib_path})... This will use rm -rf.", COLOR_RED)
                self.run_script(script)
            else:
                self.append_colored_line(f">>> Project '{lib_name}' removed from manager. Files kept at {lib_path}.", COLOR_YELLOW)
        else:
            self.append_colored_line(f">>> Project '{lib_name}' removed from manager. No physical path to delete.", COLOR_YELLOW)


    # ========== Process Actions ==========

    def on_install_sdk(self, softfp: bool, selected_path: str):
        if self.process_is_running(): return
        variant = "SoftFP" if softfp else "Official"
        vitasdk_path = selected_path or self.effective_vitasdk_path() 
        script = self.build_install_script(softfp=softfp, vitasdk_path=vitasdk_path)
        self.append_colored_line(f">>> Running full installation for {variant} VitaSDK...", COLOR_CMD)
        self.run_script(script)

    def on_update_sdk(self, softfp: bool, selected_path: str):
        if self.process_is_running(): return
        vitasdk_path = selected_path or self.effective_vitasdk_path()
        if softfp:
            script = self.build_install_script(softfp=True, vitasdk_path=vitasdk_path, only_vdpm_update=True)
            self.append_colored_line(f">>> Updating SoftFP VitaSDK (via vdpm pull/install)...", COLOR_CMD)
        else:
            script = self.build_update_script(vitasdk_path)
            self.append_colored_line(f">>> Updating Official VitaSDK...", COLOR_CMD)
        self.run_script(script)

    def on_uninstall_sdk(self, selected_path: str):
        if self.process_is_running(): return
        vitasdk_path = selected_path or self.effective_vitasdk_path()
        script = self.build_uninstall_script(vitasdk_path)
        self.append_colored_line(f">>> Running UNINSTALL for VitaSDK at {vitasdk_path}...", COLOR_RED)
        self.run_script(script)

    @Slot(dict)
    def on_build_library(self, config: dict):
        if self.process_is_running(): return
        vitasdk_path = self.effective_vitasdk_path()
        script = self.build_managed_lib_script(vitasdk_path, config["path"], config["flags"])
        self.append_colored_line(f">>> Building managed library: {config['lib_name']}...", COLOR_CMD)
        self.run_script(script)

    # ========== Helper config ==========

    def effective_vitasdk_path(self) -> str:
        p = self.sdk_config_panel.ed_vitasdk_path.text().strip()
        return p or "$HOME/vitasdk"

    # ========== Script builders ==========

    def build_common_header(self, vitasdk_path: str) -> str:
        return dedent(f("""
            #!/usr/bin/env bash
            set -u 

            echo "=== Vita SDK Manager script START ==="
            
            export GIT_PAGER=cat
            
            VITASDK="{vitasdk_path}"
            if [[ "$VITASDK" == *\\$HOME* ]]; then
                VITASDK=$(echo "$VITASDK" | sed "s/\\$HOME/$HOME/")
            fi
            
            export VITASDK
            export PATH="$VITASDK/bin:$PATH"

            echo "Using VITASDK=$VITASDK"

            log_error() {{
              echo "ERROR: $1" >&2
              exit 1
            }}
        """)).strip() + "\n\n"

    def build_delete_lib_script(self, lib_path: str) -> str:
        script = self.build_common_header(self.effective_vitasdk_path())
        script += dedent(f"""
            echo "=== Attempting to delete library files ==="
            set -e
            LIB_PATH="{lib_path}"
            if [[ "$LIB_PATH" == *\\$HOME* ]]; then
                LIB_PATH=$(echo "$LIB_PATH" | sed "s/\\$HOME/$HOME/")
            fi
            if [ -d "$LIB_PATH" ]; then
              echo "Deleting project directory: $LIB_PATH (rm -rf)"
              rm -rf "$LIB_PATH" || log_error "Failed to delete directory. Check permissions."
            else
              echo "Project directory not found: $LIB_PATH. No files deleted."
            fi
            echo "File deletion process finished."
        """)
        return script
    
    def build_install_script(self, softfp: bool, vitasdk_path: str, only_vdpm_update: bool = False) -> str:
        script = self.build_common_header(vitasdk_path)
        repo = "https://github.com/vitasdk-softfp/vdpm.git" if softfp else "https://github.com/vitasdk/vdpm.git"
        label = "softfp fork" if softfp else "official"

        script += dedent(f"""
            echo "=== Installing VitaSDK ({label}) ==="
            set -e
            if [ ! -d "$VITASDK" ]; then
              echo "Creating VITASDK directory at $VITASDK"
              mkdir -p "$VITASDK" || log_error "Cannot create $VITASDK (permissions?)"
            fi
            if [ ! -d "$HOME/vdpm" ]; then
              echo "Cloning vdpm from {repo}"
              git clone "{repo}" "$HOME/vdpm" || log_error "Failed to clone vdpm"
            else
              echo "vdpm already cloned in $HOME/vdpm, pulling latest..."
              cd "$HOME/vdpm" || log_error "Cannot enter $HOME/vdpm"
              git remote set-url origin "{repo}" 
              git pull || echo "Warning: git pull failed, continuing with existing copy"
            fi
            cd "$HOME/vdpm" || log_error "Cannot enter vdpm directory"
            if [ "{'true' if only_vdpm_update else 'false'}" != "true" ]; then
                echo "Bootstrapping VitaSDK..."
                ./bootstrap-vitasdk.sh || log_error "bootstrap-vitasdk.sh failed"
            fi
            echo "Running install-all.sh..."
            ./install-all.sh || log_error "install-all.sh failed"
            echo "VitaSDK installation done."
        """) + "\n\n"
        script += 'echo "=== All requested operations finished ==="\n'
        return script

    def build_update_script(self, vitasdk_path: str) -> str:
        script = self.build_common_header(vitasdk_path)
        script += dedent("""
            echo "=== Updating Official VitaSDK ==="
            set -e
            if ! command -v vitasdk-update >/dev/null 2>&1; then
              log_error "vitasdk-update not found. Is the Official VitaSDK installed?"
            fi
            vitasdk-update || log_error "vitasdk-update failed"
            echo "VitaSDK update completed."
        """)
        return script
        
    def build_uninstall_script(self, vitasdk_path: str) -> str:
        script = self.build_common_header(vitasdk_path)
        script += dedent(f"""
            echo "=== Uninstalling VitaSDK at {vitasdk_path} ==="
            set -e
            if [ -d "$VITASDK" ]; then
              echo "Deleting directory: $VITASDK"
              rm -rf "$VITASDK" || log_error "Failed to delete directory. Check permissions."
            fi
            if [ -d "$HOME/vdpm" ]; then
              echo "Deleting vdpm directory: $HOME/vdpm"
              rm -rf "$HOME/vdpm" || log_error "Failed to delete vdpm directory. Check permissions."
            fi
            echo "VitaSDK uninstall script finished."
        """)
        return script

    def build_managed_lib_script(self, vitasdk_path: str, lib_path: str, make_flags: str) -> str:
        script = self.build_common_header(vitasdk_path)
        if not lib_path:
            script += 'log_error "Library path is empty. Cannot build."\n'
            return script

        flags_part = make_flags.strip()
        echo_flags = f'echo "Using Make flags: {flags_part}"' if flags_part else 'echo "No extra Make flags specified."'
        
        script += dedent(f("""
            echo "=== Building Managed Library: {os.path.basename(lib_path)} ==="
            set -e
            if [ ! -d "$VITASDK/arm-vita-eabi" ]; then
              log_error "VitaSDK arm-vita-eabi directory not found. Install VitaSDK first."
            fi
            LIB_PATH="{lib_path}"
            if [[ "$LIB_PATH" == *\\$HOME* ]]; then
                LIB_PATH=$(echo "$LIB_PATH" | sed "s/\\$HOME/$HOME/")
            fi
            if [ ! -d "$LIB_PATH" ]; then
              log_error "Library directory not found: $LIB_PATH"
            fi
            cd "$LIB_PATH" || log_error "Cannot enter library directory: $LIB_PATH"
            {echo_flags}
            echo "Cleaning previous build (if any)..."
            make clean || true 
            echo "Building..."
            make {flags_part} || log_error "Compilation failed in $LIB_PATH"
            echo "Build of {os.path.basename(lib_path)} completed."
        """)) + "\n"
        script += 'echo "=== Managed library build finished ==="\n'
        return script


    # ========== Process handling & Colored Logging ==========

    def process_is_running(self) -> bool:
        if self.process and self.process.state() != QProcess.NotRunning:
            QMessageBox.information(self, "Process running", "Another operation is currently running.")
            return True
        return False

    def run_script(self, script: str):
        if sys.platform.startswith(("linux", "darwin")):
            program = "bash"
            args = ["-s"]
        elif sys.platform.startswith("win"):
            wsl = shutil.which("wsl.exe")
            if not wsl:
                self.append_colored_line("ERROR: wsl.exe not found. Aborting.", COLOR_RED)
                return
            program = wsl
            args = ["bash", "-s"]
        else:
            return

        self.set_buttons_enabled(False)
        self.set_installation_in_progress(True)
        self.log.clear() # Clear log on new run

        self.process = QProcess(self)
        self.process.setProgram(program)
        self.process.setArguments(args)

        self.process.readyReadStandardOutput.connect(self.on_proc_stdout)
        self.process.readyReadStandardError.connect(self.on_proc_stderr)
        self.process.finished.connect(self.on_proc_finished)
        self.process.errorOccurred.connect(self.on_proc_error)

        self.append_colored_line(f"--- Executing script with {program} {' '.join(args)} ---", COLOR_CMD)
        self.process.start()

        if not self.process.waitForStarted(5000):
            self.append_colored_line("ERROR: Process failed to start.", COLOR_RED)
            self.set_buttons_enabled(True)
            self.set_installation_in_progress(False)
            self.process = None
            return

        self.process.write(script.encode("utf-8"))
        self.process.closeWriteChannel()

    def on_proc_stdout(self):
        if self.process:
            self._handle_output_data(self.process.readAllStandardOutput().data())

    def on_proc_stderr(self):
        if self.process:
            self._handle_output_data(self.process.readAllStandardError().data())

    def _handle_output_data(self, data):
        """Decodes and color-codes output data similar to build.py"""
        try:
            text_chunk = data.decode("utf-8", errors="replace")
        except:
            return

        # Split by ANSI escape codes
        parts = ANSI_ESCAPE.split(text_chunk)
        current_hex = COLOR_GREY 

        for part in parts:
            if not part: continue
            
            # Check if part is an ANSI code
            if ANSI_ESCAPE.match(part):
                codes = part[2:-1].split(';')
                for c in codes:
                    if c in ANSI_COLOR_MAP:
                        current_hex = ANSI_COLOR_MAP[c]
                    elif c == '0':
                        current_hex = COLOR_GREY
            else:
                # Process plain text lines for regex highlighting
                lines = part.split('\n')
                for i, line in enumerate(lines):
                    
                    final_color = current_hex
                    line_lower = line.lower()
                    
                    # 1. Error Detection
                    if 'error:' in line_lower or 'fatal' in line_lower or 'failed' in line_lower:
                        final_color = COLOR_RED
                    elif 'warning:' in line_lower:
                        final_color = COLOR_YELLOW
                    
                    # 2. Progress/Success
                    elif 'installing' in line_lower or 'cloning' in line_lower or 'bootstrapping' in line_lower:
                        final_color = COLOR_PROGRESS
                    elif 'success' in line_lower or 'done' in line_lower or 'completed' in line_lower:
                        final_color = COLOR_SUCCESS
                    
                    # 3. Echoed commands
                    elif line.startswith("===") or line.startswith(">>>"):
                        final_color = COLOR_CMD

                    self.append_colored_line(line, final_color, newline=False)
                    
                    if i < len(lines) - 1:
                        self.append_colored_line("", COLOR_GREY) # Explicit newline

    def append_colored_line(self, text, color_hex, newline=True):
        self.log.moveCursor(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color_hex))
        
        # Bold important lines
        if text.strip().startswith("===") or "error" in text.lower():
            fmt.setFontWeight(QFont.Bold)
            
        cursor = self.log.textCursor()
        cursor.setCharFormat(fmt)
        cursor.insertText(text + ("\n" if newline else ""))
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def copy_log_to_clipboard(self):
        QApplication.clipboard().setText(self.log.toPlainText())

    def clear_log_output(self):
        self.log.clear()

    def apply_theme_icons(self):
        self.btn_log_copy.setIcon(themed_icon("alt-clipboard.svg", 18))
        self.btn_log_copy.setIconSize(self.btn_log_copy.size() * 0.6)
        self.btn_log_clear.setIcon(themed_icon("alt-trash.svg", 18))
        self.btn_log_clear.setIconSize(self.btn_log_clear.size() * 0.6)

        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if widget and hasattr(widget, "apply_theme_icons"):
                widget.apply_theme_icons()

    def on_proc_finished(self, exit_code: int, exit_status):
        color = COLOR_SUCCESS if exit_code == 0 else COLOR_RED
        self.append_colored_line(f"\n--- Process finished with code {exit_code} ---", color)
        self.set_buttons_enabled(True)
        self.set_installation_in_progress(False)
        self.process = None
        # Note: self.status_label is not defined in this scope, removing access to it
        
    def on_proc_error(self, error):
        self.append_colored_line(f"\n[QProcess error] code={error}", COLOR_RED)
        self.set_buttons_enabled(True)
        self.set_installation_in_progress(False)
        self.process = None

    def set_buttons_enabled(self, enabled: bool):
        self.sdk_config_panel.set_buttons_enabled(enabled)
        self.lib_config_panel.set_buttons_enabled(enabled)
        self.btn_add_lib.setEnabled(enabled)

    def set_installation_in_progress(self, running: bool):
        if running:
            # Note: self.status_label is not defined in this scope, removing access to it
            self.progress_bar.setRange(0, 0)
            self.progress_bar.show()
        else:
            # Note: self.status_label is not defined in this scope, removing access to it
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
            self.progress_bar.hide()
