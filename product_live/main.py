"""商品图转动态视频 - Windows desktop application.

This program intentionally creates presentation motion from the original photo;
it never uses generative AI to alter product condition, lettering or details.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Queue, Empty
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, filedialog, messagebox, ttk
import tkinter as tk

try:
    from PIL import Image, ImageOps
except ImportError as exc:  # pragma: no cover
    raise SystemExit("缺少图片处理组件，请使用完整发布版。") from exc


APP_NAME = "商品图转动态视频"
SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def app_root() -> Path:
    """Works both in source mode and in a PyInstaller one-folder package."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_ffmpeg() -> str | None:
    root = app_root()
    names = ("ffmpeg.exe", "ffmpeg")
    places = [root, root / "resources", root / "_internal", root / "_internal" / "resources"]
    for folder in places:
        for name in names:
            candidate = folder / name
            if candidate.exists():
                return str(candidate)
    return shutil.which("ffmpeg")


def find_live_engine() -> str | None:
    """Locate the MIT-licensed LivePhotoConvert native helper when bundled."""
    root = app_root()
    candidates = (
        root / "resources" / "engine" / "LivePhotoConvert.exe",
        root / "resources" / "LivePhotoConvert.exe",
        root / "LivePhotoConvert.exe",
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def run_silently(command: list[str]) -> None:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "实况照片转换引擎执行失败")


@dataclass(frozen=True)
class RenderOptions:
    effect: str
    ratio: str
    seconds: int
    quality: str
    output_kind: str

    @property
    def dimensions(self) -> tuple[int, int] | None:
        return {
            "原图比例": None,
            "小红书 3:4": (1080, 1440),
            "闲鱼 1:1": (1080, 1080),
            "竖版 9:16": (1080, 1920),
        }[self.ratio]

    @property
    def crf(self) -> str:
        return {"高清": "17", "标准": "21", "省空间": "25"}[self.quality]


def normalized_image(source: Path, destination: Path, dimensions: tuple[int, int] | None) -> None:
    """Create a high-quality JPEG canvas with no product-generating edits."""
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        if dimensions:
            canvas_w, canvas_h = dimensions
            # Crop minimally from the center; the preview explains this clearly.
            source_ratio = image.width / image.height
            target_ratio = canvas_w / canvas_h
            if source_ratio > target_ratio:
                new_width = int(image.height * target_ratio)
                left = (image.width - new_width) // 2
                image = image.crop((left, 0, left + new_width, image.height))
            else:
                new_height = int(image.width / target_ratio)
                top = (image.height - new_height) // 2
                image = image.crop((0, top, image.width, top + new_height))
            image = image.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)
        else:
            longest = max(image.size)
            if longest > 2160:
                scale = 2160 / longest
                image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
        image.save(destination, "JPEG", quality=96, subsampling=0)


def motion_filter(effect: str, fps: int, frames: int, width: int, height: int) -> str:
    # Zoompan creates optical camera movement while every pixel remains sourced
    # from the user's original photograph.
    if effect == "缓慢推进":
        zoom = "min(zoom+0.00055,1.10)"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif effect == "轻微拉远":
        zoom = "if(eq(on,0),1.10,max(1.0,zoom-0.00055))"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif effect == "从左到右":
        zoom = "1.07"
        x, y = "(iw-iw/zoom)*on/%d" % max(frames - 1, 1), "ih/2-(ih/zoom/2)"
    else:  # 从右到左
        zoom = "1.07"
        x, y = "(iw-iw/zoom)*(1-on/%d)" % max(frames - 1, 1), "ih/2-(ih/zoom/2)"
    return f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},format=yuv420p"


def output_name(path: Path, output_dir: Path, effect: str) -> Path:
    safe_effect = {"缓慢推进": "推进", "轻微拉远": "拉远", "从左到右": "左移", "从右到左": "右移"}[effect]
    base = f"{path.stem}_动态_{safe_effect}.mp4"
    candidate = output_dir / base
    number = 2
    while candidate.exists():
        candidate = output_dir / f"{path.stem}_动态_{safe_effect}_{number}.mp4"
        number += 1
    return candidate


def render_one(ffmpeg: str, source: Path, output_dir: Path, options: RenderOptions, workspace: Path) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    prepared = workspace / f"{source.stem}_{int(time.time() * 1000)}.jpg"
    normalized_image(source, prepared, options.dimensions)
    fps = 30
    frames = options.seconds * fps
    # The final scale is done in ffmpeg so all exports use a platform-safe H.264 MP4.
    if options.dimensions:
        width, height = options.dimensions
    else:
        with Image.open(prepared) as prepared_image:
            width = prepared_image.width - (prepared_image.width % 2)
            height = prepared_image.height - (prepared_image.height % 2)
    vf = motion_filter(options.effect, fps, frames, width, height)
    target = output_name(source, output_dir, options.effect)
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-i", str(prepared),
        "-vf", vf, "-frames:v", str(frames), "-c:v", "libx264", "-preset", "medium",
        "-crf", options.crf, "-movflags", "+faststart", "-an", str(target),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    prepared.unlink(missing_ok=True)
    if completed.returncode:
        detail = completed.stderr.strip() or "视频编码器未能启动"
        raise RuntimeError(detail)
    return target


class ProductLiveApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1000x700")
        self.minsize(880, 620)
        self.configure(bg="#111827")
        self.files: list[Path] = []
        self.events: Queue[tuple[str, object]] = Queue()
        self.running = False
        self.output_dir = tk.StringVar(value=str(Path.home() / "Desktop" / "商品动态视频"))
        self.effect = tk.StringVar(value="缓慢推进")
        self.ratio = tk.StringVar(value="小红书 3:4")
        self.seconds = tk.StringVar(value="3")
        self.quality = tk.StringVar(value="高清")
        # V1 creates standards-compliant MP4 files that can be posted directly.
        # Native Apple pairing remains internal until its full offline codec bundle
        # is verified on a physical iPhone.
        self.output_kind = tk.StringVar(value="MP4 动态视频")
        self.status = tk.StringVar(value="添加商品图片后，即可批量生成可发布的 MP4。")
        self._style()
        self._build()
        self.after(100, self._drain_events)

    def _style(self) -> None:
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame", background="#111827")
        s.configure("Panel.TFrame", background="#172033")
        s.configure("TLabel", background="#111827", foreground="#E5E7EB", font=("Microsoft YaHei UI", 10))
        s.configure("Title.TLabel", background="#111827", foreground="#F9FAFB", font=("Microsoft YaHei UI", 22, "bold"))
        s.configure("Hint.TLabel", background="#111827", foreground="#9CA3AF", font=("Microsoft YaHei UI", 10))
        s.configure("Panel.TLabel", background="#172033", foreground="#E5E7EB", font=("Microsoft YaHei UI", 10))
        s.configure("Accent.TButton", padding=(18, 11), background="#F97316", foreground="#FFFFFF", font=("Microsoft YaHei UI", 10, "bold"))
        s.map("Accent.TButton", background=[("active", "#EA580C"), ("disabled", "#6B7280")])
        s.configure("Soft.TButton", padding=(13, 8), background="#273449", foreground="#F3F4F6", font=("Microsoft YaHei UI", 10))
        s.map("Soft.TButton", background=[("active", "#34445E")])
        s.configure("TCombobox", padding=7, fieldbackground="#0F172A", background="#273449", foreground="#F9FAFB")
        s.configure("Horizontal.TProgressbar", troughcolor="#273449", background="#F97316")

    def _build(self) -> None:
        top = ttk.Frame(self, padding=(30, 24, 30, 12))
        top.pack(fill=X)
        ttk.Label(top, text="商品图转动态视频", style="Title.TLabel").pack(anchor="w")
        ttk.Label(top, text="保留原商品细节，只加入自然镜头运动。适合小红书、闲鱼商品展示。", style="Hint.TLabel").pack(anchor="w", pady=(7, 0))

        body = ttk.Frame(self, padding=(30, 4, 30, 12))
        body.pack(fill=BOTH, expand=True)
        left = ttk.Frame(body, style="Panel.TFrame", padding=16)
        left.pack(side=LEFT, fill=BOTH, expand=True)
        right = ttk.Frame(body, style="Panel.TFrame", padding=14)
        right.pack(side=RIGHT, fill=Y, padx=(16, 0))

        row = ttk.Frame(left, style="Panel.TFrame")
        row.pack(fill=X)
        ttk.Label(row, text="待处理图片", style="Panel.TLabel", font=("Microsoft YaHei UI", 12, "bold")).pack(side=LEFT)
        ttk.Button(row, text="添加图片", style="Soft.TButton", command=self.add_files).pack(side=RIGHT)
        ttk.Button(row, text="清空", style="Soft.TButton", command=self.clear_files).pack(side=RIGHT, padx=(0, 8))

        list_frame = tk.Frame(left, bg="#0F172A", highlightthickness=1, highlightbackground="#334155")
        list_frame.pack(fill=BOTH, expand=True, pady=(14, 0))
        self.listbox = tk.Listbox(list_frame, bg="#0F172A", fg="#E5E7EB", selectbackground="#334155", selectforeground="#FFFFFF", borderwidth=0, highlightthickness=0, font=("Microsoft YaHei UI", 10), activestyle="none")
        self.listbox.pack(side=LEFT, fill=BOTH, expand=True, padx=8, pady=8)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        scroll.pack(side=RIGHT, fill=Y)
        self.listbox.configure(yscrollcommand=scroll.set)

        ttk.Label(left, textvariable=self.status, style="Panel.TLabel", wraplength=550).pack(anchor="w", pady=(12, 0))
        self.progress = ttk.Progressbar(left, mode="determinate")
        self.progress.pack(fill=X, pady=(8, 0))

        ttk.Label(right, text="生成设置", style="Panel.TLabel", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        self._field(right, "动态效果", self.effect, ("缓慢推进", "轻微拉远", "从左到右", "从右到左"))
        self._field(right, "发布比例", self.ratio, ("小红书 3:4", "闲鱼 1:1", "竖版 9:16", "原图比例"))
        self._field(right, "视频时长", self.seconds, ("2", "3", "4"))
        self._field(right, "清晰度", self.quality, ("高清", "标准", "省空间"))
        ttk.Label(right, text="输出文件夹", style="Panel.TLabel").pack(anchor="w", pady=(12, 5))
        ttk.Entry(right, textvariable=self.output_dir, width=30).pack(fill=X)
        ttk.Button(right, text="选择文件夹", style="Soft.TButton", command=self.pick_output).pack(anchor="w", pady=(6, 12))
        self.render_button = ttk.Button(right, text="开始批量生成", style="Accent.TButton", command=self.start_render)
        self.render_button.pack(fill=X)
        ttk.Label(right, text="输出标准 MP4，可直接发布。\n商品外观不会被 AI 修改。", style="Panel.TLabel", foreground="#9CA3AF", justify="left").pack(anchor="w", pady=(10, 0))

    def _field(self, parent: ttk.Frame, label: str, value: tk.StringVar, values: tuple[str, ...]) -> None:
        ttk.Label(parent, text=label, style="Panel.TLabel").pack(anchor="w", pady=(11, 4))
        ttk.Combobox(parent, textvariable=value, values=values, state="readonly", width=26).pack(fill=X)

    def add_files(self) -> None:
        selected = filedialog.askopenfilenames(title="选择商品图片", filetypes=[("图片", "*.jpg *.jpeg *.png *.webp *.bmp")])
        added = 0
        known = set(self.files)
        for raw in selected:
            path = Path(raw)
            if path.suffix.lower() in SUPPORTED and path not in known:
                self.files.append(path)
                known.add(path)
                self.listbox.insert(END, path.name)
                added += 1
        self.status.set(f"已添加 {len(self.files)} 张商品图片。" if added else "没有添加新的图片。")

    def clear_files(self) -> None:
        if self.running:
            return
        self.files.clear()
        self.listbox.delete(0, END)
        self.progress["value"] = 0
        self.status.set("添加商品图片后，即可批量生成可发布的 MP4。")

    def pick_output(self) -> None:
        chosen = filedialog.askdirectory(title="选择输出文件夹")
        if chosen:
            self.output_dir.set(chosen)

    def start_render(self) -> None:
        if self.running:
            return
        if not self.files:
            messagebox.showinfo(APP_NAME, "请先添加至少一张商品图片。")
            return
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            messagebox.showerror(APP_NAME, "完整发布版中的视频组件缺失，无法生成 MP4。")
            return
        if self.output_kind.get() == "苹果原生 Live Photo" and not find_live_engine():
            messagebox.showerror(APP_NAME, "完整发布版中的实况照片组件缺失，无法生成苹果原生 Live Photo。")
            return
        try:
            output = Path(self.output_dir.get()).expanduser()
            output.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"无法创建输出文件夹：{exc}")
            return
        self.running = True
        self.render_button.configure(state="disabled")
        self.progress.configure(maximum=len(self.files), value=0)
        options = RenderOptions(self.effect.get(), self.ratio.get(), int(self.seconds.get()), self.quality.get(), self.output_kind.get())
        threading.Thread(target=self._render_worker, args=(ffmpeg, list(self.files), output, options), daemon=True).start()

    def _render_worker(self, ffmpeg: str, files: list[Path], output: Path, options: RenderOptions) -> None:
        workspace = output / ".product_live_temp"
        workspace.mkdir(exist_ok=True)
        completed, failures = [], []
        try:
            if options.output_kind == "MP4 动态视频":
                for index, source in enumerate(files, 1):
                    self.events.put(("status", f"正在生成 {index}/{len(files)}：{source.name}"))
                    try:
                        completed.append(render_one(ffmpeg, source, output, options, workspace))
                    except Exception as exc:  # Each batch item should not stop the rest.
                        failures.append(f"{source.name}：{exc}")
                    self.events.put(("progress", index))
            else:
                completed, failures = self._render_live_photos(ffmpeg, files, output, options, workspace)
        finally:
            try:
                workspace.rmdir()
            except OSError:
                pass
        self.events.put(("done", (completed, failures, output)))

    def _render_live_photos(self, ffmpeg: str, files: list[Path], output: Path, options: RenderOptions, workspace: Path) -> tuple[list[Path], list[str]]:
        """Create motion video first, then delegate Apple pairing metadata to engine."""
        engine = find_live_engine()
        if not engine:
            return [], ["实况照片组件缺失"]
        staging = workspace / "staging"
        motion = workspace / "motion"
        apple = output / "苹果实况照片"
        for folder in (staging, motion, apple):
            folder.mkdir(parents=True, exist_ok=True)
        failures: list[str] = []
        valid_count = 0
        for index, source in enumerate(files, 1):
            self.events.put(("status", f"正在生成动态画面 {index}/{len(files)}：{source.name}"))
            try:
                stem = f"商品实况_{index:03d}"
                staged_image = staging / f"{stem}{source.suffix.lower()}"
                shutil.copy2(source, staged_image)
                created_video = render_one(ffmpeg, staged_image, staging, options, workspace / "frames")
                created_video.replace(staging / f"{stem}.mp4")
                valid_count += 1
            except Exception as exc:
                failures.append(f"{source.name}：{exc}")
            self.events.put(("progress", index))
        if not valid_count:
            return [], failures
        self.events.put(("status", "正在写入苹果实况照片配对信息…"))
        try:
            run_silently([engine, "merge", "-i", str(staging), "-o", str(motion), "--skip-validation", "--yes"])
            run_silently([engine, "split", "-i", str(motion), "-o", str(apple), "-f", "apple", "--yes"])
        except Exception as exc:
            failures.append(f"苹果实况照片配对失败：{exc}")
            return [], failures
        pairs = list(apple.glob("*.HEIC")) + list(apple.glob("*.heic"))
        if not pairs:
            failures.append("没有生成可用的 HEIC + MOV 实况照片配对")
        return pairs, failures

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status":
                    self.status.set(str(payload))
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind == "done":
                    completed, failures, output = payload
                    self.running = False
                    self.render_button.configure(state="normal")
                    if failures:
                        self.status.set(f"完成 {len(completed)} 张；{len(failures)} 张失败。请查看输出文件夹。")
                        messagebox.showwarning(APP_NAME, "部分图片未能生成：\n\n" + "\n".join(failures[:4]))
                    else:
                        self.status.set(f"已完成 {len(completed)} 张，文件已保存到：{output}")
                        messagebox.showinfo(APP_NAME, f"已完成 {len(completed)} 张动态商品视频。\n\n保存位置：\n{output}")
                    if completed:
                        os.startfile(output) if hasattr(os, "startfile") else None
        except Empty:
            pass
        self.after(100, self._drain_events)


if __name__ == "__main__":
    ProductLiveApp().mainloop()
