"""Bounded recovery for the foreground on-premises HTTP origin."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
from pathlib import Path
import signal
from http.client import HTTPConnection, HTTPException
import logging
from logging.handlers import RotatingFileHandler
import os
import subprocess
import sys
import time

from .. import process_diagnostics as diagnostics
from ..console_logs import ConsoleLogFollower


class RestartBudget:
    def __init__(self):self.attempts=[]
    def allow(self, now):
        self.attempts=[stamp for stamp in self.attempts if now-stamp<300]
        if len(self.attempts)>=5:return False
        self.attempts.append(now)
        return True


def origin_state(host, port):
    """No environment proxy or tunnel: probe the actual same-PC HTTP listener."""
    target={'0.0.0.0':'127.0.0.1','::':'::1'}.get(host,host)
    client=HTTPConnection(target,port,timeout=2)
    try:
        client.request('GET','/_internal/origin-health',headers={'Connection':'close'})
        response=client.getresponse()
        if response.status==204 and response.getheader('X-OfferPath-Health')=='1':return 'ready'
        # Admission pressure proves the HTTP listener is alive; never restart
        # healthy processes merely because ordinary requests are overloaded.
        if response.status==503:return 'busy'
        return 'unavailable'
    except (OSError,ValueError,HTTPException):return 'unavailable'
    finally:client.close()


def stop(process):
    if process.poll() is not None:return
    try:process.terminate()
    except OSError:
        if process.poll() is None:raise
    try:process.wait(timeout=10)
    except (subprocess.TimeoutExpired,KeyboardInterrupt):
        # Slow to exit, or the user is impatient: do not wait any longer.
        process.kill();process.wait(timeout=5)


@contextmanager
def restart_event(port):
    """One auto-reset Windows event per checkout, console session and port."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateEventW
    create.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    create.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.SetEvent.argtypes = [wintypes.HANDLE]
    checkout = str(Path(__file__).resolve()).casefold().encode()
    name = f"Local\\OfferPathRestart-{hashlib.sha256(checkout).hexdigest()[:24]}-{port}"
    ctypes.set_last_error(0)
    handle = create(None, False, False, name)
    existing = ctypes.get_last_error() == 183
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    def send():
        if not kernel.SetEvent(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield existing, send, lambda: kernel.WaitForSingleObject(handle, 0) == 0
    finally:
        kernel.CloseHandle(handle)


def drain_origin(process):
    """Let the origin finish its requests (up to 45 s). Another Ctrl+C means stop now."""
    if process.poll() is None:
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=45)
        except (OSError, subprocess.TimeoutExpired):
            stop(process)
        except KeyboardInterrupt:
            stop(process)
            raise


def supervise(command,host,port,logger,restart_requested=None):
    budget=RestartBudget()
    process=None
    recovering=False
    try:
        while True:
            options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if restart_requested else {}
            process=subprocess.Popen(command, **options)
            began=time.monotonic();ready=False;missed=0;restart=False
            logger.info('Started origin PID %s on %s:%s',process.pid if hasattr(process,'pid') else '?',host,port)
            while True:
                code=process.poll()
                if code is not None:
                    if code in (0,130,-2,3221225786) or (not ready and not recovering):
                        if code in (0,130,-2,3221225786):
                            logger.info('Origin exited with status %s; no restart for shutdown or failed startup.',code)
                        else:
                            logger.error('Origin stopped before it was ready: %s. The messages above show the cause; no restart for a failed startup.',diagnostics.describe_exit(code))
                        return code
                    logger.error('Origin PID %s exited unexpectedly: %s. Its last output is above.',process.pid if hasattr(process,'pid') else '?',diagnostics.describe_exit(code))
                    restart=True;break
                if restart_requested and restart_requested():
                    logger.info("Restart requested. Stopping the current origin before starting its replacement.")
                    drain_origin(process)
                    break
                state=origin_state(host,port)
                if state=='ready':
                    if not ready:logger.info('Origin local HTTP health check is ready.')
                    ready=True;missed=0
                elif state=='busy':missed=0
                else:missed+=1
                if ready and missed>=3:
                    logger.error('Origin stopped responding to three direct local HTTP probes; restarting owned PID %s.',process.pid if hasattr(process,'pid') else '?')
                    stop(process);restart=True;break
                if not ready and time.monotonic()-began>=120:
                    logger.error('Origin never became ready within 120 seconds. Check startup output and port configuration.')
                    stop(process)
                    if not recovering:return 1
                    restart=True;break
                time.sleep(5)
            if restart:
                recovering=True
                while not budget.allow(time.monotonic()):
                    logger.error('Five restarts in five minutes. Cooling down for 60 seconds before retrying; Ctrl+C stops recovery.')
                    time.sleep(60)
                delay=min(30,2**len(budget.attempts))
                logger.warning('Restarting origin in %s seconds. In-flight writes are not replayed.',delay)
                time.sleep(delay)
                # Reopening browser tabs on every recovery is disruptive.
                if '--no-open' not in command:command=[*command,'--no-open']
    except KeyboardInterrupt:
        logger.info('Stopped by user; automatic recovery is disabled for this shutdown.')
        if process is not None and restart_requested:
            logger.info('Waiting up to 45 seconds for running requests to finish. Press Ctrl+C again to stop immediately.')
            try:drain_origin(process)
            except KeyboardInterrupt:
                logger.warning('Interrupted again: stopped the server without waiting for its requests to finish.')
        elif process is not None:
            try:process.wait(timeout=10)
            except (subprocess.TimeoutExpired,KeyboardInterrupt):stop(process)
        return 130
    finally:
        if process is not None:stop(process)


def prepare_broker():
    """Reuse the terminal configuration or prompt for the local OfferPath broker."""
    import getpass
    import os
    from urllib.parse import quote

    if os.environ.get("AMQP_URL"):
        return True
    try:
        password = getpass.getpass("RabbitMQ password for offerpath: ")
    except (EOFError, KeyboardInterrupt):
        return False
    if not password:
        return False
    import pika
    url = "amqp://offerpath:" + quote(password, safe="") + "@127.0.0.1:5672/offerpath"
    try:
        params = pika.URLParameters(url)
        params.socket_timeout = 5
        params.stack_timeout = 10
        connection = pika.BlockingConnection(params)
        connection.close()
    except (pika.exceptions.AMQPError, OSError):
        print("Could not connect to local RabbitMQ. Check the service and the offerpath password.", file=sys.stderr)
        return False
    os.environ["AMQP_URL"] = url
    return True


def main():
    arguments=sys.argv[1:]
    if "--prompt-broker" in arguments:
        arguments.remove("--prompt-broker")
        if not prepare_broker():
            return 1
    if arguments == ["--request-restart"] and sys.platform == "win32":
        with restart_event(52400) as (existing, send, _):
            if not existing:
                return 3
            send()
            print("Restart requested. The server window will show startup progress.")
            return 0
    if any(arg in ('--help','--single-admin') for arg in arguments):
        return subprocess.call([sys.executable,'-m','mailcheck','web',*arguments])
    parser=argparse.ArgumentParser(add_help=False,allow_abbrev=False)
    parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',default=52400,type=int)
    options,_=parser.parse_known_args(arguments)
    import ipaddress
    try:local = ipaddress.ip_address(options.host).is_loopback or options.host in ('0.0.0.0','::')
    except ValueError:local = options.host.lower() == 'localhost'
    if not local or not 1<=options.port<=65535:
        return subprocess.call([sys.executable,'-m','mailcheck','web',*arguments])
    from .. import config
    folder=config.control_dir()/'logs';folder.mkdir(parents=True,exist_ok=True)
    logger=logging.getLogger('offerpath.origin');logger.setLevel(logging.INFO)
    formatter=logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    from ..console_colors import ColorFormatter
    console=logging.StreamHandler();console.setFormatter(ColorFormatter('%(asctime)s %(levelname)s %(message)s'));logger.addHandler(console)
    file=RotatingFileHandler(folder/'origin-supervisor.log',maxBytes=1024*1024,backupCount=2,encoding='utf-8')
    file.setFormatter(formatter);logger.addHandler(file)
    print(f'Origin recovery log: {file.baseFilename}',flush=True)
    # Never attach a watchdog to, or stop, an instance launched elsewhere.
    if origin_state(options.host,options.port) in ('ready','busy'):
        logger.error('An HTTP origin is already running on this port. Keep its terminal open; no second server was started.')
        return 1
    command = [sys.executable,'-m','mailcheck','web',*arguments]

    def run_supervised(*extra):
        # Workers have no console; show their warnings and errors in this window.
        follower=ConsoleLogFollower(folder,level=os.environ.get('OFFERPATH_CONSOLE_LOG','warning'),exclude={'origin-supervisor.log'})
        follower.start()
        try:return supervise(command, options.host, options.port, logger, *extra)
        finally:follower.stop()

    if sys.platform == 'win32':
        with restart_event(options.port) as (existing, _, requested):
            if existing:
                logger.error("A supervisor is already running. Use restart.bat.")
                return 1
            return run_supervised(requested)
    return run_supervised()


if __name__=='__main__':raise SystemExit(main())
