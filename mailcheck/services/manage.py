"""Explicit management commands for the opt-in, isolated foundation stack."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from .settings import ROLES,ServiceSettings
from .bootstrap import InitializationError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['init','provision','migrate','verify','doctor'])
    parser.add_argument('--state-dir',type=Path,default=Path('deployment/microservices/.local'))
    parser.add_argument('--model-url',default='http://127.0.0.1:11434')
    args=parser.parse_args()
    try:
        if args.action=='init':
            from .bootstrap import initialize
            result={'state':initialize(args.state_dir),'business_ready':False}
        elif args.action=='doctor':
            from .preflight import preflight
            result=preflight(model_url=args.model_url)
        elif args.action=='provision':
            from .provision import provision_domains
            provision_domains(Path(os.environ.get('OFFERPATH_SECRET_DIR','/run/secrets')),os.environ.get('POSTGRES_HOST','postgres'),int(os.environ.get('POSTGRES_PORT','5432')))
            result={'provisioned':list(ROLES),'business_ready':False}
        elif args.action=='migrate':
            from .database import migrate_domain
            for role in ROLES:migrate_domain(ServiceSettings.load(role))
            result={'migrated':list(ROLES),'business_ready':False}
        else:
            from .dependencies import probe_dependencies
            async def verify():
                async with asyncio.timeout(12):
                    return {role:await probe_dependencies(ServiceSettings.load(role)) for role in ROLES}
            checks=asyncio.run(verify())
            result={'services':checks,'business_ready':False,'infrastructure_ready':all(all(check.values()) for check in checks.values())}
            if not result['infrastructure_ready']:
                print(json.dumps(result));return 1
        print(json.dumps(result,indent=2))
        return 0
    except InitializationError as exc:
        print(json.dumps({'ok':False,'code':exc.code,'error':str(exc),'hint':exc.hint,'type':type(exc).__name__}))
        return 1
    except Exception as exc:
        # Drivers may include credential-bearing connection URLs in tracebacks.
        print(json.dumps({'ok':False,'error':'Service operation failed; no credentials were changed automatically.','type':type(exc).__name__}))
        return 1


if __name__=='__main__':raise SystemExit(main())
