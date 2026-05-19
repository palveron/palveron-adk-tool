"""Unit tests for the public model surface."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from palveron_adk_tool import GovernanceConfig, GovernanceResult


def test_governance_config_defaults() -> None:
    cfg = GovernanceConfig(api_key="pv_test_xyz")
    assert cfg.base_url == "https://gateway.palveron.com"
    assert cfg.fail_open is True
    assert cfg.timeout_seconds == 5.0
    assert cfg.agent_id is None
    assert cfg.metadata == {}


def test_governance_config_is_frozen() -> None:
    cfg = GovernanceConfig(api_key="pv_test_xyz")
    with pytest.raises(ValidationError):
        cfg.api_key = "other"  # type: ignore[misc]


def test_governance_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        GovernanceConfig(api_key="pv_test_xyz", unknown_field=True)  # type: ignore[call-arg]


def test_governance_config_metadata_roundtrip() -> None:
    cfg = GovernanceConfig(
        api_key="pv_test_xyz",
        agent_id="a-1",
        metadata={"source": "flare-ai-kit", "protocol": "sparkdex"},
    )
    assert cfg.agent_id == "a-1"
    assert cfg.metadata["protocol"] == "sparkdex"


def test_result_allow_and_flagged_are_allowed() -> None:
    allow = GovernanceResult(decision="ALLOW", trace_id="tr_1")
    flagged = GovernanceResult(decision="FLAGGED", trace_id="tr_2", reason="advisory")
    assert allow.allowed is True
    assert flagged.allowed is True
    assert allow.blocked is False
    assert flagged.blocked is False


def test_result_block_and_require_approval_are_blocked() -> None:
    block = GovernanceResult(decision="BLOCK", trace_id="tr_3", reason="policy.budget")
    approval = GovernanceResult(decision="REQUIRE_APPROVAL", trace_id="tr_4")
    assert block.blocked is True
    assert approval.blocked is True
    assert block.allowed is False
    assert approval.allowed is False


def test_result_modify_carries_modified_content() -> None:
    result = GovernanceResult(
        decision="MODIFY",
        trace_id="tr_5",
        modified_content="<EMAIL> redacted",
        policy_violations=["pii.email"],
    )
    assert result.allowed is False
    assert result.blocked is False
    assert result.modified_content == "<EMAIL> redacted"
    assert "pii.email" in result.policy_violations


def test_result_attestation_status_default() -> None:
    result = GovernanceResult(decision="ALLOW", trace_id="tr_6")
    assert result.attestation_status == "PENDING"


def test_result_rejects_unknown_decision() -> None:
    with pytest.raises(ValidationError):
        GovernanceResult(decision="MAYBE", trace_id="tr_7")  # type: ignore[arg-type]
