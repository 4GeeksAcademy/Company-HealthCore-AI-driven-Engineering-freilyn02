"""Heavy aggregation logic for the incidents summary report.

Kept in its own module (not in main.py or tasks.py) so both the FastAPI
app and the Celery worker can import it without a circular import:
main.py -> tasks.py -> celery_app.py would collide with tasks.py needing
this function if it lived in main.py.
"""
from database import incidents_table


def generate_incident_summary() -> dict:
    """Full table scan + in-memory aggregation across four dimensions.
    This is the operation being moved off the request/response cycle."""
    docs = incidents_table.all()

    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_origin: dict[str, int] = {}
    by_branch: dict[str, int] = {}

    for doc in docs:
        by_status[doc["status"]] = by_status.get(doc["status"], 0) + 1
        by_category[doc["category"]] = by_category.get(doc["category"], 0) + 1
        by_origin[doc["origin"]] = by_origin.get(doc["origin"], 0) + 1
        by_branch[doc["branch"]] = by_branch.get(doc["branch"], 0) + 1

    return {
        "by_status": by_status,
        "by_category": by_category,
        "by_origin": by_origin,
        "by_branch": by_branch,
    }