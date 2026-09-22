"""Loopback-only operator application for the synthetic accounting system."""

from __future__ import annotations

import json
import secrets
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import unquote, urlsplit

from accounting_agent.local_system import LocalAccountingSystem, sample_bundle
from accounting_agent.operations_cockpit import (
    ReviewContext, _bank_review_facts, _build_review_queues, _collect_review_items,
    _guided_review_reason, _prioritized_review_items, _review_amount, _supplier_review_facts,
)

MAX_BODY_BYTES = 2_000_000


def _present_case(case: dict) -> dict:
    """Reuse the cockpit's evidence and risk language without mutating packets."""
    packet = case.get("packet") or {}
    bank = case.get("kind") == "bank_reconciliation"
    if bank:
        transaction = packet.get("transaction") or {}
        context = ReviewContext(
            party=str(transaction.get("counterparty") or ""),
            reference=str(transaction.get("reference") or ""),
            amount=_review_amount(transaction.get("amount_minor"), transaction.get("currency"), minor=True),
            facts=_bank_review_facts(packet),
        )
        queues = _collect_review_items(supplier_cases=[], bank_proposals=[packet], fake_manifest={}, root=Path(".").resolve())
    else:
        fields = packet.get("extracted_fields") or {}
        context = ReviewContext(
            party=str(fields.get("supplier_name") or ""),
            reference=str(fields.get("invoice_number") or ""),
            amount=_review_amount((fields.get("amounts") or {}).get("gross"), fields.get("currency")),
            facts=_supplier_review_facts(fields),
        )
        queues = _collect_review_items(
            supplier_cases=[{"summary": {}, "packet": packet}], bank_proposals=[], fake_manifest={}, root=Path(".").resolve(),
        )
    prioritized = _prioritized_review_items(_build_review_queues(queues))
    item = prioritized[0] if prioritized else None
    if item and item.context:
        context = item.context
    result = dict(case)
    result["presentation"] = {
        "party": context.party, "reference": context.reference, "amount": context.amount,
        "title": item.title if item else "Local draft prepared",
        "reason": _guided_review_reason(item) if item else "Evidence and a draft proposal are ready to inspect. No financial action has been executed.",
        "severity": item.severity if item else "low",
        "facts": [{"label": f.label, "value": f.value} for f in context.facts],
        "candidates": [{"reference": ref, "score": score} for ref, score in context.candidates],
    }
    return result


def _present_run(run: dict) -> dict:
    result = dict(run)
    result["cases"] = [_present_case(case) for case in run.get("cases", [])]
    return result


def create_server(data_dir: str | Path, *, port: int = 8767) -> ThreadingHTTPServer:
    system = LocalAccountingSystem(data_dir)
    session_token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        server_version = "AccountingLocal/1.0"

        def log_message(self, format: str, *args: object) -> None:
            # Request bodies and accounting data must never enter console logs.
            return

        def _send(self, status: int, body: bytes, content_type: str, *, download: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{download}"')
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: object, *, download: str | None = None) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(), "application/json; charset=utf-8", download=download)

        def _host_valid(self) -> bool:
            port_value = self.server.server_address[1]
            return self.headers.get("Host") in {f"127.0.0.1:{port_value}", f"localhost:{port_value}"}

        def _route(self, *, write: bool = False) -> None:
            if not self._host_valid():
                self._json(403, {"error": "This application only accepts its loopback address."})
                return
            if write:
                origin = self.headers.get("Origin")
                expected_origin = f'http://{self.headers.get("Host")}'
                if origin is not None and origin != expected_origin:
                    self._json(403, {"error": "Request origin does not match this application."})
                    return
                if not secrets.compare_digest(self.headers.get("X-Accounting-Session", ""), session_token):
                    self._json(403, {"error": "Reload this workspace before saving changes."})
                    return
                if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                    self._json(415, {"error": "Use a JSON request body."})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_BODY_BYTES:
                        self._json(413, {"error": "A request must contain JSON and stay below 2 MB."})
                        return
                    payload = json.loads(self.rfile.read(length), parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON numbers are invalid")))
                    if not isinstance(payload, dict):
                        raise ValueError("A JSON object is required")
                except (ValueError, UnicodeError):
                    self._json(400, {"error": "The request is not valid JSON."})
                    return
            else:
                payload = {}
            route = [unquote(part) for part in urlsplit(self.path).path.split("/") if part]
            try:
                if not write and not route:
                    self._asset("system.html", "text/html; charset=utf-8")
                elif not write and route == ["favicon.ico"]:
                    self._asset("favicon.svg", "image/svg+xml")
                elif not write and len(route) == 2 and route[0] == "assets" and route[1] in {"system.js", "system.css", "tokens.css", "favicon.svg"}:
                    name = route[1]
                    content_type = {"js": "text/javascript", "css": "text/css", "svg": "image/svg+xml"}[name.rsplit(".", 1)[1]]
                    self._asset(name, content_type)
                elif not write and route == ["api", "session"]:
                    self._json(200, {"csrf_token": session_token, "environment": "synthetic_local", "live_actions_enabled": False})
                elif not write and route == ["api", "health"]:
                    try:
                        self._json(200, system.health())
                    except Exception:
                        self._json(503, {"status": "unavailable", "error": "Workspace storage is not ready."})
                elif not write and route == ["api", "workspace", "backup"]:
                    from accounting_agent.local_maintenance import create_backup

                    with tempfile.TemporaryDirectory(prefix="accounting-backup-download-") as temp:
                        destination = Path(temp) / "accounting-workspace.zip"
                        create_backup(system.data_dir, destination)
                        self._send(200, destination.read_bytes(), "application/zip", download="accounting-workspace.zip")
                elif not write and route == ["api", "sample"]:
                    self._json(200, sample_bundle(), download="synthetic-accounting-bundle.json")
                elif route == ["api", "runs"]:
                    if write:
                        if set(payload) - {"bundle", "request_key"}:
                            raise ValueError("Unknown run request fields")
                        run = system.create_run(payload.get("bundle"), payload.get("request_key"))
                        self._json(201, _present_run(run))
                    else:
                        self._json(200, {"runs": system.list_runs()})
                elif len(route) >= 3 and route[:2] == ["api", "runs"]:
                    run_id = route[2]
                    if not write and len(route) == 3:
                        self._json(200, _present_run(system.get_run(run_id)))
                    elif not write and len(route) == 4 and route[3] == "export":
                        exported = system.export_run(run_id)
                        if not exported.get("integrity_verified"):
                            self._json(409, {"error": "Evidence integrity checks failed; export is blocked.", "integrity_errors": exported.get("integrity_errors", [])})
                        else:
                            self._json(200, exported, download="accounting-evidence-package.json")
                    elif len(route) in {5, 6} and route[3] == "cases":
                        case_id = route[4]
                        if not write and len(route) == 5:
                            self._json(200, _present_case(system.get_case(run_id, case_id)))
                        elif write and len(route) == 6 and route[5] == "review":
                            if set(payload) != {"outcome", "note", "expected_revision"}:
                                raise ValueError("Review requires outcome, note, and expected_revision")
                            updated = system.record_review(run_id, case_id, **payload)
                            self._json(200, _present_case(updated))
                        else:
                            self._json(404, {"error": "Route not found"})
                    else:
                        self._json(404, {"error": "Route not found"})
                else:
                    self._json(404, {"error": "Route not found"})
            except KeyError:
                self._json(404, {"error": "This run or case was not found."})
            except (ValueError, TypeError) as exc:
                self._json(400, {"error": str(exc)})
            except RuntimeError as exc:
                self._json(409, {"error": str(exc)})
            except Exception:
                self._json(500, {"error": "The operation could not complete. Reload the run to inspect its saved status."})

        def _asset(self, name: str, content_type: str) -> None:
            self._send(200, resources.files("accounting_agent").joinpath("static", name).read_bytes(), content_type)

        def do_GET(self) -> None:
            self._route()

        def do_POST(self) -> None:
            self._route(write=True)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve_local_system(data_dir: str | Path, *, port: int = 8767) -> None:
    server = create_server(data_dir, port=port)
    print(f"Accounting Agent local system: http://127.0.0.1:{server.server_address[1]}/", flush=True)
    print("Synthetic data only. Review records do not authorize financial actions.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
