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

# VITADECK
![Current app implementation](IMG/IMG1.png)


# INDEX

* [Vita Ultra Parse](#vita-ultra-parse)
* [VITADECK](#vitadeck)

  * [Features](#features)
  * [Configuration System](#configuration-system)
  * [Bottom Bar Information](#bottom-bar-information)
  * [Quick Commands](#quick-commands)
  * [Components](#components)

    * [Currently Working Components](#currently-working-components)
    * [In Progress](#in-progress)
    * [Planned Features](#planned-features)
  * [Custom Components](#custom-components)

    * [Component Locations](#component-locations)
    * [Minimal Examples](#minimal-examples)

      * [Factory Style](#factory-style)
      * [Class Style](#class-style)
    * [Supported Optional Constructor / Factory Arguments](#supported-optional-constructor--factory-arguments)
* [VitaDeck Setup Guide](#vitadeck-setup-guide)

  * [Requirements](#requirements)
  * [Prepare Your PS Vita](#1-prepare-your-ps-vita)

    * [Install CatLog](#install-catlog)
    * [Install VitaCompanion-VitaDeck](#install-vitacompanion-vitadeck)
  * [Prepare the Workspace and Run VitaDeck](#2-prepare-the-workspace-and-run-vitadeck)

    * [Install Dependencies](#install-dependencies)
    * [Run the Application](#run-the-application)
    * [Initial Setup](#initial-setup)
    * [Generating an ELF File for Crash Parsing](#generating-an-elf-file-for-crash-parsing)
* [Warnings](#warnings)



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


# VitaDeck Setup Guide

## Requirements

Before getting started, make sure you have:

* Python 3.x installed
* A PS Vita with:

  * VitaShell
  * `catlog`
  * the modified `vitacompanion-vitadeck` plugin
* Your PC and PS Vita connected to the same network

---

# 1. Prepare Your PS Vita

## Install CatLog

Make sure your PS Vita is sending logs to the server using `catlog`.

* Repository: https://github.com/isage/catlog
* Ensure both the Vita and the server use the same IP address and port configuration.

---

## Install VitaCompanion-VitaDeck

VitaDeck requires the modified VitaCompanion plugin fork with screenshot and battery command support.

* Repository: https://github.com/Rocroverss/vitacompanion-vitadeck
* Releases: https://github.com/Rocroverss/vitacompanion-vitadeck/releases

### Installation Steps

1. Launch **VitaShell** on your PS Vita.
2. Press `SELECT` to start the FTP server.
3. Copy `vitacompanion.suprx` to:

```text
ur0:/tai/
```

4. Edit:

```text
ur0:/tai/config.txt
```

5. Add the following lines:

```text
*main
ur0:tai/vitacompanion.suprx
```

6. Reboot your PS Vita.

You are now ready to use VitaDeck.

---

# 2. Prepare the Workspace and Run VitaDeck

## Install Dependencies

Install the required Python packages:

```bash
pip install -r requirements.txt
```

---

## Run the Application

Start VitaDeck using:

```bash
python main.py
```

---

Initial Setup

Open the Workspaces tab.

Create a new workspace.

Configure the modules you want to use.

Open Settings and configure the SDK path.

(Optional) Load the ELF file in the Core Dump section for crash parsing support.

Generating an ELF File for Crash Parsing

If your project build is not generating an ELF file, add the following snippet to your CMakeLists.txt.

Replace the paths and executable names with the ones matching your project setup.

# Post-build: copy raw ELF for parsing
add_custom_command(
    TARGET kkr
    POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:kkr> ${CMAKE_BINARY_DIR}/kkr.elf
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:kkr> /home/mint/Desktop/vita-parse-core/kkr.elf
    COMMENT "Copying raw ELF for parsing output"
)

What You Should Change

Replace kkr with your target name.

Replace kkr.elf with your desired ELF filename.

Replace:

/home/mint/Desktop/vita-parse-core/kkr.elf

with the output path you want to use on your system.

Configure the local executable path for the Quick Settings menu if needed.

---

> [!WARNING]
> VitaDeck has been primarily tested on Linux.
> Windows support may work, but it has not been fully tested yet.
