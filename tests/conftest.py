"""Keep bridge state out of the real temp directory during tests."""

import pytest


@pytest.fixture(autouse=True)
def isolated_bridge_state(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
