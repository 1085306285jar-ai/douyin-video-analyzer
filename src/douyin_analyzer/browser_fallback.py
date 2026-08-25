from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urljoin

from .domain import CancelToken, LinkType, ParsedLink, ProgressEvent, VideoItem
from .exceptions import CancelledError, DependencyMissingError, ExtractionError


ProgressCallback = Callable[[ProgressEvent], None]
VIDEO_LINK_RE = re.compile(r"/(?:video|note)/(\d+)")


class BrowserFallbackResolver:
    """Resolve public Douyin links through a normal, visible Microsoft Edge page.

    The dedicated profile is separate from the user's personal Edge profile. It is
    used only when direct extraction fails, and lets the user complete any platform
    verification manually. This module does not solve or bypass verification.
    """

    RESPONSE_HINTS = (
        "/aweme/v1/web/aweme/post/",
        "/aweme/v1/web/aweme/detail/",
        "/aweme/v1/web/mix/aweme/",
        "/aweme/v1/web/general/search/",
    )

    def __init__(
        self,
        profile_dir: Path,
        temp_dir: Path,
        *,
        browser_channel: str = "msedge",
        wait_timeout_seconds: int = 150,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.temp_dir = Path(temp_dir)
        self.browser_channel = browser_channel
        self.wait_timeout_seconds = max(30, wait_timeout_seconds)
        self.cookie_file: Path | None = None

    def resolve(
        self,
        parsed: ParsedLink,
        *,
        limit: int,
        callback: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> list[VideoItem]:
        self._check_cancel(cancel_token)
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise DependencyMissingError("浏览器兼容组件缺失，请重新下载完整版本。") from exc

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._emit(
            callback,
            "browser",
            "常规读取受限，正在打开独立 Edge 兼容窗口；如出现验证，请手动完成。",
        )

        items_by_id: dict[str, VideoItem] = {}
        dom_items: dict[str, VideoItem] = {}
        final_url = parsed.url

        try:
            with sync_playwright() as playwright:
                context = self._launch_context(playwright)
                try:
                    page = context.pages[0] if context.pages else context.new_page()

                    def on_response(response: Any) -> None:
                        if not any(hint in response.url for hint in self.RESPONSE_HINTS):
                            return
                        with contextlib.suppress(Exception):
                            payload = response.json()
                            for aweme in extract_aweme_records(payload):
                                item = aweme_to_video_item(aweme)
                                if item:
                                    items_by_id[item.item_id] = item

                    page.on("response", on_response)
                    try:
                        page.goto(parsed.url, wait_until="domcontentloaded", timeout=45_000)
                    except PlaywrightTimeoutError:
                        # A partially loaded page is still useful for manual verification.
                        pass

                    stable_rounds = 0
                    previous_count = -1
                    max_rounds = max(30, self.wait_timeout_seconds)
                    for round_index in range(max_rounds):
                        self._check_cancel(cancel_token)
                        final_url = page.url or final_url
                        for item in self._collect_dom_items(page, final_url):
                            dom_items[item.item_id] = item
                        final_match = VIDEO_LINK_RE.search(final_url)
                        if final_match:
                            final_id = final_match.group(1)
                            dom_items.setdefault(
                                final_id,
                                VideoItem(
                                    item_id=final_id,
                                    source_url=final_url.split("?")[0],
                                    title=f"视频_{final_id}",
                                ),
                            )

                        all_count = len(set(items_by_id) | set(dom_items))
                        if all_count == previous_count:
                            stable_rounds += 1
                        else:
                            stable_rounds = 0
                            previous_count = all_count

                        direct_single = parsed.link_type in {LinkType.SINGLE, LinkType.AUTO} and bool(final_match)
                        if direct_single and all_count >= 1 and round_index >= 2:
                            break
                        if parsed.link_type in {LinkType.COLLECTION, LinkType.AUTHOR}:
                            if all_count >= limit or (all_count > 0 and stable_rounds >= 5):
                                break
                            page.mouse.wheel(0, 2400)
                        elif all_count >= 1:
                            break

                        if round_index and round_index % 10 == 0:
                            self._emit(
                                callback,
                                "browser",
                                f"兼容窗口已读取 {all_count} 个公开视频，仍在等待页面加载……",
                            )
                        page.wait_for_timeout(1_000)

                    cookies = context.cookies()
                    self._write_cookie_file(cookies)
                finally:
                    context.close()
        except CancelledError:
            raise
        except PlaywrightError as exc:
            raise ExtractionError("无法启动 Microsoft Edge 兼容窗口，请确认系统 Edge 可正常打开。") from exc

        merged = dict(dom_items)
        merged.update(items_by_id)
        if not merged:
            direct_match = VIDEO_LINK_RE.search(final_url)
            if direct_match:
                item_id = direct_match.group(1)
                merged[item_id] = VideoItem(
                    item_id=item_id,
                    source_url=final_url,
                    title=f"视频_{item_id}",
                )
        items = list(merged.values())[:limit]
        if not items:
            raise ExtractionError(
                "兼容窗口没有读取到公开视频；请确认页面能正常观看，并在窗口中完成必要验证。"
            )
        self._emit(callback, "browser", f"兼容窗口读取成功：{len(items)} 个公开视频。", 1.0)
        return items

    def cleanup(self) -> None:
        if self.cookie_file:
            with contextlib.suppress(OSError):
                self.cookie_file.unlink(missing_ok=True)
            self.cookie_file = None

    def _launch_context(self, playwright: Any) -> Any:
        common = {
            "user_data_dir": str(self.profile_dir),
            "headless": False,
            "locale": "zh-CN",
            "viewport": {"width": 1280, "height": 820},
            "accept_downloads": False,
        }
        channels = [self.browser_channel]
        if self.browser_channel == "msedge":
            channels.append("chrome")
        last_error: Exception | None = None
        for channel in channels:
            try:
                return playwright.chromium.launch_persistent_context(channel=channel, **common)
            except Exception as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    @staticmethod
    def _collect_dom_items(page: Any, base_url: str) -> Iterable[VideoItem]:
        locator = page.locator('a[href*="/video/"], a[href*="/note/"]')
        count = min(locator.count(), 500)
        for index in range(count):
            anchor = locator.nth(index)
            with contextlib.suppress(Exception):
                href = anchor.get_attribute("href") or ""
                url = urljoin(base_url, href)
                match = VIDEO_LINK_RE.search(url)
                if not match:
                    continue
                item_id = match.group(1)
                title = (anchor.get_attribute("aria-label") or anchor.inner_text() or "").strip()
                title = re.sub(r"\s+", " ", title)[:240]
                yield VideoItem(
                    item_id=item_id,
                    source_url=url.split("?")[0],
                    title=title or f"视频_{item_id}",
                )

    def _write_cookie_file(self, cookies: list[dict[str, Any]]) -> Path:
        target = self.temp_dir / "browser_session.cookies.txt"
        lines = ["# Netscape HTTP Cookie File", "# Generated locally for the current task only."]
        for cookie in cookies:
            domain = str(cookie.get("domain") or "")
            normalized_domain = domain.lower().lstrip(".")
            allowed_domain = (
                normalized_domain == "douyin.com"
                or normalized_domain.endswith(".douyin.com")
                or normalized_domain == "iesdouyin.com"
                or normalized_domain.endswith(".iesdouyin.com")
            )
            if not allowed_domain:
                continue
            include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
            path = str(cookie.get("path") or "/")
            secure = "TRUE" if cookie.get("secure") else "FALSE"
            expires = int(float(cookie.get("expires") or 0))
            name = str(cookie.get("name") or "").replace("\t", "")
            value = str(cookie.get("value") or "").replace("\t", "").replace("\n", "")
            if name:
                lines.append(
                    "\t".join((domain, include_subdomains, path, secure, str(expires), name, value))
                )
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with contextlib.suppress(OSError):
            target.chmod(0o600)
        self.cookie_file = target
        return target

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
    ) -> None:
        if callback:
            callback(ProgressEvent(stage=stage, message=message, fraction=fraction))


def extract_aweme_records(payload: Any, *, max_depth: int = 8) -> Iterable[dict[str, Any]]:
    """Yield Douyin work records from several observed response envelope shapes."""
    seen_objects: set[int] = set()

    def walk(value: Any, depth: int) -> Iterable[dict[str, Any]]:
        if depth > max_depth:
            return
        if isinstance(value, dict):
            identity = id(value)
            if identity in seen_objects:
                return
            seen_objects.add(identity)
            if value.get("aweme_id") and isinstance(value.get("video"), dict):
                yield value
                return
            preferred_keys = (
                "aweme_detail",
                "aweme_list",
                "data",
                "item_list",
                "mix_aweme_list",
            )
            visited: set[str] = set()
            for key in preferred_keys:
                if key in value:
                    visited.add(key)
                    yield from walk(value[key], depth + 1)
            for key, child in value.items():
                if key not in visited and isinstance(child, (dict, list)):
                    yield from walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child, depth + 1)

    yield from walk(payload, 0)


def aweme_to_video_item(aweme: dict[str, Any]) -> VideoItem | None:
    item_id = str(aweme.get("aweme_id") or "")
    if not item_id:
        return None
    description = str(aweme.get("desc") or "")
    author = aweme.get("author") if isinstance(aweme.get("author"), dict) else {}
    video = aweme.get("video") if isinstance(aweme.get("video"), dict) else {}
    duration_raw = aweme.get("duration") or video.get("duration")
    try:
        duration = float(duration_raw) / 1000.0 if duration_raw else None
    except (TypeError, ValueError):
        duration = None

    hashtags: list[str] = []
    for item in aweme.get("text_extra") or []:
        if isinstance(item, dict) and item.get("hashtag_name"):
            hashtags.append(str(item["hashtag_name"]))

    direct_urls: list[str] = []
    for address_key in ("play_addr", "play_addr_h264", "download_addr"):
        address = video.get(address_key)
        if not isinstance(address, dict):
            continue
        direct_urls.extend(str(url) for url in (address.get("url_list") or []) if str(url).startswith("http"))

    return VideoItem(
        item_id=item_id,
        source_url=f"https://www.douyin.com/video/{item_id}",
        title=description[:240] or f"视频_{item_id}",
        duration=duration,
        uploader=str(author.get("nickname") or ""),
        description=description[:2000],
        hashtags=list(dict.fromkeys(hashtags))[:20],
        extractor_key="browser",
        raw_info={"direct_media_urls": list(dict.fromkeys(direct_urls))},
    )
