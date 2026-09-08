"""Monthly Clinic Supply Performance Pipeline.

Reads simulated telemetry events (standing in for `telemetry_events` in
Supabase, per PIPELINE_DESIGN.md section 3), aggregates them into monthly
per-clinic KPIs, and loads them idempotently into the
`reporting_monthly_clinic_supply_performance` TinyDB table.

MILESTONE 6 PART 3 REFACTOR NOTE: the main flow now orchestrates 3
subflows (@flow) instead of calling @task functions directly, per the
"Subflow refactoring patterns (reference)" section. All pure aggregation
logic (validation, KPI math) now lives in data/process/transforms.py so it
can be unit-tested without a Prefect runtime - see
tests/pipelines/test_pipeline.py.

NOTE ON CLINIC COUNT: PIPELINE_DESIGN.md (Part 1) says "12 clinics", written
before CONTEXT.md's final branch list was settled. CONTEXT.md now defines 14
branches, one of which ("central") is an internal/customer-complaint catch-all
and is not a physical clinic. This pipeline therefore treats CLINIC_BRANCHES
(13 branches, defined in data/process/transforms.py) as the source of truth,
derived directly from IncidentBranch, instead of hardcoding "12" anywhere.
"""
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --- sys.path bootstrap -----------------------------------------------------
# Ensures `from data.process.transforms import ...` resolves regardless of
# HOW this file is launched (editor Run button, `python data/pipelines/
# pipeline.py` from repo root, or pytest collection). Must run before the
# local import below.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from prefect import flow, task
from prefect.states import State
from tinydb import Query, TinyDB

from data.process.transforms import (
    CLINIC_BRANCHES,
    MANDATORY_EVENT_TYPES,
    aggregate_monthly_kpis,
    target_months,
    validate_supply_events,
)

# --- Path setup ------------------------------------------------------------
# services/api/data/db.json is the single TinyDB file shared with the API,
# so endpoints under services/api/main.py can read what this pipeline writes.
API_DATA_DIR = REPO_ROOT / "services" / "api" / "data"
API_DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = API_DATA_DIR / "db.json"

db = TinyDB(DB_PATH)
pipeline_runs_table = db.table("pipeline_runs")
reporting_table = db.table("reporting_monthly_clinic_supply_performance")

PipelineVersion = "1.1.0"  # bumped: Part 3 subflow + tests refactor


# --- Extract: task + subflow --------------------------------------------------

@task(retries=3, retry_delay_seconds=10)
def extract_supply_events(target_month_list: list[str]) -> list[dict]:
    """Simulates reading telemetry_events from Supabase, filtered to the four
    mandatory supply-related event types and windowed to target_month_list.

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

    for month in target_month_list:
        year, month_num, _ = (int(part) for part in month.split("-"))
        for clinic_id in CLINIC_BRANCHES:
            # Simulate a handful of events per clinic per month.
            event_count = rng.randint(3, 8)
            for _ in range(event_count):
                event_type = rng.choice(MANDATORY_EVENT_TYPES)
                day = rng.randint(1, 28)
                created_at = datetime(year, month_num, day, tzinfo=timezone.utc)

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


@flow(name="extract-telemetry-events")
def extract_telemetry_subflow(watermark_from: list[str]) -> list[dict]:
    """Subflow wrapping the extract phase. Explicit input (target months) /
    output (raw events) - can run independently of the rest of the pipeline
    for backfills or debugging."""
    return extract_supply_events(watermark_from)


# --- Transform: tasks + subflow -----------------------------------------------

@task
def validate_supply_events_task(events: list[dict]) -> list[dict]:
    """Thin @task wrapper around the pure validate_supply_events helper in
    data/process/transforms.py (PIPELINE_DESIGN.md section 9: no ETL logic
    reimplemented at the orchestration layer)."""
    return validate_supply_events(events)


def _aggregate_cache_key(context, parameters) -> str:
    """Cache key = the exact set of validated events being aggregated. Since
    events is a list of dicts (unhashable), we key on a stable summary
    instead of the raw list."""
    events = parameters["events"]
    return f"aggregate-{len(events)}-{hash(tuple(sorted(e['event_type'] for e in events)))}"


@task(cache_key_fn=_aggregate_cache_key, cache_expiration=timedelta(hours=1))
def aggregate_monthly_kpis_task(events: list[dict]) -> list[dict]:
    """Thin @task wrapper around the pure aggregate_monthly_kpis helper.
    Cached for 1h: re-running the pipeline twice in a row within an hour
    with the exact same input events skips recomputation (per
    PIPELINE_DESIGN.md section 8, "Blocks" / resilience expectations)."""
    return aggregate_monthly_kpis(events)


@flow(name="transform-business-kpis")
def transform_business_kpis_subflow(raw_events: list[dict]) -> list[dict]:
    """Subflow wrapping validate + aggregate. Explicit input (raw events) /
    output (KPI rows per clinic/month) - independently runnable and
    independently testable against a fixture list of events."""
    valid_events = validate_supply_events_task(raw_events)
    return aggregate_monthly_kpis_task(valid_events)


# --- Load: task + subflow -------------------------------------------------------

@task(retries=2, retry_delay_seconds=5)
def load_monthly_clinic_supply_performance(rows: list[dict]) -> int:
    """Idempotent upsert into reporting_monthly_clinic_supply_performance,
    keyed on (clinic_id, month_start), per CONTEXT section 5.

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


@flow(name="load-weekly-location-performance")
def load_monthly_clinic_supply_performance_subflow(aggregates: list[dict]) -> int:
    """Subflow wrapping the load phase. Named after the reference solution's
    "load_weekly_location_performance_subflow" pattern, adapted to this
    project's monthly/clinic grain. Explicit input (KPI rows) / output
    (clinics loaded count)."""
    return load_monthly_clinic_supply_performance(aggregates)


# --- Optional step (resilience pattern) -----------------------------------------

@task
def notify_ops_optional(summary: dict) -> None:
    """Stands in for a Slack/webhook notification to the ops/compliance
    channel (PIPELINE_DESIGN.md section 8, "States": Failed triggers an
    alert). Simulated here as a log line - the flow must continue even if
    this fails, since it is not critical to the pipeline's core job."""
    print(f"[ops-notify] Monthly clinic supply performance run summary: {summary}")


@flow(name="notify-ops")
def notify_ops_subflow(summary: dict) -> None:
    """Subflow wrapping the optional notification step, so it shows up as
    its own node in the Prefect UI/flow graph alongside the other 3
    subflows, per the reference architecture diagram."""
    notify_ops_optional(summary)


# --- Main flow ------------------------------------------------------------------

@flow(name="monthly_clinic_supply_performance_flow")
def monthly_clinic_supply_performance_flow(reference_date: datetime | None = None) -> dict:
    """Main orchestration flow. Coordinates 4 subflows - no inline ETL logic
    in the main body, per Milestone 6 Part 3's "Component boundaries" table.
    Recomputes the current month plus the previous month (2-month
    reprocessing window), per PIPELINE_DESIGN.md section 5, to catch
    late-arriving events."""
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    watermark_from = target_months(reference_date)

    run_record = {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "month_processed": watermark_from,
        "clinics_loaded": 0,
        "rows_extracted": 0,
        "status": "running",
        "error_summary": None,
        "pipeline_version": PipelineVersion,
    }
    pipeline_runs_table.insert(run_record)

    try:
        raw_events = extract_telemetry_subflow(watermark_from)
        kpi_rows = transform_business_kpis_subflow(raw_events)
        clinics_loaded = load_monthly_clinic_supply_performance_subflow(kpi_rows)

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
        # Optional/non-critical subflow: the main flow must not fail if this does.
        notify_state: State = notify_ops_subflow(summary, return_state=True)
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


def get_monthly_clinic_supply_performance(requested_month_start: str | None = None) -> list[dict]:
    """Returns all clinics' rows for the given month, or the most recent
    month present in the table if requested_month_start is omitted. Used by
    GET /reporting/monthly-clinic-supply-performance."""
    all_rows = reporting_table.all()
    if not all_rows:
        return []

    if requested_month_start is None:
        requested_month_start = max(row["month_start"] for row in all_rows)

    return [row for row in all_rows if row["month_start"] == requested_month_start]


if __name__ == "__main__":
    result = monthly_clinic_supply_performance_flow()
    print(f"Pipeline run complete: {result}")
    sys.exit(0 if result["status"] == "success" else 1)