"""palveron-adk-tool — explicit AI governance for Flare agents.

Companion to ``palveron-google-adk``. Where that package wires Palveron
governance into every Google ADK callback automatically, this package exposes
Palveron as an ADK ``FunctionTool`` the agent calls explicitly — useful for
agents that should govern *on demand* (drafts, social posts, signed
transactions, agent-to-agent payloads).

Quick start::

    import os
    from google.adk.agents import LlmAgent
    from palveron_adk_tool import PalveronGovernanceTool, GovernanceConfig

    governance_tool = PalveronGovernanceTool(GovernanceConfig(
        api_key=os.environ["PALVERON_API_KEY"],
        agent_id="flare-defi-agent-001",
        metadata={"source": "flare-ai-kit", "protocol": "sparkdex"},
    ))

    agent = LlmAgent(
        name="governed_flare_agent",
        model="gemini-2.0-flash",
        tools=[governance_tool, ftso_get_price, sparkdex_build_tx],
        instruction=(
            "Before any DeFi action, call palveron_governance(content=...) "
            "and only proceed if decision is 'ALLOW' or 'FLAGGED'."
        ),
    )

See ``examples/`` for full Flare-specific agents: FTSO-priced DeFi trading on
SparkDEX, social posting governance, and a generic governed-Flare-agent
showcase.
"""

from __future__ import annotations

from .models import (
    AttestationStatus,
    Decision,
    GovernanceConfig,
    GovernanceResult,
)
from .tool import PalveronGovernanceTool

__version__ = "1.1.0"

__all__ = [
    "PalveronGovernanceTool",
    "GovernanceResult",
    "GovernanceConfig",
    "Decision",
    "AttestationStatus",
    "__version__",
]
