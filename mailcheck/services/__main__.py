import argparse
import uvicorn
from .settings import ServiceSettings,ROLES
from .app import create_service_app


def main():
    parser=argparse.ArgumentParser(description='Start an isolated OfferPath service foundation.')
    parser.add_argument('role',choices=ROLES)
    parser.add_argument('--port',type=int,default=8000)
    args=parser.parse_args()
    try:settings=ServiceSettings.load(args.role)
    except ValueError as exc:parser.exit(2,f'{exc}\n')
    uvicorn.run(create_service_app(settings),host='0.0.0.0',port=args.port,access_log=False,server_header=False,
                timeout_keep_alive=5,timeout_graceful_shutdown=10)


if __name__=='__main__':main()
