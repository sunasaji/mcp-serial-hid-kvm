"""Configuration for the MCP server (thin client)."""

import os
import platform


def _default_capture_log_dir() -> str:
    """Return the platform-appropriate default directory for capture logs."""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local"))
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return os.path.join(base, "mcp-serial-hid-kvm", "captures")


class Config:
    """Minimal configuration for the MCP thin-client server."""

    def __init__(self):
        # KVM server connection
        self.kvm_host: str = os.environ.get("SHKVM_API_HOST", "127.0.0.1")
        self.kvm_port: int = int(os.environ.get("SHKVM_API_PORT", "9329"))

        # Local OCR
        self.tesseract_cmd: str | None = os.environ.get("MCP_TESSERACT_CMD")

        # Capture log directory
        raw = os.environ.get("MCP_CAPTURE_LOG_DIR")
        if raw is None:
            self.capture_log_dir: str | None = _default_capture_log_dir()
        elif raw == "":
            self.capture_log_dir = None
        else:
            self.capture_log_dir = raw


config = Config()
