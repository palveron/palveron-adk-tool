"""Governed Flare Agent — FTSO prices + Palveron governance + Coston2 attestation.

A minimal, copy-and-adapt showcase that demonstrates the explicit-governance
pattern of ``palveron-adk-tool``:

1. The agent runs on Google ADK with Gemini.
2. It can call FTSO to read a block-latency price feed.
3. Before *any* user-facing action, the agent is instructed to call
   ``palveron_governance(content=...)`` and only proceed when the decision is
   ``ALLOW`` (or ``FLAGGED`` — advisory).
4. Every check produces a ``trace_id`` that Palveron batches into a Merkle
   tree and anchors on Coston2 / Flare mainnet within 30–60 seconds.

Run this file as a script to see the governance flow without spinning up a
real Gemini key — the agent harness is constructed in ``build_agent`` and the
governance tool can be exercised directly via ``governance_tool.verify(...)``.

Requires::

    pip install palveron-adk-tool palveron-sdk google-adk
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from palveron_adk_tool import GovernanceConfig, PalveronGovernanceTool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("governed_flare_agent")


# ── Mock FTSO tool ────────────────────────────────────────────
#
# In a real flare-ai-kit deployment, this is replaced by the FTSO adapter that
# resolves ``FtsoV2Interface`` via ``ContractRegistry`` on Coston2 / Flare and
# calls ``getFeedByIdInWei(bytes21 feedId)``. For the showcase we stub the
# return value so the governance flow is observable end-to-end.
#
# FLR/USD feed id (category 0x01, "FLR/USD" right-padded to 21 bytes).
FLR_USD_FEED_ID = "0x01464c522f55534400000000000000000000000000"


@dataclass(frozen=True)
class FtsoQuote:
    feed_id: str
    price_wei: int
    timestamp: int

    @property
    def price_human(self) -> float:
        return self.price_wei / 1e18


def ftso_get_price(feed_id: str = FLR_USD_FEED_ID) -> FtsoQuote:
    """Read the latest block-latency FTSO feed for ``feed_id``.

    Replace with the real FTSO adapter (``ContractRegistry.getFtsoV2()`` →
    ``getFeedByIdInWei``) in production. The skill ``flare-ftso`` documents
    the canonical pattern.
    """
    return FtsoQuote(feed_id=feed_id, price_wei=22_500_000_000_000_000, timestamp=1_715_000_000)


# ── Build the agent ───────────────────────────────────────────


def build_agent() -> object:
    """Construct a Google ADK ``LlmAgent`` with explicit Palveron governance.

    Returns the agent object; not invoked here so the file imports cleanly
    without a real Gemini credential.
    """
    from google.adk.agents import LlmAgent  # type: ignore[import-not-found]

    governance_tool = PalveronGovernanceTool(
        GovernanceConfig(
            api_key=os.environ.get("PALVERON_API_KEY", "pv_live_REPLACE_ME"),
            agent_id="governed-flare-agent-001",
            metadata={
                "source": "flare-ai-kit",
                "engine": "ecosystem",
                "agent_kind": "showcase",
            },
            # Community-default: never block the agent when the gateway is unreachable.
            # Set to False for DORA-regulated deployments.
            fail_open=True,
        )
    )

    return LlmAgent(
        name="governed_flare_agent",
        model="gemini-2.0-flash",
        instruction=(
            "You are a Flare ecosystem assistant. You may quote FLR/USD via "
            "ftso_get_price. Before producing any user-visible message, call "
            "palveron_governance(content=<your draft>) and only emit the draft "
            "when decision is 'ALLOW' or 'FLAGGED'. On 'MODIFY', use "
            "modified_content verbatim. On 'BLOCK' or 'REQUIRE_APPROVAL', "
            "tell the user the request cannot be fulfilled and surface trace_id."
        ),
        tools=[governance_tool.as_tool(), ftso_get_price],
    )


# ── Demonstration without ADK runtime ─────────────────────────


def demonstrate_governance_flow() -> None:
    """Exercise the governance tool directly so the flow is observable.

    Useful in CI and for first-time setup: it does not need a Gemini API key
    or a running ADK runtime, only ``PALVERON_API_KEY`` (or a mock client).
    """
    governance_tool = PalveronGovernanceTool(
        GovernanceConfig(
            api_key=os.environ.get("PALVERON_API_KEY", "pv_live_REPLACE_ME"),
            agent_id="governed-flare-agent-001",
            metadata={"source": "flare-ai-kit", "agent_kind": "showcase"},
        )
    )

    quote = ftso_get_price()
    draft = (
        f"The latest FLR/USD block-latency price is ${quote.price_human:.4f} "
        f"(feed {quote.feed_id}, ts {quote.timestamp})."
    )

    logger.info("Draft message: %s", draft)
    result = governance_tool.verify(draft, metadata={"action": "user_quote_response"})
    logger.info(
        "Governance decision=%s trace_id=%s attestation=%s",
        result.decision,
        result.trace_id,
        result.attestation_status,
    )

    if result.blocked:
        logger.warning("Blocked: %s (trace %s)", result.reason, result.trace_id)
        return
    if result.decision == "MODIFY" and result.modified_content:
        logger.info("Using redacted draft: %s", result.modified_content)
        return
    logger.info("Allowed; emitting draft to user.")


if __name__ == "__main__":
    demonstrate_governance_flow()
