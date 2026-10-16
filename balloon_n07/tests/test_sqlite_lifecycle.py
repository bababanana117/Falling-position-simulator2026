"""Lifecycle regression: retain Python references; never rely on garbage collection.

The rename/unlink/TemporaryDirectory cleanup cases run on Windows as well.
No flight or real API is called.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from core import Store,Problem,make_plan
from test_n07 import candidates,CONFIG,SOURCE,HEALTH,TARGET,validator

class ConnectionLifecycleTests(unittest.TestCase):
    def captured(self):
        live=[];original=sqlite3.connect
        def factory(*a,**kw):
            db=original(*a,**kw);live.append(db);return db
        return live,factory
    def assert_closed(self,live):
        self.assertTrue(live)
        for db in live:
            with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')
    def test_all_store_operations_close_and_file_can_be_deleted(self):
        live,factory=self.captured()
        with tempfile.TemporaryDirectory() as d:
            with patch('core.sqlite3.connect',side_effect=factory):
                store=Store(d);sid=store.create(make_plan(candidates(),CONFIG,TARGET,SOURCE,HEALTH,'MOCK',validator))
                store.get(sid);store.list();store.update(sid,lambda doc:doc['history'].append({'event':'TEST'}))
            self.assert_closed(live)
            renamed=store.path.with_name('renamed.sqlite3');store.path.rename(renamed);renamed.unlink()
            self.assertFalse(renamed.exists())
        self.assertFalse(Path(d).exists())
    def test_exception_rolls_back_then_closes(self):
        live,factory=self.captured()
        with tempfile.TemporaryDirectory() as d:
            with patch('core.sqlite3.connect',side_effect=factory):
                store=Store(d);sid=store.create(make_plan(candidates(),CONFIG,TARGET,SOURCE,HEALTH,'MOCK',validator));before=store.get(sid)
                def fail(doc):doc['state']='BROKEN';raise RuntimeError('TEST rollback')
                with self.assertRaises(RuntimeError):store.update(sid,fail)
                self.assertEqual(store.get(sid),before)
            self.assert_closed(live)
    def test_setup_failure_closes_connection(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);db=Mock();db.execute.side_effect=sqlite3.OperationalError('TEST PRAGMA failure')
            with patch('core.sqlite3.connect',return_value=db):
                with self.assertRaises(sqlite3.OperationalError):
                    with store.connect():self.fail('must not yield')
            db.close.assert_called_once()
    def test_commit_failure_closes_real_connection(self):
        live,factory=self.captured()
        with tempfile.TemporaryDirectory() as d:
            with patch('core.sqlite3.connect',side_effect=factory):
                store=Store(d)
                with store.connect() as db:
                    db.execute('PRAGMA foreign_keys=ON')
                    db.execute('CREATE TABLE test_parent (id INTEGER PRIMARY KEY)')
                    db.execute('CREATE TABLE test_child (parent INTEGER REFERENCES test_parent(id) DEFERRABLE INITIALLY DEFERRED)')
                with self.assertRaises(sqlite3.IntegrityError):
                    with store.connect() as db:
                        db.execute('PRAGMA foreign_keys=ON');db.execute('INSERT INTO test_child VALUES (99)')
                with store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM test_child').fetchone()[0],0)
            self.assert_closed(live)
    def test_read_failure_and_constructor_rejection_close(self):
        live,factory=self.captured()
        with tempfile.TemporaryDirectory() as d:
            with patch('core.sqlite3.connect',side_effect=factory):
                store=Store(d)
                with self.assertRaises(Problem):store.get('NOT-FOUND')
                with store.connect() as db:db.execute('PRAGMA application_id=0')
                with self.assertRaises(Problem):Store(d)
            self.assert_closed(live)
    def test_wal_full_and_immediate_transaction_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d)
            with store.connect() as db:
                self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'wal')
                self.assertEqual(db.execute('PRAGMA synchronous').fetchone()[0],2)
                db.execute('BEGIN IMMEDIATE');self.assertTrue(db.in_transaction)
                with store.connect() as reader:self.assertEqual(reader.execute('SELECT count(*) FROM searches').fetchone()[0],0)
    def test_transaction_exit_failure_still_closes(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);db=Mock();db.__enter__=Mock(return_value=db)
            db.__exit__=Mock(side_effect=sqlite3.OperationalError('TEST transaction exit failure'))
            with patch('core.sqlite3.connect',return_value=db):
                with self.assertRaises(sqlite3.OperationalError):
                    with store.connect():pass
            db.close.assert_called_once()

if __name__=='__main__':unittest.main()
