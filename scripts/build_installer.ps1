param(
    [switch]$Clean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Utf8NoBomFile {
    param(
        [string]$Path,
        [string]$Content
    )

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$distRoot = Join-Path $projectRoot "dist"
$installerSourceRoot = Join-Path $projectRoot "build\installer-source"
$appName = "小程序工具"
$installerSourceDir = Join-Path $installerSourceRoot $appName
$installerExeName = "$appName.exe"
$innoCompiler = $null
foreach ($candidate in @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)) {
    if (Test-Path $candidate) {
        $innoCompiler = $candidate
        break
    }
}

if (-not $innoCompiler) {
    throw "未找到 Inno Setup 编译器，请先安装 Inno Setup 6。"
}

$installerScript = if ($Clean) {
    Join-Path $PSScriptRoot "installer_clean.iss"
} else {
    throw "当前仅支持基于干净源目录构建安装包，请传入 -Clean。"
}

Push-Location $projectRoot
try {
    if (-not (Test-Path $distRoot)) {
        New-Item -ItemType Directory -Path $distRoot -Force | Out-Null
    }
    if (Test-Path $installerSourceRoot) {
        Remove-Item -LiteralPath $installerSourceRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $installerSourceRoot -Force | Out-Null

    Write-Host "开始构建安装包..."
    python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --distpath $installerSourceRoot `
        --workpath (Join-Path $projectRoot "build\pyinstaller") `
        --specpath $installerSourceRoot `
        --name $appName `
        --collect-all playwright `
        desktop_main.py

    foreach ($name in @(
        "_internal\playwright\driver\package\.local-browsers",
        "_internal\playwright\driver\package\.links"
    )) {
        $target = Join-Path $installerSourceDir $name
        if (Test-Path $target) {
            Remove-Item -LiteralPath $target -Recurse -Force
        }
    }

    foreach ($name in @("data", "storage", "browser_profile", "output")) {
        $target = Join-Path $installerSourceDir $name
        New-Item -ItemType Directory -Path $target -Force | Out-Null
    }

    Write-Utf8NoBomFile -Path (Join-Path $installerSourceDir "data\accounts.json") -Content "[]`n"
    Write-Utf8NoBomFile -Path (Join-Path $installerSourceDir "data\settings.json") -Content @'
{
  "feishu_webhook": "",
  "login_wait_seconds": 120,
  "headless_fetch": true,
  "browser_profile_dir": "",
  "current_main_account_name": "",
  "auto_fetch_push_enabled": false
}
'@

    foreach ($name in @("README.md", "requirements.txt")) {
        $source = Join-Path $projectRoot $name
        if (Test-Path $source) {
            Copy-Item -LiteralPath $source -Destination $installerSourceDir -Force
        }
    }

    & $innoCompiler "/DMySourceDir=$installerSourceDir" "/DMyAppExeName=$installerExeName" $installerScript
    if (Test-Path $installerSourceRoot) {
        Remove-Item -LiteralPath $installerSourceRoot -Recurse -Force
    }
    Write-Host "安装包构建完成：$(Join-Path $distRoot 'installer\小程序工具安装包.exe')"
}
finally {
    Pop-Location
}
