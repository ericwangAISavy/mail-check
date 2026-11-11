"""Transactional, checksum-verified domain migrations using a separate role."""
from hashlib import sha256
from pathlib import Path
import psycopg
from psycopg import sql


def expected_schema_version(role):return 3


def migrate_domain(settings):
    folder=Path(__file__).parent/'migrations'
    script=(folder/'common_001.sql').read_text()
    if settings.role=='core':script+='\n'+(folder/'core_001.sql').read_text()
    migrations=[(1,script)]
    if settings.role=='core':migrations.append((2,(folder/'core_002.sql').read_text()))
    migrations.append((3,(folder/'common_003.sql').read_text()))
    with psycopg.connect(**settings.db_kwargs(migrate=True)) as conn:
        with conn.transaction():
            conn.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(f'{settings.role}_owner')))
            conn.execute('SELECT pg_advisory_xact_lock(%s)',(62107949643,))
            conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,checksum TEXT NOT NULL,installed_at TIMESTAMPTZ NOT NULL DEFAULT now())')
            installed={row[0] for row in conn.execute('SELECT version FROM schema_migrations')}
            if not installed.issubset({version for version,_ in migrations}):raise ValueError('Database schema is newer than this service')
            for version,script in migrations:
                checksum=sha256(script.encode()).hexdigest()
                row=conn.execute('SELECT checksum FROM schema_migrations WHERE version=%s',(version,)).fetchone()
                if row:
                    if row[0]!=checksum:raise ValueError('Installed service migration checksum does not match')
                else:
                    conn.execute(script,prepare=False)
                    conn.execute('INSERT INTO schema_migrations(version,checksum) VALUES(%s,%s)',(version,checksum))
            conn.execute(sql.SQL('REVOKE INSERT,UPDATE,DELETE ON schema_migrations FROM {}').format(sql.Identifier(settings.username)))
