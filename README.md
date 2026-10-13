# Outreach Studio

Personal outreach emails written by a panel of AI agents. Give it the person you want to reach (profile links, anything you know about them) and why you are reaching out:

1. **Research.** A researcher agent reads their links (and, optionally, web search results), confirms it has the right person, and writes a sourced brief.
2. **Independent drafts.** Several writers (by default Claude, GPT and Gemini, each with a different approach) draft the email in parallel without seeing each other's work.
3. **Blind cross-judging.** Every agent scores every draft on purpose, recipient fit, accuracy, tone and craft. Labels are anonymised and shuffled per judge, and **no judge's score of its own draft counts**.
4. **Decision.** The panel picks automatically only when the winner leads clearly on peer scores, every eligible judge ranked it first, and most judges did not call it a matter of taste. Otherwise it shows you the strongest options with the trade-off between them and **you choose**. Your choices are remembered and shown to future writers and judges, so the panel learns your taste.
5. **Your technical background, honestly.** Optionally, analyse your GitHub: one model writes a developer profile from your repositories (languages, dependencies, source samples, commit history), and a second model on another provider audits every claim against the evidence. Writers then describe your skills only through that profile, and judges penalise inflated self-description.

Nothing is ever sent for you. You edit, revise ("shorter", "mention Sam"), then open the email in Gmail or your mail app.

## Quick start

```bash
git clone https://github.com/Rozhinalotfi/outreach-studio && cd outreach-studio
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env        # add at least two providers' keys, or add them later in the app
outreach-studio serve       # http://127.0.0.1:8765
```

Or from the terminal:

```bash
outreach-studio check                                  # which agents have working keys
outreach-studio github your-github-login               # build your developer profile
outreach-studio draft --name "Dana Whitfield" \
  --links "https://example.com/dana" \
  --purpose "Ask for 20 minutes on how she runs design critiques" --tone warm
```

## Bring your own models and keys

There are no built-in credentials. Each provider names the environment variable that holds its key, and keys are read from your environment, a local `.env`, or the app's **Settings → API keys** (stored in `~/.outreach-studio/keys.json`, readable only by you; never sent back to the browser).

| Provider type | Works with |
| --- | --- |
| `anthropic` | Anthropic API |
| `openai` | OpenAI, OpenRouter, Groq, Together, Mistral, Ollama, LM Studio, vLLM: anything OpenAI-compatible |
| `gemini` | Google Gemini API |

Configure the panel in `~/.outreach-studio/agents.yaml` (see [`agents.example.yaml`](agents.example.yaml)) or in Settings. You can run any number of agents (at least two); they can all use one provider with different models if you only have one key. A fully local panel with Ollama works too.

Optional: `GITHUB_TOKEN` (higher rate limits for the profile analysis; public data needs no scopes) and one search API (`EXA_API_KEY`, `TAVILY_API_KEY` or `BRAVE_API_KEY`) to let the researcher find talks, posts and interviews beyond the links you paste.

## How the decision works

For each draft, the **peer score** is the mean of `overall` scores from every judge except its author. The panel decides on its own only when all three hold:

- the leader's peer score is ahead of the runner-up by at least `consensus_margin` (default 0.75 on a 10-point scale);
- every judge allowed to vote for the leader ranked it first among the drafts it could rank;
- fewer than half of the judges flagged the choice as `preference_dependent` (both strong, mainly a matter of taste).

Otherwise you get the contenders side by side with the judges' trade-off, and your pick is learned. See [`engine.py`](src/outreach_studio/engine.py).

## Privacy and safety

- Runs, settings and your profile are JSON files in `~/.outreach-studio/` (change with `OUTREACH_DATA_DIR`).
- Recipient data goes only to the model providers you configure, plus the optional search API.
- The web server binds to `127.0.0.1` and has no login. Do not expose it publicly without your own authentication.
- LinkedIn and some other sites block automated reading; paste the relevant text into "Anything else you know".
- Models can be wrong. Each draft lists assumptions to verify, and judges penalise unsupported claims, but read before you send.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

Layout: `config.py` (panel and keys), `providers.py` (API clients), `research.py`, `github_profile.py`, `engine.py` (drafting, judging, decision), `server.py` (FastAPI), `web/` (no-build front end), `cli.py`.

## License

MIT
