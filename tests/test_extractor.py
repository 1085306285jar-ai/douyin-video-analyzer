from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from douyin_analyzer.domain import LinkType, ParsedLink, VideoItem
from douyin_analyzer.exceptions import ExtractionError, ModelMissingError
from douyin_analyzer.extractor import YtDlpExtractor
from douyin_analyzer.transcriber import LocalWhisperTranscriber


class StubExtractor(YtDlpExtractor):
    def __init__(self, payload: dict) -> None:
        super().__init__()
        self.payload = payload

    def _extract(self, _url: str, _options: dict, *, download: bool) -> dict:
        self.assert_download = download
        return self.payload


class StubBrowserFallback:
    cookie_file = None

    def __init__(self) -> None:
        self.called = False
        self.cleaned = False

    def resolve(self, parsed: ParsedLink, **_kwargs: object) -> list[VideoItem]:
        self.called = True
        return [VideoItem("fallback", parsed.url, title="兼容结果")]

    def cleanup(self) -> None:
        self.cleaned = True


class FailingExtractor(YtDlpExtractor):
    def _extract(self, _url: str, _options: dict, *, download: bool) -> dict:
        raise ExtractionError("direct failed")


class ExtractorTests(unittest.TestCase):
    def test_resolve_maps_playlist_metadata(self) -> None:
        extractor = StubExtractor(
            {
                "entries": [
                    {
                        "id": "111",
                        "webpage_url": "https://www.douyin.com/video/111",
                        "title": "第一个视频",
                        "duration": 32,
                        "uploader": "博主",
                        "tags": ["干货"],
                    },
                    {
                        "id": "222",
                        "webpage_url": "https://www.douyin.com/video/222",
                        "title": "第二个视频",
                        "duration": 45,
                    },
                ]
            }
        )
        items = extractor.resolve(
            ParsedLink("https://www.douyin.com/collection/999", LinkType.COLLECTION),
            limit=2,
        )
        self.assertEqual([item.item_id for item in items], ["111", "222"])
        self.assertEqual(items[0].uploader, "博主")
        self.assertEqual(items[0].hashtags, ["干货"])

    def test_direct_failure_uses_configured_browser_fallback(self) -> None:
        fallback = StubBrowserFallback()
        extractor = FailingExtractor(browser_fallback=fallback)  # type: ignore[arg-type]
        items = extractor.resolve(
            ParsedLink("https://www.douyin.com/user/example", LinkType.AUTHOR),
            limit=10,
        )
        self.assertTrue(fallback.called)
        self.assertEqual(items[0].item_id, "fallback")
        extractor.cleanup()
        self.assertTrue(fallback.cleaned)

    def test_missing_offline_model_fails_before_importing_engine(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            transcriber = LocalWhisperTranscriber(Path(temp_dir) / "missing")
            with self.assertRaises(ModelMissingError):
                transcriber.load_model()


if __name__ == "__main__":
    unittest.main()
