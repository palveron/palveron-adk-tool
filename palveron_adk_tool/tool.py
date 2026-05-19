"""``PalveronGovernanceTool`` — explicit governance as a Google ADK FunctionTool.

Unlike ``palveron-google-adk`` which wires automatic callbacks into every ADK
``LlmAgent``, this package exposes Palveron as a *tool* the agent calls
explicitly. The model decides when to verify — typically before social posts,
before signed-transaction drafts, before agent-to-agent messages, or before
any other high-stakes hop.

Usage::

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
            "and only proceed if decision == 'ALLOW' or 'FLAGGED'."
        ),
    )

The tool calls ``POST /api/v1/verify`` synchronously. Decisions are translated
into a typed :class:`~palveron_adk_tool.models.GovernanceResult`.
"""

from __future__ import annotations

import logging
from typing import Any

from .models import GovernanceConfig, GovernanceResult

logger = logging.getLogger("palveron_adk_tool")

# Mapping from raw gateway decisions to the action-oriented set the tool exposes.
_DECISION_MAP: dict[str, str] = {
    "ALLOW": "ALLOW",
    "ALLOWED": "ALLOW",
    "PASS": "ALLOW",
    "PASSED": "ALLOW",
    "FLAGGED": "FLAGGED",
    "MODIFIED": "MODIFY",
    "MODIFY": "MODIFY",
    "BLOCK": "BLOCK",
    "BLOCKED": "BLOCK",
    "RATE_LIMITED": "BLOCK",
    "PENDING_APPROVAL": "REQUIRE_APPROVAL",
    "REQUIRE_APPROVAL": "REQUIRE_APPROVAL",
}


class PalveronGovernanceTool:
    """Palveron governance exposed as a Google ADK ``FunctionTool``.

    Construction is lazy with respect to ``google-adk``: the dependency is
    imported when :meth:`as_tool` is called (or when the instance is passed
    directly to an ``LlmAgent``), so unit tests can run without ``google-adk``
    installed.

    Args:
        config: :class:`GovernanceConfig` for API key, base URL, fail-open
            policy, timeout, agent identifier, and base metadata.
        client: Optional pre-constructed Palveron client (for testing). Must
            expose ``verify(VerifyRequest) -> VerifyResponse``.
    """

    def __init__(
        self,
        config: GovernanceConfig,
        *,
        client: Any = None,
    ) -> None:
        self._config = config
        self._client = client  # lazy-constructed in _get_client when None
        self._adk_tool: Any = None

    # ── Public API ───────────────────────────────────────────

    @property
    def config(self) -> GovernanceConfig:
        return self._config

    def verify(
        self,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> GovernanceResult:
        """Verify ``content`` against the configured Palveron policy bundle.

        This is the method the ADK runtime invokes when the agent calls
        ``palveron_governance``. It is also safe to call directly from
        application code that does not use ADK.

        Args:
            content: Text to verify (a draft message, transaction summary,
                retrieved document, agent-to-agent payload, ...).
            metadata: Per-call metadata merged on top of the base metadata
                in :class:`GovernanceConfig`.

        Returns:
            :class:`GovernanceResult` with action-oriented ``decision``.
        """
        merged_metadata = {**self._config.metadata, **(metadata or {})}

        try:
            client = self._get_client()
            request = self._build_request(content, merged_metadata)
            response = client.verify(request)
        except Exception as exc:  # noqa: BLE001 — gateway/client surface is broad
            return self._handle_error(exc)

        return self._translate_response(response)

    def as_tool(self, name: str = "palveron_governance") -> Any:
        """Return the ADK ``FunctionTool`` wrapper.

        Imports ``google.adk.tools`` lazily so the package can be imported
        without ``google-adk`` installed.
        """
        if self._adk_tool is not None:
            return self._adk_tool

        try:
            from google.adk.tools import FunctionTool  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "PalveronGovernanceTool.as_tool() requires google-adk: "
                "pip install google-adk"
            ) from exc

        verify = self.verify

        def palveron_governance(content: str) -> dict[str, Any]:
            """Verify content against Palveron AI governance policies.

            Call before posting, signing, or forwarding content that is
            user-visible or has financial/regulatory implications. Inspect
            the returned ``decision`` and only proceed when it is ``ALLOW``
            or ``FLAGGED``; on ``MODIFY`` use ``modified_content`` verbatim;
            on ``BLOCK`` or ``REQUIRE_APPROVAL`` halt and surface ``trace_id``.

            Args:
                content: Text to verify (draft post, transaction summary,
                    retrieved document, A2A payload).

            Returns:
                Dict with keys: ``decision``, ``trace_id``, ``modified_content``,
                ``reason``, ``policy_violations``, ``attestation_status``.
            """
            result = verify(content)
            return result.model_dump()

        palveron_governance.__name__ = name
        self._adk_tool = FunctionTool(func=palveron_governance)
        return self._adk_tool

    # The ADK runtime treats objects with ``func`` and a model dump similarly
    # to ``FunctionTool`` instances; we expose ``__adk_tool__`` so users can
    # pass the ``PalveronGovernanceTool`` instance directly to ``tools=[...]``.
    @property
    def __adk_tool__(self) -> Any:
        return self.as_tool()

    # ── Internals ────────────────────────────────────────────

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from palveron import Palveron  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "PalveronGovernanceTool requires palveron-sdk: "
                "pip install palveron-sdk"
            ) from exc
        self._client = Palveron(
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
        )
        return self._client

    def _build_request(self, content: str, metadata: dict[str, Any]) -> Any:
        try:
            from palveron import VerifyRequest  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "PalveronGovernanceTool requires palveron-sdk: "
                "pip install palveron-sdk"
            ) from exc

        kwargs: dict[str, Any] = {"prompt": content, "metadata": metadata}
        if self._config.agent_id:
            kwargs["agent_external_id"] = self._config.agent_id
        return VerifyRequest(**kwargs)

    def _translate_response(self, response: Any) -> GovernanceResult:
        raw_decision = self._extract_decision(response)
        decision = _DECISION_MAP.get(raw_decision, "BLOCK")
        modified = getattr(response, "output", None) or getattr(response, "modified_content", None)
        if decision != "MODIFY":
            modified = None

        attestation_status = "PENDING"
        attestation = getattr(response, "attestation", None)
        if attestation is not None:
            status = getattr(attestation, "status", None) or (
                attestation.get("status") if isinstance(attestation, dict) else None
            )
            if isinstance(status, str) and status in ("PENDING", "ANCHORED", "DISABLED"):
                attestation_status = status  # type: ignore[assignment]

        return GovernanceResult(
            decision=decision,  # type: ignore[arg-type]
            trace_id=str(getattr(response, "trace_id", "") or ""),
            modified_content=modified,
            reason=getattr(response, "reason", None),
            policy_violations=self._extract_policy_ids(response),
            attestation_status=attestation_status,  # type: ignore[arg-type]
        )

    def _handle_error(self, exc: Exception) -> GovernanceResult:
        if self._config.fail_open:
            logger.warning("Palveron gateway error, fail-open: %s", exc)
            return GovernanceResult(
                decision="ALLOW",
                trace_id="",
                reason=f"gateway_error: {exc}",
            )
        logger.error("Palveron gateway error, fail-closed: %s", exc)
        return GovernanceResult(
            decision="BLOCK",
            trace_id="",
            reason=f"gateway_error: {exc}",
        )

    @staticmethod
    def _extract_decision(response: Any) -> str:
        decision = getattr(response, "decision", None)
        if decision is None:
            return ""
        # palveron-sdk Decision enum has a .value; raw strings pass through.
        value = getattr(decision, "value", decision)
        return str(value).upper()

    @staticmethod
    def _extract_policy_ids(response: Any) -> list[str]:
        findings = (
            getattr(response, "findings", None)
            or getattr(response, "policy_results", None)
            or []
        )
        ids: list[str] = []
        for finding in findings:
            if isinstance(finding, dict):
                fid = finding.get("policy_id") or finding.get("id")
            else:
                fid = getattr(finding, "policy_id", None) or getattr(finding, "id", None)
            if isinstance(fid, str):
                ids.append(fid)
        return ids
