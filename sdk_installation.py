import sys
import shutil
from textwrap import dedent

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QLabel, QPushButton,
    QCheckBox, QHBoxLayout, QRadioButton, QLineEdit,
    QPlainTextEdit, QMessageBox, QFormLayout, QProgressBar
)
from PySide6.QtCore import Qt, QProcess
from PySide6.QtGui import QTextCursor


class SdkInstallationTab(QWidget):
    def __init__(self):
        super().__init__()

        self.process: QProcess | None = None

        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignTop)

        grp = QGroupBox("Vita SDK Installer")
        vbox = QVBoxLayout(grp)

        vbox.addWidget(QLabel(
            "Install and manage VitaSDK and VitaGL.\n"
            "Linux / macOS are supported directly.\n"
            "On Windows this runs through WSL2 (Ubuntu or similar)."
        ))

        # ---------- SDK variant ----------
        sdk_mode_box = QGroupBox("VitaSDK variant")
        sdk_mode_layout = QHBoxLayout(sdk_mode_box)
        self.rad_sdk_normal = QRadioButton("Normal (official vitasdk)")
        self.rad_sdk_softfp = QRadioButton("softfp fork (for Android-style ports)")
        self.rad_sdk_normal.setChecked(True)
        sdk_mode_layout.addWidget(self.rad_sdk_normal)
        sdk_mode_layout.addWidget(self.rad_sdk_softfp)
        vbox.addWidget(sdk_mode_box)

        # ---------- Packages ----------
        packages_box = QGroupBox("What do you want to install?")
        packages_layout = QVBoxLayout(packages_box)
        
        # Apply style for rounded checkboxes
        checkbox_style = """
            QCheckBox::indicator {
                border: 1px solid #999;
                border-radius: 6px; /* Makes the indicator rounded */
                width: 13px;
                height: 13px;
                background-color: white;
            }
            QCheckBox::indicator:checked {
                background-color: #4caf50;
                border: 1px solid #4caf50;
            }
        """

        self.chk_install_sdk = QCheckBox("VitaSDK toolchain")
        self.chk_install_sdk.setStyleSheet(checkbox_style)
        
        self.chk_install_vitagl = QCheckBox("VitaGL (clone + build + install)")
        self.chk_install_vitagl.setStyleSheet(checkbox_style)
        
        packages_layout.addWidget(self.chk_install_sdk)
        packages_layout.addWidget(self.chk_install_vitagl)
        vbox.addWidget(packages_box)

        # ---------- Advanced options ----------
        config_box = QGroupBox("Advanced options")
        config_layout = QFormLayout(config_box)

        self.ed_vitagl_flags = QLineEdit()
        self.ed_vitagl_flags.setPlaceholderText(
            "Extra VitaGL make flags, e.g.: SOFTFP_ABI=1 USE_SBRK=1"
        )

        # VitaGL debug flags
        self.chk_vitagl_debug = QCheckBox("VitaGL debug build (DEBUG=1 VGL_DEBUG=1)")
        self.chk_vitagl_debug.setStyleSheet(checkbox_style)

        self.ed_vitasdk_path = QLineEdit()
        # Using $HOME/vitasdk by default to avoid sudo / permission issues
        self.ed_vitasdk_path.setPlaceholderText("$HOME/vitasdk (default if empty)")

        config_layout.addRow("VitaGL make flags:", self.ed_vitagl_flags)
        config_layout.addRow("", self.chk_vitagl_debug)
        config_layout.addRow("VITASDK path:", self.ed_vitasdk_path)

        vbox.addWidget(config_box)

        # ---------- Buttons ----------
        btn_layout = QHBoxLayout()
        self.btn_install_selected = QPushButton("Install Selected")
        self.btn_update = QPushButton("Update VitaSDK")
        self.btn_install_vitagl_only = QPushButton("Install & Compile VitaGL (with flags)")
        btn_layout.addWidget(self.btn_install_selected)
        btn_layout.addWidget(self.btn_update)
        btn_layout.addWidget(self.btn_install_vitagl_only)
        vbox.addLayout(btn_layout)

        # ---------- Progress ----------
        self.status_label = QLabel("Idle")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.progress_bar.hide()

        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #999;
                border-radius: 9px;
                background-color: #e0e0e0;
                padding: 1px;
            }
            QProgressBar::chunk {
                border-radius: 9px;
                background-color: #4caf50;
            }
        """)

        progress_layout = QHBoxLayout()
        progress_layout.addWidget(self.status_label)
        progress_layout.addWidget(self.progress_bar)
        vbox.addLayout(progress_layout)

        # ---------- Log ----------
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        vbox.addWidget(self.log)

        main_layout.addWidget(grp)
        main_layout.addStretch()

        # Signals
        self.btn_install_selected.clicked.connect(self.on_install_selected)
        self.btn_update.clicked.connect(self.on_update_sdk)
        self.btn_install_vitagl_only.clicked.connect(self.on_install_vitagl_only)

    # ========== UI handlers ==========

    def on_install_selected(self):
        if self.process_is_running():
            return

        install_sdk = self.chk_install_sdk.isChecked()
        install_vitagl = self.chk_install_vitagl.isChecked()

        if not install_sdk and not install_vitagl:
            QMessageBox.warning(self, "Nothing selected", "Please select at least one item to install.")
            return

        softfp = self.rad_sdk_softfp.isChecked()
        vitasdk_path = self.effective_vitasdk_path()
        vitagl_flags = self.compute_vitagl_flags()

        script = self.build_install_script(
            install_sdk=install_sdk,
            install_vitagl=install_vitagl,
            softfp=softfp,
            vitasdk_path=vitasdk_path,
            vitagl_flags=vitagl_flags,
        )

        self.append_log(">>> Running installer for selected components...\n")
        self.run_script(script)

    def on_update_sdk(self):
        if self.process_is_running():
            return

        vitasdk_path = self.effective_vitasdk_path()
        script = self.build_update_script(vitasdk_path)
        self.append_log(">>> Updating VitaSDK...\n")
        self.run_script(script)

    def on_install_vitagl_only(self):
        if self.process_is_running():
            return

        vitasdk_path = self.effective_vitasdk_path()
        vitagl_flags = self.compute_vitagl_flags()
        script = self.build_vitagl_only_script(vitasdk_path, vitagl_flags)
        self.append_log(">>> Installing & compiling VitaGL with custom flags...\n")
        self.run_script(script)

    # ========== Helper config ==========

    def effective_vitasdk_path(self) -> str:
        # Default to $HOME/vitasdk (safe for WSL / Linux)
        p = self.ed_vitasdk_path.text().strip()
        return p or "$HOME/vitasdk"

    def compute_vitagl_flags(self) -> str:
        parts = []
        user = self.ed_vitagl_flags.text().strip()
        if user:
            parts.append(user)
        if self.chk_vitagl_debug.isChecked():
            parts.append("DEBUG=1 VGL_DEBUG=1")
        return " ".join(parts).strip()

    # ========== Script builders ==========

    def build_common_header(self, vitasdk_path: str) -> str:
        # NOTE: Removed set -ex to prevent log bloat and potential ANSI/encoding issues
        # from Git/Bash color codes that cause unlegible output in QPlainTextEdit.
        return dedent(f"""
            #!/usr/bin/env bash
            set -u # Fail on unset variable

            echo "=== Vita installer script START ==="
            echo "uname: $(uname -a)"

            # Added to stop git and other tools from outputting color codes (solves the "boxes" issue)
            export NO_COLOR=1 
            export GIT_PAGER=cat
            
            VITASDK="{vitasdk_path}"
            export VITASDK
            export PATH="$VITASDK/bin:$PATH"

            echo "Using VITASDK=$VITASDK"
            echo "PATH=$PATH"

            log_error() {{
              echo "ERROR: $1" >&2
              exit 1
            }}
        """).strip() + "\n\n"

    def build_install_script(
        self,
        install_sdk: bool,
        install_vitagl: bool,
        softfp: bool,
        vitasdk_path: str,
        vitagl_flags: str,
    ) -> str:
        script = self.build_common_header(vitasdk_path)

        if install_sdk:
            if softfp:
                repo = "https://github.com/vitasdk-softfp/vdpm.git"
                variant_label = "softfp fork"
            else:
                repo = "https://github.com/vitasdk/vdpm.git"
                variant_label = "official (non-softfp)"

            # set -e added here to ensure the script stops immediately if any command fails
            script += dedent(f"""
                echo "=== Installing VitaSDK ({variant_label}) ==="
                set -e

                for dep in git cmake python3 make gcc g++; do
                  if ! command -v "$dep" >/dev/null 2>&1; then
                    echo "WARNING: Missing dependency: $dep"
                  fi
                done

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
                  git pull || echo "Warning: git pull failed, continuing with existing copy"
                fi

                cd "$HOME/vdpm" || log_error "Cannot enter vdpm directory"

                echo "Bootstrapping VitaSDK..."
                ./bootstrap-vitasdk.sh || log_error "bootstrap-vitasdk.sh failed"

                echo "Running install-all.sh..."
                ./install-all.sh || log_error "install-all.sh failed"

                echo "VitaSDK installation done."
            """) + "\n\n"

        if install_vitagl:
            script += self.build_vitagl_section(vitasdk_path, vitagl_flags)

        script += 'echo "=== All requested operations finished ==="\n'
        return script

    def build_update_script(self, vitasdk_path: str) -> str:
        script = self.build_common_header(vitasdk_path)
        script += dedent("""
            echo "=== Updating VitaSDK ==="
            set -e

            if ! command -v vitasdk-update >/dev/null 2>&1; then
              log_error "vitasdk-update not found in PATH. Is VitaSDK installed correctly?"
            fi

            vitasdk-update || log_error "vitasdk-update failed"
            echo "VitaSDK update completed."
        """)
        return script

    def build_vitagl_section(self, vitasdk_path: str, vitagl_flags: str) -> str:
        flags_part = vitagl_flags.strip()
        if flags_part:
            echo_flags = f'echo "Using VitaGL make flags: {flags_part}"'
        else:
            echo_flags = 'echo "No extra VitaGL make flags specified."'

        return dedent(f"""
            echo "=== Installing VitaGL ==="
            set -e

            if [ ! -d "$VITASDK/arm-vita-eabi" ]; then
              log_error "VitaSDK arm-vita-eabi directory not found. Install VitaSDK first."
            fi

            VGL_DIR="$VITASDK/arm-vita-eabi/include/vitaGL"

            if [ ! -d "$VGL_DIR" ]; then
              echo "Cloning vitaGL into $VGL_DIR"
              git clone https://github.com/Rinnegatamante/vitaGL.git "$VGL_DIR" || log_error "Failed to clone vitaGL"
            else
              echo "vitaGL already exists, pulling latest changes..."
              cd "$VGL_DIR" || log_error "Cannot enter $VGL_DIR"
              git pull || echo "Warning: git pull failed, continuing with existing copy"
            fi

            cd "$VGL_DIR" || log_error "Cannot enter $VGL_DIR"

            {echo_flags}

            echo "Cleaning previous vitaGL build (if any)..."
            make clean || true

            echo "Building vitaGL..."
            make {flags_part} || log_error "vitaGL compilation failed"

            if [ ! -f "libvitaGL.a" ]; then
              log_error "libvitaGL.a not produced. Build probably failed."
            fi

            echo "Copying libvitaGL.a into $VITASDK/arm-vita-eabi/lib"
            mkdir -p "$VITASDK/arm-vita-eabi/lib"
            cp libvitaGL.a "$VITASDK/arm-vita-eabi/lib/" || log_error "Failed to copy libvitaGL.a"

            echo "VitaGL installation completed."
        """) + "\n"

    def build_vitagl_only_script(self, vitasdk_path: str, vitagl_flags: str) -> str:
        script = self.build_common_header(vitasdk_path)
        script += self.build_vitagl_section(vitasdk_path, vitagl_flags)
        script += 'echo "=== VitaGL-only operation finished ==="\n'
        return script

    # ========== Process handling ==========

    def process_is_running(self) -> bool:
        if self.process and self.process.state() != QProcess.NotRunning:
            QMessageBox.information(
                self,
                "Process running",
                "Another installation/update is currently running. Please wait for it to finish."
            )
            return True
        return False

    def run_script(self, script: str):
        # Decide runner
        if sys.platform.startswith(("linux", "darwin")):
            program = "bash"
            args = ["-s"]
        elif sys.platform.startswith("win"):
            wsl = shutil.which("wsl.exe")
            if not wsl:
                QMessageBox.critical(
                    self,
                    "No WSL2 found",
                    "On Windows you need WSL2 (wsl.exe) configured.\n"
                    "Open a terminal, run 'wsl' once to finish setup, then try again."
                )
                self.append_log("ERROR: wsl.exe not found. Aborting.\n")
                return
            program = wsl
            # wsl.exe bash -s   (bash will read script from stdin)
            args = ["bash", "-s"]
        else:
            QMessageBox.critical(
                self,
                "Unsupported OS",
                f"Your platform ({sys.platform}) is not supported by this installer."
            )
            return

        self.set_buttons_enabled(False)
        self.set_installation_in_progress(True)

        self.process = QProcess(self)
        self.process.setProgram(program)
        self.process.setArguments(args)

        self.process.readyReadStandardOutput.connect(self.on_proc_stdout)
        self.process.readyReadStandardError.connect(self.on_proc_stderr)
        self.process.finished.connect(self.on_proc_finished)
        # No message box on error, just log it
        self.process.errorOccurred.connect(self.on_proc_error)

        self.append_log(f"--- Executing script with {program} {' '.join(args)} ---\n")
        self.process.start()

        if not self.process.waitForStarted(5000):
            self.append_log("ERROR: Process failed to start (waitForStarted timeout).\n")
            QMessageBox.critical(
                self,
                "Process not started",
                "The installer process could not be started.\n"
                "If you are on Windows, ensure WSL2 is installed and initialized\n"
                "(try running 'wsl' once in a terminal manually)."
            )
            self.set_buttons_enabled(True)
            self.set_installation_in_progress(False)
            self.process = None
            return

        # Feed script to stdin
        self.process.write(script.encode("utf-8"))
        self.process.closeWriteChannel()

    def on_proc_stdout(self):
        if not self.process:
            return
        data = self.process.readAllStandardOutput().data().decode("utf-8", errors="ignore")
        if data:
            self.append_log(data)

    def on_proc_stderr(self):
        if not self.process:
            return
        data = self.process.readAllStandardError().data().decode("utf-8", errors="ignore")
        if data:
            self.append_log(data)

    def on_proc_finished(self, exit_code: int, exit_status):
        self.append_log(f"\n--- Process finished with code {exit_code} ---\n")
        self.set_buttons_enabled(True)
        self.set_installation_in_progress(False)
        self.process = None

    def on_proc_error(self, error):
        # QProcess-level error (couldn't spawn, crashed etc.)
        self.append_log(f"\n[QProcess error] code={error}\n")
        self.set_buttons_enabled(True)
        self.set_installation_in_progress(False)
        self.process = None

    def set_buttons_enabled(self, enabled: bool):
        self.btn_install_selected.setEnabled(enabled)
        self.btn_update.setEnabled(enabled)
        self.btn_install_vitagl_only.setEnabled(enabled)

    def set_installation_in_progress(self, running: bool):
        if running:
            self.status_label.setText("Installation in progress...")
            self.progress_bar.setRange(0, 0)  # indeterminate
            self.progress_bar.show()
        else:
            self.status_label.setText("Idle")
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
            self.progress_bar.hide()

    def append_log(self, text: str):
        self.log.appendPlainText(text.rstrip("\n"))
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()