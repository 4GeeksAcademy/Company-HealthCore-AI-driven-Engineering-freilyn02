"""Make the repository root and the API service importable from the tests.

- repository root -> `from data.pipelines import rag`
- services/api    -> `from routers import knowledge` (the endpoint tests)
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))