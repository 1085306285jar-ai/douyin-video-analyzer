$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

Write-Host "[1/7] Checking 64-bit Python 3.12..."
if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonLauncher = "py"
    $PythonArgs = @("-3.12")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonLauncher = "python"
    $PythonArgs = @()
} else {
    throw "Python 3.12 was not found. This is required only on the build computer."
}

& $PythonLauncher @PythonArgs -c "import struct,sys; assert sys.version_info[:2] == (3,12), sys.version; assert struct.calcsize('P') == 8, '64-bit Python required'"
if ($LASTEXITCODE -ne 0) { throw "Python version check failed with exit code $LASTEXITCODE." }

$VenvDir = Join-Path $ProjectRoot ".build-venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    & $PythonLauncher @PythonArgs -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed with exit code $LASTEXITCODE." }
}

Write-Host "[2/7] Installing pinned build dependencies..."
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed with exit code $LASTEXITCODE." }
& $VenvPython -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed with exit code $LASTEXITCODE." }

Write-Host "[3/7] Preparing visual assets and the embedded offline model..."
& $VenvPython scripts\generate_assets.py
if ($LASTEXITCODE -ne 0) { throw "Visual asset generation failed with exit code $LASTEXITCODE." }
& $VenvPython scripts\prepare_model.py
if ($LASTEXITCODE -ne 0) { throw "Offline model preparation failed with exit code $LASTEXITCODE." }

Write-Host "[4/7] Running automated tests..."
$env:PYTHONPATH = (Join-Path $ProjectRoot "src")
& $VenvPython -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Automated tests failed with exit code $LASTEXITCODE." }

Write-Host "[5/7] Cleaning prior build output..."
$BuildDir = Join-Path $ProjectRoot "build\pyinstaller"
$DistDir = Join-Path $ProjectRoot "dist"
if (Test-Path $BuildDir) { Remove-Item -Recurse -Force $BuildDir }
if (Test-Path $DistDir) { Remove-Item -Recurse -Force $DistDir }

Write-Host "[6/7] Building the Windows one-file executable..."
& $VenvPython -m PyInstaller --noconfirm --clean --workpath $BuildDir --distpath $DistDir DouyinAnalyzer.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE." }

$ExePath = Join-Path $DistDir "抖音视频AI解析工具.exe"
if (-not (Test-Path $ExePath)) {
    throw "Build finished without the expected EXE."
}

Write-Host "[7/7] Running packaged startup verification..."
$ReportPath = Join-Path $env:TEMP "douyin_analyzer_self_test.json"
if (Test-Path $ReportPath) { Remove-Item -Force $ReportPath }
$Process = Start-Process -FilePath $ExePath -ArgumentList @("--self-test", "--report", $ReportPath) -Wait -PassThru
if ($Process.ExitCode -ne 0 -or -not (Test-Path $ReportPath)) {
    throw "The packaged EXE failed its startup self-test."
}
$Report = Get-Content $ReportPath -Raw | ConvertFrom-Json
if (-not $Report.ok) {
    throw "The packaged EXE reported a missing component."
}
Remove-Item -Force $ReportPath

$UiReportPath = Join-Path $env:TEMP "douyin_analyzer_ui_smoke.json"
if (Test-Path $UiReportPath) { Remove-Item -Force $UiReportPath }
$UiProcess = Start-Process -FilePath $ExePath -ArgumentList @("--ui-smoke", "--report", $UiReportPath) -Wait -PassThru
if ($UiProcess.ExitCode -ne 0 -or -not (Test-Path $UiReportPath)) {
    throw "The packaged EXE failed its GUI smoke test."
}
$UiReport = Get-Content $UiReportPath -Raw | ConvertFrom-Json
if (-not $UiReport.ok) {
    throw "The packaged EXE could not construct the main window: $($UiReport.detail)"
}
Remove-Item -Force $UiReportPath
$SelfTestOutput = Join-Path $DistDir "output"
if (Test-Path $SelfTestOutput) { Remove-Item -Recurse -Force $SelfTestOutput }

$Hash = (Get-FileHash -Algorithm SHA256 $ExePath).Hash
Write-Host ""
Write-Host "BUILD PASSED" -ForegroundColor Green
Write-Host "EXE: $ExePath"
Write-Host "SHA256: $Hash"
