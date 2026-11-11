"""Role-scoped, file-based configuration; never include credentials in repr."""
from dataclasses import dataclass, field
from pathlib import Path
import os
import stat

ROLES=('core','mail','intelligence')


def read_secret(folder:Path,name:str)->str:
    path=folder/name
    try:
        if folder.is_symlink() or path.is_symlink():raise ValueError
        info=path.stat()
        if not stat.S_ISREG(info.st_mode) or not 32<=info.st_size<=256:raise ValueError
        value=path.read_text(encoding='ascii').strip()
        if not 32<=len(value)<=128 or not all(c.isalnum() or c in '-_' for c in value):raise ValueError
        return value
    except (OSError,UnicodeError,ValueError):
        raise ValueError(f'Missing or invalid secret file: {name}') from None


@dataclass(frozen=True)
class ServiceSettings:
    role:str
    secret_dir:Path
    postgres_host:str='postgres'
    postgres_port:int=5432
    broker_host:str='rabbitmq'
    broker_port:int=5672
    password:str=field(default='',repr=False)
    broker_password:str=field(default='',repr=False)

    @property
    def database(self):return f'offerpath_{self.role}'
    @property
    def username(self):return f'{self.role}_app'

    @classmethod
    def load(cls,role:str,environ=None):
        if role not in ROLES:raise ValueError('Unknown service role')
        env=os.environ if environ is None else environ
        folder=Path(env.get('OFFERPATH_SECRET_DIR','/run/secrets'))
        ports=[int(env.get('POSTGRES_PORT','5432')),int(env.get('RABBITMQ_PORT','5672'))]
        if any(not 1<=port<=65535 for port in ports):raise ValueError('Invalid service port')
        return cls(role,folder,env.get('POSTGRES_HOST','postgres'),ports[0],env.get('RABBITMQ_HOST','rabbitmq'),ports[1],
                   read_secret(folder,f'{role}_db_password'),read_secret(folder,f'{role}_broker_password'))

    def db_kwargs(self,*,migrate=False):
        return dict(host=self.postgres_host,port=self.postgres_port,dbname=self.database,
                    user=f'{self.role}_migrator' if migrate else self.username,
                    password=read_secret(self.secret_dir,f'{self.role}_migration_password') if migrate else self.password,
                    connect_timeout=2,options='-c statement_timeout=5000 -c lock_timeout=2000')
