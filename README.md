# mcp-serial-hid-kvm

MCP (Model Context Protocol) server that gives AI agents full keyboard, mouse, and screen access to a physical PC. Thin client for [serial-hid-kvm](https://github.com/sunasaji/serial-hid-kvm) — all hardware control is delegated via TCP.

## How It Works

```
Claude / AI Agent
  ↕ MCP (stdio)
mcp-serial-hid-kvm        ← this package (thin client + OCR)
  ↕ TCP (localhost:9329)
serial-hid-kvm             ← standalone KVM server (owns hardware)
  ↕ USB Serial + HDMI
Target PC
```

The KVM server (`serial-hid-kvm`) runs as a persistent process owning the serial port and capture device. This MCP server connects to it as a TCP client. Multiple MCP instances (multiple Claude sessions) can share a single KVM server without device conflicts.

## Prerequisites

1. **Hardware**: CH9329+CH340 USB HID cable + USB HDMI capture device (see [serial-hid-kvm](https://github.com/sunasaji/serial-hid-kvm) for details)
2. **serial-hid-kvm** installed and running:
   ```bash
   pip install -e /path/to/serial-hid-kvm
   serial-hid-kvm --api              # with preview window
   serial-hid-kvm --api --headless   # or headless
   ```
3. **Tesseract OCR** (for `get_screen_text` / `execute_and_read`):
   - Linux: `sudo apt install tesseract-ocr`
   - Windows: https://github.com/tesseract-ocr/tesseract

## Installation

```bash
pip install -e .
```

This automatically installs `serial-hid-kvm` as a dependency.

## MCP Client Configuration

### Claude Desktop / Claude Code

```json
{
  "mcpServers": {
    "kvm": {
      "command": "mcp-serial-hid-kvm"
    }
  }
}
```

Custom KVM server address:

```json
{
  "mcpServers": {
    "kvm": {
      "command": "mcp-serial-hid-kvm",
      "env": {
        "SHKVM_API_HOST": "127.0.0.1",
        "SHKVM_API_PORT": "9329"
      }
    }
  }
}
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SHKVM_API_HOST` | `127.0.0.1` | KVM server address |
| `SHKVM_API_PORT` | `9329` | KVM server port |
| `MCP_TESSERACT_CMD` | auto-detect | Path to tesseract executable |
| `MCP_CAPTURE_LOG_DIR` | platform default | Capture log directory (empty string to disable) |

Hardware settings (`SHKVM_SERIAL_PORT`, `SHKVM_SCREEN_WIDTH`, etc.) are configured on the **KVM server side**, not here. If the target PC uses a non-US keyboard, set `--target-layout` (or `SHKVM_TARGET_LAYOUT`) on the KVM server so that `type_text` and `send_key` produce correct characters.

## Available Tools

### Keyboard

| Tool | Description |
|------|-------------|
| `type_text` | Type text with inline tags: `ls -la{enter}`, `{ctrl+c}`, `{alt+f4}` |
| `send_key` | Single key press with modifiers |
| `send_key_sequence` | Multiple key steps with per-step delays |

### Mouse

| Tool | Description |
|------|-------------|
| `mouse_move` | Move cursor (absolute or relative) |
| `mouse_click` | Click at optional position |
| `mouse_drag` | Drag from one position to another (drag-and-drop, text selection, etc.) |
| `mouse_scroll` | Scroll wheel |

### Screen

| Tool | Description |
|------|-------------|
| `capture_screen` | Capture screen as image (high token cost) |
| `get_screen_text` | Capture + OCR to text (preferred for text content) |
| `execute_and_read` | Type command, Enter, wait, capture + OCR |

### Device Management

| Tool | Description |
|------|-------------|
| `get_device_info` | Serial port, capture device, config info |
| `list_capture_devices` | List available video devices |
| `set_capture_device` | Switch capture device |
| `set_capture_resolution` | Change capture resolution |

## Architecture

This package is intentionally minimal (~4 files):

```
mcp_serial_hid_kvm/
  server.py    MCP tool handlers → KvmClient TCP calls
  config.py    KVM host/port, tesseract, log settings
  ocr.py       Tesseract OCR (runs locally on fetched frames)
  __init__.py
```

All keyboard/mouse/capture logic lives in `serial-hid-kvm`. This package only translates MCP tool calls to TCP API calls and runs OCR locally.

### Why Separate?

- **No device conflicts** — multiple Claude sessions share one KVM server
- **Independent restarts** — restart the MCP server without losing the KVM connection
- **Standalone use** — `serial-hid-kvm` works without MCP (interactive preview, scripts, other AI frameworks)

## License

[MIT](LICENSE.txt)
