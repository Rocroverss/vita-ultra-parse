# Vita Ultra Parse

A development utility suite for the **PS Vita**, inspired by a screenshot shared on the Vita Nuova Discord by the talented developer gl33ntwine:
[v-atamanenko GitHub](https://github.com/v-atamanenko)

![Original idea](IMG/vitadeck.png)

> [!WARNING]
> This application was developed in Python and is still evolving.
> Feel free to modify it, extend it, and add your own modules.
>
> AI tools were used to help reorganize parts of the codebase after the application became functional. While the project is working, unexpected bugs or edge cases may still exist.

---


# APP
![Current app implementation](IMG/IMG1.png)

# Features

## Configuration System

Current configuration support includes:

![Configuration buttons](IMG/IMG2.png)

* Workspace management

Here you can create delete and load projects you are working on.

![Workspace management](IMG/IMG3.png)

* Basic help and information

* Settings panel with:

  * SDK configuration
  * Server listening ports
  * Theme support (custom themes can be added)
  * Component enable/disable system from the Components tab

![Theme  and component enable/disable](IMG/IMG4.png)

---

# Bottom Bar Information

The bottom status bar currently displays:

* PS Vita battery status
* Connection status
* File transfer activity
* Local PC IP address (useful to verify both devices are on the same network)

![Bottom status bar](IMG/IMG5.png)

---

# Quick Commands

Available quick actions:

* Connect to the console via FTP
* Retrieve the latest crash dump and perform core dump analysis
* Send compiled executables (`eboot.bin`) to the console and execute them
* Open a custom application
* Quit all running applications
* Reboot the console
* Capture screenshots
  * Screenshots are stored in the `screenshots` folder
* Turn the screen on/off
* Launch an application using a specific Title ID

![Available quick actions](IMG/IMG6.png)

---

# Components

## Currently Working Components

* PS Vita logging to PC
* Core dump and crash analysis
* Screenshot capture
* Project build support and build directory management
* FTP file transfer

---

## In Progress

* Basic SDK configuration tools

---

## Planned Features

* Razor capture management
* Profiling tools and performance analysis

---

# Custom Components

To create your own module, use the example located at:

```text
vita-ultra-parse/components/custom/example1.py
```

Edit it to fit your needs.

---

## Component Locations

Drop custom component files into either:

```text
components/custom/*.py
```

Recommended location.

Or:

```text
components/*.py
```

Top-level components excluding built-in module names.

On application startup, each discovered file is automatically added as a loadable component under:

```text
Settings > Component Loading
```

---

# Minimal Examples

## Factory Style

```python
from PySide6.QtWidgets import QLabel

COMPONENT_LABEL = "Example 1"

def create_component():
    return QLabel("Hello from custom component")
```

---

## Class Style

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

---

# Supported Optional Constructor / Factory Arguments

Custom components may optionally receive the following arguments by name:

* `settings`
* `cmd_thread`
* `parent`
* `project_root`
* `screenshots_dir`

---
