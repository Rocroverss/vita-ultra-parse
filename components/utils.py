import json
import os
import re
import struct
import sys
import threading
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Dict, Iterable, Optional


DYNAMIC_APP_DIR_TOKEN = "__APP_DIR__"
WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")


def get_application_dir() -> Path:
    """Returns the launched script/executable directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    main_module = sys.modules.get("__main__")
    main_file = getattr(main_module, "__file__", None)
    if main_file:
        return Path(main_file).resolve().parent

    argv0 = sys.argv[0] if sys.argv else ""
    if argv0:
        try:
            return Path(argv0).resolve().parent
        except Exception:
            pass

    return Path.cwd().resolve()


APP_DIR = get_application_dir()

DEFAULT_COMPONENT_TOGGLE_DEFAULTS = {
    "logging": True,
    "core_dump": True,
    "build": True,
    "screenshots": True,
    "file_transfer": True,
    "workspace": True,
    "help": True,
    "razor": False,
    "profiling": False,
    "android": False,
    "sdk": False,
}

DEFAULT_COMPONENT_ORDER = [
    "logging",
    "core_dump",
    "build",
    "screenshots",
    "file_transfer",
    "workspace",
    "help",
    "razor",
    "profiling",
    "android",
    "sdk",
]

PATH_SETTING_KEYS = {
    "sdk_path",
    "dump_folder",
    "last_build_dir",
    "exec_path",
    "custom_background_image",
}


def get_dynamic_dump_folder() -> str:
    return str(APP_DIR)


def _looks_like_windows_path(value: str) -> bool:
    if not value:
        return False
    return bool(WINDOWS_DRIVE_PATTERN.match(value)) or value.startswith("\\\\")


def _path_flavor(value: str) -> str:
    if _looks_like_windows_path(value):
        return "windows"
    if "\\" in value and "/" not in value:
        return "windows"
    return "posix"


def _pure_path(value: str):
    value = str(value or "").strip()
    if not value:
        return None
    if _path_flavor(value) == "windows":
        return PureWindowsPath(value)
    return PurePosixPath(value)


def normalize_path_for_storage(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    if text == DYNAMIC_APP_DIR_TOKEN:
        return text

    flavor = _path_flavor(text)
    current_is_windows = os.name == "nt"

    # Resolve current-OS paths so stored values are stable and absolute.
    if (current_is_windows and flavor == "windows") or (
        not current_is_windows and flavor == "posix"
    ):
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = APP_DIR / path
        try:
            return os.path.normpath(str(path.resolve(strict=False)))
        except Exception:
            return os.path.normpath(str(path))

    pure = _pure_path(text)
    return str(pure) if pure is not None else text


def _normalized_parts(path_value: str):
    pure = _pure_path(path_value)
    if pure is None:
        return None, ()
    parts = pure.parts
    if isinstance(pure, PureWindowsPath):
        return pure, tuple(part.lower() for part in parts)
    return pure, parts


def _relative_subpath(path_value: str, base_value: str):
    pure_path, cmp_path = _normalized_parts(path_value)
    pure_base, cmp_base = _normalized_parts(base_value)
    if pure_path is None or pure_base is None:
        return None
    if type(pure_path) is not type(pure_base):
        return None
    if len(cmp_path) < len(cmp_base) or cmp_path[: len(cmp_base)] != cmp_base:
        return None
    relative_parts = pure_path.parts[len(pure_base.parts) :]
    if isinstance(pure_path, PureWindowsPath):
        return PureWindowsPath(*relative_parts)
    return PurePosixPath(*relative_parts)


def _join_pure(base_value: str, relative_path) -> str:
    pure_base = _pure_path(base_value)
    if pure_base is None:
        return ""
    if relative_path is None:
        return str(pure_base)
    relative_parts = relative_path.parts
    if isinstance(pure_base, PureWindowsPath):
        return str(PureWindowsPath(pure_base, *relative_parts))
    return str(PurePosixPath(pure_base, *relative_parts))


def project_root_from_build_dir(build_dir: str) -> str:
    pure = _pure_path(build_dir)
    if pure is None:
        return ""
    if pure.name.lower() == "build":
        parent = pure.parent
        if str(parent) not in ("", "."):
            return str(parent)
    return str(pure)


def plan_related_path_updates(
    old_build_dir: str, new_build_dir: str, path_values: Dict[str, str]
) -> Dict[str, str]:
    old_build_dir = normalize_path_for_storage(old_build_dir)
    new_build_dir = normalize_path_for_storage(new_build_dir)
    if not old_build_dir or not new_build_dir or old_build_dir == new_build_dir:
        return {}

    updates: Dict[str, str] = {}
    old_project_root = project_root_from_build_dir(old_build_dir)
    new_project_root = project_root_from_build_dir(new_build_dir)

    for key, raw_value in path_values.items():
        current_value = normalize_path_for_storage(raw_value)
        if not current_value:
            continue

        new_value = None
        relative_to_build = _relative_subpath(current_value, old_build_dir)
        if relative_to_build is not None:
            new_value = _join_pure(new_build_dir, relative_to_build)
        else:
            relative_to_project = _relative_subpath(current_value, old_project_root)
            if relative_to_project is not None:
                new_value = _join_pure(new_project_root, relative_to_project)

        if new_value and new_value != current_value:
            updates[key] = normalize_path_for_storage(new_value)

    return updates


def is_valid_elf_file(path_value) -> bool:
    try:
        path = Path(path_value)
        if not path.is_file():
            return False
        with path.open("rb") as handle:
            return handle.read(4) == b"\x7fELF"
    except Exception:
        return False


def newest_valid_elf_in_directory(directory) -> Optional[Path]:
    try:
        base_path = Path(str(directory or ""))
    except Exception:
        return None

    if not base_path.is_dir():
        return None

    candidates = []
    for path in base_path.iterdir():
        if path.is_file() and path.suffix.lower() == ".elf" and is_valid_elf_file(path):
            candidates.append(path)

    if not candidates:
        return None

    return max(candidates, key=lambda item: item.stat().st_mtime)


def choose_preferred_elf(build_dir, fallback_dirs: Iterable) -> Optional[Path]:
    newest_build = newest_valid_elf_in_directory(build_dir)
    newest_fallback = None

    for directory in fallback_dirs:
        candidate = newest_valid_elf_in_directory(directory)
        if candidate is None:
            continue
        if newest_fallback is None or candidate.stat().st_mtime > newest_fallback.stat().st_mtime:
            newest_fallback = candidate

    if newest_build and newest_fallback:
        if newest_build.stat().st_mtime >= newest_fallback.stat().st_mtime:
            return newest_build
        return newest_fallback

    return newest_build or newest_fallback

# ==========================================
# 1. SETTINGS MANAGER (Workspace Support)
# ==========================================
class SettingsManager:
    DEFAULT_WORKSPACE_NAME = "Default"

    def __init__(self, filename="settings.json"):
        self.filename = filename
        self.lock = threading.Lock()
        
        # Define the default settings for a SINGLE workspace
        self.workspace_defaults = {
            "vita_ip": "192.168.1.21",
            "vita_port": 1337,
            "log_port": 8080,
            "sdk_path": "",
            "dump_folder": DYNAMIC_APP_DIR_TOKEN,
            "last_build_dir": os.getcwd(),
            "launch_title_id": "VHBB00001",
            "font_size": 12, 
            "log_font_size": 11,
            "exec_path": os.path.join(os.getcwd(), "eboot.bin"), 
            "target_app_id": "PCSG00000",
            "base_font_size": 10, # Added for overall app styling
            "theme_name": "default",
            "window_opacity": None,
            "background_image_opacity": None,
            "background_aspect_mode": "",
            "ui_elements_opacity": None,
            "custom_background_image": "",
            "managed_libraries": [],
            "component_toggles": dict(DEFAULT_COMPONENT_TOGGLE_DEFAULTS),
            "component_order": list(DEFAULT_COMPONENT_ORDER),
        }
        
        # Load the overall data structure, which now manages workspaces
        self.data = self.load()

    def _normalize_workspace_data(self, ws_data):
        merged = {**self.workspace_defaults, **ws_data}
        merged["dump_folder"] = DYNAMIC_APP_DIR_TOKEN
        for key in PATH_SETTING_KEYS:
            if key == "dump_folder":
                continue
            merged[key] = normalize_path_for_storage(merged.get(key, ""))
        merged["managed_libraries"] = list(merged.get("managed_libraries", []))
        default_toggles = dict(self.workspace_defaults.get("component_toggles", {}))
        raw_toggles = merged.get("component_toggles", {})
        if not isinstance(raw_toggles, dict):
            raw_toggles = {}
        merged["component_toggles"] = default_toggles | dict(raw_toggles)

        default_order = list(self.workspace_defaults.get("component_order", []))
        for key in merged["component_toggles"]:
            if key not in default_order:
                default_order.append(key)

        valid_keys = set(merged["component_toggles"].keys())
        raw_order = merged.get("component_order", [])
        if not isinstance(raw_order, list):
            raw_order = []
        seen = set()
        normalized_order = []
        for key in raw_order:
            if key in valid_keys and key not in seen:
                normalized_order.append(key)
                seen.add(key)
        for key in default_order:
            if key not in seen:
                normalized_order.append(key)
        merged["component_order"] = normalized_order
        return merged
        
    def load(self):
        """Loads settings from file or creates a new workspace structure if missing."""
        if not os.path.exists(self.filename):
            print(f"Settings file '{self.filename}' not found. Creating default workspace structure.")
            return self._create_initial_structure()

        try:
            with open(self.filename, 'r') as f:
                data = json.load(f)
                
                # Check for legacy (single-config) file structure
                if "workspaces" not in data or "current_workspace" not in data:
                    print("Found legacy settings file. Converting to workspace structure.")
                    
                    # Move all existing keys into the 'Default' workspace
                    default_settings = {k: v for k, v in data.items() if k in self.workspace_defaults}
                    
                    # Merge defaults to ensure new keys exist in the default workspace
                    default_settings = self._normalize_workspace_data(default_settings)
                    
                    return {
                        "current_workspace": self.DEFAULT_WORKSPACE_NAME,
                        "workspaces": {
                            self.DEFAULT_WORKSPACE_NAME: default_settings
                        }
                    }

                # Ensure all workspaces have new default keys
                for name, ws_data in data["workspaces"].items():
                    data["workspaces"][name] = self._normalize_workspace_data(ws_data)
                    
                return data
                
        except json.JSONDecodeError:
            print(f"Error decoding JSON in '{self.filename}'. Creating default structure.")
            return self._create_initial_structure()
        except Exception as e:
            print(f"An unexpected error occurred during loading: {e}. Creating default structure.")
            return self._create_initial_structure()

    def _create_initial_structure(self):
        """Creates the initial data structure with a single Default workspace."""
        initial_data = {
            "current_workspace": self.DEFAULT_WORKSPACE_NAME,
            "workspaces": {
                self.DEFAULT_WORKSPACE_NAME: self._normalize_workspace_data({})
            }
        }
        return initial_data
        
    def save(self):
        """Saves the current workspace data to the file."""
        with self.lock:
            try:
                with open(self.filename, 'w') as f:
                    json.dump(self.data, f, indent=4)
            except Exception as e:
                print(f"Error saving settings file: {e}")

    # --- Core Settings Access (operates on active workspace) ---
    def get(self, key, default=None):
        """Gets a setting from the current workspace."""
        current_name = self.get_current_workspace_name()
        current_ws = self.data["workspaces"].get(current_name, {})
        value = current_ws.get(key, self.workspace_defaults.get(key, default))
        if key == "dump_folder":
            if not value or value == DYNAMIC_APP_DIR_TOKEN:
                return get_dynamic_dump_folder()
            return normalize_path_for_storage(value)
        if key in PATH_SETTING_KEYS:
            return normalize_path_for_storage(value)
        return value

    def set(self, key, value):
        """Sets a setting in the current workspace and saves."""
        current_name = self.get_current_workspace_name()
        if current_name in self.data["workspaces"]:
            if key == "dump_folder":
                value = DYNAMIC_APP_DIR_TOKEN
            elif key in PATH_SETTING_KEYS:
                value = normalize_path_for_storage(value)
            self.data["workspaces"][current_name][key] = value
            self.save()

    # --- Workspace Management Methods ---
    def get_current_workspace_name(self):
        """Returns the name of the currently active workspace."""
        return self.data.get("current_workspace", self.DEFAULT_WORKSPACE_NAME)

    def get_workspaces(self):
        """Returns a list of all workspace names."""
        return list(self.data.get("workspaces", {}).keys())

    def load_workspace(self, name):
        """Sets the given workspace as active."""
        if name in self.data["workspaces"]:
            self.data["current_workspace"] = name
            self.save()
            return True
        return False
            
    def create_workspace(self, name):
        """Creates a new workspace by copying the current settings."""
        if not name or name in self.data["workspaces"]:
            return False
        
        # Deep copy from the currently active settings
        current_settings = self._normalize_workspace_data(
            self.data["workspaces"][self.get_current_workspace_name()]
        )
        self.data["workspaces"][name] = current_settings
        
        # Load the newly created workspace
        self.load_workspace(name)
        return True

    def delete_workspace(self, name):
        """Deletes a workspace."""
        if name == self.DEFAULT_WORKSPACE_NAME:
            return False 
        if name in self.data["workspaces"]:
            del self.data["workspaces"][name]
            
            # If the deleted one was the current one, switch to default
            if self.get_current_workspace_name() == name:
                self.load_workspace(self.DEFAULT_WORKSPACE_NAME)
            else:
                self.save() # Save the deletion
            return True
        return False

# Global instance
settings = SettingsManager()


# ==========================================
# 2. BINARY HELPERS & INDENT (Kept from original utils.py)
# ==========================================
LOG_CALLBACK = print 

def set_log_callback(cb):
    global LOG_CALLBACK
    LOG_CALLBACK = cb

def iprint(text=""):
    indent_spaces = " " * IndentManager.current
    # Ensure a newline is printed for log separation
    LOG_CALLBACK(f"{indent_spaces}{text}\n") 

class IndentManager:
    INDENT_WIDTH = 4
    current = 0
    
    def __enter__(self):
        IndentManager.current += IndentManager.INDENT_WIDTH
    
    def __exit__(self, *args, **kwargs):
        IndentManager.current -= IndentManager.INDENT_WIDTH

def u16(buf, off):
    # Unpack 2 bytes (little-endian)
    val = buf[off:off+2]
    if len(val) < 2: return 0
    return struct.unpack('<H', val)[0]

def u32(buf, off):
    # Unpack 4 bytes (little-endian)
    val = buf[off:off+4]
    if len(val) < 4: return 0
    return struct.unpack('<I', val)[0]

def u64(buf, off):
    # Unpack 8 bytes (little-endian)
    val = buf[off:off+8]
    if len(val) < 8: return 0
    return struct.unpack('<Q', val)[0]

def s32(buf, off):
    # Unpack 4 bytes (signed little-endian)
    val = buf[off:off+4]
    if len(val) < 4: return 0
    return struct.unpack('<i', val)[0]

def s64(buf, off):
    # Unpack 8 bytes (signed little-endian)
    val = buf[off:off+8]
    if len(val) < 8: return 0
    return struct.unpack('<q', val)[0]

def parse_str(buf, off, length):
    return buf[off:off+length].decode('utf-8', errors='ignore').split('\0')[0]
