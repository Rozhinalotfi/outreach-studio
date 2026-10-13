"""End-to-end pipeline with a fake model: research, drafts, blind judging, decision, choice, learning."""
import json
import re

from outreach_studio import config, engine, providers, research
from outreach_studio.store import Store


def fake_complete(cfg, agent, system, user, max_tokens=4000, json_mode=True):
    if "research brief" in system:
        return json.dumps({"summary": "Dana leads design.", "hooks": [{"fact": "Gave a talk", "relevance": "process", "source": "your notes"}], "confidence": "low"})
    if system.startswith("You are The"):
        return json.dumps({"subject": f"Hello from {agent.id}", "body": f"Body by {agent.id}", "approach": "x", "hooks": [], "assumptions": []})
    if "expert judge" in system:
        labels = re.findall(r"=== Draft (\w) ===\nSubject: Hello from (\w+)", user)
        quality = {"a": 9, "b": 6, "c": 5}
        scores = {lab: {c: quality[aid] for c in ["purpose", "recipient_fit", "accuracy", "tone", "craft", "overall"]} | {"note": f"Draft {lab} ok"} for lab, aid in labels}
        ranking = [lab for lab, aid in sorted(labels, key=lambda x: -quality[x[1]])]
        return json.dumps({"scores": scores, "ranking": ranking, "preference_dependent": False, "tradeoff": "", "confidence": "clear"})
    raise AssertionError(system[:60])


def setup(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setattr(providers, "complete", fake_complete)
    monkeypatch.setattr(research, "fetch_page", lambda url, limit=8000: {"url": url, "text": "page"})
    return config.save_config({"agents": [{"id": i, "persona": "The " + i.upper(), "provider": "openai", "model": "m"} for i in "abc"]})


def test_full_run_reaches_consensus(monkeypatch):
    cfg = setup(monkeypatch)
    store = Store()
    rid = store.create_run({"recipient": {"name": "Dana", "links": "example.com"}, "purpose": "chat", "status": "queued"})
    run = engine.run_pipeline(cfg, store, rid)
    assert run["status"] == "decided", run.get("error")
    assert run["chosen"] == "a" and run["final"]["subject"] == "Hello from a"
    assert run["brief"]["summary"] == "Dana leads design."
    # notes referring to anonymous labels are rewritten to persona names
    assert "Draft" not in run["judgments"]["b"]["scores"]["a"]["note"]


def test_choice_overriding_panel_is_learned(monkeypatch):
    cfg = setup(monkeypatch)
    store = Store()
    rid = store.create_run({"recipient": {"name": "Dana"}, "purpose": "chat", "status": "queued"})
    engine.run_pipeline(cfg, store, rid)
    run = engine.choose(store, rid, "b")
    assert run["chosen"] == "b" and run["chosenBy"] == "you" and run["versions"]
    learned = store.settings()["learned"]
    assert learned[-1]["chosen"] == "The B" and learned[-1]["overrodePanel"] is True
    assert "Chose The B over The A" in engine.preferences_text(store.settings())


def test_failing_writer_does_not_sink_the_panel(monkeypatch):
    cfg = setup(monkeypatch)

    def flaky(cfg_, agent, system, user, **kw):
        if agent.id == "c" and system.startswith("You are The"):
            raise providers.ProviderError("boom")
        return fake_complete(cfg_, agent, system, user, **kw)
    monkeypatch.setattr(providers, "complete", flaky)
    monkeypatch.setattr(providers.time, "sleep", lambda s: None)
    store = Store()
    rid = store.create_run({"recipient": {"name": "Dana"}, "purpose": "chat", "status": "queued"})
    run = engine.run_pipeline(cfg, store, rid)
    assert run["drafts"]["c"]["status"] == "failed"
    assert run["status"] in ("decided", "needs_choice")
