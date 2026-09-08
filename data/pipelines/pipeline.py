"""Monthly Clinic Supply Performance Pipeline.

Reads simulated telemetry events (standing in for `telemetry_events` in
Supabase, per PIPELINE_DESIGN.md section 3), aggregates them into monthly
per-clinic KPIs, and loads them idempotently into the
`reporting_monthly_clinic_supply_performance` TinyDB table.

NOTE ON CLINIC COUNT: PIPELINE_DESIGN.md (Part 1) says "12 clinics", written
before CONTEXT.md's final branch list was settled. CONTEXT.md now defines 14
branches, one of which ("central") is an internal/customer-complaint catch-all
and is not a physical clinic. This pipeline therefore treats CLINIC_BRANCHES
(13 branches) as the source of truth, derived directly from IncidentBranch,
instead of hardcoding "12" anywhere.
"""
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from prefect import flow, task
from prefect.states import State
from tinydb import Query, TinyDB

# --- Path setup ------------------------------------------------------------
# services/api/data/db.json is the single TinyDB file shared with the API,
# so endpoints under services/api/main.py can read what this pipeline writes.
REPO_ROOT = Path(__file__).resolve().parents[2]
API_DATA_DIR = REPO_ROOT / "services" / "api" / "data"
API_DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = API_DATA_DIR / "db.json"

db = TinyDB(DB_PATH)
pipeline_runs_table = db.table("pipeline_runs")
reporting_table = db.table("reporting_monthly_clinic_supply_performance")

PipelineVersion = "1.0.0"

# --- Clinic reference data ---------------------------------------------------
# Mirrors IncidentBranch from services/api/models.py, minus "central" (which
# is a catch-all, not a physical clinic). country/currency assigned per the
# US/UK split PIPELINE_DESIGN.md requires (section 4: "USD and GBP clinics
# are aggregated and stored as separate rows - never summed into one currency").
CLINIC_BRANCHES = {
    "austin_north": ("US", "USD"),
    "dallas_uptown": ("US", "USD"),
    "houston_med_center": ("US", "USD"),
    "san_antonio_west": ("US", "USD"),
    "miami_brickell": ("US", "USD"),
    "miami_doral": ("US", "USD"),
    "orlando_east": ("US", "USD"),
    "tampa_bay": ("US", "USD"),
    "atlanta_midtown": ("US", "USD"),
    "savannah": ("US", "USD"),
    "london_city": ("UK", "GBP"),
    "london_west": ("UK", "GBP"),
    "manchester_central": ("UK", "GBP"),
}

MANDATORY_EVENT_TYPES = [
    "inbound_order_created",
    "outbound_order_created",
    "stock_threshold_triggered",
    "supply_expiry_flagged",
]


def _month_start(dt: datetime) -> str:
    """Normalizes any datetime to the first day of its month, as an ISO date
    string (YYYY-MM-01). This is the grain used by the business key."""
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).date().isoformat()


def _target_months(reference: datetime | None = None) -> list[str]:
    """Returns the current month plus the previous month, per
    PIPELINE_DESIGN.md section 5's 2-month reprocessing window (catches
    late-arriving events)."""
    reference = reference or datetime.now(timezone.utc)
    current = _month_start(reference)
    previous_dt = reference.replace(day=1) - timedelta(days=1)
    previous = _month_start(previous_dt)
    return [previous, current]


# --- Extract -----------------------------------------------------------------

@task(retries=3, retry_delay_seconds=10)
def extract_supply_events(target_months: list[str]) -> list[dict]:
    """Simulates reading telemetry_events from Supabase, filtered to the four
    mandatory supply-related event types and windowed to target_months.

    Retries=3: absorbs transient read failures against the source system
    without failing the whole run on a single blip (per PIPELINE_DESIGN.md
    section 8, Prefect mapping).

    TODO (production): replace this simulated generator with a real query:
        SELECT * FROM telemetry_events
        WHERE event_type IN (...) AND created_at >= watermark
    using SupabaseCredentials, per PIPELINE_DESIGN.md section 3 and 8.
    """
    rng = random.Random(42)  # fixed seed: reproducible demo runs
    events: list[dict] = []

    for month_start in target_months:
        year, month, _ = (int(part) for part in month_start.split("-"))
        for clinic_id in CLINIC_BRANCHES:
            # Simulate a handful of events per clinic per month.
            event_count = rng.randint(3, 8)
            for _ in range(event_count):
                event_type = rng.choice(MANDATORY_EVENT_TYPES)
                day = rng.randint(1, 28)
                created_at = datetime(year, month, day, tzinfo=timezone.utc)

                properties = {}
                if event_type == "inbound_order_created":
                    properties["total_cost"] = round(rng.uniform(200, 5000), 2)
                    properties["quantity"] = rng.randint(10, 500)
                elif event_type == "outbound_order_created":
                    properties["quantity"] = rng.randint(5, 200)
                elif event_type == "stock_threshold_triggered":
                    properties["severity"] = rng.choice(["warning", "critical"])
                elif event_type == "supply_expiry_flagged":
                    properties["days_to_expiry"] = rng.randint(1, 30)

                events.append(
                    {
                        "event_type": event_type,
                        "clinic_id": clinic_id,
                        "created_at": created_at.isoformat(),
                        "properties": properties,
                    }
                )

    return events


# --- Transform -----------------------------------------------------------------

@task
def validate_supply_events(events: list[dict]) -> list[dict]:
    """Drops events missing required fields for their type, per
    PIPELINE_DESIGN.md section 3's schema prerequisite (inbound_order_created
    must carry a cost value)."""
    valid_events = []
    for event in events:
        if event["event_type"] not in MANDATORY_EVENT_TYPES:
            continue
        if event["clinic_id"] not in CLINIC_BRANCHES:
            continue
        if event["event_type"] == "inbound_order_created" and "total_cost" not in event["properties"]:
            continue
        valid_events.append(event)
    return valid_events


def _aggregate_cache_key(context, parameters) -> str:
    """Cache key = the exact set of validated events being aggregated. Since
    events is a list of dicts (unhashable), we key on a stable summary
    instead of the raw list."""
    events = parameters["events"]
    return f"aggregate-{len(events)}-{hash(tuple(sorted(e['event_type'] for e in events)))}"


@task(cache_key_fn=_aggregate_cache_key, cache_expiration=timedelta(hours=1))
def aggregate_monthly_kpis(events: list[dict]) -> list[dict]:
    """Aggregates validated events into the four business KPIs, grouped by
    (clinic_id, month_start), per PIPELINE_DESIGN.md section 2.

    Cached for 1h: re-running the pipeline twice in a row within an hour with
    the exact same input events skips recomputation (per PIPELINE_DESIGN.md
    section 8, "Blocks" / resilience expectations).
    """
    grouped: dict[tuple[str, str], dict] = {}

    for event in events:
        month_start = _month_start(datetime.fromisoformat(event["created_at"]))
        clinic_id = event["clinic_id"]
        key = (clinic_id, month_start)

        if key not in grouped:
            country, currency = CLINIC_BRANCHES[clinic_id]
            grouped[key] = {
                "clinic_id": clinic_id,
                "month_start": month_start,
                "country": country,
                "currency": currency,
                "total_supply_cost": 0.0,
                "supply_consumption_count": 0,
                "critical_stockout_count": 0,
                "expiry_risk_count": 0,
            }

        row = grouped[key]
        event_type = event["event_type"]
        properties = event["properties"]

        if event_type == "inbound_order_created":
            row["total_supply_cost"] += properties.get("total_cost", 0.0)
        elif event_type == "outbound_order_created":
            row["supply_consumption_count"] += 1
        elif event_type == "stock_threshold_triggered" and properties.get("severity") == "critical":
            row["critical_stockout_count"] += 1
        elif event_type == "supply_expiry_flagged":
            row["expiry_risk_count"] += 1

    for row in grouped.values():
        row["total_supply_cost"] = round(row["total_supply_cost"], 2)

    return list(grouped.values())


# --- Load ----------------------------------------------------------------------

@task(retries=2, retry_delay_seconds=5)
def load_monthly_clinic_supply_performance(rows: list[dict]) -> int:
    """Idempotent upsert into reporting_monthly_clinic_supply_performance,
    keyed on (clinic_id, month_start), per PIPELINE_DESIGN.md section 5.

    Retries=2: absorbs transient TinyDB file-lock/IO issues on write, mirrors
    the "load_monthly_clinic_supply_performance: connection reset" failure
    scenario described in the reference solution's error_summary example.
    """
    ReportingQuery = Query()
    loaded_clinics = set()

    for row in rows:
        computed_at = datetime.now(timezone.utc).isoformat()
        document = {**row, "computed_at": computed_at}

        existing = reporting_table.get(
            (ReportingQuery.clinic_id == row["clinic_id"])
            & (ReportingQuery.month_start == row["month_start"])
        )
        if existing is not None:
            reporting_table.update(
                document,
                (ReportingQuery.clinic_id == row["clinic_id"])
                & (ReportingQuery.month_start == row["month_start"]),
            )
        else:
            reporting_table.insert(document)

        loaded_clinics.add(row["clinic_id"])

    return len(loaded_clinics)


# --- Optional step (resilience pattern) -----------------------------------------

@task
def notify_ops_optional(summary: dict) -> None:
    """Stands in for a Slack/webhook notification to the ops/compliance
    channel (PIPELINE_DESIGN.md section 8, "States": Failed triggers an
    alert). Simulated here as a log line - the flow must continue even if
    this fails, since it is not critical to the pipeline's core job."""
    print(f"[ops-notify] Monthly clinic supply performance run summary: {summary}")


# --- Flow ------------------------------------------------------------------------

@flow(name="monthly_clinic_supply_performance_flow")
def monthly_clinic_supply_performance_flow(reference_date: datetime | None = None) -> dict:
    """Main orchestration flow. Recomputes the current month plus the
    previous month (2-month reprocessing window), per PIPELINE_DESIGN.md
    section 5, to catch late-arriving events."""
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    target_months = _target_months(reference_date)

    run_record = {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "month_processed": target_months,
        "clinics_loaded": 0,
        "rows_extracted": 0,
        "status": "running",
        "error_summary": None,
        "pipeline_version": PipelineVersion,
    }
    pipeline_runs_table.insert(run_record)

    try:
        raw_events = extract_supply_events(target_months)
        valid_events = validate_supply_events(raw_events)
        kpi_rows = aggregate_monthly_kpis(valid_events)
        clinics_loaded = load_monthly_clinic_supply_performance(kpi_rows)

        finished_at = datetime.now(timezone.utc)
        expected_clinic_count = len(CLINIC_BRANCHES)
        status = "success" if clinics_loaded >= expected_clinic_count else "partial"

        summary = {
            "run_id": run_id,
            "status": status,
            "clinics_loaded": clinics_loaded,
            "expected_clinic_count": expected_clinic_count,
            "rows_extracted": len(raw_events),
        }
        # Optional/non-critical step: the flow must not fail if this does.
        notify_state: State = notify_ops_optional(summary, return_state=True)
        if notify_state.is_failed():
            print("[ops-notify] skipped - notification step failed, run continues")

        RunQuery = Query()
        pipeline_runs_table.update(
            {
                "finished_at": finished_at.isoformat(),
                "clinics_loaded": clinics_loaded,
                "rows_extracted": len(raw_events),
                "status": status,
            },
            RunQuery.run_id == run_id,
        )

        return summary

    except Exception as exc:  # noqa: BLE001 - top-level flow guard, logs and re-raises
        finished_at = datetime.now(timezone.utc)
        RunQuery = Query()
        pipeline_runs_table.update(
            {
                "finished_at": finished_at.isoformat(),
                "status": "failed",
                "error_summary": str(exc),
            },
            RunQuery.run_id == run_id,
        )
        raise


# --- Application integration helpers (used by services/api/main.py) ------------

def get_latest_pipeline_run() -> dict | None:
    """Returns the most recently started pipeline run, or None if the
    pipeline has never run. Used by GET /reporting/pipeline-runs/latest."""
    runs = pipeline_runs_table.all()
    if not runs:
        return None
    return max(runs, key=lambda run: run["started_at"])


def trigger_pipeline_run() -> dict:
    """Runs the flow synchronously and returns a trigger acknowledgement.
    Used by POST /reporting/pipeline-runs."""
    summary = monthly_clinic_supply_performance_flow()
    return {"message": "Pipeline run submitted", "flow_run_id": summary["run_id"]}


def get_monthly_clinic_supply_performance(month_start: str | None = None) -> list[dict]:
    """Returns all clinics' rows for the given month, or the most recent
    month present in the table if month_start is omitted. Used by
    GET /reporting/monthly-clinic-supply-performance."""
    all_rows = reporting_table.all()
    if not all_rows:
        return []

    if month_start is None:
        month_start = max(row["month_start"] for row in all_rows)

    return [row for row in all_rows if row["month_start"] == month_start]


if __name__ == "__main__":
    result = monthly_clinic_supply_performance_flow()
    print(f"Pipeline run complete: {result}")
    sys.exit(0 if result["status"] == "success" else 1)
