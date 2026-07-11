from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from accounting_agent.operations_cockpit import build_public_preview
from scripts.deployment_smoke import (
    DeploymentSmokeError,
    run_deployment_smoke,
    write_deployment_summary,
)


ROOT = Path(__file__).resolve().parents[1]


class DeploymentSmokeTests(unittest.TestCase):
    def test_deployed_bundle_must_match_all_five_local_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            bundle = Path(directory) / "preview"
            build_public_preview(repo_root=ROOT, output_dir=bundle)
            requested: list[str] = []

            def fetch(url: str, _maximum_bytes: int) -> bytes:
                requested.append(url)
                return (bundle / url.rsplit("/", 1)[-1]).read_bytes()

            summary = run_deployment_smoke(
                target="https://synthetic-preview.vercel.app",
                bundle=bundle,
                fetch=fetch,
            )

        self.assertEqual(5, summary["files_verified"])
        self.assertEqual(5, len(requested))
        self.assertEqual([], summary["hash_mismatches"])
        self.assertEqual("https://synthetic-preview.vercel.app", summary["target"])
        self.assertEqual(
            {
                "LICENSE.lucide.txt",
                "favicon.svg",
                "index.html",
                "preview-manifest.json",
                "tokens.css",
            },
            set(summary["file_hashes"]),
        )
        for hashes in summary["file_hashes"].values():
            self.assertEqual(hashes["local_sha256"], hashes["remote_sha256"])
            self.assertTrue(hashes["match"])

    def test_plain_http_remote_target_is_rejected_before_transport(self) -> None:
        called = False

        def fetch(_url: str, _maximum_bytes: int) -> bytes:
            nonlocal called
            called = True
            return b""

        with self.assertRaisesRegex(DeploymentSmokeError, "HTTPS"):
            run_deployment_smoke(
                target="http://preview.vercel.app",
                bundle=ROOT,
                fetch=fetch,
            )
        self.assertFalse(called)

    def test_remote_hash_mismatch_fails_the_smoke(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            bundle = Path(directory) / "preview"
            build_public_preview(repo_root=ROOT, output_dir=bundle)

            def fetch(url: str, _maximum_bytes: int) -> bytes:
                name = url.rsplit("/", 1)[-1]
                if name == "index.html":
                    return b"tampered"
                return (bundle / name).read_bytes()

            with self.assertRaisesRegex(DeploymentSmokeError, "hash mismatch"):
                run_deployment_smoke(
                    target="https://synthetic-preview.vercel.app",
                    bundle=bundle,
                    fetch=fetch,
                )

    def test_local_or_private_target_is_rejected_before_transport(self) -> None:
        called = False

        def fetch(_url: str, _maximum_bytes: int) -> bytes:
            nonlocal called
            called = True
            return b""

        for target in (
            "https://localhost",
            "https://127.0.0.1",
            "https://10.0.0.2",
            "https://preview.internal",
        ):
            with self.subTest(target=target):
                with self.assertRaisesRegex(DeploymentSmokeError, "public Vercel"):
                    run_deployment_smoke(
                        target=target,
                        bundle=ROOT,
                        fetch=fetch,
                    )
        self.assertFalse(called)

    def test_summary_writer_creates_machine_readable_release_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "preview" / "deployment-smoke.json"
            write_deployment_summary(
                output,
                {
                    "schema_version": 1,
                    "files_verified": 5,
                    "hash_mismatches": [],
                    "synthetic_data_only": True,
                    "external_authority": False,
                },
            )

            payload = output.read_text(encoding="utf-8")

        self.assertIn('"files_verified": 5', payload)
        self.assertNotIn("token", payload.lower())


if __name__ == "__main__":
    unittest.main()
