# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.building.datastruct import Tree
from PyInstaller.building.splash import Splash
from PyInstaller.utils.hooks import collect_all, collect_submodules


ROOT = Path(SPEC).resolve().parent
datas = []
binaries = []
hiddenimports = ["tkinter", "tkinter.ttk", "tkinter.scrolledtext"]

for package in (
    "yt_dlp",
    "faster_whisper",
    "ctranslate2",
    "av",
    "tokenizers",
    "huggingface_hub",
    "onnxruntime",
    "playwright",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

hiddenimports += collect_submodules("yt_dlp.extractor")
datas += Tree(str(ROOT / "model" / "faster-whisper-base"), prefix="model/faster-whisper-base")
datas += Tree(str(ROOT / "assets"), prefix="assets")

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT), str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "tensorflow", "matplotlib", "pandas", "scipy"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

splash = Splash(
    str(ROOT / "assets" / "splash.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(56, 402),
    text_size=11,
    text_color="#CFE0FF",
    text_default="正在解压本地 AI 组件，请稍候……",
    always_on_top=True,
    center="active",
)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    a.binaries,
    a.datas,
    [],
    name="抖音视频AI解析工具",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "app.ico"),
    version=str(ROOT / "build" / "version_info.txt"),
    uac_admin=False,
)
