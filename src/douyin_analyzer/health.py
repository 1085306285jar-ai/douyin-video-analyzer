from __future__ import annotations

import importlib.util
import os
import shutil
import time
from pathlib import Path

from .config import APP_VERSION, AppPaths


def _check(name: str, ok: bool, detail: str) -> dict[str, object]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def run_startup_checks(paths: AppPaths) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = [
        _check("app_version", True, APP_VERSION),
    ]

    for module in ("yt_dlp", "faster_whisper", "ctranslate2", "av", "playwright"):
        present = importlib.util.find_spec(module) is not None
        checks.append(_check(f"module:{module}", present, "available" if present else "missing"))

    required_model_files = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")
    missing = [name for name in required_model_files if not (paths.model_root / name).is_file()]
    checks.append(
        _check(
            "offline_model",
            not missing,
            "complete" if not missing else f"missing: {', '.join(missing)}",
        )
    )

    for label, directory in (("output", paths.output_root), ("temp", paths.temp_root)):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / f"health_{os.getpid()}.tmp"
            probe.write_bytes(b"ok")
            probe.unlink(missing_ok=True)
            checks.append(_check(f"writable:{label}", True, str(directory)))
        except OSError as exc:
            checks.append(_check(f"writable:{label}", False, str(exc)))
    return checks


def cleanup_stale_temp(temp_root: Path, *, older_than_hours: int = 24) -> None:
    """Remove only stale job directories created under this app's temp root."""
    if not temp_root.is_dir():
        return
    cutoff = time.time() - older_than_hours * 3600
    for child in temp_root.iterdir():
        if not child.name.startswith("job_"):
            continue
        try:
            if child.stat().st_mtime >= cutoff:
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            elif child.is_file():
                child.unlink(missing_ok=True)
        except OSError:
            continue
