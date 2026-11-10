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
