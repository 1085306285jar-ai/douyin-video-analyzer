from __future__ import annotations

import contextlib
import http.cookiejar
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .browser_fallback import BrowserFallbackResolver
from .domain import CancelToken, LinkType, ParsedLink, ProgressEvent, VideoItem
from .exceptions import (
    AnalyzerError,
    AuthenticationRequiredError,
    CancelledError,
    ContentUnavailableError,
    DependencyMissingError,
    ExtractionError,
    NetworkError,
    PrivateContentError,
    UnsupportedLinkError,
)


ProgressCallback = Callable[[ProgressEvent], None]


class _QuietLogger:
    def debug(self, _message: str) -> None:
        return

    def warning(self, _message: str) -> None:
        return

    def error(self, _message: str) -> None:
        return


@dataclass(slots=True, frozen=True)
class ExtractorConfig:
    max_items: int = 20
    retries: int = 3
    socket_timeout: int = 25


class YtDlpExtractor:
    """Best-effort public-content extractor backed by yt-dlp.

    Douyin changes frequently. This class deliberately keeps all yt-dlp-specific
    details behind one interface so the extractor can be updated without touching
    transcription, analysis, export, or the GUI.
    """

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/149.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        config: ExtractorConfig | None = None,
        *,
        browser_fallback: BrowserFallbackResolver | None = None,
    ) -> None:
        self.config = config or ExtractorConfig()
        self.browser_fallback = browser_fallback

    @staticmethod
    def _yt_dlp() -> Any:
        try:
            import yt_dlp
        except ImportError as exc:
            raise DependencyMissingError("媒体提取组件缺失，请重新下载完整版本。") from exc
        return yt_dlp

    def resolve(
        self,
        parsed: ParsedLink,
        *,
        limit: int | None = None,
        callback: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> list[VideoItem]:
        self._check_cancel(cancel_token)
        item_limit = min(max(1, limit or self.config.max_items), 100)
        self._emit(callback, "resolve", "正在识别链接并读取公开视频列表……")

        options = self._base_options()
        options.update(
            {
                "skip_download": True,
                "playlistend": item_limit,
                "lazy_playlist": True,
                "noplaylist": parsed.link_type == LinkType.SINGLE,
            }
        )
        try:
            info = self._extract(parsed.url, options, download=False)
        except AnalyzerError:
            if not self.browser_fallback:
                raise
            return self.browser_fallback.resolve(
                parsed,
                limit=item_limit,
                callback=callback,
                cancel_token=cancel_token,
            )
        self._check_cancel(cancel_token)

        entries = list(self._flatten_entries(info, item_limit))
        if not entries:
            entries = [info] if info else []
        items = [self._to_video_item(entry, parsed.url) for entry in entries[:item_limit]]
        items = [item for item in items if item.source_url]
        if not items:
            if self.browser_fallback:
                return self.browser_fallback.resolve(
                    parsed,
                    limit=item_limit,
                    callback=callback,
                    cancel_token=cancel_token,
                )
            raise ExtractionError("没有读取到可解析的公开视频。")

        if parsed.link_type == LinkType.SINGLE and len(items) > 1:
            items = items[:1]
        self._emit(callback, "resolve", f"已识别 {len(items)} 个待处理视频。", 1.0)
        return items

    def download(
        self,
        item: VideoItem,
        target_dir: Path,
        *,
        callback: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        self._check_cancel(cancel_token)
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", item.item_id)[:80] or "video"
        template = str(target_dir / f"{safe_id}.%(ext)s")

        def progress_hook(status: dict[str, Any]) -> None:
            self._check_cancel(cancel_token)
            if status.get("status") == "downloading":
                total = status.get("total_bytes") or status.get("total_bytes_estimate")
                downloaded = status.get("downloaded_bytes") or 0
                fraction = downloaded / total if total else None
                self._emit(
                    callback,
                    "download",
                    "正在获取音频流……",
                    fraction,
                    item.item_id,
                )
            elif status.get("status") == "finished":
                self._emit(
                    callback,
                    "download",
                    "媒体读取完成，准备本地转写。",
                    1.0,
                    item.item_id,
                )

        options = self._base_options()
        options.update(
            {
                # Prefer an audio-only representation. Some Douyin posts expose only
                # a muxed media stream, so a low-resolution playable fallback is kept.
                "format": "ba[acodec!=none]/b[height<=480][acodec!=none]/best[acodec!=none]",
                "outtmpl": template,
                "noplaylist": True,
                "overwrites": True,
                "progress_hooks": [progress_hook],
            }
        )
        try:
            info = self._extract(item.source_url, options, download=True)
        except ExtractionError:
            direct_urls = item.raw_info.get("direct_media_urls") or []
            if direct_urls:
                return self._download_direct(
                    [str(url) for url in direct_urls],
                    target_dir / f"{safe_id}.mp4",
                    item,
                    callback=callback,
                    cancel_token=cancel_token,
                )
            raise
        self._check_cancel(cancel_token)

        candidates: list[Path] = []
        for download in info.get("requested_downloads") or []:
            filepath = download.get("filepath") or download.get("filename")
            if filepath:
                candidates.append(Path(filepath))
        filename = info.get("_filename")
        if filename:
            candidates.append(Path(filename))
        candidates.extend(target_dir.glob(f"{safe_id}.*"))

        for candidate in candidates:
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        raise ExtractionError("媒体读取结束，但没有生成可转写的音频文件。")

    def _base_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "logger": _QuietLogger(),
            "cachedir": False,
            "retries": self.config.retries,
            "fragment_retries": self.config.retries,
            "extractor_retries": self.config.retries,
            "socket_timeout": self.config.socket_timeout,
            "concurrent_fragment_downloads": 2,
            "windowsfilenames": True,
            "http_headers": {
                "User-Agent": self.USER_AGENT,
                "Referer": "https://www.douyin.com/",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            },
        }
        if self.browser_fallback and self.browser_fallback.cookie_file:
            options["cookiefile"] = str(self.browser_fallback.cookie_file)
        return options

    def _download_direct(
        self,
        urls: list[str],
        target: Path,
        item: VideoItem,
        *,
        callback: ProgressCallback | None,
        cancel_token: CancelToken | None,
    ) -> Path:
        cookie_jar = http.cookiejar.MozillaCookieJar()
        if self.browser_fallback and self.browser_fallback.cookie_file:
            with contextlib.suppress(OSError, http.cookiejar.LoadError):
                cookie_jar.load(
                    str(self.browser_fallback.cookie_file),
                    ignore_discard=True,
                    ignore_expires=True,
                )
        opener = build_opener(HTTPCookieProcessor(cookie_jar))
        last_error: Exception | None = None
        for url in urls:
            self._check_cancel(cancel_token)
            partial = target.with_suffix(target.suffix + ".part")
            try:
                request = Request(
                    url,
                    headers={
                        "User-Agent": self.USER_AGENT,
                        "Referer": "https://www.douyin.com/",
                        "Accept": "*/*",
                    },
                )
                with opener.open(request, timeout=self.config.socket_timeout) as response:
                    total = int(response.headers.get("Content-Length") or 0)
                    downloaded = 0
                    with partial.open("wb") as handle:
                        while True:
                            self._check_cancel(cancel_token)
                            chunk = response.read(256 * 1024)
                            if not chunk:
                                break
                            handle.write(chunk)
                            downloaded += len(chunk)
                            fraction = downloaded / total if total else None
                            self._emit(
                                callback,
                                "download",
                                "正在通过兼容窗口获取媒体……",
                                fraction,
                                item.item_id,
                            )
                if partial.stat().st_size <= 0:
                    raise OSError("empty response")
                partial.replace(target)
                self._emit(
                    callback,
                    "download",
                    "媒体读取完成，准备本地转写。",
                    1.0,
                    item.item_id,
                )
                return target
            except CancelledError:
                partial.unlink(missing_ok=True)
                raise
            except Exception as exc:
                last_error = exc
                partial.unlink(missing_ok=True)
                continue
        raise NetworkError("兼容窗口已找到视频，但媒体文件读取失败。") from last_error

    def cleanup(self) -> None:
        if self.browser_fallback:
            self.browser_fallback.cleanup()

    def _extract(self, url: str, options: dict[str, Any], *, download: bool) -> dict[str, Any]:
        yt_dlp = self._yt_dlp()
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=download)
                if not isinstance(info, dict):
                    raise ExtractionError("平台没有返回有效的视频信息。")
                return info
        except CancelledError:
            raise
        except Exception as exc:  # yt-dlp uses several extractor-specific error classes
            self._raise_friendly(exc)
            raise AssertionError("unreachable")

    @staticmethod
    def _flatten_entries(info: dict[str, Any], limit: int) -> Iterable[dict[str, Any]]:
        stack: list[Any] = list(info.get("entries") or [])
        emitted = 0
        while stack and emitted < limit:
            entry = stack.pop(0)
            if not isinstance(entry, dict):
                continue
            nested = entry.get("entries")
            if nested:
                stack[0:0] = list(nested)
                continue
            emitted += 1
            yield entry

    @staticmethod
    def _to_video_item(info: dict[str, Any], fallback_url: str) -> VideoItem:
        item_id = str(info.get("id") or info.get("display_id") or "unknown")
        source_url = str(
            info.get("webpage_url")
            or info.get("original_url")
            or info.get("url")
            or fallback_url
        )
        title = str(info.get("title") or info.get("description") or f"视频_{item_id}")
        description = str(info.get("description") or "")
        tags = [str(tag).lstrip("#") for tag in (info.get("tags") or []) if str(tag).strip()]
        tags.extend(match.group(1) for match in re.finditer(r"#([\w\u4e00-\u9fff-]{2,24})", description))
        duration_value = info.get("duration")
        try:
            duration = float(duration_value) if duration_value is not None else None
        except (TypeError, ValueError):
            duration = None
        return VideoItem(
            item_id=item_id,
            source_url=source_url,
            title=title[:240],
            duration=duration,
            uploader=str(info.get("uploader") or info.get("creator") or ""),
            description=description[:2000],
            hashtags=list(dict.fromkeys(tags))[:20],
            extractor_key=str(info.get("extractor_key") or info.get("extractor") or ""),
            raw_info={},
        )

    @staticmethod
    def _raise_friendly(exc: Exception) -> None:
        raw = str(exc)
        message = raw.lower()
        if any(token in message for token in ("login", "cookie", "verify", "captcha")):
            raise AuthenticationRequiredError() from exc
        if any(token in message for token in ("private", "非公开", "私密")):
            raise PrivateContentError() from exc
        if any(
            token in message
            for token in ("unavailable", "deleted", "removed", "not found", "失效", "删除")
        ):
            raise ContentUnavailableError() from exc
        if any(
            token in message
            for token in ("timeout", "timed out", "connection", "network", "dns", "http error")
        ):
            raise NetworkError() from exc
        if "unsupported url" in message:
            raise UnsupportedLinkError() from exc
        raise ExtractionError("抖音页面读取失败；平台页面可能已更新，请使用新版提取组件后重试。") from exc

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
