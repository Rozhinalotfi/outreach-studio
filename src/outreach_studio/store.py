"""Small JSON-file store. Each run is one file; writes are atomic and serialised per process."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .config import data_dir

_LOCK = threading.RLock()


def now_ms() -> int:
    return int(time.time() * 1000)


def _write(path: Path, obj) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


def _read(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


class Store:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or data_dir())
        (self.root / "runs").mkdir(parents=True, exist_ok=True)

    # runs
    def _run_path(self, run_id: str) -> Path:
        if not run_id.isdigit():
            raise ValueError("invalid run id")
        return self.root / "runs" / f"{run_id}.json"

    def create_run(self, data: dict) -> str:
        with _LOCK:
            run_id = str(now_ms())
            while self._run_path(run_id).exists():
                run_id = str(int(run_id) + 1)
            data = dict(data, id=run_id, createdAt=int(run_id), updatedAt=now_ms())
            _write(self._run_path(run_id), data)
            return run_id

    def get_run(self, run_id: str) -> dict | None:
        return _read(self._run_path(run_id))

    def update_run(self, run_id: str, patch: dict) -> dict:
        """Merge ``patch`` into the run. Keys containing '/' address nested fields; ``None`` deletes."""
        with _LOCK:
            run = self.get_run(run_id)
            if run is None:
                raise KeyError(run_id)
            for key, value in patch.items():
                parts = key.split("/")
                node = run
                for p in parts[:-1]:
                    node = node.setdefault(p, {})
                if value is None:
                    node.pop(parts[-1], None)
                else:
                    node[parts[-1]] = value
            run["updatedAt"] = now_ms()
            _write(self._run_path(run_id), run)
            return run

    def list_runs(self) -> list[dict]:
        out = []
        for p in (self.root / "runs").glob("*.json"):
            r = _read(p)
            if r:
                out.append({k: r.get(k) for k in ("id", "status", "createdAt", "updatedAt", "purpose")}
                           | {"name": (r.get("recipient") or {}).get("name"), "subject": (r.get("final") or {}).get("subject")})
        return sorted(out, key=lambda r: -(r.get("createdAt") or 0))

    def delete_run(self, run_id: str) -> None:
        with _LOCK:
            self._run_path(run_id).unlink(missing_ok=True)

    # settings and developer profile
    def settings(self) -> dict:
        return _read(self.root / "settings.json", {}) or {}

    def update_settings(self, patch: dict) -> dict:
        with _LOCK:
            s = self.settings()
            for k, v in patch.items():
                if v is None:
                    s.pop(k, None)
                else:
                    s[k] = v
            _write(self.root / "settings.json", s)
            return s

    def dev_profile(self) -> dict:
        return _read(self.root / "dev_profile.json", {}) or {}

    def save_dev_profile(self, prof: dict) -> None:
        with _LOCK:
            _write(self.root / "dev_profile.json", prof)
