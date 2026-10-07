"""Online SQLite backup and local health checks. Never send notifications."""
import argparse
import json
import sqlite3
import time
from pathlib import Path

from jin_trading.store import Store


def backup(source,destination):
    source,destination=Path(source),Path(destination)
    if not source.is_file():raise ValueError('Source ledger missing')
    if destination.exists() or source.resolve()==destination.resolve():raise ValueError('Backup destination must be new')
    destination.parent.mkdir(parents=True,exist_ok=True)
    # backup() captures a consistent database while workers continue writing.
    with sqlite3.connect('file:'+str(source.resolve())+'?mode=ro',uri=True) as src:
        with sqlite3.connect(destination) as target:
            src.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup integrity check failed')
    destination.chmod(0o600)
    return str(destination)


def health(path):
    state=Store(path).snapshot();now=time.time()
    errors=[]
    if state['halt']:errors.append('Emergency/daily-loss latch active')
    for bot in state['bots']:
        if bot['enabled'] and not 0<=now-bot['updated']<=30:errors.append(bot['id']+': worker heartbeat stale')
    with sqlite3.connect(path) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='portfolio_runs'").fetchone():
            held=db.execute("SELECT COUNT(*) FROM portfolio_runs WHERE state!='completed'").fetchone()[0]
            if held:errors.append(str(held)+' unsettled executions')
    return {'healthy':not errors,'errors':errors,'capital':state['capital'],'checked_at':now}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['backup','restore','health'])
    parser.add_argument('--db',default='data/jin-paper.sqlite');parser.add_argument('--destination')
    args=parser.parse_args()
    if args.action=='health':print(json.dumps(health(args.db)))
    else:
        if not args.destination:parser.error('A new destination path is required')
        print(backup(args.db,args.destination))


if __name__=='__main__':main()
