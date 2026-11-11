"""Read-only host evidence, not a synthetic production-capacity certificate."""
import ipaddress
import json
import os
import platform
import subprocess
from urllib.parse import urlparse
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler


def _run(args):
    try:return subprocess.run(args,capture_output=True,text=True,timeout=10,check=False)
    except (OSError,subprocess.TimeoutExpired):return None


def _json_command(run,args):
    value=run(args)
    if value is None or value.returncode:return None
    try:return json.loads(value.stdout)
    except (ValueError,TypeError):return None


class _NoModelRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def _model_snapshot(url):
    parsed=urlparse(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/') or (parsed.port is not None and not 1<=parsed.port<=65535):raise ValueError('Model URL must be a private server root')
    host=parsed.hostname
    if host not in ('localhost','host.docker.internal'):
        try:address=ipaddress.ip_address(host)
        except ValueError:raise ValueError('Model host must be a local/private address') from None
        if not (address.is_private or address.is_loopback) or address.is_link_local or address.is_unspecified or address.is_multicast:raise ValueError('Model host must be a local/private address')
    request=Request(url.rstrip('/')+'/api/ps')
    with build_opener(ProxyHandler({}),_NoModelRedirect()).open(request,timeout=2) as response:
        body=response.read(1048577)
        if len(body)>1048576:raise ValueError('Model response too large')
        data=json.loads(body)
    models=[]
    for item in data.get('models',[])[:32]:
        models.append({'name':str(item.get('name',''))[:128],'size_bytes':item.get('size') if type(item.get('size')) is int else None,'gpu_bytes':item.get('size_vram') if type(item.get('size_vram')) is int else None})
    return {'reachable':True,'models':models,'peak_measured':False}


def preflight(*,run=_run,model_url='http://127.0.0.1:11434'):
    docker=_json_command(run,['docker','info','--format','{{json .}}']) or {}
    windows=None
    if platform.system()=='Windows':
        windows=_json_command(run,['powershell.exe','-NoProfile','-NonInteractive','-Command',"$s=Get-CimInstance Win32_ComputerSystem;$o=Get-CimInstance Win32_OperatingSystem;@{ram_bytes=$s.TotalPhysicalMemory;free_bytes=([long]$o.FreePhysicalMemory*1024);build=$o.BuildNumber}|ConvertTo-Json -Compress"])
    model={'reachable':False,'peak_measured':False}
    if model_url:
        try:model=_model_snapshot(model_url)
        except Exception:pass
    return {'migration_ready':False,'host':{'os':platform.system(),'logical_cpus':os.cpu_count(),'windows_memory':windows},
            'docker':{'available':bool(docker),'linux_containers':docker.get('OSType')=='linux','memory_bytes':docker.get('MemTotal'),'cpus':docker.get('NCPU'),'version':docker.get('ServerVersion')},
            'model':model,'gates':{'cold_boot':'not_verified','model_peak_memory':'not_measured','fifty_user_load':'not_tested'}}
