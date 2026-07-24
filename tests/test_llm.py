import builtins

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
