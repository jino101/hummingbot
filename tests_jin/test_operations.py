import tempfile
import os
import unittest
from pathlib import Path

from jin_trading.operations import backup,health
from jin_trading.store import Store


class OperationTests(unittest.TestCase):
    def test_consistent_backup_restore_latch_and_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.sqlite';copy=Path(directory)/'backup.sqlite';restored=Path(directory)/'restore.sqlite'
            store=Store(source);store.configure({'bot':'5'});store.emergency()
            backup(source,copy);backup(copy,restored)
            self.assertTrue(Store(restored).snapshot()['halt'])
            self.assertFalse(health(restored)['healthy'])
            if os.name != 'nt':
                self.assertEqual(copy.stat().st_mode&0o777,0o600)
            with self.assertRaises(ValueError):backup(source,copy)
            with self.assertRaises(ValueError):backup(Path(directory)/'absent',Path(directory)/'new')
            store.reset();store.control('bot',True)
            self.assertIn('heartbeat',health(source)['errors'][0])

