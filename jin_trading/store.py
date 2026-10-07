"""Transactional shared paper budgets, daily limit, and persistent emergency latch."""
import json
import sqlite3
import time
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from jin_trading.arbitrage import number


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS bots (
                    id TEXT PRIMARY KEY, capital TEXT NOT NULL, initial TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY, bot TEXT, timestamp REAL, sequence TEXT,
                    input TEXT, output TEXT, route TEXT, UNIQUE(bot, sequence));
            ''')
            db.execute("INSERT OR IGNORE INTO settings VALUES ('halt', '0')")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level='IMMEDIATE')
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _setting(db, key, value):
        db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, str(value)))

    @staticmethod
    def _get(db, key, default=None):
        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    @staticmethod
    def _total(db):
        return sum((number(r[0]) for r in db.execute('SELECT capital FROM bots')), Decimal('0'))

    def configure(self, budgets):
        """Idempotent startup; never reset accumulated capital or a stopped bot."""
        if not budgets:
            raise ValueError('At least one paper budget is required')
        total = sum((number(v) for v in budgets.values()), Decimal('0'))
        if total <= 0 or total > Decimal('1000000'):
            raise ValueError('Initial paper budgets must total more than 0 and at most 1,000,000 USDT')
        with self.connect() as db:
            configured=self._get(db,'configured_budgets')
            parsed={bot:str(number(value)) for bot,value in budgets.items()}
            if configured and {bot:number(value) for bot,value in json.loads(configured).items()}!={bot:number(value) for bot,value in parsed.items()}:
                raise ValueError('Budget edits require a migration, not a restart')
            for bot, budget in budgets.items():
                if number(budget) <= 0:
                    raise ValueError('Budget must be positive')
                db.execute('INSERT OR IGNORE INTO bots(id,capital,initial) VALUES (?,?,?)',
                           (bot, str(budget), str(budget)))
                row = db.execute('SELECT initial FROM bots WHERE id=?', (bot,)).fetchone()
                if not configured and number(row[0]) != number(budget):
                    raise ValueError('Budget edits require a migration, not a restart')
            actual = {r[0] for r in db.execute('SELECT id FROM bots')}
            if actual != set(budgets):
                raise ValueError('Bot list changed; migrate the ledger explicitly')
            self._setting(db,'configured_budgets',json.dumps(parsed))

    def reset_budgets(self, budgets):
        """Explicit PAPER-only migration: reset virtual balances/trades and stop bots."""
        if not budgets:
            raise ValueError('At least one paper budget is required')
        parsed = {bot: number(value) for bot, value in budgets.items()}
        total = sum(parsed.values(), Decimal('0'))
        if any(value <= 0 for value in parsed.values()) or total > Decimal('1000000'):
            raise ValueError('Paper budgets must be positive and total at most 1,000,000 USDT')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'portfolio_settings' in existing:
                mode=db.execute("SELECT value FROM portfolio_settings WHERE key='mode'").fetchone()
                if not mode or mode[0]!='paper':raise ValueError('Budget reset is restricted to PAPER databases')
                if db.execute("SELECT 1 FROM portfolio_runs WHERE state!='completed' LIMIT 1").fetchone():
                    raise ValueError('Reconcile unsettled paper runs before resetting budgets')
                db.execute('DELETE FROM portfolio_accounts')
                db.execute("DELETE FROM portfolio_settings WHERE key!='mode'")
                for table in ('paper_wallets','paper_positions'):
                    if table in existing:db.execute('DELETE FROM '+table)
            db.execute('DELETE FROM trades')
            db.execute('DELETE FROM bots')
            for bot, budget in parsed.items():
                db.execute('INSERT INTO bots(id,capital,initial,enabled,status) VALUES (?,?,?,?,?)',
                           (bot, str(budget), str(budget), 0, '{}'))
            db.execute("DELETE FROM settings WHERE key IN ('day','baseline','reason','actual_allocation_initialized')")
            self._setting(db,'configured_budgets',json.dumps({b:str(v) for b,v in parsed.items()}))
            self._setting(db, 'halt', '0')
        # Establish today's fresh baseline immediately.
        self.snapshot()

    def _risk(self, db, now):
        # The real/demo account ledger owns its marked equity and daily baseline.
        # Configuration weights in this UI table must not create another baseline.
        if self._account_mode(db):
            row=db.execute("SELECT value FROM portfolio_settings WHERE key='halt'").fetchone()
            if row and row[0]=='1':
                self._setting(db,'halt','1')
                reason=db.execute("SELECT value FROM portfolio_settings WHERE key='reason'").fetchone()
                self._setting(db,'reason',reason[0] if reason else 'Account portfolio stopped')
                db.execute('UPDATE bots SET enabled=0')
            return self._get(db, 'halt') == '1'
        day = datetime.fromtimestamp(now, ZoneInfo('Europe/Berlin')).date().isoformat()
        total = self._total(db)
        if self._get(db, 'day') != day:
            self._setting(db, 'day', day)
            self._setting(db, 'baseline', total)
        baseline = number(self._get(db, 'baseline', total))
        if baseline <= 0 or total <= baseline * Decimal('0.90'):
            self._setting(db, 'halt', '1')
            self._setting(db, 'reason', '10% daily loss limit')
            db.execute('UPDATE bots SET enabled=0')
        return self._get(db, 'halt') == '1'

    @staticmethod
    def _account_mode(db):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='portfolio_settings'").fetchone():
            return False
        row=db.execute("SELECT value FROM portfolio_settings WHERE key='mode'").fetchone()
        return bool(row and row[0] in ('live','demo'))

    def control(self, bot, enabled):
        blocked = False
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if enabled and self._risk(db, time.time()):
                blocked = True
            else:
                result = db.execute('UPDATE bots SET enabled=? WHERE id=?', (int(enabled), bot))
                if not result.rowcount:
                    raise ValueError('Unknown bot')
        if blocked:
            raise ValueError('Emergency latch active; review before resetting')

    def emergency(self):
        with self.connect() as db:
            self._setting(db, 'halt', '1')
            self._setting(db, 'reason', 'User emergency stop')
            db.execute('UPDATE bots SET enabled=0')

    def reset(self):
        blocked = False
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if self._account_mode(db):
                if db.execute("SELECT value FROM portfolio_settings WHERE key='halt'").fetchone()[0]=='1':
                    raise ValueError('Reset the account portfolio first')
                self._setting(db,'halt','0');self._setting(db,'reason','')
                return
            self._risk(db, time.time())
            baseline = number(self._get(db, 'baseline'))
            if self._total(db) <= baseline * Decimal('0.90'):
                blocked = True
            else:
                self._setting(db, 'halt', '0')
                self._setting(db, 'reason', '')
        if blocked:
            raise ValueError('Daily loss threshold still breached')

    def trades(self):
        """Stream the complete export without the dashboard's 100-row limit."""
        with self.connect() as db:
            for row in db.execute('SELECT * FROM trades ORDER BY id'):
                yield dict(row)

    def publish(self, bot, status):
        with self.connect() as db:
            db.execute('UPDATE bots SET status=?, updated=? WHERE id=?',
                       (json.dumps(status, default=str, allow_nan=False), time.time(), bot))

    def mark_equity(self, bot, equity):
        """Capital follows the durable wallet, including marked held inventory."""
        self.mark_equities({bot:equity})

    def mark_equities(self, equities, initialize_actual=False):
        """Publish an entire allocation in one transaction, without transient losses."""
        values={bot:number(equity) for bot,equity in equities.items()}
        if any(value<0 for value in values.values()):raise ValueError('Negative allocation')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            initial=initialize_actual and self._get(db,'actual_allocation_initialized')!='1'
            if initial and set(values)!={r[0] for r in db.execute('SELECT id FROM bots')}:
                raise ValueError('Initial allocation requires all bots')
            for bot,equity in values.items():
                result=db.execute('UPDATE bots SET capital=? WHERE id=?',(str(equity),bot))
                if not result.rowcount:raise ValueError('Unknown bot')
                if initial:db.execute('UPDATE bots SET initial=? WHERE id=?',(str(equity),bot))
            if initial:self._setting(db,'actual_allocation_initialized','1')
            self._risk(db,time.time())

    def record_execution(self, bot, opportunity, result):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO trades(bot,timestamp,sequence,input,output,route) VALUES (?,?,?,?,?,?)',
                       (bot,time.time(),opportunity.sequence,result['input'],result['output'],json.dumps(opportunity.route)))

    def paper_fill(self, bot, opportunity, now=None):
        """Atomic modelled fill; no exchange orders, no stale-book reuse or over-allocation."""
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if self._risk(db, now):
                return False
            row = db.execute('SELECT * FROM bots WHERE id=?', (bot,)).fetchone()
            if not row or not row['enabled'] or opportunity.kind != 'triangular':
                return False
            capital = number(row['capital'])
            # At most 50% deployed; conservative stress budget 1% of bot equity.
            if opportunity.input_amount <= 0 or opportunity.input_amount > capital * Decimal('0.5'):
                return False
            output = number(opportunity.output_amount)
            if output <= 0 or opportunity.profit < -capital * Decimal('0.01'):
                return False
            cursor = db.execute('INSERT OR IGNORE INTO trades(bot,timestamp,sequence,input,output,route) '
                                'VALUES (?,?,?,?,?,?)', (bot, now, opportunity.sequence,
                                str(opportunity.input_amount), str(output), json.dumps(opportunity.route)))
            if not cursor.rowcount:
                return False
            db.execute('UPDATE bots SET capital=? WHERE id=?', (str(capital + opportunity.profit), bot))
            self._risk(db, now)
            return True

    def snapshot(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._risk(db, time.time())
            bots = [dict(r) for r in db.execute('SELECT * FROM bots ORDER BY id')]
            for row in bots:
                row['status'] = json.loads(row['status'])
                row['pnl'] = str(number(row['capital']) - number(row['initial']))
                row['max_order'] = str(number(row['capital']) * Decimal('0.5'))
                row['risk_budget'] = str(number(row['capital']) * Decimal('0.01'))
            trades = [dict(r) for r in db.execute('SELECT * FROM trades ORDER BY id DESC LIMIT 100')]
            return {'mode': 'paper', 'live_available': False, 'capital': str(self._total(db)), 'bots': bots,
                    'trades': trades, 'halt': self._get(db, 'halt') == '1',
                    'reason': self._get(db, 'reason', ''), 'baseline': self._get(db, 'baseline')}
