from __future__ import annotations

import os
import re
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from .domain import CancelToken, ProgressEvent, Transcript, TranscriptSegment
from .exceptions import (
    CancelledError,
    DependencyMissingError,
    ModelMissingError,
    NoSpeechError,
)


ProgressCallback = Callable[[ProgressEvent], None]


class LocalWhisperTranscriber:
    def __init__(self, model_path: Path, *, compute_type: str = "int8") -> None:
        self.model_path = Path(model_path)
        self.compute_type = compute_type
        self._model: Any | None = None
        self._model_lock = Lock()

    def load_model(self, callback: ProgressCallback | None = None) -> None:
        if self._model is not None:
            return
        with self._model_lock:
            if self._model is not None:
                return
            self._validate_model()
            self._emit(callback, "model", "正在加载本地语音模型（首次使用会稍慢）……")
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise DependencyMissingError("本地转写组件缺失，请重新下载完整版本。") from exc

            cpu_threads = max(1, min(8, os.cpu_count() or 4))
            try:
                self._model = WhisperModel(
                    str(self.model_path),
                    device="cpu",
                    compute_type=self.compute_type,
                    cpu_threads=cpu_threads,
                    num_workers=1,
                )
            except Exception as exc:
                raise ModelMissingError("本地语音模型无法加载，请重新下载完整版本。") from exc
            self._emit(callback, "model", "本地语音模型加载完成。", 1.0)

    def transcribe(
        self,
        media_path: Path,
        *,
        callback: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
        item_id: str = "",
    ) -> Transcript:
        self._check_cancel(cancel_token)
        self.load_model(callback)
        self._check_cancel(cancel_token)
        assert self._model is not None

        self._emit(callback, "transcribe", "正在本地识别口播内容……", 0.0, item_id)
        try:
            segments_generator, info = self._model.transcribe(
                str(media_path),
                language="zh",
                task="transcribe",
                beam_size=5,
                best_of=5,
                temperature=0.0,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False,
                no_speech_threshold=0.62,
                log_prob_threshold=-1.0,
                compression_ratio_threshold=2.4,
                initial_prompt="以下是普通话短视频口播，请使用简体中文和自然标点准确转写。",
            )

            duration = float(getattr(info, "duration", 0.0) or 0.0)
            segments: list[TranscriptSegment] = []
            for segment in segments_generator:
                self._check_cancel(cancel_token)
                text = str(getattr(segment, "text", "")).strip()
                if text:
                    segment_item = TranscriptSegment(
                        start=float(getattr(segment, "start", 0.0) or 0.0),
                        end=float(getattr(segment, "end", 0.0) or 0.0),
                        text=text,
                    )
                    segments.append(segment_item)
                    fraction = min(1.0, segment_item.end / duration) if duration else None
                    self._emit(
                        callback,
                        "transcribe",
                        "正在本地识别口播内容……",
                        fraction,
                        item_id,
                    )
        except CancelledError:
            raise
        except Exception as exc:
            raise NoSpeechError("音频解码或语音识别失败，未获得有效口播。") from exc

        text = self._join_segments(segments)
        if len(re.sub(r"\W", "", text, flags=re.UNICODE)) < 5:
            raise NoSpeechError()
        self._emit(callback, "transcribe", "口播转写完成。", 1.0, item_id)
        return Transcript(
            text=text,
            segments=segments,
            language=str(getattr(info, "language", "zh") or "zh"),
            language_probability=float(
                getattr(info, "language_probability", 0.0) or 0.0
            ),
            audio_duration=duration,
        )

    def _validate_model(self) -> None:
        required = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")
        if not self.model_path.is_dir():
            raise ModelMissingError()
        missing = [name for name in required if not (self.model_path / name).is_file()]
        if missing:
            raise ModelMissingError("本地语音模型文件不完整，请重新下载完整版本。")

    @staticmethod
    def _join_segments(segments: list[TranscriptSegment]) -> str:
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
        text = re.sub(r"(?<=[，。！？；：])\s+(?=[\u4e00-\u9fff])", "", text)
        text = re.sub(r"\s+([，。！？；：,.!?;:])", r"\1", text)
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()

    @staticmethod
    def _check_cancel(cancel_token: CancelToken | None) -> None:
        if cancel_token and cancel_token.cancelled:
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
