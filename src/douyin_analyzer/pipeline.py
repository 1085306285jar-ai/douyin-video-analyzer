from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable, Protocol

from .analyzer import LocalContentAnalyzer
from .domain import (
    CancelToken,
    JobResult,
    JobStatus,
    LinkType,
    ParsedLink,
    ProgressEvent,
    Transcript,
    VideoItem,
)
from .exceptions import (
    AnalyzerError,
    AuthenticationRequiredError,
    CancelledError,
    ContentUnavailableError,
    NoSpeechError,
    PrivateContentError,
)
from .exporter import ResultExporter
from .links import parse_link


ProgressCallback = Callable[[ProgressEvent], None]


class ExtractorProtocol(Protocol):
    def resolve(
        self,
        parsed: ParsedLink,
        *,
        limit: int | None = None,
        callback: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> list[VideoItem]: ...

    def download(
        self,
        item: VideoItem,
        target_dir: Path,
        *,
        callback: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path: ...


class TranscriberProtocol(Protocol):
    def transcribe(
        self,
        media_path: Path,
        *,
        callback: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
        item_id: str = "",
    ) -> Transcript: ...


class AnalyzerPipeline:
    def __init__(
        self,
        *,
        extractor: ExtractorProtocol,
        transcriber: TranscriberProtocol,
        analyzer: LocalContentAnalyzer,
        exporter: ResultExporter,
        temp_root: Path,
        minimum_duration: float = 10.0,
    ) -> None:
        self.extractor = extractor
        self.transcriber = transcriber
        self.analyzer = analyzer
        self.exporter = exporter
        self.temp_root = temp_root
        self.minimum_duration = minimum_duration

    def run(
        self,
        link_text: str,
        *,
        mode: LinkType = LinkType.AUTO,
        limit: int = 20,
        callback: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> list[JobResult]:
        token = cancel_token or CancelToken()
        parsed = parse_link(link_text, mode)
        self._check_cancel(token)
        try:
            items = self.extractor.resolve(
                parsed,
                limit=limit,
                callback=callback,
                cancel_token=token,
            )
        except Exception:
            self._cleanup_extractor()
            raise

        self.temp_root.mkdir(parents=True, exist_ok=True)
        job_dir = Path(tempfile.mkdtemp(prefix="job_", dir=self.temp_root))
        results: list[JobResult] = []
        try:
            total = len(items)
            for index, item in enumerate(items, 1):
                self._check_cancel(token)
                self._emit(
                    callback,
                    "item",
                    f"[{index}/{total}] 开始处理：{item.title}",
                    (index - 1) / max(total, 1),
                    item.item_id,
                )
                started = time.monotonic()
                if item.duration is not None and item.duration <= self.minimum_duration:
                    result = JobResult(
                        item=item,
                        status=JobStatus.SKIPPED,
                        message=f"视频时长 {item.duration:.1f} 秒，不足 {self.minimum_duration:.0f} 秒，已跳过。",
                        elapsed_seconds=time.monotonic() - started,
                    )
                    results.append(result)
                    self._emit(callback, "skip", result.message, item_id=item.item_id)
                    continue

                item_dir = job_dir / f"item_{index:03d}"
                media_path: Path | None = None
                try:
                    media_path = self.extractor.download(
                        item,
                        item_dir,
                        callback=callback,
                        cancel_token=token,
                    )
                    transcript = self.transcriber.transcribe(
                        media_path,
                        callback=callback,
                        cancel_token=token,
                        item_id=item.item_id,
                    )
                    if (
                        item.duration is None
                        and 0 < transcript.audio_duration <= self.minimum_duration
                    ):
                        result = JobResult(
                            item=item,
                            status=JobStatus.SKIPPED,
                            transcript=transcript,
                            message=(
                                f"实际音轨时长 {transcript.audio_duration:.1f} 秒，"
                                f"不足 {self.minimum_duration:.0f} 秒，已跳过。"
                            ),
                            elapsed_seconds=time.monotonic() - started,
                        )
                        results.append(result)
                        self._emit(callback, "skip", result.message, item_id=item.item_id)
                        continue
                    self._check_cancel(token)
                    self._emit(callback, "analyze", "正在进行本地结构化分析……", item_id=item.item_id)
                    report = self.analyzer.analyze(
                        transcript.text,
                        title=item.title,
                        source_hashtags=item.hashtags,
                    )
                    exports = self.exporter.export(item, transcript, report)
                    result = JobResult(
                        item=item,
                        status=JobStatus.SUCCESS,
                        transcript=transcript,
                        report=report,
                        exports=exports,
                        message="解析完成",
                        elapsed_seconds=time.monotonic() - started,
                    )
                    results.append(result)
                    self._emit(
                        callback,
                        "success",
                        f"解析完成：{item.title}",
                        index / max(total, 1),
                        item.item_id,
                    )
                except CancelledError:
                    raise
                except (AuthenticationRequiredError, PrivateContentError, ContentUnavailableError, NoSpeechError) as exc:
                    result = JobResult(
                        item=item,
                        status=JobStatus.SKIPPED,
                        message=exc.user_message,
                        elapsed_seconds=time.monotonic() - started,
                    )
                    results.append(result)
                    self._emit(callback, "skip", exc.user_message, item_id=item.item_id)
                except AnalyzerError as exc:
                    result = JobResult(
                        item=item,
                        status=JobStatus.FAILED,
                        message=exc.user_message,
                        elapsed_seconds=time.monotonic() - started,
                    )
                    results.append(result)
                    self._emit(callback, "error", exc.user_message, item_id=item.item_id)
                except Exception:
                    result = JobResult(
                        item=item,
                        status=JobStatus.FAILED,
                        message="发生未预期错误，程序已跳过该视频并继续。",
                        elapsed_seconds=time.monotonic() - started,
                    )
                    results.append(result)
                    self._emit(callback, "error", result.message, item_id=item.item_id)
                finally:
                    if media_path and media_path.is_file():
                        try:
                            media_path.unlink()
                        except OSError:
                            pass

            if len(results) > 1:
                try:
                    self.exporter.export_batch_index(results)
                except AnalyzerError as exc:
                    self._emit(callback, "warning", exc.user_message)
            return results
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
            self._cleanup_extractor()

    def _cleanup_extractor(self) -> None:
        cleanup = getattr(self.extractor, "cleanup", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                pass

    @staticmethod
    def _check_cancel(token: CancelToken) -> None:
        if token.cancelled:
            raise CancelledError()

    @staticmethod
    def _emit(
        callback: ProgressCallback | None,
        stage: str,
        message: str,
        fraction: float | None = None,
        item_id: str = "",
    ) -> None:
        if callback:
            callback(
                ProgressEvent(
                    stage=stage,
                    message=message,
                    fraction=fraction,
                    item_id=item_id,
                )
            )
