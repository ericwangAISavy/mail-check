# Windows shutdown investigation

The reported incident contains a launcher KeyboardInterrupt followed by the origin receiving SIGINT. A workspace ConnectTimeout is logged after shutdown begins. These lines establish an interrupt-driven shutdown, but do not identify the interrupt sender or prove a crash in an Interview request.

## Confirmed defect: monitoring uses a Windows console-control operation

The shared model activity probe previously called `os.kill(pid, 0)` on every platform. On POSIX this is a process existence check. On Windows, signal zero is CTRL_C_EVENT; CPython routes it through GenerateConsoleCtrlEvent. It is unsafe to use as a read-only liveness check in an application whose processes share a console.

The model coordinator records its executing process PID while an operation is active. The monitoring endpoint reads this record during polling, making this an intermittent path dependent on model activity and monitoring requests. The console interrupt path is consistent with the supplied SIGINT logs, but the precise Windows console delivery behavior and the reported Interview click have not been reproduced in this Linux environment.

The fix uses OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION and GetExitCodeProcess on Windows, and closes the handle in every query outcome. It never requests termination rights or sends console events. POSIX retains its normal existence check. Stale or inaccessible process evidence remains unknown.

Regression coverage rejects any Windows os.kill call, covers active/exited/access-denied/failed-query outcomes and handle cleanup, and repeatedly probes a dedicated live subprocess without stopping it. Windows API behavior is simulated in Linux; the subprocess test also runs natively on Windows when executed there.

Reference: [CPython 3.15 os.kill implementation](https://github.com/python/cpython/blob/3.15/Modules/posixmodule.c), [Python os.kill documentation](https://docs.python.org/3/library/os.html#os.kill).

## Other shutdown paths reviewed

- Interview list and analysis GET endpoints do not explicitly stop the HTTP server or send signals. Page entry does not submit the calendar sync POST.
- The foreground watchdog stops an unresponsive origin after repeated local probe failures. It does not send SIGINT; receiving an interrupt disables automatic recovery by design.
- Shared-process parent authentication failures drain child processes. They do not request a gateway SIGINT.
- Cloudflare tunnel mode configures the origin; the application does not launch or terminate cloudflared.

No application databases, account settings, or running admin jobs were modified during this investigation. The earlier graph changes remain in the working tree. Updating code does not patch an already running Python process; load the fix during a controlled restart after active jobs finish.
