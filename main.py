from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run packaged-app startup checks without opening the GUI.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional JSON path for --self-test results.",
    )
    parser.add_argument(
        "--analyze-text",
        type=Path,
        help="Analyze a UTF-8 transcript locally and print Markdown.",
    )
    parser.add_argument(
        "--ui-smoke",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def _run_self_test(report_path: Path | None) -> int:
    from douyin_analyzer.config import AppPaths
    from douyin_analyzer.health import run_startup_checks

    checks = run_startup_checks(AppPaths.discover())
    payload = {
        "ok": all(item["ok"] for item in checks),
        "checks": checks,
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0 if payload["ok"] else 1


def _analyze_text(path: Path) -> int:
    from douyin_analyzer.analyzer import LocalContentAnalyzer

    text = path.read_text(encoding="utf-8-sig")
    report = LocalContentAnalyzer().analyze(text, title=path.stem)
    print(report.to_markdown())
    return 0


def _run_ui_smoke(report_path: Path | None) -> int:
    payload: dict[str, object]
    root = None
    try:
        import tkinter as tk

        from douyin_analyzer.ui import AnalyzerApp, close_packaged_splash

        root = tk.Tk()
        AnalyzerApp(root)
        close_packaged_splash()
        root.update_idletasks()
        root.update()
        payload = {"ok": True, "detail": "GUI constructed and processed one event loop"}
    except Exception as exc:
        payload = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0 if payload["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.self_test:
        return _run_self_test(args.report)
    if args.analyze_text:
        return _analyze_text(args.analyze_text)
    if args.ui_smoke:
        return _run_ui_smoke(args.report)

    from douyin_analyzer.ui import run_app

    run_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
