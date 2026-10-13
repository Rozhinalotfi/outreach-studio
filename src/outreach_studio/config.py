"""Configuration: which models act as writers/judges and where their keys come from.

Secrets are never stored in configuration files. A provider names the environment variable that
holds its key (``api_key_env``); the value is read from the environment, a local ``.env`` file, or
the local key store written by the web UI (``<data dir>/keys.json``, mode 0600).
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROVIDER_TYPES = {"openai", "anthropic", "gemini"}

DEFAULT_CONFIG = {
    "providers": {
        "anthropic": {"type": "anthropic", "api_key_env": "ANTHROPIC_API_KEY"},
        "openai": {"type": "openai", "api_key_env": "OPENAI_API_KEY"},
        "gemini": {"type": "gemini", "api_key_env": "GEMINI_API_KEY"},
        "openrouter": {"type": "openai", "base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"},
        "ollama": {"type": "openai", "base_url": "http://localhost:11434/v1", "api_key_env": None},
    },
    "agents": [
        {"id": "storyteller", "persona": "The Storyteller", "provider": "anthropic", "model": "claude-sonnet-4-5",
         "lens": "Lead with the most genuine connection between the sender and the recipient. Warm and specific, never gushing."},
        {"id": "strategist", "persona": "The Strategist", "provider": "openai", "model": "gpt-5.5",
         "lens": "Lead with the value to the recipient. Crisp and confident, executive brevity; every sentence earns its place."},
        {"id": "analyst", "persona": "The Analyst", "provider": "gemini", "model": "gemini-3.1-pro-preview",
         "lens": "Lead with a sharp, informed observation about the recipient's work and connect it precisely to the ask."},
    ],
    # Which agent performs each single-agent role. Unavailable choices fall back to the first available agent.
    "roles": {"researcher": "storyteller", "analyst": "storyteller", "auditor": "strategist", "reviser": "storyteller"},
    # Optional web search for research: exa | tavily | brave | none
    "search": {"provider": "none"},
    "consensus_margin": 0.75,
}

SEARCH_KEYS = {"exa": "EXA_API_KEY", "tavily": "TAVILY_API_KEY", "brave": "BRAVE_API_KEY"}


def data_dir() -> Path:
    d = Path(os.environ.get("OUTREACH_DATA_DIR", Path.home() / ".outreach-studio")).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except ImportError:  # optional dependency
        pass


def _key_store_path() -> Path:
    return data_dir() / "keys.json"


def stored_keys() -> dict:
    p = _key_store_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_key(name: str, value: str | None) -> None:
    """Store (or with ``None`` remove) a key in the local key store, readable only by the owner."""
    if not name or not name.replace("_", "").isalnum() or not name.isupper():
        raise ValueError("key names must look like OPENAI_API_KEY")
    keys = stored_keys()
    if value:
        keys[name] = value.strip()
    else:
        keys.pop(name, None)
    p = _key_store_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(keys))
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    tmp.replace(p)


def get_secret(name: str | None) -> str | None:
    if not name:
        return None
    _load_dotenv()
    return os.environ.get(name) or stored_keys().get(name)


@dataclass
class Agent:
    id: str
    persona: str
    provider: str
    model: str
    lens: str = ""


@dataclass
class Config:
    providers: dict
    agents: list[Agent]
    roles: dict = field(default_factory=dict)
    search: dict = field(default_factory=dict)
    consensus_margin: float = 0.75

    def provider_ready(self, name: str) -> bool:
        p = self.providers.get(name)
        if not p:
            return False
        return p.get("api_key_env") is None or bool(get_secret(p.get("api_key_env")))

    def available_agents(self) -> list[Agent]:
        return [a for a in self.agents if self.provider_ready(a.provider)]

    def role(self, role: str) -> Agent:
        ready = self.available_agents()
        if not ready:
            raise RuntimeError("No agent has a configured API key. Add a key in Settings or your .env file.")
        wanted = self.roles.get(role)
        return next((a for a in ready if a.id == wanted), ready[0])

    def second_opinion(self, first: Agent) -> Agent:
        """An agent on a different provider (or at least a different agent) to audit ``first``."""
        ready = self.available_agents()
        wanted = self.roles.get("auditor")
        for a in ready:
            if a.id == wanted and a.id != first.id:
                return a
        return next((a for a in ready if a.provider != first.provider),
                    next((a for a in ready if a.id != first.id), first))

    def public(self) -> dict:
        """Configuration safe to send to the browser: no secret values, only whether keys exist."""
        return {
            "providers": {k: {"type": v.get("type"), "base_url": v.get("base_url"), "api_key_env": v.get("api_key_env"),
                              "ready": self.provider_ready(k)} for k, v in self.providers.items()},
            "agents": [a.__dict__ | {"ready": self.provider_ready(a.provider)} for a in self.agents],
            "roles": self.roles,
            "search": {"provider": self.search.get("provider", "none"),
                       "ready": bool(get_secret(SEARCH_KEYS.get(self.search.get("provider", ""), "")))},
            "github_token": bool(get_secret("GITHUB_TOKEN")),
            "consensus_margin": self.consensus_margin,
        }


def _validate(raw: dict) -> Config:
    providers = raw.get("providers") or {}
    for name, p in providers.items():
        if p.get("type") not in PROVIDER_TYPES:
            raise ValueError(f"provider {name!r}: type must be one of {sorted(PROVIDER_TYPES)}")
        for k in p:
            if k not in {"type", "base_url", "api_key_env"}:
                raise ValueError(f"provider {name!r}: unknown field {k!r} (put keys in the environment, not here)")
    agents = []
    seen = set()
    for a in raw.get("agents") or []:
        agent = Agent(id=str(a["id"]), persona=a.get("persona") or a["id"], provider=a["provider"], model=a["model"], lens=a.get("lens", ""))
        if agent.provider not in providers:
            raise ValueError(f"agent {agent.id!r} uses unknown provider {agent.provider!r}")
        if agent.id in seen:
            raise ValueError(f"duplicate agent id {agent.id!r}")
        seen.add(agent.id)
        agents.append(agent)
    if not 2 <= len(agents) <= 12:
        raise ValueError("configure between two and twelve agents so they can judge each other")
    return Config(providers=providers, agents=agents, roles=raw.get("roles") or {}, search=raw.get("search") or {},
                  consensus_margin=float(raw.get("consensus_margin", 0.75)))


def config_path() -> Path:
    return Path(os.environ.get("OUTREACH_CONFIG", data_dir() / "agents.yaml")).expanduser()


def load_config() -> Config:
    raw = json.loads(json.dumps(DEFAULT_CONFIG))
    p = config_path()
    if p.exists():
        user = yaml.safe_load(p.read_text()) or {}
        for k, v in user.items():
            if k == "providers":
                raw["providers"].update(v or {})
            else:
                raw[k] = v
    return _validate(raw)


def save_config(update: dict) -> Config:
    """Persist agents/roles/search/providers edits made in the UI, validated first."""
    p = config_path()
    current = yaml.safe_load(p.read_text()) if p.exists() else {}
    current = current or {}
    for k in ("agents", "roles", "search", "providers", "consensus_margin"):
        if k in update:
            current[k] = update[k]
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for k, v in current.items():
        if k == "providers":
            merged["providers"].update(v or {})
        else:
            merged[k] = v
    cfg = _validate(merged)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(current, sort_keys=False, allow_unicode=True))
    return cfg
