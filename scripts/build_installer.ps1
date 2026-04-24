param(
    [switch]$Clean,
    [switch]$IncludeOfflineChromium
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

function Resolve-InnoCompilerPath {
    param(
        [string]$ProjectRoot
    )

    $compilerPath = Join-Path $ProjectRoot "tools\inno\ISCC.exe"
    if (Test-Path $compilerPath) {
        return $compilerPath
    }

    throw "Inno Setup compiler not found at tools\inno\ISCC.exe."
}

function Assert-PyInstallerAvailable {
    try {
        python -m PyInstaller --version | Out-Null
    }
    catch {
        throw "PyInstaller is not available. Run: python -m pip install -r requirements-build.txt"
    }
}

function Resolve-OfflineRuntimeSource {
    param(
        [string]$ProjectRoot
    )

    $runtimePath = Join-Path $ProjectRoot "ms-playwright"
    if (-not (Test-Path $runtimePath)) {
        throw "Offline browser runtime not found. Prepare ms-playwright in the project root first."
    }
    return $runtimePath
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$distRoot = Join-Path $projectRoot "dist"
$installerSourceRoot = Join-Path $projectRoot "build\installer-source"
$appName = "小程序工具"
$installerSourceDir = Join-Path $installerSourceRoot $appName
$installerExeName = "$appName.exe"
$outputBaseFilename = if ($IncludeOfflineChromium) { "$appName-离线版" } else { "$appName-标准版" }
$innoCompiler = Resolve-InnoCompilerPath -ProjectRoot $projectRoot
Assert-PyInstallerAvailable
$offlineRuntimeSource = if ($IncludeOfflineChromium) {
    Resolve-OfflineRuntimeSource -ProjectRoot $projectRoot
} else {
    ""
}

$installerScript = if ($Clean) {
    Join-Path $PSScriptRoot "installer_clean.iss"
} else {
    throw "Only clean installer builds are supported. Pass -Clean."
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

    Write-Host "Building installer package..."
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

    if ($IncludeOfflineChromium) {
        $offlineRuntimeTarget = Join-Path $installerSourceDir "ms-playwright"
        Copy-Item -LiteralPath $offlineRuntimeSource -Destination $offlineRuntimeTarget -Recurse -Force
    }

    & $innoCompiler "/DMySourceDir=$installerSourceDir" "/DMyAppExeName=$installerExeName" "/DMyOutputBaseFilename=$outputBaseFilename" $installerScript
    if (Test-Path $installerSourceRoot) {
        Remove-Item -LiteralPath $installerSourceRoot -Recurse -Force
    }

    Write-Host "Installer build complete: $(Join-Path $distRoot "installer\$outputBaseFilename.exe")"
}
finally {
    Pop-Location
}

