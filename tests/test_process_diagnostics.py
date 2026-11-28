import re
import signal
import subprocess
import sys
import textwrap

import pytest

from mailcheck import process_diagnostics as diagnostics


@pytest.mark.parametrize("code,expected", [
    (None, "still running"),
    (0, "stopped cleanly"),
    (1, "reported an error"),
    (3221225786, "Ctrl+C"),
    (3221225477, "access violation"),
    (3221225725, "stack overflow"),
    (0xFFFFFFFF, "ended from outside"),
    (0xC0000999, "Windows error status"),
    (-9, "killed by SIGKILL" if hasattr(signal, "SIGKILL") else "killed by signal 9"),
    (-1000, "killed by signal 1000"),
])
def test_exit_codes_are_explained_in_words(code, expected):
    assert expected in diagnostics.describe_exit(code)


def test_durations_and_log_tails_are_short_and_readable(tmp_path):
    assert diagnostics.format_duration(5) == "5s"
    assert diagnostics.format_duration(125) == "2m 5s"
    assert diagnostics.format_duration(3 * 3600 + 120) == "3h 2m"
    log = tmp_path / "worker.log"
    log.write_bytes(b"\n".join(f"line {i}".encode() for i in range(100)) + b"\n\n   \n")
    assert diagnostics.tail_lines(log, 3) == "line 97\nline 98\nline 99"
    assert diagnostics.tail_lines(tmp_path / "missing.log") == ""
    # Only what was written after a given point (a worker's own output, not the log's older runs).
    assert diagnostics.tail_lines(log, 3, start=log.stat().st_size) == ""
    before = log.stat().st_size
    log.write_bytes(log.read_bytes() + b"new output\n")
    assert diagnostics.tail_lines(log, 5, start=before) == "new output"


def run_child(code: str):
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True, timeout=60)


def test_uncaught_errors_are_logged_with_time_level_and_traceback():
    result = run_child("""
        import logging, threading
        from mailcheck import process_diagnostics as diagnostics
        diagnostics.configure_process('demo')
        diagnostics.configure_process('demo')          # configuring twice must not duplicate output
        logging.getLogger('mailcheck.thing').warning('careful now')
        logging.getLogger('mailcheck.thing').info('too chatty for the default level')
        thread = threading.Thread(target=lambda: 1 / 0, name='background-job')
        thread.start(); thread.join()
        raise RuntimeError('boom')
    """)
    err = result.stderr
    assert result.returncode == 1
    assert re.search(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ WARNING mailcheck\.thing: careful now$", err, re.M)
    assert err.count("careful now") == 1
    assert "too chatty" not in err
    assert "ERROR demo: Unhandled exception in thread background-job." in err and "ZeroDivisionError" in err
    assert "CRITICAL demo: Unhandled exception: the demo process is stopping." in err
    assert "RuntimeError: boom" in err


def test_a_hard_native_crash_leaves_a_stack_dump_and_an_explainable_exit_code():
    result = run_child("""
        import faulthandler
        from mailcheck import process_diagnostics as diagnostics
        diagnostics.configure_process('demo')
        def doomed():
            faulthandler._sigsegv()
        doomed()
    """)
    assert result.returncode != 0
    assert "fatal" in result.stderr.lower() and "doomed" in result.stderr
    assert diagnostics.describe_exit(result.returncode) != "exit code 0 (stopped cleanly)"


def test_log_level_can_be_raised_for_debugging():
    result = run_child("""
        import logging
        from mailcheck import process_diagnostics as diagnostics
        diagnostics.configure_process('demo')
        logging.getLogger('mailcheck.thing').info('detail for debugging')
    """.replace("import logging", "import os; os.environ['OFFERPATH_LOG_LEVEL']='info'; import logging"))
    assert "INFO mailcheck.thing: detail for debugging" in result.stderr
