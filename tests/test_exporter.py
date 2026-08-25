from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from douyin_analyzer.analyzer import LocalContentAnalyzer
from douyin_analyzer.domain import Transcript, VideoItem
from douyin_analyzer.exporter import ResultExporter, safe_filename


class ExporterTests(unittest.TestCase):
    def test_safe_filename_handles_windows_reserved_and_forbidden_chars(self) -> None:
        self.assertEqual(safe_filename("CON"), "_CON")
        self.assertNotIn(":", safe_filename('标题:测试/\"结果\"'))
        self.assertNotIn("/", safe_filename('标题:测试/\"结果\"'))

    def test_exports_utf8_txt_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            exporter = ResultExporter(output)
            item = VideoItem(
                item_id="123",
                source_url="https://www.douyin.com/video/123",
                title="示例/视频",
                duration=61.5,
                uploader="示例博主",
            )
            transcript = Transcript(text="这是第一句。这是第二句，包含一个明确观点。")
            report = LocalContentAnalyzer().analyze(transcript.text, title=item.title)
            paths = exporter.export(
                item,
                transcript,
                report,
                now=datetime(2026, 8, 25, 12, 34, 56),
            )
            self.assertTrue(paths.transcript_path.is_file())
            self.assertTrue(paths.report_path.is_file())
            self.assertIn("这是第一句", paths.transcript_path.read_text(encoding="utf-8-sig"))
            markdown = paths.report_path.read_text(encoding="utf-8-sig")
            self.assertIn("# 视频解析结果", markdown)
            self.assertIn("## 核心观点", markdown)

    def test_does_not_overwrite_same_second_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exporter = ResultExporter(Path(temp_dir))
            item = VideoItem("123", "https://www.douyin.com/video/123", title="示例")
            transcript = Transcript(text="这是一个足够长而且可以正常解析的测试口播文本。")
            report = LocalContentAnalyzer().analyze(transcript.text)
            moment = datetime(2026, 8, 25, 12, 0, 0)
            first = exporter.export(item, transcript, report, now=moment)
            second = exporter.export(item, transcript, report, now=moment)
            self.assertNotEqual(first.report_path, second.report_path)


if __name__ == "__main__":
    unittest.main()
