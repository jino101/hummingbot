import sqlite3
import tempfile
import unittest
from pathlib import Path

from jin_trading.database import connect


class DatabaseTests(unittest.TestCase):
    def test_commit_rollback_and_file_release(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ledger.sqlite'
            with connect(path) as db:
                db.execute('CREATE TABLE entries (value INTEGER)')
                db.execute('INSERT INTO entries VALUES (1)')
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')
            with self.assertRaises(ValueError):
                with connect(path) as failed:
                    failed.execute('INSERT INTO entries VALUES (2)')
                    raise ValueError('rollback')
            with self.assertRaises(sqlite3.ProgrammingError):
                failed.execute('SELECT 1')
            with connect(path) as check:
                self.assertEqual(check.execute('SELECT value FROM entries').fetchall(), [(1,)])
            renamed = path.with_name('moved.sqlite')
            path.rename(renamed)
            renamed.unlink()
