from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from huggingface_hub import snapshot_download


REPO_ID = "Systran/faster-whisper-base"
REVISION = "ebe41f7"
REQUIRED_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "model" / "faster-whisper-base",
    )
    args = parser.parse_args()
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=True)

    snapshot_download(
        repo_id=REPO_ID,
        revision=REVISION,
        local_dir=str(destination),
        allow_patterns=["model.bin", "config.json", "tokenizer.json", "vocabulary.txt", "README.md"],
    )
    missing = [name for name in REQUIRED_FILES if not (destination / name).is_file()]
    if missing:
        raise SystemExit(f"Model download incomplete; missing: {', '.join(missing)}")
    shutil.rmtree(destination / ".cache", ignore_errors=True)
    print(f"Offline model ready: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
