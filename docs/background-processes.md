# Background Processes — Nightly Telemetry Export

Independent CLI job that exports the previous day's `telemetry_events` to a
CSV backup and triggers the Milestone 6 business performance pipeline. Runs
as its own OS process — never inside the FastAPI application.

## Architecture

crontab (02:00 UTC)
-> scripts/nightly_export.py
-> services/api/job_runner.py (job_runs lifecycle / lock)
-> data/raw/telemetry_YYYY-MM-DD.csv (backup only, from telemetry_events)
-> subprocess: data/pipelines/pipeline.py (reads telemetry_events from DB, not the CSV)


**Why a standalone script instead of a FastAPI-embedded scheduler
(`@app.on_event("startup")`, APScheduler, `@repeat_every`):** the nightly
export must survive independently of whether the API process is up, must
not block or share a thread with request handling, and must be
individually testable/re-runnable without restarting the API server. This
matches the "Recommended" option in the project's reference solution.

## Trigger — OS crontab (recommended)

```cron
0 2 * * * cd /path/to/monorepo && /usr/bin/python scripts/nightly_export.py >> /var/log/nightly_export.log 2>&1
```

Runs daily at 02:00 UTC. Chosen over APScheduler-in-FastAPI or a framework
scheduler because it keeps the job fully independent of the API's main
thread and process lifecycle — if the API crashes or redeploys, the
nightly job is unaffected, and vice versa.

## `job_runs` state machine

pending -> processing -> completed
-> failed


`status = 'processing'` doubles as the distributed lock — no separate lock
table/column. A `try/except/finally` in `main()` guarantees a crash never
leaves a row stuck in `processing`. Idempotency key is
`(job_name, target_date)`, not `job_name` alone.

| Column | Purpose |
|---|---|
| `job_name` | e.g. `nightly_export` |
| `target_date` | calendar day processed (UTC); idempotency key |
| `status` | `pending` \| `processing` \| `completed` \| `failed` |
| `started_at` / `finished_at` | set on entering `processing` / terminal state |
| `error_message` | populated on `failed` |

## `TARGET_DATE` override

Defaults to yesterday in UTC. Override for testing without code changes:

```bash
TARGET_DATE=2026-09-07 python scripts/nightly_export.py
```

## Validation evidence

**1. Successful run (real data, 17 rows exported):**

2026-09-09T01:35:11Z INFO nightly_export status=started target_date=2026-09-07
2026-09-09T01:35:12Z INFO nightly_export status=export_completed rows=17 path=.../data/raw/telemetry_2026-09-07.csv target_date=2026-09-07
2026-09-09T01:35:26Z INFO nightly_export status=pipeline_completed output=[ops-notify] Monthly clinic supply performance run summary: {'run_id': 'd2a4fcde-3c96-4ee4-8a50-a914797f6500', 'status': 'success', 'clinics_loaded': 13, 'expected_clinic_count': 13, 'rows_extracted': 141}
2026-09-09T01:35:27Z INFO nightly_export status=completed target_date=2026-09-07
2026-09-09T01:35:27Z INFO nightly_export status=finished target_date=2026-09-07


**2. Duplicate same-day run — skipped, no re-export, no re-run:**

2026-09-09T01:32:28Z INFO nightly_export status=skipped reason=duplicate target_date=2026-09-08


**3. Concurrent instance — second run cancels, no parallel `processing` row:**

2026-09-09T01:34:21Z INFO nightly_export status=cancelled reason=processing_lock target_date=2026-09-07


**4. Zombie prevention — a `processing` row from a simulated crash was
manually closed (`mark_failed`), then a fresh run for the same date
completed normally with no lingering lock**, confirming `processing`
never survives a failure without release.

**5. Forced pipeline failure — row ends `failed`, not `processing`,
`error_message` populated:**

2026-09-09T01:35:54Z INFO nightly_export status=started target_date=2026-09-06
2026-09-09T01:35:54Z INFO nightly_export status=export_completed rows=0 path=.../data/raw/telemetry_2026-09-06.csv target_date=2026-09-06
2026-09-09T01:35:54Z ERROR nightly_export status=failed error=pipeline exit code 2: ... target_date=2026-09-06
2026-09-09T01:35:54Z INFO nightly_export status=finished target_date=2026-09-06


**6. `TARGET_DATE` override** — used throughout all tests above
(`2026-09-06`, `2026-09-07`, `2026-09-08`) without any code changes.

## Dependencies note

This branch merges in `feature/business-performance-pipeline` (Milestone 6
pipeline, `data/pipelines/pipeline.py`) and `feature/telemetry-storage`
(`telemetry_events` table) as prerequisites, since neither was merged to
`main` at the time this feature branch was created. See merge commit
`5ce0b38` on `feature/background-processes`.