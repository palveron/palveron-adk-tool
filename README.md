# palveron-adk-tool

**AI Governance for Flare Agents** — policy enforcement, PII detection, and blockchain attestation for [flare-ai-kit](https://github.com/flare-foundation/flare-ai-kit) agents, exposed as a Google Agent Development Kit (ADK) `FunctionTool`.

[![PyPI](https://img.shields.io/pypi/v/palveron-adk-tool.svg?style=flat-square)](https://pypi.org/project/palveron-adk-tool/)
[![Python](https://img.shields.io/pypi/pyversions/palveron-adk-tool.svg?style=flat-square)](https://pypi.org/project/palveron-adk-tool/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![Flare Compatible](https://img.shields.io/badge/flare--ai--kit-compatible-e62058?style=flat-square)](https://github.com/flare-foundation/flare-ai-kit)

---

## Why Governance for Flare Agents?

flare-ai-kit ships agents inside Intel TDX with remote attestation. That guarantees **code integrity** — the binary that ran is the binary you signed off on. It does *not* constrain **what the agent says or does** inside that trusted boundary. PII in a tool result, a swap above the per-call budget, a social post that crosses the financial-advice line — those are governance concerns. This package lets your agent ask Palveron, on demand, whether a specific piece of content is allowed to go out.

## Installation

```bash
pip install palveron-adk-tool
```

## Quick Start

```python
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
    tools=[governance_tool.as_tool(), ftso_get_price, sparkdex_build_tx],
    instruction=(
        "Before any DeFi action, call palveron_governance(content=...) "
        "and only proceed if decision is 'ALLOW' or 'FLAGGED'."
    ),
)
```

The agent now has a `palveron_governance` tool it can call during reasoning. Every call returns a typed `GovernanceResult` with a decision, a `trace_id`, and an `attestation_status` that flips from `PENDING` to `ANCHORED` once the trace lands on Coston2 / Flare mainnet.

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                  Flare AI Kit Agent (TDX)                      │
│                                                                │
│   ┌──────────────────────────────────────────────────────────┐ │
│   │   Google ADK LlmAgent                                    │ │
│   │                                                          │ │
│   │   tools = [palveron_governance, ftso, sparkdex, ...]     │ │
│   └────────────┬─────────────────────────────────────────────┘ │
│                │                                               │
│                ▼  agent decides when to verify                 │
│   ┌──────────────────────────────────────────────────────────┐ │
│   │   PalveronGovernanceTool  (this package)                 │ │
│   └────────────┬─────────────────────────────────────────────┘ │
└────────────────┼───────────────────────────────────────────────┘
                 │  POST /api/v1/verify
                 ▼
       ┌──────────────────────────┐
       │  Palveron Gateway (NGE)  │  decision + trace_id
       └────────────┬─────────────┘
                    │ 30–60 s batch
                    ▼
       ┌──────────────────────────┐
       │  Palveron Notary on      │
       │  Coston2 / Flare mainnet │
       └──────────────────────────┘
```

## Use Cases

### DeFi (SparkDEX / OpenOcean)
Verify draft swap transactions before signing — budget caps, asset allowlists, PII redaction on user-facing receipts. See [`examples/defi_trading_agent.py`](examples/defi_trading_agent.py) for a three-hop governed swap flow.

### Social (X / Telegram / Farcaster / Slack)
Toxicity, PII, and unlicensed-financial-advice checks before posting. Drafts that hit the disclaimer policy come back as `MODIFY` with a regulator-friendly version; drafts that fail safety come back as `BLOCK` with a `trace_id` for the review queue. See [`examples/social_agent.py`](examples/social_agent.py).

### RAG over Flare Developer Hub
Govern *retrieved* documents — a Qdrant index that mixes public docs with internal runbooks needs PII detection on the retrieval result, not on the prompt. Pair `palveron-adk-tool` with `palveron-google-adk`'s `after_tool_callback` for this.

### FDC (Web2Json / EVMTransaction)
Restrict which attestation types and source URLs the agent is allowed to request, and block requests that carry credentials in headers or body before they reach the verifier round.

## Configuration

```python
GovernanceConfig(
    api_key="pv_live_...",                 # required; load from secret manager
    base_url="https://gateway.palveron.com",
    fail_open=True,                        # True → community; False → DORA/healthcare
    timeout_seconds=5.0,
    agent_id="flare-defi-agent-001",
    metadata={"source": "flare-ai-kit", "protocol": "sparkdex"},
)
```

`fail_open` semantics:
- `True` — gateway errors return `ALLOW` with `reason="gateway_error: ..."`, the agent proceeds.
- `False` — gateway errors return `BLOCK`, the agent must not proceed. Use for regulated entities; never trade compliance for uptime.

## GovernanceResult

```python
class GovernanceResult(BaseModel):
    decision: Literal["ALLOW", "BLOCK", "MODIFY", "REQUIRE_APPROVAL", "FLAGGED"]
    trace_id: str
    modified_content: str | None
    reason: str | None
    policy_violations: list[str]
    attestation_status: Literal["PENDING", "ANCHORED", "DISABLED"]

    @property
    def allowed(self) -> bool: ...  # True for ALLOW and FLAGGED
    @property
    def blocked(self) -> bool: ...  # True for BLOCK and REQUIRE_APPROVAL
```

Decision mapping from the gateway:

| Gateway value | Tool decision | Action |
|---------------|---------------|--------|
| `ALLOWED` / `ALLOW` / `PASSED` | `ALLOW` | Proceed |
| `FLAGGED` | `FLAGGED` | Proceed, log |
| `MODIFIED` | `MODIFY` | Use `modified_content` |
| `BLOCKED` | `BLOCK` | Stop |
| `RATE_LIMITED` | `BLOCK` | Stop, backoff |
| `PENDING_APPROVAL` | `REQUIRE_APPROVAL` | Pause, route to review |
| anything else | `BLOCK` | Fail-closed |

## Works with `palveron-google-adk`

`palveron-adk-tool` and [`palveron-google-adk`](https://pypi.org/project/palveron-google-adk/) are complementary:

| | `palveron-google-adk` | `palveron-adk-tool` |
|---|---|---|
| Mode | Automatic (callbacks) | Explicit (agent calls tool) |
| Wire-in | `before_/after_tool_callback`, `before_model_callback` | `tools=[governance_tool.as_tool(), ...]` |
| Trigger | Every model and tool call | Agent decides when |
| Use case | Govern everything by default | High-stakes drafts, A2A, social posting |

A single agent can use both — automatic governance as the floor, explicit governance for moments the model should be aware of (e.g. before producing a user-visible message).

## Compliance

Decisions carry policy IDs that map to the EU AI Act (Art. 14 human oversight, Art. 50 transparency), DORA (Art. 8 ICT risk, Art. 28 third-party risk), GDPR, NIST AI RMF, ISO/IEC 42001, and 7 further frameworks. The full mapping is documented in the [palveron-governance Skill](https://github.com/flare-foundation/flare-ai-skills/tree/main/skills/palveron-governance-skill).

## Requirements

- Python 3.10+
- [`palveron-sdk`](https://pypi.org/project/palveron-sdk/) ≥ 1.1.0
- [`google-adk`](https://pypi.org/project/google-adk/) ≥ 0.1.0
- [`pydantic`](https://pypi.org/project/pydantic/) ≥ 2.0.0

## Links

- [Palveron documentation](https://docs.palveron.com)
- [`palveron-governance` Skill for flare-ai-skills](https://github.com/flare-foundation/flare-ai-skills/tree/main/skills/palveron-governance-skill)
- [Flare AI Kit](https://github.com/flare-foundation/flare-ai-kit)
- [Coston2 explorer](https://coston2.testnet.flarescan.com)
- [Source on GitHub](https://github.com/palveron/palveron-adk-tool)

## License

[MIT](./LICENSE)
