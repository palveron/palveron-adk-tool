"""Unit tests for ``PalveronGovernanceTool``.

The Palveron gateway is mocked via a stand-in client object; the tests focus
on decision translation, fail-open vs fail-closed, metadata merging, and
attestation status extraction. No HTTP is performed.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any

import pytest

from palveron_adk_tool import GovernanceConfig, PalveronGovernanceTool

# ── A minimal in-memory stand-in for the palveron-sdk surface ────────────


@dataclass
class _StubAttestation:
    status: str = "PENDING"


@dataclass
class _StubDecision:
    value: str


@dataclass
class _StubFinding:
    policy_id: str


@dataclass
class _StubResponse:
    decision: _StubDecision
    trace_id: str = "tr_stub"
    output: str | None = None
    reason: str | None = None
    findings: list[_StubFinding] = field(default_factory=list)
    attestation: _StubAttestation | None = None


@dataclass
class _StubVerifyRequest:
    prompt: str
    metadata: dict[str, Any]
    agent_external_id: str | None = None


class _StubClient:
    def __init__(self, response: _StubResponse | Exception):
        self._response = response
        self.last_request: _StubVerifyRequest | None = None

    def verify(self, request: _StubVerifyRequest) -> _StubResponse:
        self.last_request = request
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


@pytest.fixture(autouse=True)
def _install_fake_palveron(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a fake ``palveron`` module so ``_build_request`` can import it."""
    fake = types.ModuleType("palveron")
    fake.VerifyRequest = _StubVerifyRequest  # type: ignore[attr-defined]
    fake.Palveron = lambda **_: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "palveron", fake)


# ── Tests ─────────────────────────────────────────────────────────────


def _config(**overrides: Any) -> GovernanceConfig:
    base: dict[str, Any] = {
        "api_key": "pv_live_xyz",
        "agent_id": "a-1",
        "metadata": {"source": "flare-ai-kit", "protocol": "sparkdex"},
    }
    base.update(overrides)
    return GovernanceConfig(**base)


def test_decision_allow_passes_through() -> None:
    client = _StubClient(_StubResponse(decision=_StubDecision("ALLOWED")))
    tool = PalveronGovernanceTool(_config(), client=client)
    result = tool.verify("hello world")
    assert result.decision == "ALLOW"
    assert result.allowed is True


def test_decision_flagged_is_allowed_but_logged() -> None:
    client = _StubClient(
        _StubResponse(decision=_StubDecision("FLAGGED"), reason="advisory.tone")
    )
    tool = PalveronGovernanceTool(_config(), client=client)
    result = tool.verify("draft tweet")
    assert result.decision == "FLAGGED"
    assert result.allowed is True


def test_decision_blocked_is_blocked() -> None:
    client = _StubClient(
        _StubResponse(
            decision=_StubDecision("BLOCKED"),
            reason="policy.budget",
            findings=[_StubFinding("policy.budget.swap_notional")],
        )
    )
    tool = PalveronGovernanceTool(_config(), client=client)
    result = tool.verify("Swap 1M FLR -> USDC")
    assert result.decision == "BLOCK"
    assert result.blocked is True
    assert "policy.budget.swap_notional" in result.policy_violations


def test_decision_rate_limited_maps_to_block() -> None:
    client = _StubClient(_StubResponse(decision=_StubDecision("RATE_LIMITED")))
    tool = PalveronGovernanceTool(_config(), client=client)
    assert tool.verify("anything").decision == "BLOCK"


def test_decision_pending_approval_maps_to_require_approval() -> None:
    client = _StubClient(_StubResponse(decision=_StubDecision("PENDING_APPROVAL")))
    tool = PalveronGovernanceTool(_config(), client=client)
    result = tool.verify("high-stakes draft")
    assert result.decision == "REQUIRE_APPROVAL"
    assert result.blocked is True


def test_decision_modified_carries_modified_content() -> None:
    client = _StubClient(
        _StubResponse(
            decision=_StubDecision("MODIFIED"),
            output="my email is <EMAIL>",
            findings=[_StubFinding("pii.email")],
        )
    )
    tool = PalveronGovernanceTool(_config(), client=client)
    result = tool.verify("my email is alice@example.com")
    assert result.decision == "MODIFY"
    assert result.modified_content == "my email is <EMAIL>"


def test_modified_content_cleared_when_not_modify() -> None:
    client = _StubClient(_StubResponse(decision=_StubDecision("ALLOWED"), output="ignored"))
    tool = PalveronGovernanceTool(_config(), client=client)
    result = tool.verify("hello")
    assert result.modified_content is None


def test_unknown_decision_fails_closed() -> None:
    client = _StubClient(_StubResponse(decision=_StubDecision("WHATEVER")))
    tool = PalveronGovernanceTool(_config(), client=client)
    result = tool.verify("hello")
    assert result.decision == "BLOCK"


def test_fail_open_returns_allow_on_gateway_error() -> None:
    client = _StubClient(RuntimeError("connection refused"))
    tool = PalveronGovernanceTool(_config(fail_open=True), client=client)
    result = tool.verify("hello")
    assert result.decision == "ALLOW"
    assert result.reason and "gateway_error" in result.reason


def test_fail_closed_returns_block_on_gateway_error() -> None:
    client = _StubClient(RuntimeError("connection refused"))
    tool = PalveronGovernanceTool(_config(fail_open=False), client=client)
    result = tool.verify("hello")
    assert result.decision == "BLOCK"
    assert result.reason and "gateway_error" in result.reason


def test_metadata_is_merged_per_call() -> None:
    client = _StubClient(_StubResponse(decision=_StubDecision("ALLOWED")))
    tool = PalveronGovernanceTool(_config(), client=client)
    tool.verify("hello", metadata={"hop": "pre_quote"})
    assert client.last_request is not None
    assert client.last_request.metadata["source"] == "flare-ai-kit"
    assert client.last_request.metadata["protocol"] == "sparkdex"
    assert client.last_request.metadata["hop"] == "pre_quote"


def test_agent_id_is_forwarded() -> None:
    client = _StubClient(_StubResponse(decision=_StubDecision("ALLOWED")))
    tool = PalveronGovernanceTool(_config(agent_id="agent-007"), client=client)
    tool.verify("hello")
    assert client.last_request is not None
    assert client.last_request.agent_external_id == "agent-007"


def test_attestation_status_extracted() -> None:
    client = _StubClient(
        _StubResponse(
            decision=_StubDecision("ALLOWED"),
            attestation=_StubAttestation(status="ANCHORED"),
        )
    )
    tool = PalveronGovernanceTool(_config(), client=client)
    result = tool.verify("hello")
    assert result.attestation_status == "ANCHORED"


def test_attestation_status_from_dict() -> None:
    response = _StubResponse(decision=_StubDecision("ALLOWED"))
    response.attestation = {"status": "DISABLED"}  # type: ignore[assignment]
    client = _StubClient(response)
    tool = PalveronGovernanceTool(_config(), client=client)
    result = tool.verify("hello")
    assert result.attestation_status == "DISABLED"


def test_dict_findings_supported() -> None:
    response = _StubResponse(decision=_StubDecision("BLOCKED"))
    response.findings = [{"policy_id": "pii.iban"}, {"id": "budget.daily"}]  # type: ignore[list-item]
    client = _StubClient(response)
    tool = PalveronGovernanceTool(_config(), client=client)
    result = tool.verify("hello")
    assert "pii.iban" in result.policy_violations
    assert "budget.daily" in result.policy_violations
