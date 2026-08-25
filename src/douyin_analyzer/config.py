from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


APP_NAME = "抖音视频AI解析工具"
APP_SLUG = "DouyinVideoAnalyzer"
APP_VERSION = "1.0.0"
MODEL_FOLDER_NAME = "faster-whisper-base"


def _resource_root() -> Path:
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parents[2]


def _executable_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _can_write(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write_test"
        probe.write_bytes(b"ok")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _fallback_data_root() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / APP_SLUG


@dataclass(slots=True, frozen=True)
class AppPaths:
    resource_root: Path
    executable_root: Path
    data_root: Path
    temp_root: Path
    output_root: Path
    model_root: Path

    @classmethod
    def discover(cls) -> "AppPaths":
        resource_root = _resource_root()
        executable_root = _executable_root()
        preferred_output = executable_root / "output"
        # Persistent browser/session state belongs in the user's app-data area even
        # when the EXE directory is writable. Only user-facing exports stay portable.
        preferred_data_root = _fallback_data_root()
        data_root = (
            preferred_data_root
            if _can_write(preferred_data_root)
            else Path(tempfile.gettempdir()) / APP_SLUG / "data"
        )
        data_root.mkdir(parents=True, exist_ok=True)
        output_root = preferred_output if _can_write(preferred_output) else data_root / "output"
        temp_root = Path(tempfile.gettempdir()) / APP_SLUG
        model_root = resource_root / "model" / MODEL_FOLDER_NAME
        return cls(
            resource_root=resource_root,
            executable_root=executable_root,
            data_root=data_root,
            temp_root=temp_root,
            output_root=output_root,
            model_root=model_root,
        )

    def ensure_runtime_dirs(self) -> None:
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)
