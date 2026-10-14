"""MEM-092: consolidation / cleanup of the agent memory.

Run it by hand or schedule it (cron, Celery beat...). The policy lives in
services/api/agent/memory/consolidate.py: re-check every stored entry against the memory
policy (patient information is deleted), expire unused entries, supersede older corrections,
cap the total size.

Usage (from the repo root):
  python scripts/memory_consolidate.py --dry-run   # show what would be removed, change nothing
  python scripts/memory_consolidate.py             # apply the cleanup
  python scripts/memory_consolidate.py --summary   # also print the audit log summary
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # `data` package
sys.path.insert(0, str(ROOT / "services" / "api"))  # `agent` package

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from agent.memory import runtime  # noqa: E402
from agent.memory.audit import AuditRecord  # noqa: E402
from agent.memory.clock import to_iso, utc_now  # noqa: E402
from agent.memory.consolidate import ENTRY_TTL_DAYS, MAX_ENTRIES, consolidate  # noqa: E402
from agent.memory.store import InMemoryMemoryStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Consolidate the agent memory (MEM-092).")
    parser.add_argument("--dry-run", action="store_true", help="report only, do not delete anything")
    parser.add_argument("--summary", action="store_true", help="print the audit log summary")
    args = parser.parse_args()

    store = runtime.get_store()
    entries = store.list()
    print("Policy: re-check every entry for patient information and other forbidden data (delete failures),")
    print(f"        expire after {ENTRY_TTL_DAYS} days unused, supersede older corrections, keep at most {MAX_ENTRIES} entries.")
    print(f"Entries before: {len(entries)}")

    target = store
    if args.dry_run:
        target = InMemoryMemoryStore()  # work on a copy: the real store is never touched
        for entry in entries:
            target.write(entry)

    report = consolidate(target)
    print(f"Removed by the memory policy (patient information, credentials...): {len(report.policy_removed)} {report.policy_removed}")
    print(f"Expired (unused): {len(report.expired)} {report.expired}")
    print(f"Superseded (newer correction or duplicate): {len(report.superseded)} {report.superseded}")
    print(f"Evicted (size cap): {len(report.evicted)} {report.evicted}")
    print(f"Entries kept: {report.kept}")
    print("DRY RUN: nothing was deleted." if args.dry_run else "Cleanup applied.")

    if report.policy_removed and not args.dry_run:
        audit = runtime.get_audit_log()
        for entry_id, reason in report.policy_removed:  # the fact text is NOT logged: it was forbidden data
            audit.append(AuditRecord(
                timestamp=to_iso(utc_now()), proposal_id=entry_id, session_id="consolidation",
                proposed_fact="[removed by the memory policy: text not logged]", user_message=None,
                decision="policy_rejected", written=False,
                reason=f"consolidation deleted a stored entry that no longer passes the policy ({reason})",
            ))

    if args.summary:
        records = runtime.get_audit_log().list()
        counts = Counter(record.decision for record in records)
        print(f"Audit log: {len(records)} records")
        for name, total in sorted(counts.items()):
            print(f"  {name}: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
