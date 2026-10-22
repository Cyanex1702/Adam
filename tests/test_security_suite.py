import asyncio
import base64

import pytest
from adam.core.config import Settings
from adam.core.privacy import contains_secret, protected_suffix_length, register_secret
from adam.evals.security import ATTACKS, evaluate_security, execute_security


def test_zero_tolerance_redteam_suite(tmp_path):
    report = asyncio.run(evaluate_security(Settings(data_dir=tmp_path)))
    assert report.passed and report.critical_failures == 0
    assert len(report.cases) == len(ATTACKS) == 10
    assert all(case.critical for case in report.cases)
    assert not list(tmp_path.iterdir())


def test_critical_failure_cannot_pass_release_gate(tmp_path, monkeypatch):
    import adam.evals.security as security

    async def vulnerable(name, runtime):
        raise AssertionError("synthetic private value must not appear in report")

    monkeypatch.setattr(security, "attack", vulnerable)
    report = asyncio.run(evaluate_security(Settings(data_dir=tmp_path)))
    assert not report.passed and report.critical_failures == 10
    assert all(case.error_code == "SECURITY.GATE_FAILED" for case in report.cases)
    assert "synthetic private" not in report.model_dump_json()


def test_known_secret_encodings_and_split_prefix_are_blocked():
    value = "synthetic-encoding-token-727914"
    register_secret(value)
    encoded = base64.b64encode(value.encode()).decode()
    assert contains_secret(encoded)
    assert contains_secret(
        " ".join(encoded[index : index + 4] for index in range(0, len(encoded), 4))
    )
    assert contains_secret(value.encode().hex())
    assert contains_secret("".join(f"%{byte:02X}" for byte in value.encode()))
    assert protected_suffix_length(encoded[:12]) == 12
    spaced = encoded[:4] + " \n" + encoded[4:12]
    assert protected_suffix_length(spaced) == len(spaced)
    assert not contains_secret("ordinary public text")


def test_unknown_attack_fixture_cannot_execute(tmp_path):
    with pytest.raises(ValueError, match="UNKNOWN_SCENARIO"):
        asyncio.run(execute_security("not_a_fixture", Settings(data_dir=tmp_path)))
