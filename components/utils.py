import struct
import json
import os
import threading

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
            "dump_folder": os.getcwd(),
            "last_build_dir": os.getcwd(),
            "launch_title_id": "VHBB00001",
            "font_size": 12, 
            "log_font_size": 11,
            "exec_path": os.path.join(os.getcwd(), "eboot.bin"), 
            "target_app_id": "PCSG00000",
            "base_font_size": 10, # Added for overall app styling
            "theme_name": "default",
            "window_opacity": 1.0,
            "background_image_opacity": 1.0,
            "background_aspect_mode": "keep",
            "ui_elements_opacity": 1.0,
            "managed_libraries": [],
            "component_toggles": {
                "workspace": True,
                "help": True,
                "logging": True,
                "core_dump": True,
                "razor": True,
                "profiling": True,
                "android": True,
                "screenshots": True,
                "build": True,
                "sdk": True,
                "file_transfer": True,
            },
            "component_order": [
                "workspace",
                "help",
                "logging",
                "core_dump",
                "razor",
                "profiling",
                "android",
                "screenshots",
                "build",
                "sdk",
                "file_transfer",
            ],
        }
        
        # Load the overall data structure, which now manages workspaces
        self.data = self.load()

    def _normalize_workspace_data(self, ws_data):
        merged = {**self.workspace_defaults, **ws_data}
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
        return current_ws.get(key, self.workspace_defaults.get(key, default))

    def set(self, key, value):
        """Sets a setting in the current workspace and saves."""
        current_name = self.get_current_workspace_name()
        if current_name in self.data["workspaces"]:
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
