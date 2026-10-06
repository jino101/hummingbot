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
        if not budgets or sum((number(v) for v in budgets.values()), Decimal('0')) != Decimal('5'):
            raise ValueError('Initial paper budgets must total 5 USDT')
        with self.connect() as db:
            for bot, budget in budgets.items():
                if number(budget) <= 0:
                    raise ValueError('Budget must be positive')
                db.execute('INSERT OR IGNORE INTO bots(id,capital,initial) VALUES (?,?,?)',
                           (bot, str(budget), str(budget)))
                row = db.execute('SELECT initial FROM bots WHERE id=?', (bot,)).fetchone()
                if number(row[0]) != number(budget):
                    raise ValueError('Budget edits require a migration, not a restart')
            actual = {r[0] for r in db.execute('SELECT id FROM bots')}
            if actual != set(budgets):
                raise ValueError('Bot list changed; migrate the ledger explicitly')

    def _risk(self, db, now):
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

    def control(self, bot, enabled):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if enabled and self._risk(db, time.time()):
                raise ValueError('Emergency latch active; review before resetting')
            result = db.execute('UPDATE bots SET enabled=? WHERE id=?', (int(enabled), bot))
            if not result.rowcount:
                raise ValueError('Unknown bot')

    def emergency(self):
        with self.connect() as db:
            self._setting(db, 'halt', '1')
            self._setting(db, 'reason', 'User emergency stop')
            db.execute('UPDATE bots SET enabled=0')

    def reset(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._risk(db, time.time())
            baseline = number(self._get(db, 'baseline'))
            if self._total(db) <= baseline * Decimal('0.90'):
                raise ValueError('Daily loss threshold still breached')
            self._setting(db, 'halt', '0')
            self._setting(db, 'reason', '')

    def publish(self, bot, status):
        with self.connect() as db:
            db.execute('UPDATE bots SET status=?, updated=? WHERE id=?',
                       (json.dumps(status, default=str, allow_nan=False), time.time(), bot))

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
