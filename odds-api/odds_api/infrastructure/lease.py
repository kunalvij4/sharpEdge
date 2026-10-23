"""Process-lifetime ownership: PostgreSQL advisory lock, local SQLite file lock."""

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url


class CollectorLease:
    def __init__(self, engine, key=911712349):
        self.engine, self.connection, self.file = engine, None, None
        self.key = key

    def __enter__(self):
        if self.engine.dialect.name == "postgresql":
            self.connection = self.engine.connect()
            if not self.connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key}
            ).scalar_one():
                self.connection.close()
                self.connection = None
                raise RuntimeError("Another collector owns this database")
        elif self.engine.dialect.name == "sqlite":
            import os

            db = make_url(str(self.engine.url)).database
            if not db or db == ":memory:":
                raise RuntimeError("Collector requires a persistent database")
            suffix = ".collector.lock" if self.key == 911712349 else f".collector-{self.key}.lock"
            self.file = Path(db).resolve().with_suffix(suffix).open("a+b")
            self.file.seek(0)
            self.file.write(b"0")
            self.file.flush()
            self.file.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.file.close()
                self.file = None
                raise RuntimeError("Another collector owns this database") from None
        else:
            raise RuntimeError("Supported databases: PostgreSQL and SQLite")
        return self

    def ping(self):
        if self.connection:
            self.connection.execute(text("SELECT 1"))

    def __exit__(self, *_):
        if self.connection:
            try:
                self.connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self.key})
            finally:
                self.connection.close()
        if self.file:
            self.file.close()
