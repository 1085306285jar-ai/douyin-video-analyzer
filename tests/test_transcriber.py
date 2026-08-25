from __future__ import annotations

import unittest

from douyin_analyzer.domain import TranscriptSegment
from douyin_analyzer.transcriber import LocalWhisperTranscriber


class TranscriberTextTests(unittest.TestCase):
    def test_joins_chinese_segments_without_artificial_spaces(self) -> None:
        text = LocalWhisperTranscriber._join_segments(
            [
                TranscriptSegment(0, 1, "这是第一句。"),
                TranscriptSegment(1, 2, "这是第二句。"),
            ]
        )
        self.assertEqual(text, "这是第一句。这是第二句。")

    def test_preserves_spaces_between_english_words(self) -> None:
        text = LocalWhisperTranscriber._join_segments(
            [
                TranscriptSegment(0, 1, "AI tools"),
                TranscriptSegment(1, 2, "work locally"),
            ]
        )
        self.assertEqual(text, "AI tools work locally")


if __name__ == "__main__":
    unittest.main()
