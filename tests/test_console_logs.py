import logging
from types import SimpleNamespace
from unittest.mock import Mock

from mailcheck.console_logs import ConsoleLogFollower
from mailcheck.workspace_workers import Worker, WorkerPool


def follower(folder, level="warning", **kwargs):
    out = []
    return ConsoleLogFollower(folder, level=level, write=out.append, **kwargs), out


def append(path, text):
    with path.open("ab") as stream:
        stream.write(text.encode())


STAMP = "2026-11-21 04:59:39,607"


def test_shows_warnings_errors_and_whole_tracebacks_with_the_worker_name(tmp_path):
    log = tmp_path / "shared-api-0.log"
    append(log, f"{STAMP} ERROR old.problem: from before the server started\n")
    f, out = follower(tmp_path)
    f.tick()                                     # remembers where the log ends; history is not replayed
    assert out == []
    append(log, f"{STAMP} INFO mailcheck.x: routine detail\n"
                f"INFO:     Started server process [4684]\n"
                f"{STAMP} WARNING mailcheck.x: slow request\n"
                f"WARNING:  uvicorn says careful\n"
                f"{STAMP} ERROR mailcheck.x: operation failed\n"
                "Traceback (most recent call last):\n"
                '  File "x.py", line 3, in run\n'
                "ValueError: bad value\n"
                f"{STAMP} INFO mailcheck.x: back to normal\n"
                "   an indented line of the quiet INFO message\n")
    f.tick()
    assert out == [
        f"[shared-api-0] {STAMP} WARNING mailcheck.x: slow request",
        "[shared-api-0] WARNING:  uvicorn says careful",
        f"[shared-api-0] {STAMP} ERROR mailcheck.x: operation failed",
        "[shared-api-0] Traceback (most recent call last):",
        '[shared-api-0]   File "x.py", line 3, in run',
        "[shared-api-0] ValueError: bad value",
    ]


def test_native_crash_dumps_are_shown_and_levels_can_be_changed(tmp_path):
    log = tmp_path / "shared-job-collection-1.log"
    f, out = follower(tmp_path)
    f.tick()
    append(log, "Windows fatal exception: access violation\n\nCurrent thread 0x0000a1 (most recent call first):\n"
                '  File "runtime.py", line 12 in run\n')
    f.tick()
    assert out[0] == "[shared-job-collection-1] Windows fatal exception: access violation"
    assert "[shared-job-collection-1]   File \"runtime.py\", line 12 in run" in out

    quiet, quiet_out = follower(tmp_path, level="error")
    quiet.tick()
    append(log, f"{STAMP} WARNING a: warning\n{STAMP} ERROR a: error\n")
    quiet.tick()
    assert quiet_out == [f"[shared-job-collection-1] {STAMP} ERROR a: error"]

    chatty, chatty_out = follower(tmp_path, level="info")
    chatty.tick()
    append(log, f"{STAMP} INFO a: shown at info level\n")
    chatty.tick()
    assert chatty_out == [f"[shared-job-collection-1] {STAMP} INFO a: shown at info level"]

    off, off_out = follower(tmp_path, level="off")
    off.start()
    off.tick()
    assert not off.enabled and off_out == []


def test_new_logs_are_read_from_the_start_truncation_is_handled_and_excluded_files_are_skipped(tmp_path):
    f, out = follower(tmp_path, exclude={"origin-supervisor.log"})
    f.tick()
    append(tmp_path / "shared-api-1.log", f"{STAMP} ERROR a: first error from a brand new worker log\n")
    append(tmp_path / "origin-supervisor.log", f"{STAMP} ERROR supervisor: already printed in the window\n")
    f.tick()
    assert out == [f"[shared-api-1] {STAMP} ERROR a: first error from a brand new worker log"]
    (tmp_path / "shared-api-1.log").write_bytes(f"{STAMP} ERROR a: after the log was replaced\n".encode())
    f.tick()
    assert out[-1] == f"[shared-api-1] {STAMP} ERROR a: after the log was replaced"
    # A line that is still being written is held back until it is complete.
    append(tmp_path / "shared-api-1.log", f"{STAMP} ERROR a: half writ")
    f.tick()
    assert len(out) == 2
    append(tmp_path / "shared-api-1.log", "ten\n")
    f.tick()
    assert out[-1].endswith("half written")


def test_a_crash_loop_cannot_flood_the_window(tmp_path):
    clock = [0.0]
    f, out = follower(tmp_path, burst=5, window=10.0, clock=lambda: clock[0])
    f.tick()
    append(tmp_path / "w.log", "".join(f"{STAMP} ERROR a: failure {i}\n" for i in range(50)))
    f.tick()
    assert len(out) == 5
    clock[0] = 11.0
    f.tick()
    assert "45 more lines hidden" in out[-1]


def pool_with(worker):
    pool = WorkerPool(SimpleNamespace(root=None), "http://127.0.0.1:1", ("config", "db", "auth"))
    pool.workers["slot"] = worker
    return pool


def dead_worker(tmp_path, code=3221225477):
    log = tmp_path / "slot.log"
    log.write_bytes(b"output of an earlier run\n")
    start = log.stat().st_size
    with log.open("ab") as stream:
        stream.write(b"starting\nsomething was happening\nTraceback (most recent call last):\nValueError: last words\n")
    process = Mock()
    process.poll.return_value = code
    return Worker("slot", 1, "token", process, log.open("ab"), log_start=start)


def test_a_worker_that_dies_by_itself_is_reported_once_with_the_end_of_its_log(tmp_path, caplog):
    worker = dead_worker(tmp_path)
    pool = pool_with(worker)
    with caplog.at_level(logging.ERROR):
        pool.check_health("slot")
        pool.check_health("slot")                # a second sweep must not repeat the report
    reports = [record.getMessage() for record in caplog.records if "exited unexpectedly" in record.getMessage()]
    assert len(reports) == 1
    assert "Worker slot exited unexpectedly" in reports[0]
    assert "access violation" in reports[0] and "ValueError: last words" in reports[0] and "slot.log" in reports[0]
    assert "earlier run" not in reports[0]          # only what this worker wrote


def test_stops_the_pool_asked_for_are_not_reported_as_crashes(tmp_path, caplog):
    for state in ("retiring", "closing"):
        worker = dead_worker(tmp_path, code=0)
        pool = pool_with(worker)
        if state == "retiring":
            pool._retiring.add("slot")
        else:
            pool.closing = True
        with caplog.at_level(logging.ERROR):
            pool.check_health("slot")
        assert not [r for r in caplog.records if "exited unexpectedly" in r.getMessage()], state


def test_a_second_ctrl_c_while_stopping_does_not_escape(tmp_path):
    f, _ = follower(tmp_path)
    f.start()
    f._thread.join = lambda timeout=None: (_ for _ in ()).throw(KeyboardInterrupt())
    f.stop()                                     # must return quietly
