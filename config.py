import os

# ==========================================
# MOCK SETTINGS / REAL SETTINGS HANDLING
# ==========================================

class MockSettings:
    DEFAULT_WORKSPACE_NAME = "Default"

    _all_workspaces = {
        DEFAULT_WORKSPACE_NAME: {
            "log_font_size": 13,
            "vita_ip": "192.168.1.100",
            "sdk_path": "/path/to/vitasdk",
            "last_build_dir": os.getcwd(),
            "log_port": 8080,
            "exec_path": "",
            "target_app_id": "PCSG00000",
            "launch_title_id": "VHBB00001",
            "dump_folder": "",
            "vita_port": 1337,
            "base_font_size": 10,
            "theme_name": "default",
        },
    }
    _current_workspace_name = DEFAULT_WORKSPACE_NAME

    def __init__(self):
        self._current_data = self._all_workspaces.get(
            self._current_workspace_name,
            self._all_workspaces[self.DEFAULT_WORKSPACE_NAME],
        )

    def get_workspaces(self):
        return list(self._all_workspaces.keys())

    def get_current_workspace_name(self):
        return self._current_workspace_name

    def load_workspace(self, name: str) -> bool:
        if name in self._all_workspaces:
            self._current_workspace_name = name
            self._current_data = self._all_workspaces[name]
            return True
        return False

    def create_workspace(self, name: str) -> bool:
        name = name.strip()
        if not name or name in self._all_workspaces:
            return False
        self._all_workspaces[name] = self._current_data.copy()
        self.load_workspace(name)
        return True

    def delete_workspace(self, name: str) -> bool:
        if name == self.DEFAULT_WORKSPACE_NAME:
            return False
        if name in self._all_workspaces:
            del self._all_workspaces[name]
            if self._current_workspace_name == name:
                self.load_workspace(self.DEFAULT_WORKSPACE_NAME)
            return True
        return False

    def get(self, key, default=None):
        return self._current_data.get(key, default)

    def set(self, key, value):
        self._current_data[key] = value

    def save(self):
        print(f"Mock Save: Current workspace '{self._current_workspace_name}' saved.")

# Try to import real settings, fall back to mock
try:
    from utils import settings
except ImportError:
    settings = MockSettings()