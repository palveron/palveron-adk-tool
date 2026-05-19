# Changelog

All notable changes to `palveron-adk-tool` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] — 2026-05-19

### Added
- Initial release of `palveron-adk-tool` — Palveron AI governance exposed as a Google ADK `FunctionTool`.
- `PalveronGovernanceTool` with synchronous `verify(content, metadata=...)` and `as_tool(name=...)` ADK adapter.
- `GovernanceConfig` (api_key, base_url, fail_open, timeout, agent_id, metadata) — frozen Pydantic model.
- `GovernanceResult` with action-oriented decisions (`ALLOW`, `BLOCK`, `MODIFY`, `REQUIRE_APPROVAL`, `FLAGGED`),
  `trace_id`, `modified_content`, `reason`, `policy_violations`, and `attestation_status`
  (`PENDING` / `ANCHORED` / `DISABLED`).
- Decision translation from raw gateway values (`ALLOWED`, `MODIFIED`, `BLOCKED`, `PENDING_APPROVAL`,
  `RATE_LIMITED`) to the action set; unknown values fail-closed to `BLOCK`.
- Fail-open / fail-closed behaviour on gateway errors, configurable per agent.
- Flare-specific example agents:
  - `examples/governed_flare_agent.py` — FTSO price + governance + attestation showcase.
  - `examples/defi_trading_agent.py` — SparkDEX swap drafts with three governance hops
    (pre-quote, pre-trade, post-trade receipt).
  - `examples/social_agent.py` — X / Telegram posting with toxicity, PII, and disclaimer policies.
- Unit tests (`tests/test_tool.py`, `tests/test_models.py`) with a stand-in Palveron client; no HTTP performed.
- PEP 561 `py.typed` marker.
- GitHub Actions workflows: `ci.yml` (Python 3.10–3.13 matrix build + test + import-check)
  and `publish.yml` (trusted-publisher PyPI release on tag).
