from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from accounting_agent.local_system import LocalAccountingSystem, LocalSystemConflict, sample_bundle


class LocalRunRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.system = LocalAccountingSystem(self.temp.name)

    def test_live_pid_without_lease_is_recovered_on_same_key_replay(self):
        bundle = sample_bundle()
        with patch.object(self.system, '_process_bundle', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.system.create_run(bundle, 'abandoned')
        with self.system._session() as connection:
            row = connection.execute('SELECT * FROM runs').fetchone()
            self.assertEqual(os.getpid(), row['owner_pid'])
        replay = self.system.create_run(bundle, 'abandoned')
        self.assertEqual('interrupted', replay['status'])
        self.assertEqual([], replay['cases'])
        self.assertEqual('run_interrupted', replay['audit'][-1]['event_type'])
        self.assertTrue(replay['integrity_verified'])
        self.assertEqual(1, len(self.system.list_runs()))

    def test_transient_completion_failure_retries_without_duplicate_processing(self):
        complete = self.system._complete_run
        calls = []
        def fail_once(*args):
            calls.append(1)
            if len(calls) == 1:
                raise sqlite3.OperationalError('database is locked')
            return complete(*args)
        with patch.object(self.system, '_complete_run', side_effect=fail_once), patch.object(
                self.system, '_process_bundle', wraps=self.system._process_bundle) as process:
            run = self.system.create_run(sample_bundle(), 'retry-once')
        self.assertEqual(2, len(calls))
        self.assertEqual(1, process.call_count)
        self.assertEqual('completed', run['status'])
        self.assertEqual(35, len(run['cases']))
        self.assertEqual(run['run_id'], self.system.create_run(sample_bundle(), 'retry-once')['run_id'])
        self.assertTrue(self.system.export_run(run['run_id'])['integrity_verified'])

    def test_exhausted_completion_failure_remains_recoverable(self):
        with patch.object(self.system, '_complete_run', side_effect=sqlite3.OperationalError('database is locked')) as commit:
            with self.assertRaises(sqlite3.OperationalError):
                self.system.create_run(sample_bundle(), 'retry-exhausted')
        self.assertEqual(3, commit.call_count)
        self.assertEqual('processing', self.system.list_runs()[0]['status'])
        restarted = LocalAccountingSystem(self.temp.name)
        run = restarted.create_run(sample_bundle(), 'retry-exhausted')
        self.assertEqual('interrupted', run['status'])
        self.assertTrue(run['integrity_verified'])
        self.assertEqual([], run['cases'])
        self.assertNotIn('run_failed', [event['event_type'] for event in run['audit']])

    def test_late_completion_cannot_replace_a_terminal_state(self):
        run = self.system.create_run(sample_bundle(), 'complete')
        original = self.system.export_run(run['run_id'])
        with self.assertRaises(LocalSystemConflict):
            self.system._complete_run(run['run_id'], sample_bundle(), [])
        self.assertEqual(original, self.system.export_run(run['run_id']))
