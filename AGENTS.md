# Agent Guidance

## Project Overview

User-space Linux driver for the Huion Keydial Mini Bluetooth input device. Creates a virtual input device via Linux's `uinput` subsystem, translating BLE HID events into keyboard/mouse actions.

**Language:** Python 3.10+  
**Entry Points:** `huion-keydial-mini` (daemon), `keydialctl` (CLI)

## Key Commands

```bash
make install-dev    # Install in dev mode with test deps
make test           # Run pytest
make test-cov       # Run with coverage report
make lint           # Run ruff linter
```

## Directory Structure

```
src/huion_keydial_mini/   # Main source (12 Python modules)
tests/                    # pytest suite with fixtures
packaging/                # Systemd, udev, distro packages
```

## Component Architecture

```
Device (BLE/GATT) → hid_parser.py → keybind_manager.py → uinput_handler.py → /dev/input/*
```

| Module | Responsibility |
|--------|---------------|
| `device.py` | BLE connection lifecycle, D-Bus monitoring |
| `hid_parser.py` | Raw HID byte parsing, combo detection, sticky/held modifiers |
| `keybind_manager.py` | Keybind maps, layers, Unix socket server for runtime config |
| `uinput_handler.py` | Virtual device creation, keyboard/mouse/scroll event emission |
| `bluetooth_watcher.py` | D-Bus signals for device connect/disconnect |
| `config.py` | YAML loading, defaults, per-binding config |
| `keydialctl.py` | CLI for runtime keybind management |
| `main.py` | `DriverManager` daemon lifecycle, signal handling |
| `event_logger.py` | Standalone HID event logger and diagnostic tool |
| `notification.py` | Desktop notification helper (notify-send, used for layer changes) |

## Code Conventions

- **Style:** PEP 8, type hints throughout, async/await for I/O
- **Async:** Use `asyncio`, `bleak` for BLE, `dbus_next` for D-Bus
- **Testing:** pytest + pytest-asyncio, mocks in `conftest.py`
- **Linting:** ruff (configured in `pyproject.toml`, run via `make lint`)

## Adding Features

1. **New HID event type:** Edit `hid_parser.py` - parse bytes in `_parse_button_events()` or `_parse_dial_events()`, emit binding key via `parse()`
2. **New action type:** Add an `EventType` variant to `keybind_manager.py`, register it in `event_type_for_keys()`, add the dispatch case in `uinput_handler.py`. For scroll-style actions, also add a token to `SCROLL_ACTIONS`.
3. **New config option:** Add to `DEFAULT_CONFIG` in `config.py`, reference in relevant module
4. **DBus integration:** Modify `bluetooth_watcher.py` - uses `dbus_next` ServiceWatcher

## Testing Strategy

- Unit tests in `tests/` mirror source structure (`test_hid_parser.py`, etc.)
- Use `conftest.py` fixtures for mock BLE devices, mock uinput
- Run specific test: `pytest tests/test_hid_parser.py`
- Integration tests require a real device or mocked BLE server

## Configuration

YAML-based, loaded from `~/.config/huion-keydial-mini/config.yaml`. Defaults in `packaging/config.yaml.default`. Key top-level fields:

| Field | Description |
|-------|-------------|
| `device_address` | BLE MAC address (auto-discovers if null) |
| `key_mappings` | Button → key/combo bindings (`BUTTON_1: "KEY_F1"`) |
| `sticky_key_mappings` | Legacy sticky bindings (prefer held-modifier support in `key_mappings`) |
| `dial_settings` | `DIAL_CW`, `DIAL_CCW`, `DIAL_CLICK` actions + `sensitivity` multiplier |
| `layers` | List of layer dicts (each has `name`, `key_mappings`, `sticky_key_mappings`, `dial_settings`); omit to use single-layer flat config |
| `uinput_device_name` | Name of the created virtual input device |
| `connection_timeout` | BLE connection timeout in seconds (default 10.0) |
| `debug_mode` | Verbose logging when true |

Scroll actions are expressed as action tokens inside `key_mappings`/`dial_settings` (e.g. `DIAL_CW: "SCROLL_UP"`), not as a separate config section.

### Layer System

Layers cycle via `LAYER_NEXT` bound to any button/dial action. The driver starts at layer 0. Each layer inherits bindings from the layer below (only define overrides). Use `keydialctl layer show` / `keydialctl layer next` for runtime control.

## Runtime Configuration

The daemon listens on a Unix socket for live keybind updates. Use `keydialctl` to modify bindings without restarting the service.

**Socket path:** `~/.local/share/huion-keydial-mini/control.sock`

## See Also

- `ARCHITECTURE.md` — data flow, auto-connection detection, security model
- `CONTRIBUTING.md` — development setup, testing tools, code style
- `TROUBLESHOOTING.md` — common issues and diagnostic steps
