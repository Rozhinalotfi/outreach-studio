"""Minimal clients for the three API families. Any OpenAI-compatible endpoint works
(OpenAI, OpenRouter, Groq, Together, Ollama, LM Studio, vLLM...)."""
from __future__ import annotations

import time

import httpx

from .config import Agent, Config, get_secret
from .jsonutil import parse_json

TIMEOUT = httpx.Timeout(240.0, connect=20.0)


class ProviderError(RuntimeError):
    pass


def complete(cfg: Config, agent: Agent, system: str, user: str, max_tokens: int = 4000, json_mode: bool = True) -> str:
    p = cfg.providers[agent.provider]
    key = get_secret(p.get("api_key_env"))
    kind = p["type"]
    with httpx.Client(timeout=TIMEOUT) as http:
        if kind == "anthropic":
            r = http.post((p.get("base_url") or "https://api.anthropic.com") + "/v1/messages",
                          headers={"x-api-key": key or "", "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json={"model": agent.model, "max_tokens": max_tokens, "system": system,
                                "messages": [{"role": "user", "content": user}]})
            _check(r, agent)
            return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        if kind == "openai":
            body = {"model": agent.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            r = http.post((p.get("base_url") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions", headers=headers, json=body)
            if r.status_code == 400 and json_mode and "response_format" in r.text:
                body.pop("response_format")  # some compatible servers do not support JSON mode
                r = http.post((p.get("base_url") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions", headers=headers, json=body)
            _check(r, agent)
            return r.json()["choices"][0]["message"]["content"] or ""
        if kind == "gemini":
            base = p.get("base_url") or "https://generativelanguage.googleapis.com/v1beta"
            gen = {"maxOutputTokens": max_tokens}
            if json_mode:
                gen["responseMimeType"] = "application/json"
            r = http.post(f"{base}/models/{agent.model}:generateContent", headers={"x-goog-api-key": key or ""},
                          json={"systemInstruction": {"parts": [{"text": system}]},
                                "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": gen})
            _check(r, agent)
            parts = r.json()["candidates"][0]["content"]["parts"]
            return "".join(x.get("text", "") for x in parts if not x.get("thought"))
    raise ProviderError(f"unknown provider type {kind!r}")


def _check(r: httpx.Response, agent: Agent) -> None:
    if r.status_code >= 400:
        detail = r.text[:300].replace("\n", " ")
        raise ProviderError(f"{agent.provider}/{agent.model} returned HTTP {r.status_code}: {detail}")


def complete_json(cfg: Config, agent: Agent, system: str, user: str, max_tokens: int = 4000, attempts: int = 2):
    """Call a model and parse its JSON answer, retrying once on network, HTTP or parse failures."""
    err: Exception | None = None
    for k in range(attempts):
        try:
            return parse_json(complete(cfg, agent, system, user, max_tokens=max_tokens))
        except (ProviderError, httpx.HTTPError, ValueError, KeyError, IndexError) as e:
            err = e
            time.sleep(2 + 3 * k)
    raise ProviderError(str(err))
