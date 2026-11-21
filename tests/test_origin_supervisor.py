from unittest.mock import Mock,patch
from mailcheck.web import supervisor


class Process:
    def __init__(self,codes):self.codes=list(codes);self.terminated=False
    def poll(self):
        return self.codes.pop(0) if len(self.codes)>1 else self.codes[0]
    def terminate(self):self.terminated=True;self.codes=[-15]
    def kill(self):self.codes=[-9]
    def wait(self,timeout=None):return self.poll()


def run_processes(processes,states):
    clock=[0.]
    def sleep(seconds):clock[0]+=seconds
    with patch.object(supervisor.subprocess,'Popen',side_effect=processes) as spawn,patch.object(supervisor,'origin_state',side_effect=states),patch.object(supervisor.time,'monotonic',side_effect=lambda:clock[0]),patch.object(supervisor.time,'sleep',side_effect=sleep):
        result=supervisor.supervise(['python','-m','mailcheck','web'],'127.0.0.1',52400,Mock())
    return result,spawn


def test_runtime_crash_restarts_with_same_port_and_no_extra_browser():
    result,spawn=run_processes([Process([None,None,1]),Process([0])],['ready','ready'])
    assert result==0
    assert spawn.call_count==2
    assert spawn.call_args.args[0]==['python','-m','mailcheck','web','--no-open']


def test_three_failed_probes_restart_owned_process():
    hung=Process([None])
    result,spawn=run_processes([hung,Process([0])],['ready','unavailable','unavailable','unavailable'])
    assert result==0 and hung.terminated and spawn.call_count==2


def test_overload_does_not_restart_a_reachable_origin():
    result,spawn=run_processes([Process([None,None,None,0])],['ready','busy','busy'])
    assert result==0 and spawn.call_count==1


def test_bad_startup_and_user_interrupt_do_not_loop():
    for code in (1,130,3221225786):
        result,spawn=run_processes([Process([code])],[])
        assert result==code and spawn.call_count==1


def test_repeated_restarts_are_bounded():
    budget=supervisor.RestartBudget()
    assert [budget.allow(100) for _ in range(6)]==[True]*5+[False]
    assert budget.allow(401)


def test_unready_startup_has_a_deadline_and_is_not_restarted():
    process=Process([None])
    result,spawn=run_processes([process],['unavailable']*30)
    assert result==1 and process.terminated and spawn.call_count==1


def test_process_exit_between_poll_and_terminate_is_harmless():
    process=Mock();process.poll.side_effect=[None,0]
    process.terminate.side_effect=ProcessLookupError('already exited')
    supervisor.stop(process)
    process.kill.assert_not_called()


def test_windows_restart_signal_crosses_processes_and_resets():
    import os
    import subprocess
    import sys
    import pytest
    if sys.platform != 'win32':
        pytest.skip('Windows launcher')
    key = 100000 + os.getpid()
    with supervisor.restart_event(key) as (existing, _, requested):
        assert not existing
        command = (
            'from mailcheck.web.supervisor import restart_event\n'
            f'with restart_event({key}) as (existing, send, _):\n'
            '    assert existing\n'
            '    send()'
        )
        subprocess.run([sys.executable, '-c', command], check=True)
        assert requested()
        assert not requested()


def test_requested_restart_waits_for_owned_origin_then_relaunches():
    import sys
    import pytest
    if sys.platform != 'win32':
        pytest.skip('Windows launcher')
    child = Mock()
    child.poll.return_value = None
    with patch.object(supervisor.subprocess, 'Popen', side_effect=[child, Process([0])]) as spawn:
        code = supervisor.supervise(['python', 'server'], '127.0.0.1', 52400, Mock(), lambda: True)
    assert code == 0 and spawn.call_count == 2
    child.send_signal.assert_called_once_with(supervisor.signal.CTRL_BREAK_EVENT)
    child.wait.assert_called_once_with(timeout=45)


def test_cold_start_prompts_only_without_an_inherited_broker(monkeypatch):
    import os
    import sys
    pika = Mock()
    monkeypatch.setitem(sys.modules, "pika", pika)
    from urllib.parse import unquote, urlsplit
    monkeypatch.delenv('AMQP_URL', raising=False)
    with patch('getpass.getpass', return_value='special@:/%') as prompt, patch.object(pika, 'BlockingConnection') as connect:
        assert supervisor.prepare_broker()
        url = urlsplit(os.environ['AMQP_URL'])
        assert (url.username, unquote(url.password), url.hostname, url.port, url.path) == ('offerpath', 'special@:/%', '127.0.0.1', 5672, '/offerpath')
        assert supervisor.prepare_broker()
        prompt.assert_called_once()
        connect.assert_called_once()


def test_second_ctrl_c_while_draining_stops_the_origin_without_a_traceback():
    import sys
    import pytest
    if sys.platform != 'win32':
        pytest.skip('Windows launcher')
    child = Mock()
    child.poll.return_value = None
    child.terminate.side_effect = lambda: setattr(child.poll, 'return_value', -15)
    calls = []
    def wait(timeout=None):
        calls.append(timeout)
        if len(calls) == 1:
            raise KeyboardInterrupt          # the second Ctrl+C, during the 45 s graceful wait
        return -15
    child.wait.side_effect = wait
    logger = Mock()
    with patch.object(supervisor.subprocess, 'Popen', return_value=child), patch.object(supervisor, 'origin_state', return_value='ready'),          patch.object(supervisor.time, 'sleep', side_effect=KeyboardInterrupt):   # the first Ctrl+C
        code = supervisor.supervise(['python', 'server'], '127.0.0.1', 52400, logger, lambda: False)
    assert code == 130
    assert calls[0] == 45
    child.terminate.assert_called()
    assert any('Interrupted again' in str(call.args[0]) for call in logger.warning.call_args_list)


def test_ctrl_c_while_stopping_kills_instead_of_waiting():
    child = Mock()
    child.poll.return_value = None
    child.wait.side_effect = [KeyboardInterrupt, 0]
    supervisor.stop(child)
    child.terminate.assert_called_once()
    child.kill.assert_called_once()
