import re
from pathlib import Path
from typing import Any, Dict


class Theme:
    def __init__(self, name: str, theme_dir: Path, parsed_sections: Dict[str, Dict[str, str]]):
        self.name: str = name
        self.theme_dir: Path = theme_dir
        self.base_dir: str = str(theme_dir)
        self.parsed_sections = parsed_sections

        self.opacity: float = 1.0
        self.image_opacity: float = 1.0
        self.image_location: str = "none"
        self.aspect_ratio_mode: str = "keep"
        self.color_palette: Dict[str, str] = {}
        self.palette: Dict[str, str] = {}
        self.icons: Dict[str, str] = {}
        self.background_settings: Dict[str, str] = {}

        self._load_config()
        self._load_palette()
        self._load_icons()

    def load(self):
        self._load_config()
        self._load_palette()
        self._load_icons()

    def _parse_theme_line(self, line: str, key_name: str, default_value: Any) -> Any:
        match = re.search(fr"^{re.escape(key_name)}\s*=\s*([^\s#]+)", line, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return default_value

    def _load_config(self):
        config_path = self.theme_dir / "theme.txt"

        if not config_path.is_file():
            print(f"Error: Theme config file not found at {config_path}")
            return

        try:
            content = config_path.read_text()
        except Exception as e:
            print(f"Error reading theme config: {e}")
            return

        lines = content.splitlines()

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if line.lower().startswith("opacity"):
                val = self._parse_theme_line(line, "opacity", "1.0")
                try:
                    self.opacity = float(val)
                except ValueError:
                    self.opacity = 1.0

            elif line.lower().startswith("image_opacity"):
                val = self._parse_theme_line(line, "image_opacity", "1.0")
                try:
                    self.image_opacity = float(val)
                except ValueError:
                    self.image_opacity = 1.0

            elif line.lower().startswith("image_location"):
                self.image_location = self._parse_theme_line(line, "image_location", "none")

            elif line.lower().startswith("aspect_ratio_mode"):
                self.aspect_ratio_mode = self._parse_theme_line(
                    line, "aspect_ratio_mode", "keep"
                ).lower()

        self.background_settings = {
            "opacity": str(self.opacity),
            "image_opacity": str(self.image_opacity),
            "image_location": self.image_location,
            "aspect_ratio_mode": self.aspect_ratio_mode,
        }

    def _load_palette(self):
        theme_file = self.theme_dir / "theme.txt"
        palette: Dict[str, str] = {}

        if theme_file.exists():
            try:
                with open(theme_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or line.startswith("//"):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                        elif ":" in line:
                            key, val = line.split(":", 1)
                        else:
                            continue
                        palette[key.strip()] = val.strip()
            except Exception as e:
                print(f"Warning: failed to read theme file '{theme_file}': {e}")

        self.palette = palette
        self.color_palette = palette

    def _load_icons(self):
        def icon_path(filename: str) -> str:
            return str(self.theme_dir / filename)

        self.icons = {
            "workspace": icon_path("alt-workspace.svg"),
            "settings": icon_path("alt-setting.svg"),
            "help": icon_path("alt-info.svg"),
            "refresh": icon_path("alt-refresh.svg"),
            "terminal": icon_path("alt-terminal.svg"),
            "folder": icon_path("alt-folder.svg"),
            "save": icon_path("alt-save-floppy.svg"),
            "search": icon_path("alt-search.svg"),
            "trash": icon_path("alt-trash.svg"),
            "clipboard": icon_path("alt-clipboard.svg"),
        }
