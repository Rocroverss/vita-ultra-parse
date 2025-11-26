import struct
import json
import os

# ==========================================
# 1. SETTINGS MANAGER (CORRECTED)
# ==========================================
class SettingsManager:
    def __init__(self, filename="settings.json"):
        self.filename = filename
        self.defaults = {
            "vita_ip": "192.168.1.21",
            "vita_port": 1337,
            "log_port": 8080,
            "sdk_path": "",
            "dump_folder": os.getcwd(),
            "last_build_dir": os.getcwd(),
            "launch_title_id": "VHBB00001",
            # Added for Settings Tab and Style
            "font_size": 12, 
            # Added for Run Executable Sidebar
            "exec_path": os.path.join(os.getcwd(), "eboot.bin"), 
            "target_app_id": "PCSG00000"
        }
        self.data = self.load()

    def load(self):
        if not os.path.exists(self.filename):
            return self.defaults.copy()
        try:
            with open(self.filename, 'r') as f:
                data = json.load(f)
                # Merge with defaults to ensure all required keys exist
                for key, val in self.defaults.items():
                    if key not in data:
                        data[key] = val
                return data
        except Exception:
            return self.defaults.copy()

    def save(self):
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            # Added print for debugging save failures
            print(f"Error saving settings: {e}") 

    # CORRECTED: Takes optional 'default' argument
    def get(self, key, default=None): 
        """Retrieves a setting value, using a provided default if the key is missing."""
        if default is None:
            # Fall back to the internal default if no specific default is provided
            return self.data.get(key, self.defaults.get(key))
        else:
            # Use the provided default value
            return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()

# Global instance
settings = SettingsManager()


# ==========================================
# 2. BINARY HELPERS & INDENT
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

def c_str(buf, off):
    # Read null-terminated string
    if off < 0 or off >= len(buf):
        return ""
    
    end = buf.find(b'\0', off)
    if end == -1:
        end = len(buf)
        
    try:
        return buf[off:end].decode('ascii', errors='ignore')
    except Exception:
        return buf[off:end].decode('latin-1', errors='ignore')