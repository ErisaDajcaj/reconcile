import builtins
import json

import pytest

import reconcile.llm as llm_module
from reconcile.llm import AnthropicClient, FakeLLMClient, LLMError


def test_fake_client_returns_canned_response_and_records_the_call():
    client = FakeLLMClient([{"ok": True}])
    out = client.structured(system="s", user="u", schema={"type": "object"})
    assert out == {"ok": True}
    assert client.calls == [{"system": "s", "user": "u", "schema": {"type": "object"}}]


def test_fake_client_raises_when_out_of_responses():
    client = FakeLLMClient([])
    with pytest.raises(LLMError):
        client.structured(system="s", user="u", schema={})


def test_fake_client_can_raise_a_canned_error():
    client = FakeLLMClient([LLMError("boom")])
    with pytest.raises(LLMError, match="boom"):
        client.structured(system="s", user="u", schema={})


def test_importing_the_seam_does_not_import_the_sdk():
    """The core package must install and import with zero runtime dependencies."""
    assert not hasattr(llm_module, "anthropic")


def test_anthropic_client_error_names_the_llm_extra(monkeypatch):
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(ImportError, match=r"\[llm\]"):
        AnthropicClient("claude-sonnet-5")


# -- AnthropicClient.structured, exercised with a stub in place of the SDK client. --
# No `anthropic` import, no network, no key: `_client`/`_model` are set directly
# on an instance built via `object.__new__`, bypassing `__init__`'s lazy import.


class _Block:
    def __init__(self, type_, text=None):
        self.type = type_
        self.text = text


class _Response:
    def __init__(self, content):
        self.content = content


class _StubMessages:
    def __init__(self, *, response=None, error=None):
        self._response = response
        self._error = error

    def create(self, **kwargs):
        if self._error is not None:
            raise self._error
        return self._response


class _StubSDKClient:
    def __init__(self, *, response=None, error=None):
        self.messages = _StubMessages(response=response, error=error)


def _adapter(stub_client, model="test-model") -> AnthropicClient:
    adapter = object.__new__(AnthropicClient)
    adapter._client = stub_client
    adapter._model = model
    return adapter


def test_structured_raises_when_the_response_carries_no_text_block():
    adapter = _adapter(_StubSDKClient(response=_Response([_Block("tool_use")])))
    with pytest.raises(LLMError, match="no text block"):
        adapter.structured(system="s", user="u", schema={})


def test_structured_raises_when_the_response_is_not_valid_json():
    adapter = _adapter(_StubSDKClient(response=_Response([_Block("text", text="not json")])))
    with pytest.raises(LLMError, match="not valid JSON"):
        adapter.structured(system="s", user="u", schema={})


def test_structured_raises_when_the_response_json_is_not_an_object():
    response = _Response([_Block("text", text=json.dumps([1, 2, 3]))])
    adapter = _adapter(_StubSDKClient(response=response))
    with pytest.raises(LLMError, match="not an object"):
        adapter.structured(system="s", user="u", schema={})


def test_structured_wraps_sdk_exceptions_in_llmerror():
    original = RuntimeError("connection reset")
    adapter = _adapter(_StubSDKClient(error=original))
    with pytest.raises(LLMError) as exc_info:
        adapter.structured(system="s", user="u", schema={})
    assert exc_info.value.__cause__ is original


def test_structured_happy_path_returns_the_parsed_dict():
    payload = {"mapping": [], "confidence": 0.9}
    response = _Response([_Block("text", text=json.dumps(payload))])
    adapter = _adapter(_StubSDKClient(response=response))
    assert adapter.structured(system="s", user="u", schema={}) == payload
