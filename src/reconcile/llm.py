"""The LLM seam: the only place a vendor SDK may enter the system.

Everything downstream depends on the `LLMClient` protocol, never on `anthropic`.
The core package has zero runtime dependencies, so `AnthropicClient` imports the
SDK lazily -- `import reconcile.llm` works without the `llm` extra installed.
"""

import json
from typing import Any, Protocol

INGEST_MODEL = "claude-haiku-4-5"
MATCHER_MODEL = "claude-sonnet-5"

MAX_TOKENS = 16000


class LLMError(RuntimeError):
    """The model returned something unusable. Callers fail closed on this."""


class LLMClient(Protocol):
    def structured(self, *, system: str, user: str, schema: dict) -> dict:
        """Return a JSON object conforming to `schema`, or raise `LLMError`."""
        ...


class FakeLLMClient:
    """Deterministic LLMClient for tests and CI: no network, no key, no cost.

    Exercises the harness (parsing, validation, routing, fail-closed paths),
    never model quality -- that is measured by scripts/eval_agents.py.
    """

    def __init__(self, responses: list[Any] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict] = []

    def structured(self, *, system: str, user: str, schema: dict) -> dict:
        self.calls.append({"system": system, "user": user, "schema": schema})
        if not self._responses:
            raise LLMError("FakeLLMClient: no canned response left")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class AnthropicClient:
    """Real adapter over the Anthropic SDK. Requires: pip install -e '.[llm]'."""

    def __init__(self, model: str, *, api_key: str | None = None) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "AnthropicClient needs the optional SDK: pip install -e '.[llm]'"
            ) from exc
        self._client = (
            anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        )
        self._model = model

    def structured(self, *, system: str, user: str, schema: dict) -> dict:
        # Broad on purpose: this call is the one place a vendor exception type
        # could enter the system. Every failure the SDK can raise --
        # connection errors, rate limits, HTTP status errors, whatever comes
        # next -- must become an `LLMError` here, or a caller (and eventually
        # a package consumer) would need `import anthropic` to handle it.
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except Exception as exc:
            raise LLMError(f"{self._model}: request to the API failed: {exc}") from exc
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise LLMError(f"{self._model}: response carried no text block")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"{self._model}: response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise LLMError(f"{self._model}: response JSON was not an object")
        return payload
