"""Developer profile from public GitHub evidence: an analyst model writes it, a second model audits it."""
from __future__ import annotations

import json
import re

import httpx
from bs4 import BeautifulSoup

from .config import Config, get_secret
from .prompts import ANALYST_SYSTEM, AUDITOR_SYSTEM
from .providers import complete_json
from .store import now_ms

MANIFESTS = {"package.json", "requirements.txt", "pyproject.toml", "Pipfile", "go.mod", "Cargo.toml", "pom.xml",
             "build.gradle", "Gemfile", "composer.json", "Dockerfile"}
CODE_RE = re.compile(r"\.(py|ts|tsx|js|jsx|go|rs|java|kt|rb|php|c|cpp|cs|swift)$")
SKIP_RE = re.compile(r"(migrations?/|alembic/versions|node_modules|dist/|build/|vendor/|\.min\.|\.d\.ts$|components/ui/)")
TEST_RE = re.compile(r"(^|/)(tests?|__tests__|spec)(/|_)|test_.*\.py$|\.test\.[jt]sx?$|\.spec\.[jt]sx?$")


class GitHub:
    def __init__(self, token: str | None = None):
        self.http = httpx.Client(base_url="https://api.github.com", timeout=30, headers={
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "outreach-studio",
            **({"Authorization": f"Bearer {token}"} if token else {})})

    def get(self, path: str, raw: bool = False) -> httpx.Response:
        return self.http.get(path, headers={"Accept": "application/vnd.github.raw"} if raw else None)

    def json(self, path: str):
        r = self.get(path)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            raise RuntimeError("GitHub rate limit reached. Add a GITHUB_TOKEN (no scopes needed for public data) and retry.")
        r.raise_for_status()
        return r.json()


def gather_evidence(login: str, token: str | None = None, max_repos: int = 12, extra_urls: list[str] | None = None) -> dict:
    gh = GitHub(token)
    me = gh.json(f"/users/{login}")
    repos = [r for r in gh.json(f"/users/{login}/repos?per_page=100&type=owner&sort=pushed") if not r.get("fork")]
    pack = {"login": me["login"], "profile": {k: me.get(k) for k in ("name", "bio", "company", "blog", "location", "public_repos", "followers", "created_at")},
            "repos": [], "pages": []}
    for r in repos[:max_repos]:
        full = r["full_name"]
        item = {"name": r["name"], "url": r["html_url"], "description": r.get("description"), "stars": r.get("stargazers_count"),
                "topics": r.get("topics"), "created": (r.get("created_at") or "")[:10], "pushed": (r.get("pushed_at") or "")[:10],
                "sizeKB": r.get("size"), "homepage": r.get("homepage")}
        try:
            item["languages"] = gh.json(f"/repos/{full}/languages")
            c = gh.get(f"/repos/{full}/commits?author={login}&per_page=1")
            m = re.search(r'page=(\d+)>; rel="last"', c.headers.get("Link", ""))
            item["userCommits"] = int(m.group(1)) if m else (len(c.json()) if c.is_success else None)
            tree = gh.json(f"/repos/{full}/git/trees/{r.get('default_branch') or 'main'}?recursive=1").get("tree", [])
            blobs = {t["path"]: t.get("size", 0) for t in tree if t.get("type") == "blob"}
            item["fileCount"] = len(blobs)
            item["files"] = [p for p in blobs if not re.search(r"(node_modules|dist/|\.lock$|package-lock|\.(png|jpe?g|svg|ico|woff2?)$)", p)][:120]
            item["hasTests"] = any(TEST_RE.search(p) for p in blobs)
            item["hasCI"] = any(p.startswith(".github/workflows/") for p in blobs)
            item["manifests"] = {p: gh.get(f"/repos/{full}/contents/{p}", raw=True).text[:2500]
                                 for p in blobs if p.split("/")[-1] in MANIFESTS and p.count("/") <= 2}
            code = sorted((p for p in blobs if CODE_RE.search(p) and not SKIP_RE.search(p) and 400 < blobs[p] < 30000),
                          key=lambda p: -blobs[p])[:4]
            item["sourceSamples"] = {p: gh.get(f"/repos/{full}/contents/{p}", raw=True).text[:3500] for p in code}
            readme = gh.get(f"/repos/{full}/readme", raw=True)
            if readme.is_success:
                item["readme"] = readme.text[:4000]
        except (httpx.HTTPError, ValueError, KeyError) as e:
            item["evidenceError"] = str(e)[:200]
        pack["repos"].append(item)
    for u in [x for x in [me.get("blog"), *(extra_urls or [])] if x]:
        try:
            html = httpx.get(u if u.startswith("http") else "https://" + u, timeout=20, follow_redirects=True).text
            pack["pages"].append({"url": u, "text": re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" "))[:6000]})
        except httpx.HTTPError:
            pass
    return pack


def analyze(cfg: Config, login: str, extra_urls: list[str] | None = None) -> dict:
    pack = gather_evidence(login, get_secret("GITHUB_TOKEN"), extra_urls=extra_urls)
    analyst = cfg.role("analyst")
    auditor = cfg.second_opinion(analyst)
    evidence = "EVIDENCE\n" + json.dumps(pack, ensure_ascii=False)[:120000]
    draft = complete_json(cfg, analyst, ANALYST_SYSTEM, evidence + "\n\nWrite the profile now.", max_tokens=16000)
    audited = complete_json(cfg, auditor, AUDITOR_SYSTEM,
                            evidence + "\n\nPROFILE TO AUDIT\n" + json.dumps(draft, ensure_ascii=False) + "\n\nAudit it now.", max_tokens=16000)
    keys = ("summary", "level", "activity", "skills", "projects", "strengths", "claimable", "avoid", "gaps")
    prof = {k: audited.get(k, draft.get(k)) for k in keys}
    prof.update({"status": "done", "login": pack["login"], "auditNotes": audited.get("auditNotes") or [],
                 "analyst": f"{analyst.provider}/{analyst.model}", "auditor": f"{auditor.provider}/{auditor.model}",
                 "repoCount": len(pack["repos"]), "sources": [r["url"] for r in pack["repos"]] + [p["url"] for p in pack["pages"]],
                 "analyzedAt": now_ms(), "enabled": True})
    return prof


def for_prompt(prof: dict) -> dict | None:
    """The slice of the profile writers and judges see."""
    if not prof or prof.get("status") != "done" or prof.get("enabled") is False:
        return None
    return {"summary": prof.get("summary"), "level": prof.get("level"),
            "skills": [s for s in prof.get("skills") or [] if s.get("level") in ("demonstrated", "working")],
            "projects": (prof.get("projects") or [])[:5], "claimable": prof.get("claimable"), "avoid": prof.get("avoid")}
