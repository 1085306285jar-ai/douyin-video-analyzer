from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from douyin_analyzer.analyzer import LocalContentAnalyzer
from douyin_analyzer.domain import (
    CancelToken,
    JobStatus,
    ParsedLink,
    Transcript,
    VideoItem,
)
from douyin_analyzer.exceptions import CancelledError
from douyin_analyzer.exporter import ResultExporter
from douyin_analyzer.pipeline import AnalyzerPipeline


class FakeExtractor:
    def resolve(self, parsed: ParsedLink, **_kwargs: object) -> list[VideoItem]:
        return [
            VideoItem("short", parsed.url, title="太短", duration=8),
            VideoItem("good", parsed.url, title="正常视频", duration=45, hashtags=["知识分享"]),
        ]

    def download(self, item: VideoItem, target_dir: Path, **_kwargs: object) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        media = target_dir / f"{item.item_id}.m4a"
        media.write_bytes(b"fake-media")
        return media


class FakeTranscriber:
    def transcribe(self, _media_path: Path, **_kwargs: object) -> Transcript:
        return Transcript(
            text=(
                "第一步先确定目标。第二步根据问题设计内容。"
                "记住，不是内容越多越好，而是每一条都要解决问题。"
            )
        )


class UnknownDurationExtractor(FakeExtractor):
    def resolve(self, parsed: ParsedLink, **_kwargs: object) -> list[VideoItem]:
        return [VideoItem("unknown", parsed.url, title="未知时长", duration=None)]


class ShortAudioTranscriber(FakeTranscriber):
    def transcribe(self, _media_path: Path, **_kwargs: object) -> Transcript:
        return Transcript(
            text="这段口播文字足够识别，但实际音轨长度不足十秒。",
            audio_duration=9.5,
        )


class PipelineTests(unittest.TestCase):
    def test_end_to_end_with_test_doubles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pipeline = AnalyzerPipeline(
                extractor=FakeExtractor(),
                transcriber=FakeTranscriber(),
                analyzer=LocalContentAnalyzer(),
                exporter=ResultExporter(root / "output"),
                temp_root=root / "temp",
            )
            events = []
            results = pipeline.run(
                "https://www.douyin.com/video/123456789",
                callback=events.append,
            )
            self.assertEqual([result.status for result in results], [JobStatus.SKIPPED, JobStatus.SUCCESS])
            self.assertIsNotNone(results[1].exports)
            assert results[1].exports is not None
            self.assertTrue(results[1].exports.report_path.is_file())
            self.assertTrue(any(event.stage == "success" for event in events))
            self.assertFalse(any((root / "temp").glob("job_*")))

    def test_cancelled_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pipeline = AnalyzerPipeline(
                extractor=FakeExtractor(),
                transcriber=FakeTranscriber(),
                analyzer=LocalContentAnalyzer(),
                exporter=ResultExporter(root / "output"),
                temp_root=root / "temp",
            )
            token = CancelToken()
            token.cancel()
            with self.assertRaises(CancelledError):
                pipeline.run(
                    "https://www.douyin.com/video/123456789",
                    cancel_token=token,
                )

    def test_unknown_metadata_duration_is_filtered_after_transcription(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pipeline = AnalyzerPipeline(
                extractor=UnknownDurationExtractor(),
                transcriber=ShortAudioTranscriber(),
                analyzer=LocalContentAnalyzer(),
                exporter=ResultExporter(root / "output"),
                temp_root=root / "temp",
            )
            results = pipeline.run("https://www.douyin.com/video/123456789")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].status, JobStatus.SKIPPED)
            self.assertIn("9.5", results[0].message)
            self.assertIsNone(results[0].exports)


if __name__ == "__main__":
    unittest.main()
