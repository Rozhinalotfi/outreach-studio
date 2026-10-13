import json
import os
import stat

import pytest

from outreach_studio import config


def test_defaults_have_no_secrets_and_need_keys():
    cfg = config.load_config()
    assert len(cfg.agents) >= 2
    assert cfg.available_agents() == []
    text = json.dumps(cfg.public())
    assert "sk-" not in text
    with pytest.raises(RuntimeError):
        cfg.role("researcher")


def test_env_key_enables_agent(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-value")
    cfg = config.load_config()
    assert [a.id for a in cfg.available_agents()] == ["strategist"]
    assert "test-value" not in json.dumps(cfg.public())


def test_key_store_is_private_and_never_public():
    config.save_key("ANTHROPIC_API_KEY", "secret-123")
    p = config.data_dir() / "keys.json"
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    cfg = config.load_config()
    assert cfg.provider_ready("anthropic")
    assert "secret-123" not in json.dumps(cfg.public())
    config.save_key("ANTHROPIC_API_KEY", None)
    assert not config.load_config().provider_ready("anthropic")


def test_rejects_keys_in_config_and_bad_agents():
    with pytest.raises(ValueError):
        config.save_config({"providers": {"openai": {"type": "openai", "api_key": "sk-nope"}}})
    with pytest.raises(ValueError):
        config.save_config({"agents": [{"id": "a", "provider": "openai", "model": "m"}]})
    with pytest.raises(ValueError):
        config.save_key("bad name", "x")


def test_single_provider_panel(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    cfg = config.save_config({"agents": [
        {"id": "a", "persona": "A", "provider": "openai", "model": "m1"},
        {"id": "b", "persona": "B", "provider": "openai", "model": "m2"}]})
    assert len(cfg.available_agents()) == 2
    assert cfg.second_opinion(cfg.role("analyst")).id == "b"
