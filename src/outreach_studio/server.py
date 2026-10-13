"""Local web app. Binds to 127.0.0.1 by default: there is no login, so do not expose it publicly."""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config as config_mod
from . import engine, github_profile
from .store import Store, now_ms

WEB = Path(__file__).parent / "web"
app = FastAPI(title="Outreach Studio")
store = Store()
_busy: set[str] = set()
_busy_lock = threading.Lock()


def _background(key: str, fn, *args) -> bool:
    with _busy_lock:
        if key in _busy:
            return False
        _busy.add(key)

    def run():
        try:
            fn(*args)
        finally:
            with _busy_lock:
                _busy.discard(key)
    threading.Thread(target=run, daemon=True).start()
    return True


class NewRun(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = ""
    links: str = ""
    notes: str = Field("", max_length=30000)
    purpose: str = Field(min_length=1, max_length=5000)
    outcome: str = ""
    tone: str = "warm"
    length: str = "short"
    language: str = "English"


class Final(BaseModel):
    subject: str
    body: str


class Text(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class Key(BaseModel):
    name: str
    value: str | None = None


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/api/config")
def get_config():
    return config_mod.load_config().public()


@app.put("/api/config")
def put_config(update: dict):
    try:
        return config_mod.save_config(update).public()
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/keys")
def put_key(k: Key):
    try:
        config_mod.save_key(k.name, k.value)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return config_mod.load_config().public()  # never echoes key values


@app.get("/api/settings")
def get_settings():
    return store.settings()


@app.patch("/api/settings")
def patch_settings(patch: dict):
    allowed = {"senderName", "senderRole", "senderBackground", "signature", "styleNotes", "defaultTone", "githubLogin", "learned"}
    return store.update_settings({k: v for k, v in patch.items() if k in allowed})


@app.get("/api/profile")
def get_profile():
    return store.dev_profile()


@app.patch("/api/profile")
def patch_profile(patch: dict):
    prof = store.dev_profile()
    if "enabled" in patch:
        prof["enabled"] = bool(patch["enabled"])
        store.save_dev_profile(prof)
    return prof


@app.post("/api/profile/analyze")
def analyze_profile(login: Text):
    cfg = config_mod.load_config()
    store.update_settings({"githubLogin": login.text.strip()})
    prev = store.dev_profile()

    def work():
        store.save_dev_profile(prev | {"status": "analyzing", "startedAt": now_ms(), "error": None})
        try:
            store.save_dev_profile(github_profile.analyze(cfg, login.text.strip()) | {"enabled": prev.get("enabled", True)})
        except Exception as e:
            store.save_dev_profile(prev | {"status": "error", "error": str(e)[:300]})
    if not _background("profile", work):
        raise HTTPException(409, "analysis already running")
    return {"ok": True}


@app.get("/api/runs")
def list_runs():
    return store.list_runs()


@app.post("/api/runs")
def create_run(r: NewRun):
    cfg = config_mod.load_config()
    run_id = store.create_run({
        "recipient": {"name": r.name.strip(), "email": r.email.strip(), "links": r.links.strip(), "notes": r.notes.strip()},
        "purpose": r.purpose.strip(), "outcome": r.outcome.strip(), "tone": r.tone, "length": r.length,
        "language": r.language.strip() or "English", "status": "queued"})
    _background(run_id, engine.run_pipeline, cfg, store, run_id)
    return {"id": run_id}


def _run_or_404(run_id: str) -> dict:
    try:
        run = store.get_run(run_id)
    except ValueError:
        run = None
    if not run:
        raise HTTPException(404, "run not found")
    return run


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = _run_or_404(run_id)
    run["running"] = run_id in _busy
    return run


@app.post("/api/runs/{run_id}/retry")
def retry(run_id: str):
    _run_or_404(run_id)
    store.update_run(run_id, {"status": "queued", "error": None})
    if not _background(run_id, engine.run_pipeline, config_mod.load_config(), store, run_id):
        raise HTTPException(409, "already running")
    return {"ok": True}


@app.post("/api/runs/{run_id}/choose/{draft_id}")
def choose(run_id: str, draft_id: str):
    _run_or_404(run_id)
    try:
        return engine.choose(store, run_id, draft_id)
    except KeyError:
        raise HTTPException(404, "draft not found") from None


@app.put("/api/runs/{run_id}/final")
def put_final(run_id: str, f: Final):
    _run_or_404(run_id)
    return engine.save_final(store, run_id, f.subject, f.body)


@app.post("/api/runs/{run_id}/revise")
def revise(run_id: str, t: Text):
    _run_or_404(run_id)
    try:
        return engine.revise(config_mod.load_config(), store, run_id, t.text)
    except Exception as e:
        raise HTTPException(502, str(e)[:300]) from e


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    _run_or_404(run_id)
    store.delete_run(run_id)
    return {"ok": True}
