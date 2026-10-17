"""Make the repository root and the API service importable from the tests.

- repository root -> `from data.pipelines import rag`
- services/api    -> `from routers import knowledge` (the endpoint tests)

Also provides the `env` fixture used by the RFP Part 3 tests (approval flow).
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))


@pytest.fixture
def env(tmp_path):
    """Isolated store + checkpointer files per test.

    Returns (store, build, tmp_path). `build()` creates a NEW ApprovalWorkflow on the
    same files, which simulates a process restart.
    """
    # Imported lazily so the other test modules do not depend on langgraph.
    from data.pipelines.rfp_produce import (
        ApprovalWorkflow,
        SqliteTicketStore,
        get_checkpointer,
    )
    from data.pipelines.rfp_produce.fixtures import make_revision_hook

    store = SqliteTicketStore(tmp_path / "tickets.sqlite")
    ckpt_path = tmp_path / "ckpt.sqlite"

    def build(hook="clean", max_revisions=3):
        checkpointer = get_checkpointer(ckpt_path)
        revision_hook = make_revision_hook(store) if hook == "clean" else hook
        return ApprovalWorkflow(
            store,
            checkpointer,
            revision_hook=revision_hook,
            max_revisions=max_revisions,
            output_dir=tmp_path / "final",
        )

    return store, build, tmp_path
