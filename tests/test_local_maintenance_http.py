from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from urllib.request import urlopen

from accounting_agent.local_maintenance import DATABASE_NAME, restore_backup
from accounting_agent.local_system import LocalAccountingSystem
from tests.test_local_app_http import _request, _running_server


class LocalMaintenanceHTTPTests(unittest.TestCase):
    def test_health_and_downloaded_backup_restore_the_same_saved_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "workspace"
            with _running_server(data) as url:
                _, session, _ = _request(url, "/api/session")
                _, bundle, _ = _request(url, "/api/sample")
                _, run, _ = _request(url, "/api/runs", method="POST", token=session["csrf_token"],
                                     payload={"bundle": bundle, "request_key": "backup-http"})
                status, health, _ = _request(url, "/api/health")
                self.assertEqual(200, status)
                self.assertEqual("ready", health["status"])
                self.assertEqual(35, health["storage_counts"]["cases"])
                with urlopen(url + "/api/workspace/backup", timeout=5) as response:
                    self.assertEqual("application/zip", response.headers["Content-Type"])
                    self.assertIn("attachment", response.headers["Content-Disposition"])
                    backup = root / "download.zip"
                    backup.write_bytes(response.read())
                _, original, _ = _request(url, f"/api/runs/{run['run_id']}/export")
            restore_backup(backup, root / "restored")
            restored = LocalAccountingSystem(root / "restored")
            self.assertEqual(original, restored.export_run(run["run_id"]))

    def test_unhealthy_storage_returns_503_without_internal_database_details(self):
        with tempfile.TemporaryDirectory() as temp, _running_server(Path(temp)) as url:
            connection = sqlite3.connect(Path(temp) / DATABASE_NAME)
            try:
                connection.execute("DROP TABLE reviews")
                connection.commit()
            finally:
                connection.close()
            status, response, _ = _request(url, "/api/health")
            self.assertEqual(503, status)
            self.assertEqual("unavailable", response["status"])
            self.assertNotIn(temp, json.dumps(response))
