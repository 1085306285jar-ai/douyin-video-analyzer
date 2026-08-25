from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from .analyzer import LocalContentAnalyzer
from .browser_fallback import BrowserFallbackResolver
from .config import APP_NAME, APP_VERSION, AppPaths
from .domain import CancelToken, JobResult, JobStatus, LinkType, ProgressEvent
from .exceptions import AnalyzerError, CancelledError, InvalidLinkError
from .exporter import ResultExporter, safe_filename
from .extractor import ExtractorConfig, YtDlpExtractor
from .health import cleanup_stale_temp
from .links import parse_link
from .pipeline import AnalyzerPipeline
from .transcriber import LocalWhisperTranscriber


COLORS = {
    "window": "#F4F7FB",
    "panel": "#FFFFFF",
    "border": "#DCE3ED",
    "text": "#182230",
    "muted": "#667085",
    "primary": "#2563EB",
    "primary_active": "#1D4ED8",
    "secondary": "#EEF2F7",
    "success": "#16845B",
    "warning": "#B54708",
    "danger": "#C4320A",
    "log": "#101828",
    "log_text": "#D0D5DD",
}

MODE_LABEL_TO_VALUE = {
    "自动识别": LinkType.AUTO,
    "单视频": LinkType.SINGLE,
    "合集批量": LinkType.COLLECTION,
    "博主主页": LinkType.AUTHOR,
}


class AnalyzerApp:
    def __init__(self, root: tk.Tk, paths: AppPaths | None = None) -> None:
        self.root = root
        self.paths = paths or AppPaths.discover()
        self.paths.ensure_runtime_dirs()
        cleanup_stale_temp(self.paths.temp_root)

        self.browser_resolver = BrowserFallbackResolver(
            self.paths.data_root / "browser_profile",
            self.paths.temp_root,
        )
        self.media_extractor = YtDlpExtractor(
            ExtractorConfig(max_items=20),
            browser_fallback=self.browser_resolver,
        )
        self.pipeline = AnalyzerPipeline(
            extractor=self.media_extractor,
            transcriber=LocalWhisperTranscriber(self.paths.model_root),
            analyzer=LocalContentAnalyzer(),
            exporter=ResultExporter(self.paths.output_root),
            temp_root=self.paths.temp_root,
        )
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancel_token: CancelToken | None = None
        self.worker: threading.Thread | None = None
        self.running = False
        self.results: list[JobResult] = []
        self.row_to_result: dict[str, JobResult] = {}
        self._last_progress_log: tuple[str, str] | None = None

        self._configure_window()
        self._configure_styles()
        self._build_ui()
        self._center_window()
        self.root.after(100, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_window(self) -> None:
        self.root.title(f"{APP_NAME}  v{APP_VERSION}")
        icon_path = self.paths.resource_root / "assets" / "app.ico"
        if icon_path.is_file():
            try:
                self.root.iconbitmap(default=str(icon_path))
            except tk.TclError:
                pass
        self.root.geometry("1180x800")
        self.root.minsize(980, 680)
        self.root.configure(bg=COLORS["window"])

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        default_font = ("Microsoft YaHei UI", 10)
        self.root.option_add("*Font", default_font)
        style.configure("TFrame", background=COLORS["window"])
        style.configure("Panel.TFrame", background=COLORS["panel"])
        style.configure(
            "Title.TLabel",
            background=COLORS["window"],
            foreground=COLORS["text"],
            font=("Microsoft YaHei UI", 20, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=COLORS["window"],
            foreground=COLORS["muted"],
            font=("Microsoft YaHei UI", 9),
        )
        style.configure(
            "PanelTitle.TLabel",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.configure(
            "PanelMuted.TLabel",
            background=COLORS["panel"],
            foreground=COLORS["muted"],
            font=("Microsoft YaHei UI", 9),
        )
        style.configure(
            "Primary.TButton",
            foreground="#FFFFFF",
            background=COLORS["primary"],
            borderwidth=0,
            padding=(18, 9),
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[("active", COLORS["primary_active"]), ("disabled", "#98A2B3")],
        )
        style.configure(
            "Secondary.TButton",
            foreground=COLORS["text"],
            background=COLORS["secondary"],
            bordercolor=COLORS["border"],
            padding=(14, 8),
        )
        style.map("Secondary.TButton", background=[("active", "#E4EAF2")])
        style.configure(
            "Danger.TButton",
            foreground=COLORS["danger"],
            background="#FFF3F0",
            bordercolor="#FFD5CC",
            padding=(14, 8),
        )
        style.configure(
            "TRadiobutton",
            background=COLORS["panel"],
            foreground=COLORS["text"],
        )
        style.map("TRadiobutton", background=[("active", COLORS["panel"])])
        style.configure(
            "TCheckbutton",
            background=COLORS["panel"],
            foreground=COLORS["text"],
        )
        style.map("TCheckbutton", background=[("active", COLORS["panel"])])
        style.configure(
            "Treeview",
            rowheight=30,
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
        )
        style.configure(
            "Treeview.Heading",
            background="#F8FAFC",
            foreground=COLORS["muted"],
            font=("Microsoft YaHei UI", 9, "bold"),
            padding=(6, 7),
        )
        style.map("Treeview", background=[("selected", "#E8F0FE")], foreground=[("selected", COLORS["text"])])
        style.configure("TNotebook", background=COLORS["panel"], borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 8), background="#F2F4F7")
        style.map("TNotebook.Tab", background=[("selected", "#FFFFFF")], foreground=[("selected", COLORS["primary"])])
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#E9EEF5",
            background=COLORS["primary"],
            bordercolor="#E9EEF5",
            lightcolor=COLORS["primary"],
            darkcolor=COLORS["primary"],
        )

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(20, 16, 20, 14))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="抖音视频 AI 智能解析", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="仅联网读取抖音公开媒体；语音转写、内容分析和文件保存均在本机完成",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(
            header,
            text=f"本地离线分析引擎  ·  v{APP_VERSION}",
            style="Subtitle.TLabel",
        ).grid(row=0, column=1, rowspan=2, sticky="e")

        input_panel = ttk.Frame(outer, style="Panel.TFrame", padding=14)
        input_panel.grid(row=1, column=0, sticky="ew")
        input_panel.columnconfigure(0, weight=1)
        ttk.Label(input_panel, text="粘贴抖音分享内容或链接", style="PanelTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            input_panel,
            text="支持单视频、合集、博主主页；分享文案里的链接会自动提取",
            style="PanelMuted.TLabel",
        ).grid(row=0, column=1, sticky="e")

        input_row = ttk.Frame(input_panel, style="Panel.TFrame")
        input_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(9, 10))
        input_row.columnconfigure(0, weight=1)
        self.link_text = tk.Text(
            input_row,
            height=3,
            wrap="word",
            relief="solid",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["primary"],
            bg="#FFFFFF",
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            padx=10,
            pady=8,
            undo=True,
        )
        self.link_text.grid(row=0, column=0, sticky="ew")
        self.paste_button = ttk.Button(
            input_row, text="一键粘贴", style="Secondary.TButton", command=self._paste
        )
        self.paste_button.grid(row=0, column=1, sticky="ns", padx=(10, 0))

        options = ttk.Frame(input_panel, style="Panel.TFrame")
        options.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Label(options, text="解析模式：", style="PanelMuted.TLabel").pack(side="left")
        self.mode_var = tk.StringVar(value="自动识别")
        for label in MODE_LABEL_TO_VALUE:
            ttk.Radiobutton(options, text=label, value=label, variable=self.mode_var).pack(
                side="left", padx=(0, 12)
            )
        ttk.Separator(options, orient="vertical").pack(side="left", fill="y", padx=(2, 14))
        ttk.Label(options, text="批量上限：", style="PanelMuted.TLabel").pack(side="left")
        self.limit_var = tk.IntVar(value=20)
        self.limit_spin = ttk.Spinbox(
            options,
            from_=1,
            to=100,
            width=5,
            textvariable=self.limit_var,
            justify="center",
        )
        self.limit_spin.pack(side="left")
        ttk.Label(options, text="个", style="PanelMuted.TLabel").pack(
            side="left", padx=(5, 0)
        )
        ttk.Separator(options, orient="vertical").pack(side="left", fill="y", padx=(14, 12))
        self.compat_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options,
            text="风控时启用 Edge 兼容",
            variable=self.compat_var,
        ).pack(side="left")

        controls = ttk.Frame(outer)
        controls.grid(row=2, column=0, sticky="ew", pady=12)
        controls.columnconfigure(5, weight=1)
        self.start_button = ttk.Button(
            controls, text="开始解析", style="Primary.TButton", command=self._start
        )
        self.start_button.grid(row=0, column=0, padx=(0, 8))
        self.cancel_button = ttk.Button(
            controls,
            text="取消任务",
            style="Danger.TButton",
            command=self._cancel,
            state="disabled",
        )
        self.cancel_button.grid(row=0, column=1, padx=(0, 8))
        ttk.Button(
            controls, text="清空结果", style="Secondary.TButton", command=self._clear_results
        ).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(
            controls, text="清空日志", style="Secondary.TButton", command=self._clear_log
        ).grid(row=0, column=3, padx=(0, 8))
        self.export_button = ttk.Button(
            controls,
            text="另存所选结果",
            style="Secondary.TButton",
            command=self._save_selected,
            state="disabled",
        )
        self.export_button.grid(row=0, column=4)
        ttk.Button(
            controls,
            text="打开导出目录",
            style="Secondary.TButton",
            command=self._open_output,
        ).grid(row=0, column=6, sticky="e")

        workspace = ttk.Panedwindow(outer, orient="vertical")
        workspace.grid(row=3, column=0, sticky="nsew")

        result_area = ttk.Frame(workspace, style="Panel.TFrame", padding=10)
        result_area.columnconfigure(1, weight=1)
        result_area.rowconfigure(1, weight=1)
        workspace.add(result_area, weight=4)

        status_row = ttk.Frame(result_area, style="Panel.TFrame")
        status_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 9))
        status_row.columnconfigure(1, weight=1)
        self.status_var = tk.StringVar(value="就绪：请粘贴抖音链接")
        self.status_label = ttk.Label(
            status_row, textvariable=self.status_var, style="PanelTitle.TLabel"
        )
        self.status_label.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(
            status_row, orient="horizontal", mode="determinate", maximum=100
        )
        self.progress.grid(row=0, column=1, sticky="ew", padx=(18, 0))

        queue_frame = ttk.Frame(result_area, style="Panel.TFrame")
        queue_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        queue_frame.rowconfigure(1, weight=1)
        queue_frame.columnconfigure(0, weight=1)
        ttk.Label(queue_frame, text="处理队列", style="PanelTitle.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self.result_tree = ttk.Treeview(
            queue_frame,
            columns=("status", "title", "duration"),
            show="headings",
            height=10,
            selectmode="browse",
        )
        self.result_tree.heading("status", text="状态")
        self.result_tree.heading("title", text="视频")
        self.result_tree.heading("duration", text="耗时")
        self.result_tree.column("status", width=62, minwidth=56, anchor="center", stretch=False)
        self.result_tree.column("title", width=230, minwidth=160, anchor="w")
        self.result_tree.column("duration", width=58, minwidth=52, anchor="center", stretch=False)
        tree_scroll = ttk.Scrollbar(queue_frame, orient="vertical", command=self.result_tree.yview)
        self.result_tree.configure(yscrollcommand=tree_scroll.set)
        self.result_tree.grid(row=1, column=0, sticky="nsew")
        tree_scroll.grid(row=1, column=1, sticky="ns")
        self.result_tree.bind("<<TreeviewSelect>>", self._show_selected)

        detail_frame = ttk.Frame(result_area, style="Panel.TFrame")
        detail_frame.grid(row=1, column=1, sticky="nsew")
        detail_frame.rowconfigure(0, weight=1)
        detail_frame.columnconfigure(0, weight=1)
        self.detail_tabs = ttk.Notebook(detail_frame)
        self.detail_tabs.grid(row=0, column=0, sticky="nsew")
        self.report_text = self._make_readonly_text(self.detail_tabs, bg="#FFFFFF", fg=COLORS["text"])
        self.transcript_text = self._make_readonly_text(
            self.detail_tabs, bg="#FFFFFF", fg=COLORS["text"]
        )
        self.detail_tabs.add(self.report_text, text="结构化分析")
        self.detail_tabs.add(self.transcript_text, text="原始口播")

        log_panel = ttk.Frame(workspace, style="Panel.TFrame", padding=(10, 8))
        log_panel.rowconfigure(1, weight=1)
        log_panel.columnconfigure(0, weight=1)
        workspace.add(log_panel, weight=2)
        log_header = ttk.Frame(log_panel, style="Panel.TFrame")
        log_header.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        log_header.columnconfigure(0, weight=1)
        ttk.Label(log_header, text="运行日志", style="PanelTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            log_header,
            text="不会记录或上传链接与口播内容",
            style="PanelMuted.TLabel",
        ).grid(row=0, column=1, sticky="e")
        self.log_text = ScrolledText(
            log_panel,
            height=7,
            wrap="word",
            state="disabled",
            relief="flat",
            borderwidth=0,
            bg=COLORS["log"],
            fg=COLORS["log_text"],
            insertbackground=COLORS["log_text"],
            padx=10,
            pady=7,
            font=("Consolas", 9),
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")

        footer = ttk.Frame(outer)
        footer.grid(row=4, column=0, sticky="ew", pady=(9, 0))
        ttk.Label(
            footer,
            text=f"结果自动保存到：{self.paths.output_root}",
            style="Subtitle.TLabel",
        ).pack(side="left")
        ttk.Label(
            footer,
            text="仅处理你有权访问和使用的公开内容",
            style="Subtitle.TLabel",
        ).pack(side="right")

    @staticmethod
    def _make_readonly_text(parent: tk.Misc, *, bg: str, fg: str) -> ScrolledText:
        widget = ScrolledText(
            parent,
            wrap="word",
            state="disabled",
            relief="flat",
            borderwidth=0,
            bg=bg,
            fg=fg,
            padx=14,
            pady=12,
            font=("Microsoft YaHei UI", 10),
        )
        return widget

    def _center_window(self) -> None:
        self.root.update_idletasks()
        width = max(self.root.winfo_width(), 980)
        height = max(self.root.winfo_height(), 680)
        x = max(0, (self.root.winfo_screenwidth() - width) // 2)
        y = max(0, (self.root.winfo_screenheight() - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _paste(self) -> None:
        try:
            value = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("提示", "剪贴板中没有可粘贴的文字。", parent=self.root)
            return
        self.link_text.delete("1.0", "end")
        self.link_text.insert("1.0", value.strip())
        self.link_text.focus_set()

    def _start(self) -> None:
        if self.running:
            return
        link_text = self.link_text.get("1.0", "end").strip()
        mode = MODE_LABEL_TO_VALUE[self.mode_var.get()]
        try:
            parse_link(link_text, mode)
            limit = min(100, max(1, int(self.limit_var.get())))
        except (InvalidLinkError, AnalyzerError) as exc:
            messagebox.showwarning("链接有误", exc.user_message, parent=self.root)
            self.link_text.focus_set()
            return
        except (TypeError, ValueError):
            messagebox.showwarning("设置有误", "批量上限必须是 1—100 的整数。", parent=self.root)
            return

        self._clear_results()
        self._last_progress_log = None
        self.media_extractor.browser_fallback = (
            self.browser_resolver if self.compat_var.get() else None
        )
        self.running = True
        self.cancel_token = CancelToken()
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.paste_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.status_var.set("正在启动解析任务……")
        self._append_log("任务已开始。", "info")

        self.worker = threading.Thread(
            target=self._run_worker,
            args=(link_text, mode, limit, self.cancel_token),
            name="analyzer-worker",
            daemon=True,
        )
        self.worker.start()

    def _run_worker(
        self,
        link_text: str,
        mode: LinkType,
        limit: int,
        token: CancelToken,
    ) -> None:
        try:
            results = self.pipeline.run(
                link_text,
                mode=mode,
                limit=limit,
                callback=lambda event: self.events.put(("progress", event)),
                cancel_token=token,
            )
            self.events.put(("done", results))
        except CancelledError as exc:
            self.events.put(("cancelled", exc))
        except AnalyzerError as exc:
            self.events.put(("error", exc))
        except Exception:
            self.events.put(("error", AnalyzerError("发生未预期错误，任务已安全停止。")))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    self._handle_progress(payload)
                elif kind == "done":
                    self._handle_done(payload)
                elif kind == "cancelled":
                    self._handle_cancelled()
                elif kind == "error":
                    self._handle_error(payload)
        except queue.Empty:
            pass
        finally:
            if self.root.winfo_exists():
                self.root.after(100, self._drain_events)

    def _handle_progress(self, event: ProgressEvent) -> None:
        self.status_var.set(event.message)
        if event.fraction is not None:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=max(0, min(100, event.fraction * 100)))
        level = "error" if event.stage == "error" else "warning" if event.stage in {"skip", "warning"} else "success" if event.stage == "success" else "info"
        progress_key = (event.stage, event.message)
        if progress_key != self._last_progress_log or event.stage in {"success", "skip", "error", "warning"}:
            self._append_log(event.message, level)
            self._last_progress_log = progress_key

    def _handle_done(self, results: list[JobResult]) -> None:
        self.results = results
        self._populate_results()
        success = sum(result.status == JobStatus.SUCCESS for result in results)
        skipped = sum(result.status == JobStatus.SKIPPED for result in results)
        failed = sum(result.status == JobStatus.FAILED for result in results)
        self.status_var.set(f"任务完成：成功 {success}，跳过 {skipped}，失败 {failed}")
        self.progress.stop()
        self.progress.configure(mode="determinate", value=100)
        self._append_log(
            f"任务结束：共 {len(results)} 个，成功 {success}，跳过 {skipped}，失败 {failed}。",
            "success" if success else "warning",
        )
        self._set_idle()
        if success:
            messagebox.showinfo(
                "解析完成",
                f"已完成 {success} 个视频，TXT 和 Markdown 结果已自动保存。",
                parent=self.root,
            )
        elif results:
            messagebox.showwarning(
                "没有成功结果",
                "本次内容均被跳过或解析失败，请查看运行日志中的原因。",
                parent=self.root,
            )

    def _handle_cancelled(self) -> None:
        self.status_var.set("任务已取消")
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self._append_log("任务已取消，临时文件已清理。", "warning")
        self._set_idle()

    def _handle_error(self, error: AnalyzerError) -> None:
        self.status_var.set("任务失败")
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self._append_log(error.user_message, "error")
        self._set_idle()
        messagebox.showerror("解析失败", error.user_message, parent=self.root)

    def _set_idle(self) -> None:
        self.running = False
        self.cancel_token = None
        self.start_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.paste_button.configure(state="normal")
        self.export_button.configure(
            state="normal" if any(r.status == JobStatus.SUCCESS for r in self.results) else "disabled"
        )

    def _cancel(self) -> None:
        if self.cancel_token:
            self.cancel_token.cancel()
            self.cancel_button.configure(state="disabled")
            self.status_var.set("正在安全停止任务……")
            self._append_log("已收到取消请求，正在结束当前步骤。", "warning")

    def _populate_results(self) -> None:
        self.row_to_result.clear()
        for row in self.result_tree.get_children():
            self.result_tree.delete(row)
        first_success: str | None = None
        first_row: str | None = None
        for result in self.results:
            status = {
                JobStatus.SUCCESS: "成功",
                JobStatus.SKIPPED: "跳过",
                JobStatus.FAILED: "失败",
            }[result.status]
            row = self.result_tree.insert(
                "",
                "end",
                values=(status, result.item.title, f"{result.elapsed_seconds:.1f}s"),
            )
            self.row_to_result[row] = result
            first_row = first_row or row
            if result.status == JobStatus.SUCCESS and first_success is None:
                first_success = row
        selected = first_success or first_row
        if selected:
            self.result_tree.selection_set(selected)
            self.result_tree.focus(selected)
            self.result_tree.see(selected)
            self._show_selected()

    def _show_selected(self, _event: tk.Event[Any] | None = None) -> None:
        selection = self.result_tree.selection()
        if not selection:
            return
        result = self.row_to_result.get(selection[0])
        if not result:
            return
        if result.status == JobStatus.SUCCESS and result.report and result.transcript:
            self._replace_text(self.report_text, result.report.to_markdown())
            self._replace_text(self.transcript_text, result.transcript.text)
            self.export_button.configure(state="normal")
        else:
            self._replace_text(self.report_text, f"处理结果：{result.message}")
            self._replace_text(self.transcript_text, "没有可显示的原始口播。")
            self.export_button.configure(state="disabled")

    @staticmethod
    def _replace_text(widget: ScrolledText, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")
        widget.yview_moveto(0)

    def _selected_result(self) -> JobResult | None:
        selection = self.result_tree.selection()
        if not selection:
            return None
        return self.row_to_result.get(selection[0])

    def _save_selected(self) -> None:
        result = self._selected_result()
        if not result or result.status != JobStatus.SUCCESS or not result.exports:
            messagebox.showinfo("提示", "请先选择一个解析成功的结果。", parent=self.root)
            return
        destination = filedialog.askdirectory(title="选择另存目录", parent=self.root)
        if not destination:
            return
        target_dir = Path(destination)
        try:
            for source in (result.exports.transcript_path, result.exports.report_path):
                target = target_dir / source.name
                if target.exists():
                    target = target_dir / f"{safe_filename(source.stem)}_{datetime.now():%H%M%S}{source.suffix}"
                shutil.copy2(source, target)
        except OSError:
            messagebox.showerror("保存失败", "无法写入所选目录，请检查权限或磁盘空间。", parent=self.root)
            return
        messagebox.showinfo("保存完成", "原始文案和分析报告已另存。", parent=self.root)

    def _open_output(self) -> None:
        self.paths.output_root.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(self.paths.output_root)  # type: ignore[attr-defined]
            elif sys_platform() == "darwin":
                subprocess.Popen(["open", str(self.paths.output_root)])
            else:
                subprocess.Popen(["xdg-open", str(self.paths.output_root)])
        except OSError:
            messagebox.showinfo(
                "导出目录",
                str(self.paths.output_root),
                parent=self.root,
            )

    def _clear_results(self) -> None:
        if self.running:
            return
        self.results.clear()
        self.row_to_result.clear()
        for row in self.result_tree.get_children():
            self.result_tree.delete(row)
        self._replace_text(self.report_text, "")
        self._replace_text(self.transcript_text, "")
        self.export_button.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _append_log(self, message: str, level: str = "info") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "info": "INFO",
            "success": " OK ",
            "warning": "WARN",
            "error": "ERR ",
        }.get(level, "INFO")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {prefix}  {message}\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _on_close(self) -> None:
        if self.running:
            if not messagebox.askyesno(
                "确认退出",
                "任务仍在运行。退出会取消任务并清理临时文件，是否继续？",
                parent=self.root,
            ):
                return
            if self.cancel_token:
                self.cancel_token.cancel()
        self.root.destroy()


def sys_platform() -> str:
    import sys

    return sys.platform


def close_packaged_splash() -> None:
    try:
        import pyi_splash

        pyi_splash.close()
    except (ImportError, RuntimeError):
        pass


def run_app() -> None:
    root = tk.Tk()
    AnalyzerApp(root)
    close_packaged_splash()
    root.mainloop()
