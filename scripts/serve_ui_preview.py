#!/usr/bin/env python3
"""Build and serve the synthetic-only cockpit for browser QA on loopback."""

from __future__ import annotations

import argparse
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from accounting_agent.operations_cockpit import build_public_preview  # noqa: E402


class PreviewRequestHandler(SimpleHTTPRequestHandler):
    """Static-only handler with release-like privacy and cache headers."""

    def log_message(self, format: str, *args: object) -> None:
        """Keep parallel QA output focused on browser failures."""

        return

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'none'; object-src 'none'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'",
        )
        super().end_headers()

    def list_directory(self, path: str):  # type: ignore[no-untyped-def]
        self.send_error(404, "Directory listing is disabled")
        return None


class PreviewServer(ThreadingHTTPServer):
    """Threaded loopback server sized for parallel browser workers."""

    daemon_threads = True
    request_queue_size = 128


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4173)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("UI preview server must bind to loopback")
    if not 1024 <= args.port <= 65535:
        raise SystemExit("port must be between 1024 and 65535")

    output_dir = Path(".local") / "ui-preview"
    result = build_public_preview(repo_root=REPO_ROOT, output_dir=output_dir)
    bundle = result.output_path.parent
    if result.broken_links:
        raise SystemExit(f"preview contains broken links: {result.broken_links}")

    os.chdir(bundle)
    server = PreviewServer((args.host, args.port), PreviewRequestHandler)
    print(
        f"Synthetic UI preview: http://{args.host}:{args.port} "
        f"({len(tuple(bundle.iterdir()))} files)",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
