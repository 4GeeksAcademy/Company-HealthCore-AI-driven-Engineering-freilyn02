"""Make the repository root importable so tests can do `from data.pipelines import rag`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))