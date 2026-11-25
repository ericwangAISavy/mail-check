"""Initialize an unused workspace locally; never replace data or recovery files."""
import argparse
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mailcheck import config
from mailcheck.workspaces import initialize_unused_workspace
from mailcheck.web.system_monitoring import database_snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',required=True,help='Managed workspace ID from monitoring evidence')
    parser.add_argument('--control-dir',type=Path,default=config.control_dir())
    args=parser.parse_args()
    try:
        database=initialize_unused_workspace(args.control_dir,args.workspace,(config.config_path(),config.db_path()))
        evidence=database_snapshot(database)
        if evidence['status']!='healthy':
            raise RuntimeError('Database was initialized but its health read failed; inspect monitoring evidence.')
    except (OSError,sqlite3.Error,ValueError,RuntimeError) as exc:
        parser.exit(1,f'Initialization stopped: {exc}\n')
    print('Workspace database initialized and readable. Monitoring will update on its next check.')


if __name__=='__main__':
    main()
