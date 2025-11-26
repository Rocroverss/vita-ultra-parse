import os
import threading
import time
import ftplib
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QLabel, QLineEdit, QSplitter, QTreeView, 
                               QFileSystemModel, QMenu, QAbstractItemView, QStyle,
                               QInputDialog, QMessageBox, QFrame, QFileDialog)
from PySide6.QtGui import QStandardItemModel, QStandardItem, QAction, QColor, QPainter
from PySide6.QtCore import Qt, QThread, Signal, Slot, QDir
from utils import settings

class FtpWorker(QThread):
    status_signal = Signal(str, str)  # status_msg, color_code
    listing_signal = Signal(list)
    progress_signal = Signal(str)
    
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
                    elif cmd == 'list': self._do_list(args[0])
                    elif cmd == 'upload': self._do_upload(args[0], args[1], args[2])
                    elif cmd == 'download': self._do_download(args[0], args[1])
                    elif cmd == 'mk_dir': self._do_mkdir(args[0])
                    elif cmd == 'rename': self._do_rename(args[0], args[1])
                    elif cmd == 'delete': self._do_delete(args[0], args[1])
                except Exception as e:
                    self.status_signal.emit(f"FTP Error: {str(e)}", "red")
                    self.progress_signal.emit("Error")
            time.sleep(0.1)

    def _do_connect(self, ip, port):
        self.status_signal.emit(f"Connecting to {ip}:{port}...", "orange")
        try:
            self.ftp = ftplib.FTP()
            self.ftp.connect(ip, int(port), timeout=10)
            self.ftp.login() 
            self.status_signal.emit(f"Connected to Console @ {ip}", "#3ecf4c") 
            self._do_list("/")
        except Exception as e:
            self.status_signal.emit(f"Connection Failed: {e}", "red")

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
                entries.append({
                    "name": name, "is_dir": line.startswith('d'),
                    "size": parts[4], "date": f"{parts[5]} {parts[6]} {parts[7]}"
                })
            entries.sort(key=lambda x: (not x['is_dir'], x['name']))
            self.listing_signal.emit(entries)
        except Exception as e:
            self.status_signal.emit(f"List Error: {e}", "orange")

    def _do_upload(self, local, remote, replace):
        if not self.ftp: return
        try:
            self.progress_signal.emit(f"Uploading {remote}...")
            if not replace:
                try:
                    self.ftp.size(remote)
                    raise FileExistsError
                except ftplib.error_perm: pass
            with open(local, 'rb') as f:
                self.ftp.storbinary(f'STOR {remote}', f)
            self.progress_signal.emit("Idle")
            if not remote.startswith("ux0:/"): self._do_list(self.current_path)
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
        except Exception as e: self.status_signal.emit(f"Mkdir Error: {e}", "red")

    def _do_rename(self, old, new):
        try:
            self.ftp.rename(old, new)
            self._do_list(self.current_path)
        except Exception as e: self.status_signal.emit(f"Rename Error: {e}", "red")

    def _do_delete(self, name, is_dir):
        try:
            if is_dir: self.ftp.rmd(name)
            else: self.ftp.delete(name)
            self._do_list(self.current_path)
        except Exception as e: self.status_signal.emit(f"Delete Error: {e}", "red")

    def stop(self):
        self.running = False
        if self.ftp:
            try: self.ftp.quit()
            except: pass
        self.wait()

class FileTransferTab(QWidget):
    def __init__(self):
        super().__init__()
        self.ftp_thread = FtpWorker()
        self.ftp_thread.listing_signal.connect(self.update_remote_view)
        self.ftp_thread.start()
        
        layout = QVBoxLayout(self)

        # Connection Bar
        conn = QHBoxLayout()
        conn.addWidget(QLabel("PS Vita IP:"))
        self.ip_input = QLineEdit(settings.get("vita_ip"))
        self.ip_input.textChanged.connect(lambda t: settings.set("vita_ip", t))
        conn.addWidget(self.ip_input)
        conn.addWidget(QLabel("Port:"))
        self.port_input = QLineEdit(str(settings.get("vita_port")))
        self.port_input.setFixedWidth(60)
        conn.addWidget(self.port_input)
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.connect_ftp)
        conn.addWidget(self.btn_connect)
        conn.addStretch()
        layout.addLayout(conn)

        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        
        # Local
        local_w = QWidget()
        l_lay = QVBoxLayout(local_w)
        l_lay.addWidget(QLabel("Local Site:"))
        self.local_model = QFileSystemModel()
        self.local_model.setRootPath(QDir.rootPath())
        self.local_tree = QTreeView()
        self.local_tree.setModel(self.local_model)
        self.local_tree.setRootIndex(self.local_model.index(os.path.expanduser("~")))
        self.local_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        l_lay.addWidget(self.local_tree)
        
        # Buttons
        # Buttons (This section starts the layout for the buttons in the middle)
        btn_cont = QWidget()
        b_lay = QVBoxLayout(btn_cont) # <--- This is the correct layout name: b_lay
        b_lay.addStretch()
        
        # Upload Button
        btn_up = QPushButton("Upload ->")
        # NOTE: Using ftp_upload_dialog with force_replace=False for the default button
        btn_up.clicked.connect(lambda: self.ftp_upload_dialog(force_replace=False)) 
        b_lay.addWidget(btn_up)
        
        # Upload & Replace Button (New/Restored)
        self.btn_upload_replace = QPushButton("Upload & Replace ->")
        self.btn_upload_replace.clicked.connect(lambda: self.ftp_upload_dialog(force_replace=True))
        b_lay.addWidget(self.btn_upload_replace)

        # Download Button
        btn_dl = QPushButton("<- Download")
        btn_dl.clicked.connect(self.download_selected)
        b_lay.addWidget(btn_dl)
        
        # Rename Button (New/Restored)
        self.btn_rename = QPushButton("Rename")
        self.btn_rename.clicked.connect(self.ftp_rename_selected)
        b_lay.addWidget(self.btn_rename)

        # Delete Button (New/Restored - Styled Red)
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.clicked.connect(self.ftp_delete_selected)
        self.btn_delete.setStyleSheet("background-color: #8B0000; border: 1px solid #FF4500;") 
        b_lay.addWidget(self.btn_delete)
        
        b_lay.addStretch()

        # Remote
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
        splitter.setSizes([400, 50, 400])
        layout.addWidget(splitter)

    # --- Add these methods to the FileTransferTab class (in file_transfer.py) ---
    def ftp_rename_selected(self):
        indexes = self.remote_tree.selectionModel().selectedIndexes()
        if not indexes:
            QMessageBox.warning(self, "Selection Error", "Please select an item to rename.")
            return
        
        # Only use the first selected item
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
                if name == ".." or name == ".":
                    continue
                
                # Assuming 'dir' or 'file' is stored in Qt.UserRole
                is_dir = (item.data(Qt.UserRole) == "dir") 
                items_to_delete.append((name, is_dir))

        if not items_to_delete:
            return

        reply = QMessageBox.question(
            self, "Confirm Delete", 
            f"Are you sure you want to delete the following {len(items_to_delete)} item(s)?\n\n" + 
            "\n".join([name for name, _ in items_to_delete]), 
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            for name, is_dir in items_to_delete:
                self.ftp_thread.add_command('delete', name, is_dir)

    # Fix for "Upload and Replace"
    def ftp_upload_dialog(self, force_replace=False):
        # ... Your existing dialog code ...
        # This method handles file selection and queues the command.
        # The 'force_replace' argument ensures the correct worker logic is used.
        
        # The confirmation message for "Upload & Replace" is critical here:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select files to upload")
        for path in paths:
            if os.path.isfile(path):
                filename = os.path.basename(path)
                
                if force_replace:
                    # This is the confirmation box for the "Upload & Replace" button
                    reply = QMessageBox.question(
                        self, "Confirm Replace", 
                        f"Are you sure you want to replace '{filename}' on the remote server?", 
                        QMessageBox.Yes | QMessageBox.No
                    )
                    if reply == QMessageBox.No:
                        continue
                
                # The worker will use force_replace to decide whether to check for file existence
                self.ftp_thread.add_command('upload', path, filename, force_replace)

    def connect_ftp(self):
        ip = self.ip_input.text()
        port = self.port_input.text()
        settings.set("vita_ip", ip)
        self.ftp_thread.add_command('connect', ip, port)

    @Slot(list)
    def update_remote_view(self, entries):
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

    def upload_selected(self):
        for idx in self.local_tree.selectionModel().selectedIndexes():
            if idx.column() == 0:
                path = self.local_model.filePath(idx)
                if os.path.isfile(path):
                    self.ftp_thread.add_command('upload', path, os.path.basename(path), True)

    def download_selected(self):
        local_dir = self.local_model.filePath(self.local_tree.currentIndex())
        if not os.path.isdir(local_dir): local_dir = os.getcwd()
        for idx in self.remote_tree.selectionModel().selectedIndexes():
            if idx.column() == 0:
                item = self.remote_model.itemFromIndex(idx)
                if item.data(Qt.UserRole) == "file":
                    self.ftp_thread.add_command('download', item.text(), local_dir)
                    
    def cleanup(self):
        self.ftp_thread.stop()