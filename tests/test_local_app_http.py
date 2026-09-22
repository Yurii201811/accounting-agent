from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from accounting_agent.local_app import create_server


@contextmanager
def _running_server(data_dir: Path):
    server = create_server(data_dir, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: object | None = None,
    raw_body: bytes | None = None,
    token: str | None = None,
    origin: str | None = None,
    host: str | None = None,
    content_type: str = "application/json",
) -> tuple[int, object, dict[str, str]]:
    if raw_body is not None:
        body = raw_body
    elif payload is not None:
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
    else:
        body = None
    headers: dict[str, str] = {}
    if body is not None:
        headers["Content-Type"] = content_type
    if token is not None:
        headers["X-Accounting-Session"] = token
    if origin is not None:
        headers["Origin"] = origin
    if host is not None:
        headers["Host"] = host
    request = Request(base_url + path, data=body, headers=headers, method=method)
    try:
        response = urlopen(request, timeout=5)
    except HTTPError as exc:
        response = exc
    try:
        response_body = response.read()
        decoded = json.loads(response_body) if response_body else None
        return response.status, decoded, dict(response.headers.items())
    finally:
        response.close()


class LocalAppHTTPTests(unittest.TestCase):
    def test_create_review_export_and_restart_preserve_one_synthetic_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_dir = Path(temp)
            with _running_server(data_dir) as base_url:
                session_status, session, _ = _request(base_url, "/api/session")
                self.assertEqual(200, session_status)
                self.assertEqual("synthetic_local", session["environment"])
                self.assertFalse(session["live_actions_enabled"])
                token = session["csrf_token"]

                sample_status, bundle, sample_headers = _request(base_url, "/api/sample")
                self.assertEqual(200, sample_status)
                self.assertIn("attachment", sample_headers["Content-Disposition"])

                create_status, created, _ = _request(
                    base_url,
                    "/api/runs",
                    method="POST",
                    payload={"bundle": bundle, "request_key": "http-acceptance-1"},
                    token=token,
                    origin=base_url,
                )
                self.assertEqual(201, create_status)
                run_id = created["run_id"]
                self.assertTrue(created["cases"])
                case = next(
                    item for item in created["cases"]
                    if item["policy_mode"] != "forbidden"
                )
                case_id = case["case_id"]

                case_status, case_detail, _ = _request(
                    base_url, f"/api/runs/{run_id}/cases/{case_id}"
                )
                self.assertEqual(200, case_status)
                self.assertEqual(case_id, case_detail["case_id"])
                self.assertIn("presentation", case_detail)

                review_status, reviewed, _ = _request(
                    base_url,
                    f"/api/runs/{run_id}/cases/{case_id}/review",
                    method="POST",
                    payload={
                        "outcome": "reviewed",
                        "note": "Synthetic evidence checked locally.",
                        "expected_revision": case_detail["review_revision"],
                    },
                    token=token,
                    origin=base_url,
                )
                self.assertEqual(200, review_status)
                self.assertEqual("reviewed", reviewed["review_status"])
                self.assertEqual(case_detail["review_revision"] + 1, reviewed["review_revision"])

                export_status, exported, export_headers = _request(
                    base_url, f"/api/runs/{run_id}/export"
                )
                self.assertEqual(200, export_status)
                self.assertIn("attachment", export_headers["Content-Disposition"])
                self.assertEqual(run_id, exported["run"]["run_id"])
                self.assertTrue(exported["synthetic"])
                self.assertTrue(exported["integrity_verified"])
                self.assertEqual([], exported["integrity_errors"])
                self.assertIn(
                    "review_recorded",
                    {event["event_type"] for event in exported["audit"]},
                )

            with _running_server(data_dir) as restarted_url:
                list_status, listing, _ = _request(restarted_url, "/api/runs")
                self.assertEqual(200, list_status)
                self.assertEqual([run_id], [run["run_id"] for run in listing["runs"]])

                run_status, reopened, _ = _request(restarted_url, f"/api/runs/{run_id}")
                self.assertEqual(200, run_status)
                reopened_case = next(item for item in reopened["cases"] if item["case_id"] == case_id)
                self.assertEqual("reviewed", reopened_case["review_status"])

                export_status, restarted_export, _ = _request(
                    restarted_url, f"/api/runs/{run_id}/export"
                )
                self.assertEqual(200, export_status)
                self.assertEqual(exported, restarted_export)
                matching_review = next(
                    item for item in restarted_export["reviews"]
                    if item["case_id"] == case_id
                )
                self.assertEqual("Synthetic evidence checked locally.", matching_review["note"])

    def test_export_blocks_tampered_persisted_case_without_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data_dir = Path(temp)
            with _running_server(data_dir) as base_url:
                _, session, _ = _request(base_url, "/api/session")
                _, bundle, _ = _request(base_url, "/api/sample")
                create_status, created, _ = _request(
                    base_url,
                    "/api/runs",
                    method="POST",
                    payload={"bundle": bundle, "request_key": "tampered-export"},
                    token=session["csrf_token"],
                    origin=base_url,
                )
                self.assertEqual(201, create_status)
                run_id = created["run_id"]
                case_id = created["cases"][0]["case_id"]

                database_path = data_dir / "local_accounting_system.sqlite"
                with closing(sqlite3.connect(database_path)) as connection:
                    packet_json = connection.execute(
                        "SELECT packet_json FROM cases WHERE run_id = ? AND case_id = ?",
                        (run_id, case_id),
                    ).fetchone()[0]
                    packet = json.loads(packet_json)
                    packet["tampered"] = True
                    with connection:
                        connection.execute(
                            "UPDATE cases SET packet_json = ? WHERE run_id = ? AND case_id = ?",
                            (json.dumps(packet, sort_keys=True), run_id, case_id),
                        )

                status, error, headers = _request(
                    base_url, f"/api/runs/{run_id}/export"
                )
                self.assertEqual(409, status)
                self.assertIn("integrity", error["error"].casefold())
                self.assertIn(
                    f"case_evidence_hash_mismatch:{case_id}",
                    error["integrity_errors"],
                )
                self.assertFalse(
                    any(name.casefold() == "content-disposition" for name in headers)
                )

    def test_mutations_reject_bad_input_stale_reviews_and_cross_origin_requests(self) -> None:
        with tempfile.TemporaryDirectory() as temp, _running_server(Path(temp)) as base_url:
            _, session, _ = _request(base_url, "/api/session")
            token = session["csrf_token"]
            _, bundle, _ = _request(base_url, "/api/sample")

            host_status, _, _ = _request(
                base_url, "/api/session", host="attacker.invalid"
            )
            self.assertEqual(403, host_status)

            status, error, _ = _request(
                base_url,
                "/api/runs",
                method="POST",
                payload={"bundle": bundle, "request_key": "guarded-run"},
                origin=base_url,
            )
            self.assertEqual(403, status)
            self.assertIn("Reload", error["error"])

            status, _, _ = _request(
                base_url,
                "/api/runs",
                method="POST",
                payload={"bundle": bundle, "request_key": "guarded-run"},
                token=token,
                origin="https://attacker.invalid",
            )
            self.assertEqual(403, status)

            status, error, _ = _request(
                base_url,
                "/api/runs",
                method="POST",
                raw_body=b'{"bundle":',
                token=token,
                origin=base_url,
            )
            self.assertEqual(400, status)
            self.assertIn("valid JSON", error["error"])

            status, _, _ = _request(
                base_url,
                "/api/runs",
                method="POST",
                payload={"bundle": {}, "request_key": "malformed-bundle"},
                token=token,
                origin=base_url,
            )
            self.assertEqual(400, status)

            create_status, created, _ = _request(
                base_url,
                "/api/runs",
                method="POST",
                payload={"bundle": bundle, "request_key": "guarded-run"},
                token=token,
                origin=base_url,
            )
            self.assertEqual(201, create_status)
            run_id = created["run_id"]
            case = next(
                item for item in created["cases"]
                if item["policy_mode"] != "forbidden"
            )
            review_path = f'/api/runs/{run_id}/cases/{case["case_id"]}/review'
            empty_note_status, _, _ = _request(
                base_url,
                review_path,
                method="POST",
                payload={
                    "outcome": "needs_changes",
                    "note": "   ",
                    "expected_revision": case["review_revision"],
                },
                token=token,
                origin=base_url,
            )
            self.assertEqual(400, empty_note_status)
            review_payload = {
                "outcome": "needs_changes",
                "note": "Synthetic correction requested.",
                "expected_revision": case["review_revision"],
            }
            review_status, _, _ = _request(
                base_url,
                review_path,
                method="POST",
                payload=review_payload,
                token=token,
                origin=base_url,
            )
            self.assertEqual(200, review_status)
            stale_status, _, _ = _request(
                base_url,
                review_path,
                method="POST",
                payload=review_payload,
                token=token,
                origin=base_url,
            )
            self.assertEqual(409, stale_status)

            _, before_replay, _ = _request(base_url, "/api/runs")

            replay_status, replayed, _ = _request(
                base_url,
                "/api/runs",
                method="POST",
                payload={"bundle": bundle, "request_key": "guarded-run"},
                token=token,
                origin=base_url,
            )
            self.assertEqual(201, replay_status)
            self.assertEqual(run_id, replayed["run_id"])
            conflicting_bundle = dict(bundle)
            conflicting_bundle["name"] = "Changed replay content"
            conflict_status, _, _ = _request(
                base_url,
                "/api/runs",
                method="POST",
                payload={
                    "bundle": conflicting_bundle,
                    "request_key": "guarded-run",
                },
                token=token,
                origin=base_url,
            )
            self.assertEqual(409, conflict_status)
            _, listing, _ = _request(base_url, "/api/runs")
            self.assertEqual(len(before_replay["runs"]), len(listing["runs"]))


if __name__ == "__main__":
    unittest.main()
