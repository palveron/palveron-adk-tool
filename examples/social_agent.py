"""Social Agent — X / Telegram posting with toxicity, PII, and disclaimer governance.

flare-ai-kit's Social Engine connects to X, Telegram, Farcaster, and Slack.
This example wires Palveron governance between *draft* and *post*:

* **Toxicity / harassment** — block before sending; public channels get a
  stricter bar than internal Slack.
* **PII** — block or redact addresses, emails, account numbers.
* **Unlicensed financial advice** — modify drafts to include a regulatory
  disclaimer, or block in jurisdictions where the project is not licensed.

The example is deliberately small: one tool to govern, one tool to post.
The interesting work happens in the policy bundle on the Palveron side, not
in the agent instructions.

Requires::

    pip install palveron-adk-tool palveron-sdk google-adk
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from palveron_adk_tool import GovernanceConfig, PalveronGovernanceTool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("social_agent")


# ── Mock social posting tool ──────────────────────────────────


@dataclass(frozen=True)
class PostReceipt:
    channel: str
    text: str
    external_id: str


def post_to_x(text: str) -> PostReceipt:
    """Post ``text`` to X (Twitter). Replace with the real X client in production."""
    logger.info("Posting to X: %s", text)
    return PostReceipt(channel="x.com", text=text, external_id="1815000000000000000")


def post_to_telegram(text: str, chat_id: str) -> PostReceipt:
    """Post ``text`` to a Telegram channel. Replace with the real client in production."""
    logger.info("Posting to Telegram %s: %s", chat_id, text)
    return PostReceipt(channel=f"telegram:{chat_id}", text=text, external_id="msg_123")


# ── Build the agent ───────────────────────────────────────────


def _build_governance_tool(channel: str) -> PalveronGovernanceTool:
    return PalveronGovernanceTool(
        GovernanceConfig(
            api_key=os.environ.get("PALVERON_API_KEY", "pv_live_REPLACE_ME"),
            agent_id=f"social-agent-{channel}",
            metadata={
                "source": "flare-ai-kit",
                "engine": "social",
                "channel": channel,
            },
            # Social posts on public channels: never fail-open silently.
            # Better to skip the post than to leak something on X.
            fail_open=False,
        )
    )


def build_agent(channel: str = "x.com") -> object:
    from google.adk.agents import LlmAgent  # type: ignore[import-not-found]

    governance_tool = _build_governance_tool(channel)
    post_tool = post_to_x if channel == "x.com" else post_to_telegram

    return LlmAgent(
        name=f"social_agent_{channel.replace('.', '_')}",
        model="gemini-2.0-flash",
        instruction=(
            "You write short Flare ecosystem updates. Workflow:\n"
            "1. Draft the post.\n"
            "2. Call palveron_governance(content=<draft>).\n"
            "3. If decision == 'ALLOW' or 'FLAGGED', post via the channel tool.\n"
            "4. If decision == 'MODIFY', post modified_content verbatim.\n"
            "5. If decision == 'BLOCK' or 'REQUIRE_APPROVAL', do not post; "
            "respond with the trace_id and reason and stop."
        ),
        tools=[governance_tool.as_tool(), post_tool],
    )


# ── Demonstration without ADK runtime ─────────────────────────


def demonstrate_post_flow() -> int:
    governance_tool = _build_governance_tool(channel="x.com")

    draft = (
        "FLR is at $0.0225 right now per FTSO — perfect entry. "
        "Trust me, this is going to 10x by EOY."
    )

    result = governance_tool.verify(draft, metadata={"action": "x_post"})
    logger.info(
        "decision=%s trace=%s policies=%s",
        result.decision,
        result.trace_id,
        result.policy_violations,
    )

    if result.blocked:
        logger.warning(
            "Post blocked: %s (trace %s) — route to human review.",
            result.reason,
            result.trace_id,
        )
        return 0

    text_to_post = (
        result.modified_content if result.decision == "MODIFY" and result.modified_content else draft
    )
    receipt = post_to_x(text_to_post)
    logger.info("Posted: %s -> %s", receipt.channel, receipt.external_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(demonstrate_post_flow())
