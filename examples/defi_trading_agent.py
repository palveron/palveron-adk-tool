"""DeFi Trading Agent — FTSO + SparkDEX with PII and budget governance.

A SparkDEX trading flow with three governance hops:

1. **Pre-quote check** — the user request is verified to make sure it is not
   asking for unlicensed financial advice and does not contain PII.
2. **Pre-trade check** — the draft transaction summary is verified against
   the budget and asset-allowlist policies (e.g. swap notional ≤ $5k per call,
   FLR/USDC/USDT only).
3. **Post-trade redaction** — the user-facing receipt is verified so that
   wallet addresses or memo PII do not leak into the chat history.

The agent never signs on behalf of the user — it produces a draft transaction
the user signs in their own wallet. This is the pattern Flare projects use
with SparkDEX, OpenOcean, and similar non-custodial venues.

Requires::

    pip install palveron-adk-tool palveron-sdk google-adk
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from palveron_adk_tool import GovernanceConfig, GovernanceResult, PalveronGovernanceTool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("defi_trading_agent")


# ── Mock SparkDEX + FTSO tools ────────────────────────────────


@dataclass(frozen=True)
class SwapDraft:
    sell_token: str
    buy_token: str
    sell_amount_usd: float
    expected_slippage_bps: int
    route: str
    user_wallet: str  # only used to build the tx; never goes into the chat


def ftso_quote(pair: str) -> float:
    """Return the FTSO mid price for ``pair`` (e.g. ``"FLR/USD"``).

    Replace with the real FTSO adapter in production.
    """
    return {"FLR/USD": 0.0225, "ETH/USD": 3450.0, "BTC/USD": 69_000.0}.get(pair, 1.0)


def sparkdex_draft_swap(sell_token: str, buy_token: str, sell_amount_usd: float, user_wallet: str) -> SwapDraft:
    """Build a SparkDEX swap draft (not signed)."""
    return SwapDraft(
        sell_token=sell_token,
        buy_token=buy_token,
        sell_amount_usd=sell_amount_usd,
        expected_slippage_bps=18,
        route="SparkDEX V2: FLR → USDC",
        user_wallet=user_wallet,
    )


# ── Governance plumbing ───────────────────────────────────────


def _build_governance_tool() -> PalveronGovernanceTool:
    return PalveronGovernanceTool(
        GovernanceConfig(
            api_key=os.environ.get("PALVERON_API_KEY", "pv_live_REPLACE_ME"),
            agent_id="defi-trading-agent-001",
            metadata={
                "source": "flare-ai-kit",
                "engine": "ecosystem",
                "protocol": "sparkdex",
            },
            # DeFi agents in regulated jurisdictions should fail-closed.
            fail_open=False,
        )
    )


def _govern(tool: PalveronGovernanceTool, content: str, *, hop: str) -> GovernanceResult:
    result = tool.verify(content, metadata={"hop": hop})
    logger.info(
        "[%s] decision=%s trace=%s policies=%s",
        hop,
        result.decision,
        result.trace_id,
        result.policy_violations,
    )
    return result


# ── Build the agent ───────────────────────────────────────────


def build_agent() -> object:
    from google.adk.agents import LlmAgent  # type: ignore[import-not-found]

    governance_tool = _build_governance_tool()

    return LlmAgent(
        name="defi_trading_agent",
        model="gemini-2.0-flash",
        instruction=(
            "You are a non-custodial Flare DeFi assistant. Workflow:\n"
            "1. Call palveron_governance on the user request before quoting.\n"
            "2. Use ftso_quote to get FLR/USD or relevant pair.\n"
            "3. Use sparkdex_draft_swap to construct a draft transaction.\n"
            "4. Call palveron_governance with the draft transaction summary; "
            "if blocked, surface the trace_id and stop.\n"
            "5. Present the user-facing receipt to palveron_governance once "
            "more and use modified_content if PII was redacted."
        ),
        tools=[governance_tool.as_tool(), ftso_quote, sparkdex_draft_swap],
    )


# ── Demonstration without ADK runtime ─────────────────────────


def demonstrate_trade_flow() -> int:
    """Run the three governance hops directly.

    Returns the process exit code: ``0`` on success / governed-block,
    ``2`` on unexpected error.
    """
    governance_tool = _build_governance_tool()

    user_request = "Swap 1000 FLR to USDC on SparkDEX from my wallet 0xC0FFEE...DEAD"

    # Hop 1: pre-quote check on the raw user request.
    pre_quote = _govern(governance_tool, user_request, hop="pre_quote")
    if pre_quote.blocked:
        logger.error("Pre-quote blocked: %s (trace %s)", pre_quote.reason, pre_quote.trace_id)
        return 0

    # Use modified content if the gateway redacted the wallet address.
    cleaned_request = (
        pre_quote.modified_content if pre_quote.decision == "MODIFY" and pre_quote.modified_content else user_request
    )
    logger.info("Working request: %s", cleaned_request)

    flr_usd = ftso_quote("FLR/USD")
    draft = sparkdex_draft_swap(
        sell_token="FLR",
        buy_token="USDC",
        sell_amount_usd=1000 * flr_usd,
        user_wallet="0xC0FFEE0000000000000000000000000000000DEAD",
    )

    # Hop 2: pre-trade check on the draft transaction summary.
    draft_summary = (
        f"Draft swap: {draft.sell_token} -> {draft.buy_token} "
        f"notional ${draft.sell_amount_usd:.2f} via {draft.route} "
        f"(slippage {draft.expected_slippage_bps} bps)"
    )
    pre_trade = _govern(governance_tool, draft_summary, hop="pre_trade")
    if pre_trade.blocked:
        logger.error("Pre-trade blocked: %s (trace %s)", pre_trade.reason, pre_trade.trace_id)
        return 0

    # Hop 3: post-trade receipt redaction.
    receipt = (
        f"Receipt: signed by {draft.user_wallet} — swap {draft.sell_token} -> {draft.buy_token} "
        f"for ${draft.sell_amount_usd:.2f}. Route: {draft.route}."
    )
    post_trade = _govern(governance_tool, receipt, hop="post_trade")
    final_receipt = (
        post_trade.modified_content if post_trade.decision == "MODIFY" and post_trade.modified_content else receipt
    )
    logger.info("User-facing receipt: %s", final_receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(demonstrate_trade_flow())
