from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from adam.api.app import create_app
from adam.core.config import Settings
from adam.evals.suite import ProbeProvider
from adam.operations.service import Operations, OperationsError, Preferences, Schedule
from adam.security.request import AUTHORITY
from auth_client import OwnerClient
from pydantic import ValidationError


@pytest.fixture
def operations(tmp_path):
    clock = [1700000000.0]
    return Operations(tmp_path, lambda: clock[0]), clock


def schedule(clock, **fields):
    return Schedule(
        request_id=uuid4(),
        text="Take a break",
        due_at=datetime.fromtimestamp(clock[0], UTC),
        **fields,
    )


def test_restart_and_atomic_duplicate(operations):
    service, clock = operations
    job = service.create(schedule(clock))
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: service.tick(), range(4)))
    reopened = Operations(service.path.parent.parent, lambda: clock[0])
    assert len(reopened.inbox()) == 1
    assert reopened.status()["jobs"][0]["state"] == "COMPLETED"
    reopened.acknowledge(reopened.inbox()[0]["id"])
    assert not reopened.inbox()
    assert job["id"]


def test_repeat_coalesces_overdue_and_clock_backwards(operations):
    service, clock = operations
    service.create(schedule(clock, every_seconds=60))
    clock[0] += 3600
    service.tick()
    assert len(service.inbox()) == 1
    assert service.status()["jobs"][0]["due"] == clock[0] + 60
    clock[0] -= 200
    service.tick()
    assert len(service.inbox()) == 1


def test_cancel_pending_and_emitted(operations):
    service, clock = operations
    job = service.create(schedule(clock))
    service.tick()
    service.cancel(job["id"])
    assert not service.inbox()
    service.tick()
    assert not service.inbox()


def test_pause_rechecks_before_execution(operations):
    service, clock = operations
    service.create(schedule(clock))
    service.configure(Preferences(enabled=False))
    service.tick()
    assert service.status()["jobs"][0]["state"] == "SCHEDULED"
    service.configure(Preferences())
    service.tick()
    assert len(service.inbox()) == 1


def test_quiet_hours_cross_midnight_no_priority_bypass(operations):
    service, clock = operations
    clock[0] = datetime(2026, 10, 10, 22, tzinfo=UTC).timestamp()
    service.create(schedule(clock, priority="HIGH"))
    service.configure(Preferences(quiet_start=21 * 60, quiet_end=7 * 60, utc_offset_minutes=0))
    service.tick()
    assert not service.inbox()
    clock[0] += 10 * 3600
    assert len(service.inbox()) == 1


def test_invalid_quiet_pair(operations):
    service, _ = operations
    with pytest.raises(OperationsError):
        service.configure(Preferences(quiet_start=2))


def test_active_routing_offline_and_revoked_fallback(operations):
    service, clock = operations
    sid = uuid4()
    service.create(schedule(clock, route="ACTIVE", session_id=sid))
    service.tick()

    def primary(_):
        return "phone"

    assert len(service.inbox(primary=primary)) == 1  # Phone offline.
    service.seen(str(sid), "phone")
    assert not service.inbox(primary=primary)
    mobile = service.inbox("phone", primary)
    assert len(mobile) == 1
    assert "Take a break" not in str(mobile) and str(sid) not in str(mobile)
    assert len(service.inbox(primary=lambda _: "desktop")) == 1  # Revocation/handoff.
    clock[0] += 31
    assert len(service.inbox(primary=primary)) == 1


def test_opt_in_registry_explanation_and_daily_rate_limit(operations):
    service, clock = operations
    service.create(schedule(clock))
    service.tick()
    clock[0] += 86401
    service.tick()
    assert len(service.inbox()) == 1  # Default off.
    service.configure(Preferences(proactive=True, triggers=["unread_reminders"]))
    service.tick()
    service.tick()
    suggestions = [item for item in service.inbox() if item["job"].startswith("trigger:")]
    assert len(suggestions) == 1 and "24 hours" in suggestions[0]["reason"]
    service.configure(Preferences())
    assert len(service.inbox()) == 1


def test_no_unknown_condition_or_tool_execution():
    with pytest.raises(ValidationError):
        Preferences(proactive=True, triggers=["watch_files"])
    with pytest.raises(ValidationError):
        Schedule(request_id=uuid4(), text="test", due_at=datetime.now(UTC), tool="terminal.run")


@pytest.mark.parametrize("text", [" ", "bad\ntext", "password=SecretPassword123!", "x" * 501])
def test_unsafe_text_denied(text):
    with pytest.raises(ValidationError):
        Schedule(request_id=uuid4(), text=text, due_at=datetime.now(UTC))


def test_time_requires_timezone_and_bounded_future(operations):
    service, clock = operations
    with pytest.raises(ValidationError):
        Schedule(request_id=uuid4(), text="test", due_at=datetime(2026, 1, 1))
    value = schedule(clock)
    with pytest.raises(OperationsError):
        service.create(
            value.model_copy(update={"due_at": datetime.fromtimestamp(clock[0] + 315360001, UTC)})
        )


def test_idempotency_and_conflict(operations):
    service, clock = operations
    value = schedule(clock)
    assert service.create(value)["id"] == service.create(value)["id"]
    with pytest.raises(OperationsError):
        service.create(value.model_copy(update={"text": "Different"}))


def test_expired_authority_cannot_create(operations):
    service, clock = operations

    def deny():
        raise OperationsError("AUTH.CHANGED")

    marker = AUTHORITY.set(deny)
    try:
        with pytest.raises(OperationsError):
            service.create(schedule(clock))
    finally:
        AUTHORITY.reset(marker)
    assert not service.status()["jobs"]


def test_owner_api_guest_and_restart(tmp_path):
    settings = Settings(data_dir=tmp_path)
    app = create_app(settings, ProbeProvider())
    with OwnerClient(app, base_url="http://localhost") as client:
        payload = Schedule(
            request_id=uuid4(), text="API reminder", due_at=datetime.now(UTC)
        ).model_dump(mode="json")
        response = client.post("/operations/schedule", json=payload)
        assert response.status_code == 200
        identifier = response.json()["id"]
        app.state.operations.tick()
        assert client.get("/operations/inbox").json()[0]["text"] == "API reminder"
        guest = app.state.auth.issue("guest")
        for method, path in [
            ("GET", "/operations"),
            ("GET", "/operations/inbox"),
            ("POST", "/operations/preferences"),
        ]:
            response = client.request(
                method,
                path,
                headers={"Authorization": "Bearer " + guest},
                json={} if method == "POST" else None,
            )
            assert response.status_code == 403
    with OwnerClient(create_app(settings, ProbeProvider()), base_url="http://localhost") as client:
        assert client.get("/operations").json()["jobs"][0]["id"] == identifier
        assert client.post("/operations/cancel", json={"identifier": identifier}).status_code == 200


def test_damaged_optional_store_preserves_local_core(tmp_path):
    folder = tmp_path / "operations"
    folder.mkdir()
    damaged = folder / "jobs.sqlite3"
    damaged.write_bytes(b"damaged test database")
    app = create_app(Settings(data_dir=tmp_path), ProbeProvider())
    with OwnerClient(app, base_url="http://localhost") as client:
        assert client.get("/operations").status_code == 409
        assert client.get("/identity").status_code == 200
    assert damaged.read_bytes() == b"damaged test database"


def test_replay_after_original_due_time(operations):
    service, clock = operations
    value = schedule(clock)
    job = service.create(value)
    clock[0] += 1000
    assert service.create(value)["id"] == job["id"]


def test_priority_and_full_day_quiet(operations):
    service, clock = operations
    service.create(schedule(clock))
    service.create(schedule(clock, priority="HIGH"))
    service.tick()
    assert service.inbox()[0]["priority"] == "HIGH"
    service.configure(Preferences(quiet_start=0, quiet_end=0))
    assert not service.inbox()


def test_backpressure_preserves_due_job(operations):
    service, clock = operations
    value = schedule(clock)
    service.create(value)
    with service.db() as db:
        db.executemany(
            "INSERT INTO notifications(id,job,occurrence,text,priority,route,created,reason) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [
                (
                    str(i),
                    "fixture",
                    i,
                    "fixture",
                    "NORMAL",
                    "DESKTOP",
                    clock[0],
                    "synthetic capacity fixture",
                )
                for i in range(1000)
            ],
        )
    service.tick()
    assert service.status()["jobs"][0]["state"] == "SCHEDULED"
    service.acknowledge("0")
    service.tick()
    assert service.status()["jobs"][0]["state"] == "COMPLETED"
