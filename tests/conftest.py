import pytest


@pytest.fixture(autouse=True)
def isolated_compute_admission(monkeypatch):
    """Unit fixtures do not depend on other applications consuming host RAM.

    Hardware probes retain real telemetry; resource tests inject pressure explicitly.
    Live QA and real-model evaluation run outside this fixture.
    """
    monkeypatch.setattr(
        "adam.compute.resources.telemetry",
        lambda *args, **kwargs: {
            "ram_available_bytes": 4 * 1024**3,
            "ram_used_percent": 50,
            "disk_free_bytes": 4 * 1024**3,
            "scope": "synthetic unit-test resource fixture",
        },
    )
