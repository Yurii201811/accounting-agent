from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from accounting_agent.bank_reconciliation import BankReconciliationPipeline
from accounting_agent.agentic import agentic_platform_summary
from accounting_agent.db import LocalQueue
from accounting_agent.fake_client_dry_run import (
    DEFAULT_FAKE_CLIENT_OUTPUT,
    DEFAULT_FAKE_CLIENT_REPORT,
    FakeClientDryRunError,
    run_fake_client_dry_run,
)
from accounting_agent.intake import IntakeSourceType, LocalIntakeProcessor, SQLiteIntakeStore
from accounting_agent.erp import erp_registry_summary
from accounting_agent.jurisdictions import jurisdiction_registry_summary
from accounting_agent.local_demo import (
    DEFAULT_DEMO_OUTPUT,
    DEMO_EVALUATION_DATE,
    LocalDemoError,
    run_supplier_invoice_autopilot_demo,
)
from accounting_agent.operations_cockpit import (
    DEFAULT_OUTPUT_PATH as DEFAULT_OPERATIONS_COCKPIT_OUTPUT,
    build_operations_cockpit,
)
from accounting_agent.supplier_invoice import SupplierInvoicePipeline


DEFAULT_FIXTURES = Path("fixtures/supplier_invoices")
DEFAULT_BANK_FIXTURES = Path("fixtures/bank_reconciliation")
DEFAULT_M365_FIXTURES = Path("fixtures/microsoft365_intake")
DEFAULT_DB = Path(".local/accounting_agent.sqlite")
DEFAULT_OUTPUT = Path(".local/approval_packets")
DEFAULT_BANK_OUTPUT = Path(".local/bank_reconciliation_packets")
DEFAULT_INTAKE_STORAGE = Path(".local/intake_documents")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Accounting Agent local operator CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    process = subparsers.add_parser(
        "process-fixtures",
        help="Process supplier invoice sample fixtures into approval packets.",
    )
    process.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    process.add_argument("--db", type=Path, default=DEFAULT_DB)
    process.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    process.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=DEMO_EVALUATION_DATE,
        help="Evaluation date for deterministic fixture risk review (YYYY-MM-DD).",
    )

    reconcile = subparsers.add_parser(
        "reconcile-bank-fixtures",
        help="Process sample bank transactions into reconciliation proposals.",
    )
    reconcile.add_argument("--fixtures", type=Path, default=DEFAULT_BANK_FIXTURES)
    reconcile.add_argument("--output", type=Path, default=DEFAULT_BANK_OUTPUT)

    intake = subparsers.add_parser(
        "scan-intake-folder",
        help="Scan a local/mock Microsoft 365 folder into normalized intake cases.",
    )
    intake.add_argument("--folder", type=Path, default=DEFAULT_M365_FIXTURES)
    intake.add_argument("--db", type=Path, default=DEFAULT_DB)
    intake.add_argument("--storage", type=Path, default=DEFAULT_INTAKE_STORAGE)
    intake.add_argument(
        "--source-type",
        choices=[source_type.value for source_type in IntakeSourceType],
        default=IntakeSourceType.ONEDRIVE_FOLDER_FILE.value,
    )

    demo = subparsers.add_parser(
        "demo-supplier-invoice-autopilot",
        help="Run the complete local Supplier Invoice Autopilot demo.",
    )
    demo.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    demo.add_argument("--output", type=Path, default=DEFAULT_DEMO_OUTPUT)
    demo.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=DEMO_EVALUATION_DATE,
        help="Evaluation date for deterministic fixture risk review (YYYY-MM-DD).",
    )

    fake_client = subparsers.add_parser(
        "fake-client-dry-run",
        help="Run a full synthetic Swedish fake-client month through the local MVP.",
    )
    fake_client.add_argument("--output", type=Path, default=DEFAULT_FAKE_CLIENT_OUTPUT)
    fake_client.add_argument("--report", type=Path, default=DEFAULT_FAKE_CLIENT_REPORT)

    cockpit = subparsers.add_parser(
        "build-operations-cockpit",
        help="Build a read-only static local operations cockpit from repo artifacts.",
    )
    cockpit.add_argument("--output", type=Path, default=DEFAULT_OPERATIONS_COCKPIT_OUTPUT)

    platform_status = subparsers.add_parser(
        "platform-status",
        help="Show jurisdiction, ERP capability, computer-use, role, and specialist boundaries.",
    )
    platform_status.add_argument(
        "--json",
        action="store_true",
        help="Emit the complete machine-readable platform declaration.",
    )

    args = parser.parse_args(argv)
    if args.command == "process-fixtures":
        pipeline = SupplierInvoicePipeline(
            db_path=args.db,
            output_dir=args.output,
            evaluation_date=args.as_of,
        )
        packets = pipeline.process_fixture_dir(args.fixtures)
        queue = LocalQueue(args.db)
        print(f"Processed {len(packets)} supplier invoice fixtures")
        print(f"Approval packets: {args.output}")
        print(f"SQLite queue: {args.db}")
        print(f"Stored approval packets: {queue.count('approval_packets')}")
        print(f"Evaluation date: {args.as_of.isoformat()}")
        for packet in packets:
            print(
                f"- {packet['case']['fixture_name']}: "
                f"{packet['policy_decision']['mode']} / "
                f"{packet['risk']['level']} risk -> {packet['packet_path']}"
            )
        return 0

    if args.command == "reconcile-bank-fixtures":
        pipeline = BankReconciliationPipeline(output_dir=args.output)
        proposals = pipeline.process_fixture_dir(args.fixtures)
        packet_count = sum(1 for proposal in proposals if proposal.get("approval_packet_path"))
        print(f"Processed {len(proposals)} bank transaction fixtures")
        print(f"Approval packets: {args.output}")
        print(f"Approval packets generated: {packet_count}")
        for proposal in proposals:
            selected = proposal["selected_candidate"]
            target = selected["target_id"] if selected else "unmatched"
            packet_path = proposal.get("approval_packet_path", "")
            suffix = f" -> {packet_path}" if packet_path else ""
            print(
                f"- {proposal['transaction']['transaction_id']}: "
                f"{target} / {proposal['policy_decision']['mode']} / "
                f"{proposal['confidence']:.2f} confidence{suffix}"
            )
        return 0

    if args.command == "scan-intake-folder":
        store = SQLiteIntakeStore(args.db)
        processor = LocalIntakeProcessor(store=store, storage_root=args.storage)
        cases = processor.scan_folder(
            args.folder,
            source_type=IntakeSourceType(args.source_type),
        )
        tasks = store.list_extraction_tasks()
        print(f"Scanned {len(cases)} local intake files")
        print(f"SQLite queue: {args.db}")
        print(f"Stored documents: {args.storage}")
        print(f"Extraction tasks queued: {len(tasks)}")
        for case in cases:
            duplicate = (
                f" duplicate_of={case.duplicate_of_case_id} reasons={','.join(case.duplicate_reasons)}"
                if case.duplicate_reasons
                else ""
            )
            print(f"- {case.file_name}: {case.case_id} client={case.client_id}{duplicate}")
        return 0

    if args.command == "demo-supplier-invoice-autopilot":
        try:
            manifest = run_supplier_invoice_autopilot_demo(
                supplier_fixture_dir=args.fixtures,
                output_dir=args.output,
                evaluation_date=args.as_of,
            )
        except LocalDemoError as exc:
            print(f"Demo failed: {exc}", file=sys.stderr)
            return 1
        summary = manifest["summary"]
        print("Supplier Invoice Autopilot local demo complete")
        print(f"Output folder: {summary['output_dir']}")
        print(f"Normalized intake cases: {summary['normalized_intake_cases']}")
        print(f"Approval packets: {summary['approval_packets']}")
        print(f"Execution permits issued: {summary['execution_permits_issued']}")
        print(f"Evaluation date: {summary['evaluation_date']}")
        print("Live Fortnox calls: 0")
        print("Live Microsoft 365 calls: 0")
        print("Emails/payments/filings: 0")
        print(f"Summary: {args.output / 'summary.json'}")
        print(f"Manifest: {args.output / 'manifest.json'}")
        return 0

    if args.command == "fake-client-dry-run":
        try:
            manifest = run_fake_client_dry_run(
                output_dir=args.output,
                report_path=args.report,
            )
        except (FakeClientDryRunError, LocalDemoError) as exc:
            print(f"Fake-client dry run failed: {exc}", file=sys.stderr)
            return 1
        metrics = manifest["metrics"]
        print("Fake-client accounting MVP dry run complete")
        print(f"Output folder: {manifest['run']['output_dir']}")
        print(f"Report: {manifest['run']['report_path']}")
        print(
            "Sample data: "
            f"{metrics['sample_counts']['supplier_invoices_or_receipts']} supplier invoices/receipts, "
            f"{metrics['sample_counts']['customer_invoices']} customer invoices, "
            f"{metrics['sample_counts']['bank_transactions']} bank transactions"
        )
        print(f"Primary policy decisions: {metrics['primary_case_decision_counts']}")
        print(f"Observed policy decisions: {metrics['observed_policy_decision_counts']}")
        print(f"False positives: {len(metrics['false_positives'])}")
        print(f"Unsafe misses: {len(metrics['unsafe_misses'])}")
        print(f"Unclear outputs: {len(metrics['unclear_outputs'])}")
        print(f"Policy alignment warnings: {len(metrics['policy_alignment_warnings'])}")
        print("Live Fortnox calls: 0")
        print("Live Microsoft 365 calls: 0")
        print("Emails/payments/filings/final postings: 0")
        return 0

    if args.command == "build-operations-cockpit":
        result = build_operations_cockpit(output_path=args.output)
        print("Operations cockpit built")
        print(f"Output: {result.output_path}")
        print(f"Links checked: {result.link_targets_checked}")
        print(f"Broken links: {len(result.broken_links)}")
        print("Live Fortnox calls: 0")
        print("Live Microsoft 365 calls: 0")
        print("Emails/payments/filings/final postings: 0")
        if result.broken_links:
            for path in result.broken_links:
                print(f"- broken link target: {path}")
            return 1
        return 0

    if args.command == "platform-status":
        payload = {
            "jurisdictions": jurisdiction_registry_summary(),
            "erp": erp_registry_summary(),
            "agentic": agentic_platform_summary(),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        print("Accounting Agent v2 platform boundary")
        print("Default jurisdiction: se-2026 (foundation only, no filing claim)")
        print("ERP profiles:")
        for profile in payload["erp"]["profiles"]:
            print(f"- {profile['display_name']}: {profile['connection_status']}")
        print("External post/approve/send/pay/file/delete/settings: forbidden")
        print("Computer use: supervised observation and evidence only")
        print(
            "Bounded specialists: "
            f"{len(payload['agentic']['specialists'])}; human decision gate required"
        )
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
