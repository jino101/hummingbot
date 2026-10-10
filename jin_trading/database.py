"""SQLite transactions that release their connection when the scope ends."""
import sqlite3


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(database, **kwargs):
    return sqlite3.connect(database, factory=ClosingConnection, **kwargs)
