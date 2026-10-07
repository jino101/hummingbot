"""Durable portfolio guard and order journal shared by cooperating bot processes.

An unknown submission is never retried. Reservations stay locked until every
order is reconciled; emergency reset cannot discard held or uncertain exposure.
"""
import json
import sqlite3
import time
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from jin_trading.arbitrage import number

TERMINAL = {'closed', 'canceled', 'rejected', 'expired'}


class Portfolio:
    def __init__(self, path, mode='paper', account_age=30):
        if mode not in ('paper', 'demo', 'live') or not 0 < account_age <= 120:
            raise ValueError('Invalid portfolio mode/freshness')
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path, self.mode, self.account_age = str(path), mode, account_age
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS portfolio_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS portfolio_accounts
                    (id TEXT PRIMARY KEY, equity TEXT, free TEXT, observed REAL, permissions TEXT);
                CREATE TABLE IF NOT EXISTS portfolio_runs
                    (id TEXT PRIMARY KEY, bot TEXT, state TEXT, created REAL, reason TEXT DEFAULT '');
                CREATE TABLE IF NOT EXISTS portfolio_reservations
                    (run TEXT, account TEXT, asset TEXT, amount TEXT, value TEXT, PRIMARY KEY(run,account,asset));
                CREATE TABLE IF NOT EXISTS portfolio_orders
                    (client_id TEXT PRIMARY KEY, run TEXT, account TEXT, pair TEXT, side TEXT,
                     amount TEXT, price TEXT, state TEXT, exchange_id TEXT, filled TEXT DEFAULT '0',
                     cost TEXT DEFAULT '0', fees TEXT DEFAULT '[]', updated REAL);
                CREATE TABLE IF NOT EXISTS portfolio_events
                    (id INTEGER PRIMARY KEY, timestamp REAL, kind TEXT, payload TEXT);
            ''')
            previous = self.get(db, 'mode')
            if previous and previous != mode:
                raise ValueError('A portfolio cannot mix paper/demo/live state')
            self.put(db, 'mode', mode)
            if self.get(db, 'halt') is None:self.put(db, 'halt', '0')

    def db(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level='IMMEDIATE')
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def get(db, key):
        row = db.execute('SELECT value FROM portfolio_settings WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    @staticmethod
    def put(db, key, value):
        db.execute('INSERT OR REPLACE INTO portfolio_settings VALUES (?,?)', (key, str(value)))

    @staticmethod
    def event(db, kind, payload):
        db.execute('INSERT INTO portfolio_events(timestamp,kind,payload) VALUES (?,?,?)',
                   (time.time(), kind, json.dumps(payload, default=str, allow_nan=False)))

    def register(self, accounts):
        accounts = sorted(set(accounts))
        if not accounts or any(not a for a in accounts):raise ValueError('Accounts required')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            known = [r[0] for r in db.execute('SELECT id FROM portfolio_accounts ORDER BY id')]
            if known and known != accounts:raise ValueError('Account registry changes require a migration')
            for account in accounts:db.execute('INSERT OR IGNORE INTO portfolio_accounts(id) VALUES (?)', (account,))

    def update_account(self, account, equity, free, observed_at=None, permissions=None):
        equity = number(equity)
        balances = {k: str(number(v)) for k, v in free.items()}
        stamp = time.time() if observed_at is None else float(number(observed_at))
        if equity < 0 or any(number(v) < 0 for v in balances.values()):raise ValueError('Negative account value')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            result = db.execute('UPDATE portfolio_accounts SET equity=?,free=?,observed=?,permissions=? WHERE id=?',
                                (str(equity), json.dumps(balances), stamp, json.dumps(permissions or {}), account))
            if not result.rowcount:raise ValueError('Unknown portfolio account')
            self.risk(db, time.time())

    def invalidate_account(self,account):
        with self.db() as db:
            db.execute('UPDATE portfolio_accounts SET observed=0 WHERE id=?',(account,))

    def risk(self, db, now):
        accounts = list(db.execute('SELECT * FROM portfolio_accounts'))
        if not accounts or any(r['equity'] is None or r['observed'] is None for r in accounts):
            return 'Account snapshots incomplete'
        if any(not 0 <= now-r['observed'] <= self.account_age for r in accounts):return 'Account snapshots stale'
        equity = sum((number(r['equity']) for r in accounts), Decimal('0'))
        day = datetime.fromtimestamp(now, ZoneInfo('Europe/Berlin')).date().isoformat()
        if self.get(db, 'day') != day:
            self.put(db, 'day', day);self.put(db, 'baseline', equity)
        baseline = number(self.get(db, 'baseline'))
        if baseline <= 0 or equity <= baseline * Decimal('.9'):
            self._halt(db, '10% portfolio daily loss limit')
        if self.get(db, 'halt') == '1':return self.get(db, 'reason') or 'Portfolio stopped'
        if self.mode == 'live':
            for row in accounts:
                p = json.loads(row['permissions'])
                checked = p.get('checked_at')
                if (p.get('read') is not True or p.get('trade') is not True or p.get('withdraw') is not False
                        or not isinstance(checked, (int,float)) or not 0 <= now-checked <= self.account_age):
                    return 'Verified current API permissions required'
        return ''

    def _halt(self, db, reason):
        if self.get(db, 'halt') == '1' and self.get(db, 'reason') == reason:return
        self.put(db, 'halt', '1');self.put(db, 'reason', reason)
        self.event(db, 'halt', {'reason': reason})

    def halt(self, reason='User emergency stop'):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE');self._halt(db, reason)

    def reset(self):
        error = None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.risk(db, time.time())
            rows = list(db.execute('SELECT equity,observed FROM portfolio_accounts'))
            total = sum((number(r[0]) for r in rows if r[0] is not None), Decimal('0'))
            baseline = number(self.get(db, 'baseline') or 0)
            if any(r[0] is None or r[1] is None or not 0 <= time.time()-r[1] <= self.account_age for r in rows):
                error = 'Fresh account snapshots required'
            elif baseline <= 0 or total <= baseline * Decimal('.9'):error = 'Daily loss threshold still breached'
            elif db.execute("SELECT 1 FROM portfolio_runs WHERE state!='completed' LIMIT 1").fetchone():
                error = 'Reconcile open, held or unknown runs before resetting'
            else:self.put(db, 'halt', '0');self.put(db, 'reason', '')
        if error:raise ValueError(error)

    def reserve(self, bot, requirements, run_id=None):
        """requirements = [(account, asset, token amount, quote value), ...]."""
        run_id = run_id or uuid.uuid4().hex
        items = [(a, s, number(q), number(v)) for a,s,q,v in requirements]
        if not items or any(q <= 0 or v <= 0 for _,_,q,v in items):raise ValueError('Invalid reservation')
        if len({(a,s) for a,s,_,_ in items}) != len(items):raise ValueError('Duplicate reservation asset')
        error = None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            reason = self.risk(db, time.time())
            if reason:error = reason
            elif db.execute('SELECT 1 FROM portfolio_runs WHERE id=?', (run_id,)).fetchone():
                error = 'Execution identifier already used'
            else:
                total = sum((number(r[0]) for r in db.execute('SELECT equity FROM portfolio_accounts')), Decimal('0'))
                reserved = sum((number(r[0]) for r in db.execute('SELECT value FROM portfolio_reservations')), Decimal('0'))
                if reserved + sum((v for _,_,_,v in items), Decimal('0')) > total * Decimal('.5'):
                    error = 'Shared 50% deployment ceiling exceeded'
                for account,asset,amount,value in items:
                    row = db.execute('SELECT free FROM portfolio_accounts WHERE id=?', (account,)).fetchone()
                    if not row:error = 'Unknown portfolio account';break
                    if db.execute('SELECT 1 FROM portfolio_reservations WHERE account=? LIMIT 1',(account,)).fetchone():
                        error = 'Account has an unsettled execution';break
                    free = number(json.loads(row[0]).get(asset,0))
                    busy = sum((number(r[0]) for r in db.execute(
                        'SELECT amount FROM portfolio_reservations WHERE account=? AND asset=?',(account,asset))), Decimal('0'))
                    if amount+busy > free:error = 'Insufficient unreserved account inventory';break
                if not error:
                    db.execute('INSERT INTO portfolio_runs(id,bot,state,created) VALUES (?,?,?,?)', (run_id,bot,'running',time.time()))
                    db.executemany('INSERT INTO portfolio_reservations VALUES (?,?,?,?,?)',
                                   [(run_id,a,s,str(q),str(v)) for a,s,q,v in items])
                    self.event(db,'reserve',{'run':run_id,'bot':bot})
        if error:raise ValueError(error)
        return run_id

    def prepare(self, run, account, pair, side, amount, price):
        if side not in ('buy','sell') or number(amount) <= 0 or number(price) <= 0:raise ValueError('Invalid order')
        client_id = 'jin'+uuid.uuid4().hex[:24]
        error = None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            record=db.execute('SELECT state FROM portfolio_runs WHERE id=?',(run,)).fetchone()
            if not record or record[0]!='running':raise ValueError('Execution stopped')
            if not db.execute('SELECT 1 FROM portfolio_reservations WHERE run=? AND account=?',(run,account)).fetchone():
                raise ValueError('Order account was not reserved')
            error = self.risk(db,time.time())
            if not error:
                db.execute('INSERT INTO portfolio_orders(client_id,run,account,pair,side,amount,price,state,updated) '
                           'VALUES (?,?,?,?,?,?,?,?,?)',(client_id,run,account,pair,side,str(amount),str(price),'prepared',time.time()))
                self.event(db,'prepare',{'client_id':client_id,'run':run})
        if error:raise ValueError(error)
        return client_id

    def submitting(self, client_id):
        error=None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT o.state,r.state FROM portfolio_orders o JOIN portfolio_runs r ON r.id=o.run WHERE client_id=?',(client_id,)).fetchone()
            if not row or row[0]!='prepared':raise ValueError('Submission may already have happened; no retry allowed')
            error=self.risk(db,time.time())
            if row[1]!='running':error=error or 'Execution stopped'
            if not error:
                db.execute("UPDATE portfolio_orders SET state='submitting',updated=? WHERE client_id=?",(time.time(),client_id))
        if error:raise ValueError(error)

    def unknown(self, client_id, reason):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE portfolio_orders SET state='unknown',updated=? WHERE client_id=?",(time.time(),client_id))
            self._halt(db,reason)

    def observe(self, client_id, order):
        status=order.get('status')
        if status not in TERMINAL | {'open','cancel_pending'}:raise ValueError('Unconfirmed order status')
        filled,cost=number(order.get('filled',0)),number(order.get('cost',0))
        fees=order.get('fees')
        if fees is None:fees=[order['fee']] if order.get('fee') else []
        if filled<0 or cost<0 or not isinstance(fees,list):raise ValueError('Invalid fill')
        fees=[{'currency':str(f['currency']), 'cost':str(number(f['cost']))} for f in fees]
        if any(number(f['cost'])<0 for f in fees):raise ValueError('Invalid fee')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT * FROM portfolio_orders WHERE client_id=?',(client_id,)).fetchone()
            if not previous:raise ValueError('Unknown client identifier')
            exchange_id=str(order.get('id') or previous['exchange_id'] or '')
            if not exchange_id or filled>number(previous['amount']):raise ValueError('Invalid exchange response')
            if previous['exchange_id'] and exchange_id!=previous['exchange_id']:raise ValueError('Order identity changed')
            if filled<number(previous['filled']) or cost<number(previous['cost']):return False
            if filled and (not cost or not fees):raise ValueError('Filled order needs notional and confirmed fees')
            db.execute('UPDATE portfolio_orders SET state=?,exchange_id=?,filled=?,cost=?,fees=?,updated=? WHERE client_id=?',
                       (status,exchange_id,str(filled),str(cost),json.dumps(fees),time.time(),client_id))
            self.event(db,'order',{'client_id':client_id,'status':status,'filled':filled,'cost':cost,'fees':fees})
        return True

    def finish(self, run, completed=False, reason=''):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            orders=list(db.execute('SELECT * FROM portfolio_orders WHERE run=?',(run,)))
            if completed and (not orders or any(r['state'] not in TERMINAL for r in orders)):
                raise ValueError('Unreconciled orders cannot release reservations')
            if completed:
                db.execute('DELETE FROM portfolio_reservations WHERE run=?',(run,))
            else:self._halt(db,reason or 'Held or unknown execution needs reconciliation')
            db.execute('UPDATE portfolio_runs SET state=?,reason=? WHERE id=?',
                       ('completed' if completed else 'held',reason,run))

    def abort_unsubmitted(self, run):
        """Release only durable intents that have never reached submission."""
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            orders=list(db.execute('SELECT state FROM portfolio_orders WHERE run=?',(run,)))
            if any(r[0]!='prepared' for r in orders):return False
            db.execute("UPDATE portfolio_orders SET state='rejected' WHERE run=?",(run,))
            db.execute('DELETE FROM portfolio_reservations WHERE run=?',(run,))
            db.execute("UPDATE portfolio_runs SET state='completed',reason='Aborted before submission' WHERE id=?",(run,))
            return True

    def settle_held(self, run, acknowledgement):
        """Explicit inventory acceptance after reconciliation; never a blind reset.

        This releases inventory for subsequent strategies, not a claim that the
        original arbitrage completed. All orders must be terminal and snapshots
        fresh. Record the operator's acknowledgement for the audit trail.
        """
        if acknowledgement != 'ACCEPT_RECONCILED_INVENTORY':raise ValueError('Inventory acknowledgement required')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state FROM portfolio_runs WHERE id=?',(run,)).fetchone()
            if not row or row[0]!='held':raise ValueError('Held execution required')
            accounts=list(db.execute('SELECT observed,equity FROM portfolio_accounts'))
            if any(r[1] is None or r[0] is None or not 0<=time.time()-r[0]<=self.account_age for r in accounts):
                raise ValueError('Fresh inventory valuation required')
            orders=list(db.execute('SELECT state FROM portfolio_orders WHERE run=?',(run,)))
            if any(r[0] not in TERMINAL for r in orders):raise ValueError('Every order must be reconciled first')
            db.execute('DELETE FROM portfolio_reservations WHERE run=?',(run,))
            db.execute("UPDATE portfolio_runs SET state='completed',reason='Operator accepted reconciled inventory' WHERE id=?",(run,))
            self.event(db,'inventory_accepted',{'run':run})

    def orders(self, unsettled_only=False):
        with self.db() as db:
            sql='SELECT o.* FROM portfolio_orders o JOIN portfolio_runs r ON r.id=o.run'
            if unsettled_only:sql+=" WHERE r.state!='completed'"
            return [dict(r) for r in db.execute(sql+' ORDER BY o.updated')]

    def snapshot(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            reason=self.risk(db,time.time())
            accounts=[dict(r) for r in db.execute('SELECT id,equity,observed FROM portfolio_accounts ORDER BY id')]
            runs=[dict(r) for r in db.execute('SELECT * FROM portfolio_runs ORDER BY created DESC LIMIT 100')]
            equity=sum((number(r['equity']) for r in accounts if r['equity'] is not None),Decimal('0'))
            return {'mode':self.mode,'equity':str(equity),'baseline':self.get(db,'baseline'),
                    'ready':not reason,'halt':self.get(db,'halt')=='1','reason':reason,
                    'accounts':accounts,'runs':runs,'orders':self.orders()}
