"""Colors for the server window, so a problem stands out from routine output.

critical  white on red, bold      the server cannot continue
error     bright red              something failed
warning   yellow                  needs attention, still running
success   green                   started, ready, completed
info      cyan                    routine progress
debug     dim gray                detail

Colors are used only on a real terminal, never when ``NO_COLOR`` is set, and
``OFFERPATH_COLOR=always`` or ``never`` overrides the detection.
"""
from __future__ import annotations

import logging
import os
import re
import sys

RESET = "\x1b[0m"
STYLES = {
    "critical": "\x1b[1;97;41m",
    "error": "\x1b[91m",
    "warning": "\x1b[93m",
    "success": "\x1b[92m",
    "info": "\x1b[96m",
    "debug": "\x1b[90m",
    "label": "\x1b[1;95m",   # the [worker] prefix
}
SUCCESS = re.compile(r"\b(ready|started|completed?|recovered|healthy|connected|saved|ok)\b", re.I)
_enabled: bool | None = None


def _enable_windows_vt() -> bool:
    """Turn on ANSI escape handling for this console (Windows 10+)."""
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def enabled() -> bool:
    global _enabled
    if _enabled is None:
        choice = os.environ.get("OFFERPATH_COLOR", "").strip().lower()
        if choice == "never" or "NO_COLOR" in os.environ:
            _enabled = False
        elif choice == "always":
            _enabled = True
        else:
            try:
                tty = sys.stdout.isatty()
            except Exception:
                tty = False
            _enabled = tty and (sys.platform != "win32" or _enable_windows_vt())
    return _enabled


def paint(text: str, kind: str) -> str:
    if not enabled() or kind not in STYLES:
        return text
    return f"{STYLES[kind]}{text}{RESET}"


def kind_for(level: str, message: str = "") -> str:
    """The color kind for a log level; routine INFO that reports success is green."""
    kind = level.lower()
    if kind == "info" and SUCCESS.search(message):
        return "success"
    return kind if kind in STYLES else "info"


class ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        return paint(text, kind_for(record.levelname, record.getMessage()))
