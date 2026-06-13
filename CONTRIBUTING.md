# Contributing to Huion Keydial Mini Driver

Thank you for your interest in contributing to the Huion Keydial Mini driver! This document provides guidelines for contributing to the project.

## Getting Started

### Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Triforcey/huion-keydial-mini-uinput.git
   cd huion-keydial-mini-uinput
   ```

2. **Set up development environment**:
   ```bash
   # Install in development mode with test and dev dependencies
   pip install -e ".[test,dev]"
   ```

3. **Install system dependencies**:
   ```bash
   # Install udev rules (for testing)
   sudo make install-udev

   # Add user to input group
   sudo usermod -a -G input $USER
   ```

### Building from Source

```bash
# Install in development mode with all dependencies
pip install -e ".[test,dev]"

# Run tests
make test

# Build a wheel
make build
```

## Testing

### Running Tests

```bash
# Run all tests
python -m pytest tests/

# Run with coverage
python -m pytest tests/ --cov=huion_keydial_mini

# Run specific test file
python -m pytest tests/test_hid_parser.py -v
```

### Testing Tools

```bash
# Test event logger
python -m huion_keydial_mini.event_logger --test

# Test with debug logging
python -m huion_keydial_mini --log-level DEBUG

# Test HID diagnostic tool
python diagnose_hid.py

# Test HID parser with sample data
python src/huion_keydial_mini/debug_parser.py

# Interactive HID parser test
python src/huion_keydial_mini/debug_parser.py --interactive
```

### Manual Testing

1. **Test device connection**:
   ```bash
   # Start service in debug mode
   python -m huion_keydial_mini --log-level DEBUG

   # Connect device and verify events
   bluetoothctl connect AA:BB:CC:DD:EE:FF
   ```

2. **Test key bindings**:
   ```bash
   # Set up test bindings
   keydialctl bind BUTTON_1 KEY_F1
   keydialctl bind DIAL_CW KEY_VOLUMEUP

   # Test functionality
   keydialctl list-bindings
   ```

### Running the Driver for Development

```bash
# Run the driver directly (requires sudo)
sudo python -m huion_keydial_mini

# Run with debug logging
sudo python -m huion_keydial_mini --log-level DEBUG

# Run event logger to see parsed events
sudo python -m huion_keydial_mini.event_logger
```

## Code Style

### Python Style Guide

- **Follow PEP 8** for Python code style
- **Use type hints** for function parameters and return values
- **Document functions** with docstrings
- **Keep functions focused** and reasonably sized

### Code Formatting

The project uses [ruff](https://docs.astral.sh/ruff/) for linting and import sorting. It is included in the `dev` extras (`pip install -e ".[dev]"`).

```bash
# Check for lint errors
make lint
# or: ruff check src/ tests/

# Auto-fix safe violations (unused imports, import sorting)
ruff check src/ tests/ --fix

# Check for dependency issues
pip check
```

Ruff is configured in `pyproject.toml` (`[tool.ruff]`). Line length is 120. Selected rules: `E` (pycodestyle errors), `F` (pyflakes), `W` (pycodestyle warnings), `I` (isort).

### Example Code Style

```python
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

def parse_hid_data(data: bytes) -> Optional[List[InputEvent]]:
    """Parse HID data into input events.

    Args:
        data: Raw HID data bytes

    Returns:
        List of input events, or None if parsing failed
    """
    if not data:
        logger.warning("Empty HID data received")
        return None

    # Implementation here
    return events
```

## Development Workflow

### Branch Strategy

1. **Fork the repository** to your GitHub account
2. **Create a feature branch** from main:
   ```bash
   git checkout -b feature/my-new-feature
   ```
3. **Make your changes** with appropriate tests
4. **Commit with descriptive messages**:
   ```bash
   git commit -m "Add support for additional button mappings"
   ```
5. **Push to your fork**:
   ```bash
   git push origin feature/my-new-feature
   ```
6. **Create a pull request** against the main branch

### Commit Messages

- Use **present tense** ("Add feature" not "Added feature")
- Use **imperative mood** ("Move cursor to..." not "Moves cursor to...")
- **Limit first line** to 72 characters or less
- **Reference issues** when applicable: "Fix #123: Handle device disconnection"

### Pull Request Process

1. **Ensure tests pass**: Run the full test suite
2. **Update documentation**: Update README, docstrings, etc.
3. **Add tests**: Include tests for new functionality
4. **Keep changes focused**: One feature/fix per pull request
5. **Respond to reviews**: Address feedback promptly

## Project Structure

```
huion-keydial-mini-uinput/
├── src/huion_keydial_mini/     # Main source code
│   ├── __init__.py
│   ├── __main__.py             # Package entry point (delegates to main.py)
│   ├── bluetooth_watcher.py    # D-Bus device connect/disconnect monitoring
│   ├── config.py               # YAML config loading and defaults
│   ├── device.py               # BLE connection lifecycle
│   ├── event_logger.py         # Standalone HID event logger / diagnostic tool
│   ├── hid_parser.py           # Raw HID byte parsing, combos, sticky/held modifiers
│   ├── keybind_manager.py      # Keybind maps, layers, Unix socket server
│   ├── keydialctl.py           # CLI for runtime keybind management
│   ├── main.py                 # DriverManager lifecycle (daemon entry point)
│   ├── notification.py         # Desktop notification helper (notify-send)
│   └── uinput_handler.py       # Virtual input device creation and event emission
├── tests/                      # pytest test suite
├── packaging/                  # Systemd, udev, distro packages
└── README.md                   # Main documentation
```

## Areas for Contribution

### High Priority

- **Bug fixes**: Address reported issues
- **Device compatibility**: Support for additional Huion devices
- **Performance improvements**: Optimize event processing
- **Documentation**: Improve user and developer docs

### Medium Priority

- **New features**: Additional action types, advanced bindings
- **Testing**: Expand test coverage
- **Packaging**: Support for additional distributions
- **Error handling**: Better error messages and recovery

### Low Priority

- **UI improvements**: Better CLI interface
- **Monitoring**: Health checks and metrics
- **Logging**: Enhanced logging capabilities

## Reporting Issues

### Before Reporting

1. **Search existing issues** to avoid duplicates
2. **Test with latest version** to ensure issue still exists
3. **Gather debugging information** using provided tools

### Issue Template

When reporting bugs, include:

- **System information**: OS, kernel version, Python version
- **Device information**: Model, firmware version if available
- **Complete logs**: Full service logs showing the error
- **Steps to reproduce**: Exact steps that trigger the issue
- **Configuration**: Your config file (remove sensitive info)

### Feature Requests

For feature requests, include:

- **Use case**: Why is this feature needed?
- **Proposed solution**: How should it work?
- **Alternatives**: What other approaches were considered?
- **Impact**: Who would benefit from this feature?

## Code Review Guidelines

### For Contributors

- **Self-review**: Review your own code before submitting
- **Test thoroughly**: Ensure all tests pass
- **Document changes**: Update relevant documentation
- **Be responsive**: Address review feedback promptly

### For Reviewers

- **Be constructive**: Provide helpful feedback
- **Focus on code quality**: Check for bugs, performance, maintainability
- **Respect contributors**: Be polite and professional
- **Test changes**: Verify functionality when possible

## Release Process

1. **Version bump**: Update version in relevant files
2. **Update changelog**: Document changes since last release
3. **Tag release**: Create annotated git tag
4. **Build packages**: Generate distribution packages
5. **Publish**: Upload to package repositories

## License

By contributing to this project, you agree that your contributions will be licensed under the MIT License.

## Questions?

If you have questions about contributing:

1. **Check existing documentation** first
2. **Search closed issues** for similar questions
3. **Open a discussion** on GitHub
4. **Ask in pull request** if specific to your changes
