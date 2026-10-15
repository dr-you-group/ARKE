import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="session")
def data_dir() -> Path:
    """Folder with the experiment data (Playbook CSV and saved results); regression tests need it."""
    value = os.environ.get("ARKE_DATA_DIR")
    if not value:
        pytest.skip("set ARKE_DATA_DIR to run regression tests against the published results")  # ty: ignore[too-many-positional-arguments]
    return Path(value)
