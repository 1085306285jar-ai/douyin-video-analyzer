from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .domain import AnalysisReport, ExportPaths, JobResult, JobStatus, Transcript, VideoItem
from .exceptions import ExportError


WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def safe_filename(value: str, limit: int = 60) -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value or "")
    value = re.sub(r"\s+", " ", value).strip(" ._")
    value = value[:limit].rstrip(" ._") or "未命名视频"
    if value.upper() in WINDOWS_RESERVED:
        value = f"_{value}"
    return value


class ResultExporter:
    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root

    def export(
        self,
        item: VideoItem,
        transcript: Transcript,
        report: AnalysisReport,
        *,
        now: datetime | None = None,
    ) -> ExportPaths:
        moment = now or datetime.now()
        day_dir = self.output_root / moment.strftime("%Y-%m-%d")
        title = safe_filename(item.title)
        item_id = safe_filename(item.item_id, 24)
        prefix = f"{moment:%H%M%S}_{title}_{item_id}"
        transcript_path = day_dir / f"{prefix}_原始文案.txt"
        report_path = day_dir / f"{prefix}_分析报告.md"

        try:
            day_dir.mkdir(parents=True, exist_ok=True)
            transcript_path = self._unique_path(transcript_path)
            report_path = self._unique_path(report_path)
            transcript_path.write_text(transcript.text.strip() + "\n", encoding="utf-8-sig")
            report_path.write_text(
                self._render_report(item, report, moment), encoding="utf-8-sig"
            )
        except OSError as exc:
            raise ExportError() from exc

        return ExportPaths(transcript_path=transcript_path, report_path=report_path)

    def export_batch_index(
        self,
        results: list[JobResult],
        *,
        now: datetime | None = None,
    ) -> Path:
        moment = now or datetime.now()
        day_dir = self.output_root / moment.strftime("%Y-%m-%d")
        target = self._unique_path(day_dir / f"{moment:%H%M%S}_批量解析索引.md")
        success_count = sum(result.status == JobStatus.SUCCESS for result in results)
        lines = [
            "# 批量解析索引",
            "",
            f"- 生成时间：{moment:%Y-%m-%d %H:%M:%S}",
            f"- 总数：{len(results)}",
            f"- 成功：{success_count}",
            f"- 跳过/失败：{len(results) - success_count}",
            "",
            "| 序号 | 视频 | 状态 | 结果 |",
            "| ---: | --- | --- | --- |",
        ]
        for index, result in enumerate(results, 1):
            status = {
                JobStatus.SUCCESS: "成功",
                JobStatus.SKIPPED: "跳过",
                JobStatus.FAILED: "失败",
            }[result.status]
            link = ""
            if result.exports:
                link = f"[分析报告]({result.exports.report_path.name})"
            detail = link or result.message.replace("|", "｜")
            lines.append(
                f"| {index} | {result.item.title.replace('|', '｜')} | {status} | {detail} |"
            )
        try:
            day_dir.mkdir(parents=True, exist_ok=True)
            target.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
        except OSError as exc:
            raise ExportError() from exc
        return target

    @staticmethod
    def _render_report(item: VideoItem, report: AnalysisReport, moment: datetime) -> str:
        metadata = [
            "# 视频解析结果",
            "",
            f"- 视频标题：{item.title}",
            f"- 博主：{item.uploader or '未知'}",
            f"- 视频 ID：{item.item_id}",
            f"- 解析时间：{moment:%Y-%m-%d %H:%M:%S}",
        ]
        if item.duration is not None:
            metadata.append(f"- 视频时长：{item.duration:.1f} 秒")
        metadata.extend(["", report.to_markdown().removeprefix("# 视频内容分析报告\n\n")])
        return "\n".join(metadata).rstrip() + "\n"

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        for index in range(2, 1000):
            candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
            if not candidate.exists():
                return candidate
        raise ExportError("同名文件过多，无法保存结果。")
