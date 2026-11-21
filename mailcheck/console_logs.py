"""Show warnings and errors from every worker's log file in the server window.

Workers write to ``logs/<worker>.log`` (they have no console), so a problem in
one used to be invisible until you opened the file. This follows those files
and prints the warning, error and crash blocks, labelled with the worker's name.
Everything stays in the files too; ``OFFERPATH_CONSOLE_LOG`` picks how much is
shown here (``info``, ``warning`` by default, ``error``, or ``off``).
"""
from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Callable

LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}
# "2026-11-21 04:59:39,607 WARNING name: ..." (our format) or "WARNING:  ..." (uvicorn).
HEADER = re.compile(r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,.]\d+ )?(DEBUG|INFO|WARNING|ERROR|CRITICAL)(?:\b|:)")
BLOCK_START = re.compile(
    r"^(Traceback \(most recent call last\)|Fatal Python error|Windows fatal exception|"
    r"Exception in thread|Current thread|Thread 0x)")
MAX_LINE = 2000


def _default_write(text: str) -> None:
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"), flush=True)
    except OSError:
        pass  # the console went away; never let that stop the server


class _Tracked:
    __slots__ = ("pos", "partial", "in_block")

    def __init__(self, pos: int):
        self.pos, self.partial, self.in_block = pos, b"", False


class ConsoleLogFollower:
    def __init__(self, folder: Path, *, level: str = "warning", exclude: set[str] | None = None,
                 write: Callable[[str], None] | None = None, burst: int = 60, window: float = 10.0,
                 clock: Callable[[], float] = time.monotonic):
        self.folder = Path(folder)
        self.level = LEVELS.get(level.strip().lower()) if level.strip().lower() != "off" else None
        self.exclude = exclude or set()
        self._write = write or _default_write
        self._tracked: dict[Path, _Tracked] = {}
        self._scanned = False
        self._burst, self._window, self._clock = burst, window, clock
        self._window_start, self._printed, self._hidden = clock(), 0, 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        return self.level is not None

    # -- output, with a flood limit so a crash loop cannot bury the window ----
    def _emit(self, name: str, line: str) -> None:
        now = self._clock()
        if now - self._window_start >= self._window:
            self._flush_hidden()
            self._window_start, self._printed = now, 0
        if self._printed >= self._burst:
            self._hidden += 1
            return
        self._printed += 1
        text = line if len(line) <= MAX_LINE else line[:MAX_LINE] + " ..."
        self._write(f"[{name}] {text}")

    def _flush_hidden(self) -> None:
        if self._hidden:
            self._write(f"[logs] ... {self._hidden} more lines hidden to keep this window readable. See the files in {self.folder}")
            self._hidden = 0

    def _handle(self, name: str, state: _Tracked, line: str) -> None:
        match = HEADER.match(line)
        if match:
            level = LEVELS[match.group(1).lower()]
            state.in_block = level >= self.level
            if state.in_block:
                self._emit(name, line)
        elif BLOCK_START.match(line):
            state.in_block = True
            self._emit(name, line)
        elif state.in_block and line.strip():
            self._emit(name, line)

    # -- following the files ---------------------------------------------------
    def tick(self) -> None:
        if not self.enabled:
            return
        try:
            files = sorted(self.folder.glob("*.log"))
        except OSError:
            return
        first_scan = not self._scanned
        self._scanned = True
        for path in files:
            if path.name in self.exclude:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            state = self._tracked.get(path)
            if state is None:
                # History that existed when the server started is not replayed;
                # a log created afterwards is read from its first byte.
                state = self._tracked[path] = _Tracked(size if first_scan else 0)
            if size < state.pos:  # truncated or replaced
                state.pos, state.partial = 0, b""
            if size == state.pos:
                continue
            try:
                with path.open("rb") as stream:
                    if size - state.pos > 1024 * 1024:  # a huge backlog: keep the recent part
                        state.pos = size - 256 * 1024
                        state.partial = b""
                    stream.seek(state.pos)
                    data = stream.read(256 * 1024)
            except OSError:
                continue
            state.pos += len(data)
            *lines, state.partial = (state.partial + data).split(b"\n")
            for raw in lines:
                self._handle(path.stem, state, raw.decode("utf-8", errors="replace").rstrip("\r\n").rstrip())
        now = self._clock()
        if now - self._window_start >= self._window:
            self._flush_hidden()

    def _run(self) -> None:
        while not self._stop.wait(1.0):
            try:
                self.tick()
            except Exception:  # following logs must never take the server down
                logging.getLogger(__name__).debug("Console log follower hit an error.", exc_info=True)

    def start(self) -> None:
        if not self.enabled or self._thread:
            return
        self.tick()  # remember where every log ends right now
        self._write(f"Warnings and errors from every server process appear here. Full logs: {self.folder}")
        self._thread = threading.Thread(target=self._run, name="console-log-follower", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
            try:
                self.tick()  # whatever was written while stopping
            except Exception:
                pass
            self._flush_hidden()
