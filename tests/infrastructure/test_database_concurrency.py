"""WAL readers remain responsive and replacement drains owned connections."""

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from worklogger.infrastructure.database.connection import SQLiteConnectionFactory


class DatabaseConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.factory = SQLiteConnectionFactory(self.directory / "concurrent.db")
        with self.factory.transaction() as connection:
            connection.execute("CREATE TABLE sample(value TEXT)")
            connection.execute("INSERT INTO sample VALUES('committed')")

    def test_reader_does_not_wait_for_a_writer_or_observe_uncommitted_rows(self):
        writing, release, read = threading.Event(), threading.Event(), threading.Event()
        values, errors = [], []

        def writer():
            try:
                with self.factory.transaction() as connection:
                    connection.execute("INSERT INTO sample VALUES('pending')")
                    writing.set()
                    release.wait(5)
            except Exception as exc:  # noqa: BLE001 - Forward worker failures to the test thread.
                errors.append(exc)

        def reader():
            try:
                with self.factory.connection() as connection:
                    values.extend(row[0] for row in connection.execute("SELECT value FROM sample"))
            except Exception as exc:  # noqa: BLE001 - Forward worker failures to the test thread.
                errors.append(exc)
            finally:
                read.set()

        write_thread = threading.Thread(target=writer)
        read_thread = threading.Thread(target=reader)
        write_thread.start()
        try:
            self.assertTrue(writing.wait(2))
            read_thread.start()
            self.assertTrue(read.wait(2), "Read blocked behind the active write transaction")
            self.assertEqual(values, ["committed"])
        finally:
            release.set()
            write_thread.join(3)
            if read_thread.ident is not None:
                read_thread.join(3)
        self.assertFalse(errors)
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0], 2)

    def test_maintenance_delays_new_readers_and_reinitializes_after_replacement(self):
        held, release, read = threading.Event(), threading.Event(), threading.Event()
        errors = []

        def maintenance():
            try:
                with self.factory.maintenance():
                    held.set()
                    release.wait(5)
                    self.factory.invalidate()
            except Exception as exc:  # noqa: BLE001 - Forward worker failures to the test thread.
                errors.append(exc)

        def reader():
            try:
                with self.factory.connection() as connection:
                    self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            except Exception as exc:  # noqa: BLE001 - Forward worker failures to the test thread.
                errors.append(exc)
            finally:
                read.set()

        worker, query = threading.Thread(target=maintenance), threading.Thread(target=reader)
        worker.start()
        try:
            self.assertTrue(held.wait(2))
            query.start()
            self.assertFalse(read.wait(0.1))
        finally:
            release.set()
            worker.join(3)
            if query.ident is not None:
                query.join(3)
        self.assertTrue(read.is_set())
        self.assertFalse(errors)

    def test_read_contexts_cannot_mutate_or_upgrade_into_a_writer(self):
        with self.factory.connection() as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM sample")
            with self.assertRaisesRegex(RuntimeError, "database_write_during_read"), self.factory.transaction():
                pass
            with self.assertRaisesRegex(RuntimeError, "database_maintenance_during_connection"), self.factory.maintenance():
                pass

    def test_disappearing_prepared_database_is_not_recreated_as_an_empty_file(self):
        path = Path(self.factory.database_path)
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            with self.factory.connection():
                pass
        self.assertFalse(path.exists())

    def test_nested_reader_can_finish_while_maintenance_waits_for_it(self):
        entered, finished = threading.Event(), threading.Event()
        errors = []

        def maintenance():
            try:
                with self.factory.maintenance():
                    finished.set()
            except Exception as error:
                errors.append(error)

        with self.factory.connection():
            worker = threading.Thread(target=maintenance)
            worker.start()
            with self.factory._activity:
                self.assertTrue(self.factory._activity.wait_for(lambda: self.factory._maintenance_owner is not None, timeout=2))
            with self.factory.connection() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0], 1)
                entered.set()
        worker.join(3)
        self.assertTrue(entered.is_set() and finished.is_set())
        self.assertFalse(errors)

    def test_write_lock_timeout_keeps_changes_atomic(self):
        held, release = threading.Event(), threading.Event()

        def writer():
            with self.factory.transaction():
                held.set()
                release.wait(3)

        worker = threading.Thread(target=writer)
        worker.start()
        try:
            self.assertTrue(held.wait(2))
            self.factory.busy_timeout_ms = 20
            with self.assertRaisesRegex(sqlite3.OperationalError, "database is busy"), self.factory.transaction():
                pass
        finally:
            release.set()
            worker.join(3)
