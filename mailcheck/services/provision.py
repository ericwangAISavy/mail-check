"""One-shot bootstrap only: domain runtimes never receive these admin secrets."""
import psycopg
from psycopg import sql
from .settings import ROLES,read_secret


def provision_domains(folder,host='postgres',port=5432):
    admin=dict(host=host,port=port,dbname='postgres',user='postgres',password=read_secret(folder,'postgres_admin_password'),connect_timeout=3)
    with psycopg.connect(**admin,autocommit=True) as root:
        root.execute('SELECT pg_advisory_lock(%s)',(62107949642,))
        try:
            for role in ROLES:
                owner=f'{role}_owner';app=f'{role}_app';migrator=f'{role}_migrator';database=f'offerpath_{role}'
                for name,password in [(owner,None),(app,read_secret(folder,f'{role}_db_password')),(migrator,read_secret(folder,f'{role}_migration_password'))]:
                    existing=root.execute('SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=%s',(name,)).fetchone()
                    if existing:
                        if existing[0]!=(password is not None) or any(existing[1:]):raise ValueError('Existing service role has unsafe attributes')
                    elif password is None:root.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(name)))
                    else:root.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(name),sql.Literal(password)))
                root.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(owner),sql.Identifier(migrator)))
                existing=root.execute('SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s',(database,)).fetchone()
                if existing and existing[0]!=owner:raise ValueError('Existing database has a different owner')
                if not existing:root.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(database),sql.Identifier(owner)))
                root.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(database)))
                root.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {},{}').format(sql.Identifier(database),sql.Identifier(app),sql.Identifier(migrator)))
                with psycopg.connect(**{**admin,'dbname':database}) as conn:
                    conn.execute('REVOKE ALL ON SCHEMA public FROM PUBLIC')
                    conn.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(app)))
                    conn.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(owner)))
                    conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO {}').format(sql.Identifier(app)))
                    conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO {}').format(sql.Identifier(app)))
                # Detect a wrong secret directory without changing stored passwords.
                for user,filename in [(app,f'{role}_db_password'),(migrator,f'{role}_migration_password')]:
                    with psycopg.connect(**{**admin,'dbname':database,'user':user,'password':read_secret(folder,filename)}) as check:check.execute('SELECT 1')
        finally:root.execute('SELECT pg_advisory_unlock(%s)',(62107949642,))
