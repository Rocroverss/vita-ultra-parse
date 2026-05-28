# Custom Components

Drop custom component files in either:

- `components/custom/*.py` (recommended)
- `components/*.py` (top-level, excluding built-in module names)

On app startup, each discovered file is added as a loadable component in **Settings > Component Loading**.

## Minimal examples

### Factory style

```python
from PySide6.QtWidgets import QLabel

COMPONENT_LABEL = "Example 1"

def create_component():
    return QLabel("Hello from custom component")
```

### Class style

```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

COMPONENT_KEY = "example1"
COMPONENT_LABEL = "Example 1"

class ComponentTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Hello from custom component"))
```

Supported optional constructor/factory args by name:

- `settings`
- `cmd_thread`
- `parent`
- `project_root`
- `screenshots_dir`
