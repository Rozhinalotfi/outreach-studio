"""The panel: independent drafts, blind cross-judging (no agent scores its own draft), and a decision rule
that only picks automatically when the panel clearly agrees."""
from __future__ import annotations

import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor

from . import github_profile, research
from .config import Agent, Config
from .prompts import JUDGE_SYSTEM, LENGTH_RULES, REVISER_SYSTEM, WRITER_SYSTEM
from .providers import complete_json
from .store import Store, now_ms

CRITERIA = ["purpose", "recipient_fit", "accuracy", "tone", "craft", "overall"]
WORKING = {"queued", "researching", "drafting", "judging"}


# ── context ───────────────────────────────────────────────────────────────────────────────
def preferences_text(settings: dict) -> str:
    out = []
    if settings.get("styleNotes"):
        out.append("Stated preferences: " + settings["styleNotes"])
    learned = sorted(settings.get("learned") or [], key=lambda v: v.get("at", 0))[-8:]
    if learned:
        out.append("Revealed preferences from past choices:")
    for v in learned:
        line = "- Chose {} over {}".format(v.get("chosen", "?"), ", ".join(v.get("over") or []) or "the alternatives")
        if v.get("tradeoff"):
            line += " when the trade-off was: " + v["tradeoff"]
        if v.get("overrodePanel"):
            line += " (overriding the panel's pick)"
        out.append(line)
    return "\n".join(out) or "None recorded yet."


def context_text(run: dict, settings: dict, dev_profile: dict | None) -> str:
    sender = {k: settings.get(k) for k in ("senderName", "senderRole", "senderBackground", "signature") if settings.get(k)}
    if dev_profile:
        sender["technical_profile"] = dev_profile
    rec = run.get("recipient") or {}
    ctx = {
        "sender": sender or "Not provided; keep sender details minimal and do not invent them.",
        "recipient": {k: rec.get(k) for k in ("name", "email", "links", "notes") if rec.get(k)},
        "research_brief": run.get("brief") or {},
        "purpose": run.get("purpose"),
        "desired_outcome": run.get("outcome") or "infer the most natural, low-friction next step",
        "tone": run.get("tone") or settings.get("defaultTone") or "warm and professional",
        "length": run.get("length") or "short",
        "language": run.get("language") or "English",
    }
    return "CONTEXT\n" + json.dumps(ctx, ensure_ascii=False, indent=1) + "\n\nSENDER PREFERENCES\n" + preferences_text(settings)


def _agent_meta(a: Agent) -> dict:
    return {"persona": a.persona, "provider": a.provider, "model": a.model}


# ── stages ────────────────────────────────────────────────────────────────────────────────
def write_draft(cfg: Config, agent: Agent, ctx: str, length: str) -> dict:
    system = WRITER_SYSTEM.format(persona=agent.persona, lens=agent.lens, length=LENGTH_RULES.get(length, LENGTH_RULES["short"]))
    t0 = time.time()
    try:
        d = complete_json(cfg, agent, system, ctx + "\n\nWrite the email now.")
        body = str(d.get("body", "")).strip()
        if not body:
            raise ValueError("empty body")
        return {"status": "done", "subject": str(d.get("subject", "")).strip(), "body": body, "approach": d.get("approach", ""),
                "hooks": d.get("hooks") or [], "assumptions": d.get("assumptions") or [],
                "ms": int((time.time() - t0) * 1000), **_agent_meta(agent)}
    except Exception as e:  # one failed writer must not sink the panel
        return {"status": "failed", "error": str(e)[:300], **_agent_meta(agent)}


def judge_drafts(cfg: Config, judge: Agent, ctx: str, drafts: dict) -> dict:
    ids = list(drafts)
    random.shuffle(ids)  # fresh order per judge to counter position bias
    labels = list("XYZWVUTSRQPONM")[:len(ids)]  # letters unlikely to collide with words in judges' notes
    lab2id = dict(zip(labels, ids, strict=True))
    shown = "\n\n".join(f"=== Draft {lab} ===\nSubject: {drafts[i]['subject']}\n\n{drafts[i]['body']}" for lab, i in lab2id.items())

    def named(s) -> str:
        s = str(s or "")
        for lab, i in lab2id.items():
            s = re.sub(r"\b(?:Draft |draft )?" + lab + r"\b", drafts[i]["persona"], s)
        return s

    try:
        j = complete_json(cfg, judge, JUDGE_SYSTEM, ctx + "\n\nDRAFTS (anonymous)\n" + shown + "\n\nJudge them now.")
        raw_scores = j.get("scores") or {}
        scores = {}
        for lab, i in lab2id.items():
            sc = raw_scores.get(lab) or raw_scores.get("Draft " + lab)
            if not sc:
                raise ValueError("missing score for draft " + lab)
            scores[i] = {c: float(sc.get(c) or 0) for c in CRITERIA} | {"note": named(sc.get("note"))[:400]}
        ranking = [lab2id[lab] for lab in j.get("ranking") or [] if lab in lab2id]
        ranking += [i for i in sorted(ids, key=lambda i: -scores[i]["overall"]) if i not in ranking]
        return {"status": "done", "scores": scores, "ranking": ranking, "preference_dependent": bool(j.get("preference_dependent")),
                "tradeoff": named(j.get("tradeoff"))[:400], "confidence": j.get("confidence", ""), **_agent_meta(judge)}
    except Exception as e:
        return {"status": "failed", "error": str(e)[:300], **_agent_meta(judge)}


def aggregate(drafts: dict, judgments: dict, margin_needed: float = 0.75) -> dict:
    """Peer scores exclude each judge's score of its own draft (judge id == author id).

    Automatic pick only when the leader is ahead by ``margin_needed`` on peer scores, every judge able to vote
    for it ranked it first among the drafts it could rank, and no majority called the choice a matter of taste.
    """
    personas = {d: drafts[d].get("persona", d) for d in drafts}
    J = {k: v for k, v in judgments.items() if v.get("status") == "done"}
    table = {}
    for d in drafts:
        peers = [J[j]["scores"][d]["overall"] for j in J if j != d and d in J[j]["scores"]]
        every = [J[j]["scores"][d]["overall"] for j in J if d in J[j]["scores"]]
        crit = {c: round(sum(J[j]["scores"][d][c] for j in J if j != d and d in J[j]["scores"]) / max(1, len(peers)), 2) for c in CRITERIA}
        table[d] = {"peer": round(sum(peers) / len(peers), 2) if peers else 0.0,
                    "all": round(sum(every) / len(every), 2) if every else 0.0, "n": len(peers), "criteria": crit}
    order = sorted(drafts, key=lambda d: (-table[d]["peer"], -table[d]["all"]))
    win = order[0]
    margin = round(table[win]["peer"] - table[order[1]]["peer"], 2) if len(order) > 1 else 10.0
    picks = {}
    for j, v in J.items():
        options = [d for d in v["ranking"] if d != j and d in drafts]
        if options:
            picks[j] = options[0]
    eligible = [j for j in picks if j != win]
    agree = bool(eligible) and all(picks[j] == win for j in eligible)
    taste_votes = sum(1 for v in J.values() if v.get("preference_dependent"))
    taste = taste_votes * 2 > len(J)
    tradeoffs = [v["tradeoff"] for v in J.values() if v.get("tradeoff") and v.get("preference_dependent")]
    tradeoffs += [v["tradeoff"] for v in J.values() if v.get("tradeoff") and not v.get("preference_dependent")]
    if agree and margin >= margin_needed and not taste:
        mode, contenders = "consensus", [win]
        reason = f"{personas[win]} leads by {margin:.1f} on peer scores and every eligible judge ranked it first."
    else:
        mode = "review"
        contenders = [d for d in order if table[win]["peer"] - table[d]["peer"] < max(margin_needed, 1.0) + 0.01][:3]
        if len(contenders) < 2 and len(order) > 1:
            contenders = order[:2]
        bits = []
        if margin < margin_needed:
            bits.append(f"the top drafts are within {margin:.1f} points")
        if not agree:
            bits.append("the judges' first choices split")
        if taste:
            bits.append("most judges said the choice comes down to your taste")
        reason = ("Your call: " + ", ".join(bits) + ".") if bits else "Your call."
    return {"mode": mode, "winner": win, "order": order, "margin": margin, "contenders": contenders, "picks": picks,
            "agree": agree, "tasteVotes": taste_votes, "table": table, "tradeoff": tradeoffs[0] if tradeoffs else "",
            "reason": reason, "at": now_ms()}


# ── pipeline ──────────────────────────────────────────────────────────────────────────────
def run_pipeline(cfg: Config, store: Store, run_id: str) -> dict:
    """Research → independent drafts → blind cross-judging → decision. Idempotent: finished work is reused."""
    try:
        run = store.get_run(run_id)
        settings = store.settings()
        if not run.get("brief"):
            store.update_run(run_id, {"status": "researching", "error": None})
            run = store.update_run(run_id, {"brief": research.build_brief(cfg, run)})
        agents = cfg.available_agents()
        if len(agents) < 2:
            raise RuntimeError("At least two agents need working API keys. Add keys in Settings.")
        ctx = context_text(run, settings, github_profile.for_prompt(store.dev_profile()))

        drafts = {k: v for k, v in (run.get("drafts") or {}).items() if v.get("status") == "done"}
        todo = [a for a in agents if a.id not in drafts]
        if todo:
            store.update_run(run_id, {"status": "drafting", **{f"drafts/{a.id}": {"status": "writing", **_agent_meta(a)} for a in todo}})

            def one(a):
                d = write_draft(cfg, a, ctx, run.get("length") or "short")
                store.update_run(run_id, {f"drafts/{a.id}": d})
                return a.id, d
            with ThreadPoolExecutor(len(todo)) as ex:
                for aid, d in ex.map(one, todo):
                    if d["status"] == "done":
                        drafts[aid] = d
        if len(drafts) < 2:
            raise RuntimeError("Fewer than two drafts succeeded. Check the API keys and model names in Settings.")

        judgments = {k: v for k, v in (run.get("judgments") or {}).items()
                     if v.get("status") == "done" and set(v.get("scores") or {}) == set(drafts)}
        jtodo = [a for a in agents if a.id not in judgments]
        if jtodo:
            store.update_run(run_id, {"status": "judging", **{f"judgments/{a.id}": {"status": "judging", **_agent_meta(a)} for a in jtodo}})

            def judge(a):
                j = judge_drafts(cfg, a, ctx, drafts)
                store.update_run(run_id, {f"judgments/{a.id}": j})
                return a.id, j
            with ThreadPoolExecutor(len(jtodo)) as ex:
                for jid, j in ex.map(judge, jtodo):
                    if j["status"] == "done":
                        judgments[jid] = j
        if len(judgments) < 2:
            raise RuntimeError("Fewer than two judges succeeded.")

        dec = aggregate(drafts, judgments, cfg.consensus_margin)
        patch = {"decision": dec}
        if dec["mode"] == "consensus":
            w = drafts[dec["winner"]]
            patch |= {"status": "decided", "chosen": dec["winner"], "chosenBy": "panel",
                      "final": {"subject": w["subject"], "body": w["body"], "source": "draft:" + dec["winner"], "version": 1, "at": now_ms()}}
        else:
            patch |= {"status": "needs_choice", "chosen": None, "final": None}
        return store.update_run(run_id, patch)
    except Exception as e:
        return store.update_run(run_id, {"status": "error", "error": str(e)[:400]})


def choose(store: Store, run_id: str, draft_id: str) -> dict:
    """Record the user's pick and learn from it when it settled a split or overrode the panel."""
    run = store.get_run(run_id)
    d = (run.get("drafts") or {}).get(draft_id)
    if not d or d.get("status") != "done":
        raise KeyError(draft_id)
    dec = run.get("decision") or {}
    patch = {"chosen": draft_id, "chosenBy": "you", "status": "chosen",
             "final": {"subject": d["subject"], "body": d["body"], "source": "draft:" + draft_id, "version": 1, "at": now_ms()}}
    if run.get("final"):
        patch[f"versions/{now_ms()}"] = run["final"]
    pool = dec.get("contenders") if dec.get("mode") == "review" else [run.get("chosen") or dec.get("winner")]
    over = [run["drafts"][x]["persona"] for x in pool or [] if x and x != draft_id and x in run["drafts"]]
    if over:
        settings = store.settings()
        learned = (settings.get("learned") or []) + [{
            "at": now_ms(), "run": run_id, "chosen": d["persona"], "over": over, "tradeoff": dec.get("tradeoff", ""),
            "overrodePanel": dec.get("mode") == "consensus" and run.get("chosenBy") != "you",
            "recipient": (run.get("recipient") or {}).get("name", "")}]
        store.update_settings({"learned": learned[-50:]})
    return store.update_run(run_id, patch)


def save_final(store: Store, run_id: str, subject: str, body: str, source: str = "edited", **extra) -> dict:
    run = store.get_run(run_id)
    prev = run.get("final") or {}
    patch = {"final": {"subject": subject, "body": body, "source": source, "version": (prev.get("version") or 1) + 1, "at": now_ms(), **extra}}
    if prev:
        patch[f"versions/{now_ms()}"] = prev
    return store.update_run(run_id, patch)


def revise(cfg: Config, store: Store, run_id: str, instruction: str) -> dict:
    run = store.get_run(run_id)
    cur = run.get("final") or {}
    agent = cfg.role("reviser")
    payload = {"recipient": run.get("recipient"), "purpose": run.get("purpose"), "outcome": run.get("outcome"),
               "brief": run.get("brief"), "sender_style_notes": store.settings().get("styleNotes", ""),
               "sender_technical_profile": github_profile.for_prompt(store.dev_profile()),
               "current": {"subject": cur.get("subject"), "body": cur.get("body")}, "instruction": instruction}
    j = complete_json(cfg, agent, REVISER_SYSTEM, json.dumps(payload, ensure_ascii=False))
    return save_final(store, run_id, j.get("subject") or cur.get("subject", ""), j.get("body") or cur.get("body", ""),
                      source="revision", instruction=instruction, change=j.get("change", ""))
