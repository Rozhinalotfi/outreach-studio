import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTREACH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("OUTREACH_CONFIG", raising=False)
    for k in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "GITHUB_TOKEN", "EXA_API_KEY"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)  # keep a developer's real .env out of tests
    yield
