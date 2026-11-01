from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from mailcheck.config import Config
from mailcheck.web import app as web


def test_scheduler_requests_mail_and_calendar_in_one_job():
    cfg=Config()
    cfg.watch.auto_check=True
    with patch.object(web.cfgmod,'load',return_value=cfg), patch.object(web.time,'sleep',side_effect=[None,StopIteration]), patch.dict(web._job, running=False), patch.dict(web._sched,next_due=0), patch.object(web,'_state',return_value={'has_accounts':True}), patch.object(web,'_reschedule'), patch.object(web,'_job_lock') as lock, patch.object(web,'_run_check') as run:
        lock.acquire.return_value=True
        with pytest.raises(StopIteration):web._scheduler()
        assert run.call_args.kwargs.get('include_calendar') is True


@pytest.mark.parametrize('calendar_failure',[False,True])
def test_combined_job_collects_calendar_and_still_checks_mail(calendar_failure):
    cfg=Config()
    mail=SimpleNamespace(interview_changes=[{'id':2}],fetched=1,classified=1,from_cache=0,prefiltered=0,pruned=0,retryable=0,errors=[])
    collector=Mock(side_effect=RuntimeError('calendar offline')) if calendar_failure else Mock(return_value={'changes':[{'id':1}],'errors':[],'accounts':1})
    def start(work,**kwargs):work()
    with patch.object(web.cfgmod,'load',return_value=cfg), patch.object(web.db,'session',side_effect=lambda:nullcontext(Mock())), patch.object(web,'check_once',return_value=mail) as check, patch.object(web.interviews,'collect_calendar_events',collector), patch.object(web,'_start_job',side_effect=start), patch.dict(web._job):
        web._run_check(web.CheckBody(),include_calendar=True)
        collector.assert_called_once()
        check.assert_called_once()
        assert web._job['ok'] is (not calendar_failure)
        assert {c['id'] for c in web._job['interview_changes']}==({2} if calendar_failure else {1,2})


def test_calendar_updates_survive_a_later_mail_failure():
    calendar={'changes':[{'id':7}],'errors':[],'accounts':1}
    with patch.object(web.cfgmod,'load',return_value=Config()), patch.object(web.db,'session',side_effect=lambda:nullcontext(Mock())), patch.object(web,'check_once',side_effect=RuntimeError('model unavailable')), patch.object(web.interviews,'collect_calendar_events',return_value=calendar), patch.object(web,'_start_job',side_effect=lambda work,**kwargs:work()), patch.dict(web._job):
        with pytest.raises(RuntimeError,match='model unavailable'):
            web._run_check(web.CheckBody(),include_calendar=True)
        assert web._job['interview_changes']==[{'id':7}]
