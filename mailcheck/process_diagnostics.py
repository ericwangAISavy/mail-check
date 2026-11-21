"""Make server problems visible: readable log lines, crash reports and exit explanations.

Every OfferPath process (the gateway and each worker) calls ``configure_process``
once at start. Afterwards a warning or error carries a timestamp, level and
source; an exception nobody catches is logged with its traceback instead of
vanishing; and a hard crash (a segfault or fatal interpreter error) writes the
stack of every thread. Worker output goes to ``logs/<worker>.log`` and the
server window mirrors the warnings and errors from those files.
"""
from __future__ import annotations

import faulthandler
import logging
import os
import signal
import sys
import threading
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configured = False


def _level(name: str | None, default: int) -> int:
    value = logging.getLevelName((name or "").strip().upper())
    return value if isinstance(value, int) else default


def configure_process(role: str) -> None:
    """Idempotent. ``OFFERPATH_LOG_LEVEL`` (DEBUG/INFO/WARNING/ERROR) sets the detail."""
    global _configured
    if _configured:
        return
    _configured = True
    root = logging.getLogger()
    if not any(getattr(handler, "_offerpath", False) for handler in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        handler._offerpath = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.setLevel(_level(os.environ.get("OFFERPATH_LOG_LEVEL"), logging.WARNING))
    logging.captureWarnings(True)
    log = logging.getLogger(role)

    def unhandled(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Unhandled exception: the %s process is stopping.", role, exc_info=(exc_type, exc, tb))

    def unhandled_in_thread(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "unknown"
        log.error("Unhandled exception in thread %s.", name,
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    def unraisable(args):
        log.error("Unraisable exception in %r.", args.object,
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = unhandled
    threading.excepthook = unhandled_in_thread
    sys.unraisablehook = unraisable
    try:
        # A native crash cannot be caught, but it can leave every thread's stack.
        faulthandler.enable(all_threads=True)
    except (AttributeError, OSError, RuntimeError, ValueError):
        pass


# Windows exit statuses that mean something specific (NTSTATUS values).
_WINDOWS = {
    0xC000013A: "interrupted (Ctrl+C, or its console was closed)",
    0xC0000005: "access violation (a native crash)",
    0xC00000FD: "stack overflow",
    0xC0000409: "fast-fail / stack buffer overrun (a native crash)",
    0xC0000374: "heap corruption (a native crash)",
    0xC000001D: "illegal instruction (a native crash)",
    0xC0000142: "a required library failed to initialise",
    0xC0000017: "not enough memory",
    0xFFFFFFFF: "ended from outside (Task Manager, taskkill or a forced stop)",
}


def describe_exit(code: int | None) -> str:
    """A process exit status in words."""
    if code is None:
        return "still running"
    if code == 0:
        return "exit code 0 (stopped cleanly)"
    if code < 0:  # POSIX: terminated by a signal
        try:
            return f"killed by {signal.Signals(-code).name}"
        except ValueError:
            return f"killed by signal {-code}"
    if code in _WINDOWS:
        return f"exit code {code} (0x{code:08X}): {_WINDOWS[code]}"
    if code >= 0x80000000:
        return f"exit code {code} (0x{code:08X}): a Windows error status"
    return f"exit code {code} (the process reported an error)"


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def tail_lines(path: str | os.PathLike, count: int = 12, window: int = 32 * 1024, start: int = 0) -> str:
    """The last ``count`` non-empty lines of a text file written after byte ``start``, or ''."""
    try:
        with Path(path).open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(start, size - window, 0))
            data = stream.read()
    except OSError:
        return ""
    lines = [line.rstrip() for line in data.decode("utf-8", errors="replace").splitlines() if line.strip()]
    return "\n".join(lines[-count:])
