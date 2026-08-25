from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from threading import Event
from typing import Any


class LinkType(str, Enum):
    AUTO = "auto"
    SINGLE = "single"
    COLLECTION = "collection"
    AUTHOR = "author"

    @property
    def label(self) -> str:
        return {
            LinkType.AUTO: "自动识别",
            LinkType.SINGLE: "单视频",
            LinkType.COLLECTION: "合集",
            LinkType.AUTHOR: "博主主页",
        }[self]


class JobStatus(str, Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class ParsedLink:
    url: str
    link_type: LinkType


@dataclass(slots=True)
class VideoItem:
    item_id: str
    source_url: str
    title: str = "未命名视频"
    duration: float | None = None
    uploader: str = ""
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    extractor_key: str = ""
    raw_info: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(slots=True, frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(slots=True)
class Transcript:
    text: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    language: str = "zh"
    language_probability: float = 0.0
    audio_duration: float = 0.0


@dataclass(slots=True)
class AnalysisReport:
    topic: str
    core_points: list[str]
    highlights: list[str]
    emotion: str
    tags: list[str]
    transcript: str

    def to_markdown(self) -> str:
        points = "\n".join(
            f"{index}. {point}" for index, point in enumerate(self.core_points, 1)
        ) or "1. 未提取到足够的有效观点"
        highlights = "\n".join(f"> {line}" for line in self.highlights)
        if not highlights:
            highlights = "> 未提取到明确的原文金句"
        tags = " ".join(self.tags)
        return (
            "# 视频内容分析报告\n\n"
            f"## 视频核心主题\n\n{self.topic}\n\n"
            f"## 核心观点\n\n{points}\n\n"
            f"## 高光金句（原文）\n\n{highlights}\n\n"
            f"## 内容情绪属性\n\n{self.emotion}\n\n"
            f"## 推荐话题标签\n\n{tags}\n\n"
            f"## 完整原始口播\n\n{self.transcript.strip()}\n"
        )


@dataclass(slots=True, frozen=True)
class ExportPaths:
    transcript_path: Path
    report_path: Path


@dataclass(slots=True)
class JobResult:
    item: VideoItem
    status: JobStatus
    transcript: Transcript | None = None
    report: AnalysisReport | None = None
    exports: ExportPaths | None = None
    message: str = ""
    elapsed_seconds: float = 0.0


@dataclass(slots=True, frozen=True)
class ProgressEvent:
    stage: str
    message: str
    fraction: float | None = None
    item_id: str = ""


class CancelToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()
