"""Command line: `outreach-studio serve`, `outreach-studio draft ...`, `outreach-studio github <login>`."""
from __future__ import annotations

import argparse
import json
import sys

from . import config as config_mod
from . import engine, github_profile
from .store import Store


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="outreach-studio", description="Tailored outreach emails from a panel of AI agents.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the local web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    d = sub.add_parser("draft", help="run the panel from the terminal")
    d.add_argument("--name", required=True)
    d.add_argument("--purpose", required=True)
    d.add_argument("--links", default="", help="newline- or space-separated profile URLs")
    d.add_argument("--notes", default="")
    d.add_argument("--outcome", default="")
    d.add_argument("--tone", default="warm")
    d.add_argument("--length", default="short", choices=["short", "medium", "detailed"])
    g = sub.add_parser("github", help="analyse a GitHub account into your developer profile")
    g.add_argument("login")
    sub.add_parser("check", help="show which agents have working keys")
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn
        if args.host not in ("127.0.0.1", "localhost"):
            print("Warning: the app has no login. Only bind to a public interface behind your own auth.", file=sys.stderr)
        uvicorn.run("outreach_studio.server:app", host=args.host, port=args.port)
        return 0
    cfg = config_mod.load_config()
    store = Store()
    if args.cmd == "check":
        print(json.dumps(cfg.public(), indent=2))
        return 0
    if args.cmd == "github":
        prof = github_profile.analyze(cfg, args.login)
        store.save_dev_profile(prof)
        print(json.dumps({k: prof[k] for k in ("summary", "level", "claimable", "avoid")}, indent=2, ensure_ascii=False))
        return 0
    run_id = store.create_run({"recipient": {"name": args.name, "links": args.links, "notes": args.notes}, "purpose": args.purpose,
                               "outcome": args.outcome, "tone": args.tone, "length": args.length, "status": "queued"})
    run = engine.run_pipeline(cfg, store, run_id)
    if run["status"] == "error":
        print("Error:", run.get("error"), file=sys.stderr)
        return 1
    dec = run["decision"]
    print(dec["reason"], "\n")
    for did in (dec["contenders"] if dec["mode"] == "review" else [dec["winner"]]):
        dr = run["drafts"][did]
        print(f"── {dr['persona']} ({dr['provider']}/{dr['model']}), peer score {dec['table'][did]['peer']:.1f}")
        print("Subject:", dr["subject"], "\n")
        print(dr["body"], "\n")
    if dec["mode"] == "review":
        print(f"Pick one in the web app (outreach-studio serve) or reuse run {run_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
