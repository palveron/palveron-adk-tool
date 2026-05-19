"""Pydantic models for palveron-adk-tool.

These types are returned to the Google ADK runtime when the agent calls the
``palveron_governance`` tool, and consumed by callers that configure the tool.
They wrap the Palveron ``/api/v1/verify`` decision surface in a stable,
typed shape that is forward-compatible with new decision values from the
gateway.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Decision = Literal["ALLOW", "BLOCK", "MODIFY", "REQUIRE_APPROVAL", "FLAGGED"]
"""Stable subset of Palveron decisions exposed by the tool.

The Palveron gateway returns ``ALLOW``, ``FLAGGED``, ``MODIFIED``, ``BLOCKED``,
``PENDING_APPROVAL``, and ``RATE_LIMITED``. The tool normalises these into a
shorter, action-oriented set the agent can branch on:

* ``ALLOW``            — proceed
* ``FLAGGED``          — proceed, advisory only
* ``MODIFY``           — use ``modified_content`` instead of the original
* ``BLOCK``            — do not proceed (covers gateway ``BLOCKED`` and
                          ``RATE_LIMITED``; ``reason`` carries the detail)
* ``REQUIRE_APPROVAL`` — pause and route to human review
"""

AttestationStatus = Literal["PENDING", "ANCHORED", "DISABLED"]


class GovernanceConfig(BaseModel):
    """Configuration for :class:`PalveronGovernanceTool`.

    The configuration is constructed once per agent and bound to the tool
    instance. Per-call metadata (such as a draft transaction hash) is passed
    through the tool's ``metadata`` argument at call time.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key: str = Field(
        ...,
        description="Palveron API key (pv_live_... or pv_test_...). Load from a secret manager; never hardcode.",
    )
    base_url: str = Field(
        default="https://gateway.palveron.com",
        description="Palveron gateway base URL. Override for on-prem or regional deployments.",
    )
    fail_open: bool = Field(
        default=True,
        description=(
            "When True, gateway errors return ALLOW with reason='gateway_error' so the agent can proceed. "
            "When False, gateway errors return BLOCK and the agent must not proceed. "
            "Community default is True; regulated deployments (DORA, healthcare) should set False."
        ),
    )
    timeout_seconds: float = Field(
        default=5.0,
        gt=0.0,
        description="HTTP timeout for the /api/v1/verify call.",
    )
    agent_id: str | None = Field(
        default=None,
        description="Stable identifier for the agent that scopes traces and per-agent policy bundles.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Base metadata attached to every verify request (merged with per-call metadata). "
            'Recommended keys: {"source": "flare-ai-kit", "engine": "ecosystem", "protocol": "sparkdex"}.'
        ),
    )


class GovernanceResult(BaseModel):
    """Result returned by the ``palveron_governance`` tool to the ADK agent.

    The agent inspects ``decision`` and branches:

    * ``ALLOW`` / ``FLAGGED`` — proceed
    * ``MODIFY``              — use ``modified_content`` in place of the original
    * ``BLOCK``               — do not proceed; ``reason`` explains why
    * ``REQUIRE_APPROVAL``    — pause; route ``trace_id`` to human review queue
    """

    model_config = ConfigDict(extra="forbid")

    decision: Decision = Field(
        ...,
        description="Action-oriented decision: ALLOW, BLOCK, MODIFY, REQUIRE_APPROVAL, or FLAGGED.",
    )
    trace_id: str = Field(
        ...,
        description="Stable trace identifier. Use for audit lookup and human-review routing.",
    )
    modified_content: str | None = Field(
        default=None,
        description="Present when decision == 'MODIFY'. Redacted text to use in place of the original prompt.",
    )
    reason: str | None = Field(
        default=None,
        description="Short human-readable reason. Use for logging only; never feed back into the model as instruction.",
    )
    policy_violations: list[str] = Field(
        default_factory=list,
        description="IDs of the policies that fired (e.g. ['pii.email', 'budget.swap_notional']).",
    )
    attestation_status: AttestationStatus = Field(
        default="PENDING",
        description=(
            "ANCHORED once the trace is on-chain; "
            "PENDING during the 30-60s batching window; "
            "DISABLED if the project opts out."
        ),
    )

    @property
    def allowed(self) -> bool:
        """True when the agent should proceed (covers ALLOW and FLAGGED)."""
        return self.decision in ("ALLOW", "FLAGGED")

    @property
    def blocked(self) -> bool:
        """True when the agent must not proceed."""
        return self.decision in ("BLOCK", "REQUIRE_APPROVAL")
