# Ainos Desktop

A cross-platform desktop GUI for the Ainos AI backend. Built with Python and PySide6 (Qt for Python).

## Features

- **Dashboard**: Real-time system overview with CPU, memory, GPU, and temperature monitoring
- **Model Manager**: Browse, load, unload, and manage AI models with drag-and-drop support
- **Inference Playground**: Interactive chat interface with streaming output and configurable parameters
- **System Monitor**: Detailed performance metrics, process list, and diagnostics tools
- **Context Viewer**: Browse, search, export, and manage inference context history
- **Settings**: Comprehensive configuration for connection, appearance, inference, and logging
- **Log Viewer**: Real-time log stream with filtering and search capabilities
- **Dark/Light Theme**: Toggle between dark and light color schemes
- **System Tray**: Minimize to tray with quick access to common actions

## Requirements

- Python 3.10 or later
- PySide6 >= 6.6.0
- pyqtgraph >= 0.13.3 (for charts)
- psutil >= 5.9.0 (for system monitoring)
- PyYAML >= 6.0 (for configuration)

## Installation

### Using pip

```bash
pip install ainos-desktop
```

### From source

```bash
git clone https://github.com/ainos/desktop.git
cd userland/desktop
pip install -e .
```

### Development install

```bash
pip install -e ".[dev]"
```

## Usage

Run the application:

```bash
ainos-desktop
```

Or directly from source:

```bash
python src/main.py
```

### Command-line options

```
--theme dark|light|system    Initial theme (default: dark)
--config PATH                Path to configuration file
--verbose, -v               Enable verbose logging
--log-file PATH              Path to log file
--no-tray                    Disable system tray icon
--minimized                  Start minimized to system tray
--fullscreen                 Start in fullscreen mode
--geometry WxH or X,Y,WxH   Window geometry
--version                    Show version and exit
```

## Project Structure

```
userland/desktop/
├── src/
│   ├── main.py                 # Application entry point
│   ├── app.py                  # QApplication setup with theme management
│   ├── window.py               # Main window with tab navigation
│   ├── client/                 # Backend client
│   │   ├── ainos_client.py     # Ainos backend client
│   │   ├── transport.py        # TCP transport layer
│   │   └── models.py           # Data models (dataclasses)
│   ├── widgets/                # UI widgets
│   │   ├── dashboard.py        # Dashboard overview
│   │   ├── model_manager.py    # Model management
│   │   ├── inference.py        # Inference playground
│   │   ├── monitor.py          # System monitoring
│   │   ├── context_viewer.py   # Context viewer
│   │   ├── settings.py         # Settings page
│   │   ├── log_viewer.py       # Log viewer
│   │   ├── status_bar.py       # Status bar
│   │   └── charts.py           # Chart components
│   ├── dialogs/                # Dialog windows
│   │   ├── about.py            # About dialog
│   │   ├── model_load.py       # Model loading dialog
│   │   └── settings.py         # Settings dialog
│   ├── theme/                  # Theme definitions
│   │   ├── dark_theme.py       # Dark theme
│   │   ├── light_theme.py      # Light theme
│   │   └── styles.py           # Style manager
│   └── utils/                  # Utilities
│       ├── config.py           # Configuration management
│       └── logger.py           # Logging utilities
├── tests/                      # Unit tests
│   ├── test_dashboard.py
│   ├── test_model_manager.py
│   └── conftest.py
├── requirements.txt
├── setup.py
├── pyproject.toml
└── README.md
```

## License

MIT License - Copyright (c) 2024 Ainos Team