import os
import shutil
import threading
import time
import ftplib
import re
from pathlib import Path
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QLabel, QLineEdit, QSplitter, QTreeView, 
                               QFileSystemModel, QMenu, QAbstractItemView, QStyle,
                               QInputDialog, QMessageBox, QFrame, QFileDialog)
from PySide6.QtGui import QStandardItemModel, QStandardItem, QAction, QColor, QPainter, QIntValidator
from PySide6.QtCore import Qt, QThread, Signal, Slot, QDir
from utils import settings

class FtpWorker(QThread):
    # Signals
    status_signal = Signal(str, str)  # status_msg, color_code
    listing_signal = Signal(list)
    progress_signal = Signal(str)
    downloaded_file_signal = Signal(str)
    SUPPORTED_SCREENSHOT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    
    def __init__(self):
        super().__init__()
        self.ftp = None
        self.current_path = "/"
        self.command_queue = [] 
        self.running = True
        self.mutex = threading.Lock()

    def add_command(self, cmd, *args):
        with self.mutex:
            self.command_queue.append((cmd, args))

    def run(self):
        while self.running:
            if self.command_queue:
                with self.mutex:
                    cmd, args = self.command_queue.pop(0)
                try:
                    if cmd == 'connect': self._do_connect(args[0], args[1])
                    elif cmd == 'disconnect': self._do_disconnect()
                    elif cmd == 'list': self._do_list(args[0])
                    elif cmd == 'upload': self._do_upload(args[0], args[1], args[2])
                    elif cmd == 'download': self._do_download(args[0], args[1])
                    elif cmd == 'mk_dir': self._do_mkdir(args[0])
                    elif cmd == 'rename': self._do_rename(args[0], args[1])
                    elif cmd == 'delete': self._do_delete(args[0], args[1])
                    elif cmd == 'download_latest': self._do_download_latest(*args)
                except Exception as e:
                    print(f"[FTP_ERROR] Worker Thread Exception: {str(e)}")
                    self.status_signal.emit(f"FTP Worker Error: {str(e)}", "red")
                    self.progress_signal.emit("Error")
            time.sleep(0.1)

    # --- Connection Management ---
    def _do_disconnect(self):
        if self.ftp:
            try:
                self.ftp.quit()
            except Exception:
                pass 
            finally:
                self.ftp = None
                self.status_signal.emit("Disconnected from Console.", "#777")

    def _do_connect(self, ip, port):
        self.status_signal.emit(f"Connecting to {ip}:{port}...", "orange")
        try:
            self.ftp = ftplib.FTP()
            self.ftp.connect(ip, int(port), timeout=10)
            self.ftp.login() 
            self.status_signal.emit(f"Connected to Console @ {ip}", "#3ecf4c") 
            # Auto-list root upon connection
            self._do_list("/")
        except Exception as e:
            self.status_signal.emit(f"Connection Failed: {e}", "red")
            self.ftp = None

    # --- Standard FTP Operations (Restored from Original) ---
    def _do_list(self, path):
        if not self.ftp: return
        try:
            self.ftp.cwd(path)
            self.current_path = path
            entries = []
            lines = []
            self.ftp.dir(lines.append)
            
            for line in lines:
                parts = line.split()
                if len(parts) < 9: continue
                name = " ".join(parts[8:])
                if name in [".", ".."]: continue
                
                is_dir = line.startswith('d')
                size = parts[4]
                date = " ".join(parts[5:8])
                
                entries.append({
                    'name': name, 
                    'type': "dir" if is_dir else "file", 
                    'size': size, 
                    'date': date, 
                    'is_dir': is_dir
                })
            
            # Sort: Directories first, then files
            entries.sort(key=lambda x: (not x['is_dir'], x['name']))
            self.listing_signal.emit(entries)
        except Exception as e:
            self.status_signal.emit(f"Error listing path: {e}", "red")

    def _do_upload(self, local, remote, replace):
        if not self.ftp: return
        try:
            self.progress_signal.emit(f"Uploading {remote}...")
            if not replace:
                try:
                    self.ftp.size(remote)
                    # If size succeeds, file exists
                    raise FileExistsError
                except ftplib.error_perm: 
                    pass # File doesn't exist, proceed

            with open(local, 'rb') as f:
                self.ftp.storbinary(f'STOR {remote}', f)
            
            self.progress_signal.emit("Idle")
            # Refresh list if we are currently in that directory
            if not remote.startswith("ux0:/"): 
                self._do_list(self.current_path)
        except FileExistsError:
            self.status_signal.emit("File exists. Use Replace.", "red")
        except Exception as e:
            self.status_signal.emit(f"Upload Error: {e}", "red")

    def _do_download(self, remote, local_dir):
        try:
            self.progress_signal.emit(f"Downloading {remote}...")
            local_file = os.path.join(local_dir, os.path.basename(remote))
            with open(local_file, 'wb') as f:
                self.ftp.retrbinary(f'RETR {remote}', f.write)
            self.progress_signal.emit("Idle")
        except Exception as e:
            self.status_signal.emit(f"Download Error: {e}", "red")

    def _do_mkdir(self, folder):
        try:
            self.ftp.mkd(folder)
            self._do_list(self.current_path)
        except Exception as e: 
            self.status_signal.emit(f"Mkdir Error: {e}", "red")

    def _do_rename(self, old, new):
        try:
            self.ftp.rename(old, new)
            self._do_list(self.current_path)
        except Exception as e: 
            self.status_signal.emit(f"Rename Error: {e}", "red")

    def _do_delete(self, name, is_dir):
        try:
            if is_dir: self.ftp.rmd(name)
            else: self.ftp.delete(name)
            self._do_list(self.current_path)
        except Exception as e: 
            self.status_signal.emit(f"Delete Error: {e}", "red")

    def stop(self):
        self.running = False
        self.add_command('disconnect') 
        self.wait()

    # --- New Functionality: Screenshot / Flat List ---
    def _get_file_list_flat(self, path):
        """
        Lists files in a single directory using DIR (LIST) command.
        This is necessary because the Vita's server fails on recursive commands.
        """
        files_list = []
        print(f"[FTP_DEBUG] Attempting flat scan of directory: {path}") 
        
        try:
            self.ftp.cwd(path) 
            lines = []
            self.ftp.dir(lines.append) 
            
            for line in lines:
                parts = line.split(maxsplit=8)
                if len(parts) < 9: continue 

                name = parts[-1]
                is_dir = line.startswith('d') 
                
                if name in ('.', '..'): continue
                
                if not is_dir:
                    full_remote_path = f"{path.rstrip('/')}/{name}"
                    files_list.append(full_remote_path)
                    
            print(f"[FTP_DEBUG] Files found in {path}: {len(files_list)}")
        except Exception as e:
            print(f"[FTP_ERROR] Error listing {path}: {e}")
            self.status_signal.emit(f"FTP Error listing {path}: {e}", "red")
            
        return files_list

    def _is_supported_screenshot_file(self, file_name: str) -> bool:
        return Path(file_name).suffix.lower() in self.SUPPORTED_SCREENSHOT_EXTENSIONS

    def _screenshot_sort_key(self, remote_file: str):
        file_name = Path(remote_file).name
        stem = Path(file_name).stem
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", stem):
            return (1, stem)
        return (0, file_name.lower())

    def _do_download_latest(self, remote_path: str, local_path: Path, file_pattern: str, is_recursive: bool):
        if not self.ftp:
            self.status_signal.emit("Error: Not connected to Vita console.", "red")
            self.progress_signal.emit("Error")
            return
        
        self.progress_signal.emit("Scanning for latest screenshot...")
        
        try:
            all_files = self._get_file_list_flat(remote_path) 
            
            pattern = re.compile(file_pattern, re.IGNORECASE) if file_pattern else None
            relevant_files = []
            for remote_file in all_files:
                file_name = Path(remote_file).name
                if not self._is_supported_screenshot_file(file_name):
                    continue
                if pattern is not None:
                    if not pattern.fullmatch(file_name):
                        continue
                relevant_files.append(remote_file)

            if not relevant_files and pattern is not None:
                relevant_files = [
                    remote_file
                    for remote_file in all_files
                    if self._is_supported_screenshot_file(Path(remote_file).name)
                ]
            
            if not relevant_files:
                self.status_signal.emit(
                    f"No screenshot image files found in {remote_path}.",
                    "#777",
                )
                self.progress_signal.emit("Idle")
                return

            relevant_files.sort(key=self._screenshot_sort_key)
            latest_file_remote_path = relevant_files[-1]
            latest_file_name = Path(latest_file_remote_path).name
            
            target_download_dir = Path(local_path or os.getcwd())
            target_download_dir.mkdir(parents=True, exist_ok=True)
            downloaded_file_path = target_download_dir / latest_file_name

            # Always import a copy into the app gallery folder.
            program_root = Path(__file__).resolve().parents[1]
            screenshots_dir = program_root / "screenshots"
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            gallery_file_path = screenshots_dir / latest_file_name
            
            self.progress_signal.emit(f"Downloading {latest_file_name}...")
            
            with open(downloaded_file_path, 'wb') as local_file:
                self.ftp.retrbinary(
                    f"RETR {latest_file_remote_path}",
                    local_file.write,
                )

            if downloaded_file_path.resolve() != gallery_file_path.resolve():
                shutil.copy2(downloaded_file_path, gallery_file_path)

            self.status_signal.emit(
                f"Imported screenshot to {gallery_file_path.parent.name}/{latest_file_name}",
                "#3ecf4c",
            )
            self.downloaded_file_signal.emit(str(gallery_file_path))
            self.progress_signal.emit("Idle")

        except Exception as e:
            print(f"[FTP_ERROR] Download Error: {e}")
            self.status_signal.emit(f"An error occurred: {e}", "red")
            self.progress_signal.emit("Error")


class FileTransferTab(QWidget):
    
    def __init__(self):
        super().__init__()
        
        # Initialize FTP Worker
        self.ftp_thread = FtpWorker()
        self.ftp_thread.start()
        
        # Initialize UI elements
        self.local_model = QFileSystemModel()
        self.remote_model = QStandardItemModel()
        
        # Layout setup
        layout = QVBoxLayout(self)
        
        # --- Connection Row ---
        conn = QHBoxLayout()
        conn.addWidget(QLabel("Vita IP:"))
        self.ip_input = QLineEdit(settings.get("vita_ip", "192.168.1.100"))
        self.ip_input.textChanged.connect(lambda t: settings.set("vita_ip", t))
        conn.addWidget(self.ip_input)
        
        conn.addWidget(QLabel("Port:"))
        self.port_input = QLineEdit(str(settings.get("vita_port", 1337)))
        self.port_input.setFixedWidth(60)
        self.port_input.setValidator(QIntValidator(1, 65535)) 
        self.port_input.textChanged.connect(lambda t: settings.set("vita_port", int(t) if t.isdigit() else 1337))
        conn.addWidget(self.port_input)
        
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.connect_ftp)
        conn.addWidget(self.btn_connect)
        conn.addStretch()
        layout.addLayout(conn)
        
        # --- REMOVED STATUS LABEL FROM UI ---
        # The space previously taken by the label will now be used by the splitter below.
        
        # --- Splitter Area (Local vs Remote) ---
        splitter = QSplitter(Qt.Horizontal)
        
        # 1. Local Site
        local_w = QWidget()
        l_lay = QVBoxLayout(local_w)
        l_lay.addWidget(QLabel("Local Site:"))
        
        self.local_model.setRootPath(QDir.rootPath())
        self.local_tree = QTreeView()
        self.local_tree.setModel(self.local_model)
        self.local_tree.setRootIndex(self.local_model.index(os.path.expanduser("~")))
        self.local_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        l_lay.addWidget(self.local_tree)
        
        # 2. Middle Buttons
        btn_cont = QWidget()
        b_lay = QVBoxLayout(btn_cont)
        b_lay.addStretch()
        
        # Upload
        btn_up = QPushButton("Upload ->")
        btn_up.clicked.connect(lambda: self.ftp_upload_dialog(force_replace=False)) 
        b_lay.addWidget(btn_up)
        
        # Upload & Replace
        self.btn_upload_replace = QPushButton("Upload & Replace ->")
        self.btn_upload_replace.clicked.connect(lambda: self.ftp_upload_dialog(force_replace=True))
        b_lay.addWidget(self.btn_upload_replace)

        # Download
        btn_dl = QPushButton("<- Download")
        btn_dl.clicked.connect(self.download_selected)
        b_lay.addWidget(btn_dl)
        
        # Rename
        self.btn_rename = QPushButton("Rename")
        self.btn_rename.clicked.connect(self.ftp_rename_selected)
        b_lay.addWidget(self.btn_rename)

        # Delete (Red)
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.clicked.connect(self.ftp_delete_selected)
        self.btn_delete.setStyleSheet("background-color: #8B0000; border: 1px solid #FF4500;") 
        b_lay.addWidget(self.btn_delete)
        
        b_lay.addStretch()

        # 3. Remote Site
        remote_w = QWidget()
        r_lay = QVBoxLayout(remote_w)
        r_lay.addWidget(QLabel("Remote Site:"))
        
        self.remote_model = QStandardItemModel()
        self.remote_model.setHorizontalHeaderLabels(["Filename", "Size", "Date"])
        self.remote_tree = QTreeView()
        self.remote_tree.setModel(self.remote_model)
        self.remote_tree.doubleClicked.connect(self.remote_double_click)
        self.remote_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        r_lay.addWidget(self.remote_tree)

        splitter.addWidget(local_w)
        splitter.addWidget(btn_cont)
        splitter.addWidget(remote_w)
        splitter.setSizes([400, 100, 400])
        layout.addWidget(splitter)

        # Connect signals
        self.ftp_thread.status_signal.connect(self.update_status)
        self.ftp_thread.listing_signal.connect(self.update_remote_view)

    # --- GUI Slots & Updates ---
    @Slot(str, str)
    def update_status(self, msg: str, color: str):
        # Printing to console instead of updating a label on UI
        print(f"[FTP Status - {color}]: {msg}")

    @Slot(list)
    def update_remote_view(self, entries: list):
        self.remote_model.removeRows(0, self.remote_model.rowCount())
        if self.ftp_thread.current_path != "/":
            up = QStandardItem("..")
            up.setData("dir", Qt.UserRole)
            self.remote_model.appendRow([up, QStandardItem(""), QStandardItem("")])
        
        f_icon = self.style().standardIcon(QStyle.SP_FileIcon)
        d_icon = self.style().standardIcon(QStyle.SP_DirIcon)

        for e in entries:
            name = QStandardItem(e['name'])
            name.setEditable(False)
            if e['is_dir']:
                name.setIcon(d_icon)
                name.setData("dir", Qt.UserRole)
            else:
                name.setIcon(f_icon)
                name.setData("file", Qt.UserRole)
            self.remote_model.appendRow([name, QStandardItem(e['size']), QStandardItem(e['date'])])

    def connect_ftp(self):
        """Standard connection from the button."""
        vita_ip = settings.get("vita_ip", self.ip_input.text())
        vita_port = settings.get("vita_port", 1337)
        if vita_ip:
            self.ftp_thread.add_command('connect', vita_ip, vita_port)
        else:
            QMessageBox.warning(self, "Connection Error", "Vita IP address is not set in settings.")

    # --- Screenshot Logic (Called externally) ---
    def download_latest_file_async(self, remote_path: str, local_path: Path, file_pattern: str, is_recursive: bool):
        """ 
        Public method called by VitaDeckModern to get the latest screenshot.
        Forces a disconnect/reconnect to ensure a fresh FTP state.
        """
        vita_ip = settings.get("vita_ip", self.ip_input.text())
        vita_port = settings.get("vita_port", 1337)
        if not vita_ip:
            # We use print because status label is gone, but we can also use valid Signal
            print("Error: Vita IP not set.")
            return

        # Force fresh connection flow
        self.ftp_thread.add_command('disconnect') 
        self.ftp_thread.add_command('connect', vita_ip, vita_port)
        self.ftp_thread.add_command(
            'download_latest', remote_path, local_path, file_pattern, is_recursive
        )

    # --- File Management Actions ---
    def remote_double_click(self, index):
        name_idx = index.siblingAtColumn(0)
        item = self.remote_model.itemFromIndex(name_idx)
        name = item.text()
        if name == "..":
            path = os.path.dirname(self.ftp_thread.current_path.rstrip('/'))
            self.ftp_thread.add_command('list', path or "/")
        elif item.data(Qt.UserRole) == "dir":
            path = self.ftp_thread.current_path.rstrip('/') + '/' + name
            self.ftp_thread.add_command('list', path)

    def download_selected(self):
        local_dir = self.local_model.filePath(self.local_tree.currentIndex())
        if not os.path.isdir(local_dir): local_dir = os.getcwd()
        
        for idx in self.remote_tree.selectionModel().selectedIndexes():
            if idx.column() == 0:
                item = self.remote_model.itemFromIndex(idx)
                if item.data(Qt.UserRole) == "file":
                    self.ftp_thread.add_command('download', item.text(), local_dir)

    def ftp_upload_dialog(self, force_replace=False):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select files to upload")
        for path in paths:
            if os.path.isfile(path):
                filename = os.path.basename(path)
                if force_replace:
                    reply = QMessageBox.question(
                        self, "Confirm Replace", 
                        f"Are you sure you want to replace '{filename}' on the remote server?", 
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply == QMessageBox.No:
                        continue
                self.ftp_thread.add_command('upload', path, filename, force_replace)

    def ftp_rename_selected(self):
        indexes = self.remote_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "Selection Error", "Please select an item to rename.")
            return
        
        name_idx = indexes[0].siblingAtColumn(0)
        old_name = self.remote_model.itemFromIndex(name_idx).text()
        
        new_name, ok = QInputDialog.getText(
            self, "Rename Item", f"Enter new name for '{old_name}':", QLineEdit.Normal, old_name
        )
        
        if ok and new_name and new_name != old_name:
            self.ftp_thread.add_command('rename', old_name, new_name)

    def ftp_delete_selected(self):
        indexes = self.remote_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "Selection Error", "Please select one or more items to delete.")
            return

        items_to_delete = []
        for idx in indexes:
            if idx.column() == 0:
                item = self.remote_model.itemFromIndex(idx)
                name = item.text()
                if name in ("..", "."): continue
                
                is_dir = (item.data(Qt.UserRole) == "dir") 
                items_to_delete.append((name, is_dir))

        if not items_to_delete: return

        reply = QMessageBox.question(
            self, "Confirm Delete", 
            f"Are you sure you want to delete the following {len(items_to_delete)} item(s)?\n\n" + 
            "\n".join([name for name, _ in items_to_delete]), 
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            for name, is_dir in items_to_delete:
                self.ftp_thread.add_command('delete', name, is_dir)

    def sync_with_settings(self):
        """Refreshes connection fields from the currently selected workspace settings."""
        expected_ip = settings.get("vita_ip", "192.168.1.100")
        expected_port = str(settings.get("vita_port", 1337))

        if self.ip_input.text() != expected_ip:
            self.ip_input.setText(expected_ip)
        if self.port_input.text() != expected_port:
            self.port_input.setText(expected_port)

    def cleanup(self):
        self.ftp_thread.stop()
