"""Bounded recovery for the foreground on-premises HTTP origin."""
from __future__ import annotations
import argparse
from http.client import HTTPConnection, HTTPException
import logging
from logging.handlers import RotatingFileHandler
import subprocess
import sys
import time


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
    except subprocess.TimeoutExpired:
        process.kill();process.wait(timeout=5)


def supervise(command,host,port,logger):
    budget=RestartBudget()
    process=None
    try:
        while True:
            process=subprocess.Popen(command)
            began=time.monotonic();ready=False;missed=0;restart=False
            logger.info('Started origin PID %s on %s:%s',process.pid if hasattr(process,'pid') else '?',host,port)
            while True:
                code=process.poll()
                if code is not None:
                    if code in (0,130,-2,3221225786) or not ready:
                        logger.info('Origin exited with status %s; no restart for shutdown or failed startup.',code)
                        return code
                    logger.error('Origin PID %s exited unexpectedly: status %s',process.pid if hasattr(process,'pid') else '?',code)
                    restart=True;break
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
                    stop(process);return 1
                time.sleep(5)
            if restart:
                if not budget.allow(time.monotonic()):
                    logger.error('Recovery stopped after five restarts in five minutes. Inspect server and tunnel logs.')
                    return 1
                delay=min(30,2**len(budget.attempts))
                logger.warning('Restarting origin in %s seconds. In-flight writes are not replayed.',delay)
                time.sleep(delay)
                # Reopening browser tabs on every recovery is disruptive.
                if '--no-open' not in command:command=[*command,'--no-open']
    except KeyboardInterrupt:
        logger.info('Stopped by user; automatic recovery is disabled for this shutdown.')
        if process is not None:
            try:process.wait(timeout=10)
            except (subprocess.TimeoutExpired,KeyboardInterrupt):stop(process)
        return 130
    finally:
        if process is not None:stop(process)


def main():
    arguments=sys.argv[1:]
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
    console=logging.StreamHandler();console.setFormatter(formatter);logger.addHandler(console)
    file=RotatingFileHandler(folder/'origin-supervisor.log',maxBytes=1024*1024,backupCount=2,encoding='utf-8')
    file.setFormatter(formatter);logger.addHandler(file)
    print(f'Origin recovery log: {file.baseFilename}',flush=True)
    # Never attach a watchdog to, or stop, an instance launched elsewhere.
    if origin_state(options.host,options.port) in ('ready','busy'):
        logger.error('An HTTP origin is already running on this port. Keep its terminal open; no second server was started.')
        return 1
    return supervise([sys.executable,'-m','mailcheck','web',*arguments],options.host,options.port,logger)


if __name__=='__main__':raise SystemExit(main())
