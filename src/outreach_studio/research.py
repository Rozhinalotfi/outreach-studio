"""Recipient research: read the provided links, optionally search the web, then have a model write a brief."""
from __future__ import annotations

import json
import re

import httpx
from bs4 import BeautifulSoup

from .config import SEARCH_KEYS, Config, get_secret
from .prompts import RESEARCH_SYSTEM
from .providers import complete_json

UA = {"User-Agent": "Mozilla/5.0 (compatible; OutreachStudio/0.1; +https://github.com)"}


def split_links(links: str) -> list[str]:
    out = []
    for tok in re.split(r"[\s,]+", links or ""):
        tok = tok.strip()
        if not tok:
            continue
        out.append(tok if tok.startswith("http") else "https://" + tok)
    return out


def fetch_page(url: str, limit: int = 8000) -> dict:
    try:
        r = httpx.get(url, headers=UA, timeout=20, follow_redirects=True)
        if r.status_code >= 400:
            return {"url": url, "error": f"HTTP {r.status_code} (the site may block automated reading)"}
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        title = (soup.title.string or "").strip() if soup.title else ""
        text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
        return {"url": url, "title": title, "text": text[:limit]}
    except httpx.HTTPError as e:
        return {"url": url, "error": str(e)[:200]}


def web_search(cfg: Config, query: str, n: int = 6) -> list[dict]:
    """Optional search through Exa, Tavily or Brave; returns [] when not configured."""
    provider = (cfg.search or {}).get("provider", "none")
    key = get_secret(SEARCH_KEYS.get(provider, ""))
    if not key:
        return []
    try:
        if provider == "exa":
            r = httpx.post("https://api.exa.ai/search", headers={"x-api-key": key},
                           json={"query": query, "numResults": n, "contents": {"text": {"maxCharacters": 3000}}}, timeout=40)
            return [{"url": x.get("url"), "title": x.get("title"), "text": x.get("text", "")} for x in r.json().get("results", [])]
        if provider == "tavily":
            r = httpx.post("https://api.tavily.com/search", json={"api_key": key, "query": query, "max_results": n}, timeout=40)
            return [{"url": x.get("url"), "title": x.get("title"), "text": x.get("content", "")} for x in r.json().get("results", [])]
        if provider == "brave":
            r = httpx.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": n},
                          headers={"X-Subscription-Token": key, "Accept": "application/json"}, timeout=40)
            return [{"url": x.get("url"), "title": x.get("title"), "text": x.get("description", "")}
                    for x in (r.json().get("web") or {}).get("results", [])]
    except (httpx.HTTPError, ValueError):
        return []
    return []


def build_brief(cfg: Config, run: dict) -> dict:
    rec = run.get("recipient") or {}
    pages = [fetch_page(u) for u in split_links(rec.get("links", ""))[:8]]
    name = rec.get("name", "")
    if name:
        hint = " ".join(x for x in [name, (rec.get("notes") or "")[:80]] if x)
        pages += web_search(cfg, hint)
        pages += web_search(cfg, f"{name} interview OR talk OR podcast OR blog", n=4)
    material = {
        "recipient": rec,
        "purpose": run.get("purpose"),
        "pages": [p for p in pages if p.get("text") or p.get("error")],
    }
    agent = cfg.role("researcher")
    brief = complete_json(cfg, agent, RESEARCH_SYSTEM, json.dumps(material, ensure_ascii=False)[:90000] + "\n\nWrite the brief now.",
                          max_tokens=6000)
    brief["researcher"] = f"{agent.provider}/{agent.model}"
    brief["pagesRead"] = len([p for p in pages if p.get("text")])
    return brief
