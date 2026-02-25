"""MCP server for KVM control — thin client that delegates to KVM server.

All hardware operations (serial, capture) are delegated to the KVM server
via TCP.  OCR is run locally using frames fetched from the KVM server.
"""

import asyncio
import base64
import datetime
import io
import json
import logging
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    ImageContent,
    Tool,
)

from PIL import Image

from .config import config
from serial_hid_kvm.client import KvmClient, KvmClientError
from .ocr import TerminalOCR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global instances
_client: KvmClient | None = None
_ocr: TerminalOCR | None = None


def get_client() -> KvmClient:
    global _client
    if _client is None:
        _client = KvmClient(config.kvm_host, config.kvm_port)
        _client.connect()
        logger.info("Connected to KVM server")
    return _client


def get_ocr() -> TerminalOCR:
    global _ocr
    if _ocr is None:
        _ocr = TerminalOCR(config.tesseract_cmd)
    return _ocr


def _save_capture_log(image: Image.Image, suffix: str = "") -> str | None:
    """Save a capture image to the log directory if configured."""
    log_dir = config.capture_log_dir
    if log_dir is None:
        return None

    try:
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        tag = f"_{suffix}" if suffix else ""
        filename = f"{ts}{tag}.jpg"
        filepath = os.path.join(log_dir, filename)
        image.save(filepath, format="JPEG", quality=85)
        logger.info(f"Capture log saved: {filepath}")
        return filepath
    except Exception as e:
        logger.warning(f"Failed to save capture log: {e}")
        return None


def _capture_image(quality: int = 85) -> Image.Image:
    """Fetch a frame from KVM server and return as PIL Image."""
    jpeg_bytes, w, h = get_client().capture_frame_jpeg(quality)
    return Image.open(io.BytesIO(jpeg_bytes))


# Create MCP server
app = Server("mcp-serial-hid-kvm")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="type_text",
            description="Type a string as keyboard input on the target PC. Supports inline tags: {enter}, {tab}, {0x87} (raw HID keycode), {ctrl+c}, {shift+0x87}, etc. Use {{ / }} for literal braces. Example: \"ls -la{enter}\"",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text with optional {tag} sequences. Plain chars use the target keyboard layout configured on the KVM server (default: US). Tags: {enter}, {tab}, {f1}-{f12}, {0xNN} for raw HID keycodes, {mod+key} for combos (ctrl+c, shift+0x87).",
                    },
                    "char_delay_ms": {
                        "type": "integer",
                        "description": "Delay between characters in milliseconds (default: 20)",
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="send_key",
            description="Send a single key press with optional modifier keys (e.g., Ctrl+C, Alt+F4).",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Key name: a-z, 0-9, enter, tab, escape, backspace, delete, up, down, left, right, home, end, pageup, pagedown, f1-f12, space, insert, printscreen",
                    },
                    "modifiers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Modifier keys: ctrl, shift, alt, win (gui/super/meta)",
                    },
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="send_key_sequence",
            description="Send a sequence of key steps with optional per-step delays. Useful for complex keyboard operations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string", "description": "Key name"},
                                "modifiers": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Modifier keys",
                                },
                                "delay_ms": {
                                    "type": "integer",
                                    "description": "Delay after this step in ms (default: 100)",
                                },
                            },
                            "required": ["key"],
                        },
                        "description": "List of key steps to execute",
                    },
                    "default_delay_ms": {
                        "type": "integer",
                        "description": "Default delay between steps in ms (default: 100)",
                    },
                },
                "required": ["steps"],
            },
        ),
        Tool(
            name="mouse_move",
            description="Move the mouse cursor on the target PC.",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {
                        "type": "integer",
                        "description": "X coordinate (screen pixels for absolute, offset for relative)",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Y coordinate (screen pixels for absolute, offset for relative)",
                    },
                    "relative": {
                        "type": "boolean",
                        "description": "If true, move relative to current position (default: false)",
                    },
                },
                "required": ["x", "y"],
            },
        ),
        Tool(
            name="mouse_click",
            description="Click a mouse button on the target PC, optionally at a specific position.",
            inputSchema={
                "type": "object",
                "properties": {
                    "button": {
                        "type": "string",
                        "enum": ["left", "right", "middle"],
                        "description": "Mouse button (default: left)",
                    },
                    "x": {
                        "type": "integer",
                        "description": "Optional X screen coordinate to click at",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Optional Y screen coordinate to click at",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="mouse_drag",
            description="Drag from one position to another (press button at start, move to end, release). Useful for drag-and-drop, selecting text, resizing windows, etc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_x": {
                        "type": "integer",
                        "description": "Starting X screen coordinate",
                    },
                    "start_y": {
                        "type": "integer",
                        "description": "Starting Y screen coordinate",
                    },
                    "end_x": {
                        "type": "integer",
                        "description": "Ending X screen coordinate",
                    },
                    "end_y": {
                        "type": "integer",
                        "description": "Ending Y screen coordinate",
                    },
                    "button": {
                        "type": "string",
                        "enum": ["left", "right", "middle"],
                        "description": "Mouse button (default: left)",
                    },
                },
                "required": ["start_x", "start_y", "end_x", "end_y"],
            },
        ),
        Tool(
            name="mouse_scroll",
            description="Scroll the mouse wheel on the target PC.",
            inputSchema={
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "integer",
                        "description": "Scroll amount: positive=up, negative=down (-127 to 127)",
                    },
                },
                "required": ["amount"],
            },
        ),
        Tool(
            name="capture_screen",
            description="Capture the target PC screen via HDMI capture device. Returns the image. Use sparingly as images consume many tokens.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_screen_text",
            description="Capture the target PC screen and extract text using OCR. Prefer this over capture_screen for text content.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="execute_and_read",
            description="Type a command, press Enter, wait for output, then capture screen and OCR. Convenient for running shell commands on the target PC.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to type and execute",
                    },
                    "wait_seconds": {
                        "type": "number",
                        "description": "Seconds to wait for output (default: 1.0)",
                    },
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="get_device_info",
            description="Show connection status and device information for the serial adapter and HDMI capture device.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="list_capture_devices",
            description="List all available video capture devices with their index and name. Use this to find the correct HDMI capture device.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="set_capture_resolution",
            description="Change the HDMI capture resolution. Common values: 1920x1080, 1280x720, 640x480. The actual resolution depends on what the capture device supports.",
            inputSchema={
                "type": "object",
                "properties": {
                    "width": {
                        "type": "integer",
                        "description": "Capture width in pixels (e.g. 1920)",
                    },
                    "height": {
                        "type": "integer",
                        "description": "Capture height in pixels (e.g. 1080)",
                    },
                },
                "required": ["width", "height"],
            },
        ),
        Tool(
            name="set_capture_device",
            description="Switch the active capture device by index or path. Use list_capture_devices first to see available options. Reopens the capture device.",
            inputSchema={
                "type": "object",
                "properties": {
                    "device": {
                        "type": "string",
                        "description": "Device index (e.g. '0', '1') or path (e.g. '/dev/video0')",
                    },
                },
                "required": ["device"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent | ImageContent]:
    """Handle tool calls."""
    try:
        client = get_client()

        if name == "type_text":
            text = arguments["text"]
            char_delay = arguments.get("char_delay_ms")
            result = client.type_text(text, char_delay)
            return [TextContent(type="text", text=f"Typed {len(text)} characters")]

        elif name == "send_key":
            key = arguments["key"]
            modifiers = arguments.get("modifiers", [])
            client.send_key(key, modifiers)
            mod_str = "+".join(modifiers) + "+" if modifiers else ""
            return [TextContent(type="text", text=f"Sent: {mod_str}{key}")]

        elif name == "send_key_sequence":
            steps = arguments["steps"]
            default_delay = arguments.get("default_delay_ms", 100)
            client.send_key_sequence(steps, default_delay)
            return [TextContent(type="text", text=f"Sent {len(steps)} key steps")]

        elif name == "mouse_move":
            x = arguments["x"]
            y = arguments["y"]
            relative = arguments.get("relative", False)
            client.mouse_move(x, y, relative)
            if relative:
                return [TextContent(type="text", text=f"Moved mouse by ({x}, {y})")]
            else:
                return [TextContent(type="text", text=f"Moved mouse to ({x}, {y})")]

        elif name == "mouse_click":
            button = arguments.get("button", "left")
            x = arguments.get("x")
            y = arguments.get("y")
            client.mouse_click(button, x, y)
            pos_str = f" at ({x}, {y})" if x is not None and y is not None else ""
            return [TextContent(type="text", text=f"Clicked {button}{pos_str}")]

        elif name == "mouse_drag":
            start_x = arguments["start_x"]
            start_y = arguments["start_y"]
            end_x = arguments["end_x"]
            end_y = arguments["end_y"]
            button = arguments.get("button", "left")
            client.mouse_down(button, start_x, start_y)
            await asyncio.sleep(0.05)
            client.mouse_move(end_x, end_y)
            await asyncio.sleep(0.05)
            client.mouse_up(button, end_x, end_y)
            return [TextContent(
                type="text",
                text=f"Dragged {button} from ({start_x}, {start_y}) to ({end_x}, {end_y})",
            )]

        elif name == "mouse_scroll":
            amount = arguments["amount"]
            client.mouse_scroll(amount)
            direction = "up" if amount > 0 else "down"
            return [TextContent(type="text", text=f"Scrolled {direction} by {abs(amount)}")]

        elif name == "capture_screen":
            image = _capture_image()
            _save_capture_log(image, "capture")
            # Use JPEG to keep size under 20MB (base64 limit)
            quality = 85
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality)
            # If still too large, reduce quality then resize
            while buffer.tell() > 10_000_000 and quality > 20:
                quality -= 15
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=quality)
            if buffer.tell() > 10_000_000:
                image = image.resize((image.width // 2, image.height // 2))
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=60)
            b64_image = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
            return [ImageContent(
                type="image",
                data=b64_image,
                mimeType="image/jpeg",
            )]

        elif name == "get_screen_text":
            image = _capture_image()
            _save_capture_log(image, "ocr")
            text = get_ocr().extract_text(image)
            return [TextContent(type="text", text=text)]

        elif name == "execute_and_read":
            command = arguments["command"]
            wait_seconds = arguments.get("wait_seconds", 1.0)

            client.type_text(command)
            await asyncio.sleep(0.1)
            client.send_key("enter")
            await asyncio.sleep(wait_seconds)

            image = _capture_image()
            _save_capture_log(image, "exec")
            text = get_ocr().extract_text(image)
            return [TextContent(type="text", text=text)]

        elif name == "get_device_info":
            info = client.get_device_info()
            return [TextContent(
                type="text",
                text=json.dumps(info, indent=2, ensure_ascii=False),
            )]

        elif name == "set_capture_resolution":
            width = arguments["width"]
            height = arguments["height"]
            result = client.set_capture_resolution(width, height)
            cap_info = result.get("info", {})
            return [TextContent(
                type="text",
                text=f"Resolution set: {cap_info.get('width')}x{cap_info.get('height')} (requested {width}x{height})",
            )]

        elif name == "list_capture_devices":
            result = client.list_capture_devices()
            devices = result.get("devices", [])
            if not devices:
                return [TextContent(type="text", text="No capture devices found.")]
            return [TextContent(
                type="text",
                text=json.dumps(devices, indent=2, ensure_ascii=False),
            )]

        elif name == "set_capture_device":
            device = arguments["device"]
            result = client.set_capture_device(device)
            cap_info = result.get("info", {})
            return [TextContent(
                type="text",
                text=f"Switched to device {device}: {cap_info.get('width')}x{cap_info.get('height')} ({cap_info.get('backend')})",
            )]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except KvmClientError as e:
        logger.error(f"KVM server error in tool {name}: {e}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]
    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def run():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main():
    """Entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
