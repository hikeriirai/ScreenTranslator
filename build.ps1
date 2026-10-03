param(
    [string]$Python = ".venv\Scripts\python.exe",
    [string]$InnoCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$PythonPath = if ([System.IO.Path]::IsPathRooted($Python)) {
    $Python
} else {
    Join-Path $Root $Python
}
$Python = [System.IO.Path]::GetFullPath($PythonPath)
$InnoCompiler = [System.IO.Path]::GetFullPath($InnoCompiler)
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Project Python was not found: $Python. Create .venv and install requirements.txt first."
}
if (-not (Test-Path -LiteralPath $InnoCompiler -PathType Leaf)) {
    throw "Inno Setup 6 compiler was not found: $InnoCompiler"
}

$EasyOcrSource = Join-Path $env:USERPROFILE ".EasyOCR\model"
$ArgosSource = (& $Python -c "import argostranslate.settings as s; print(s.package_data_dir)")
if ($LASTEXITCODE -ne 0) {
    throw "Could not locate installed Argos model packages."
}
if (-not (Test-Path -LiteralPath $EasyOcrSource -PathType Container)) {
    throw "EasyOCR model cache not found: $EasyOcrSource"
}
if (-not (Test-Path -LiteralPath $ArgosSource -PathType Container)) {
    throw "Argos model package directory not found: $ArgosSource"
}

$RequiredOcrModels = @("craft_mlt_25k.pth", "english_g2.pth", "japanese_g2.pth")
foreach ($Model in $RequiredOcrModels) {
    if (-not (Test-Path -LiteralPath (Join-Path $EasyOcrSource $Model) -PathType Leaf)) {
        throw "Required EasyOCR model missing: $(Join-Path $EasyOcrSource $Model)"
    }
}

$ArgosSelections = @(
    @{ From = "ja"; To = "en" },
    @{ From = "en"; To = "ru" }
)
$SelectedArgos = @()
foreach ($Selection in $ArgosSelections) {
    $Match = $null
    foreach ($Directory in Get-ChildItem -LiteralPath $ArgosSource -Directory) {
        $MetadataPath = Join-Path $Directory.FullName "metadata.json"
        if (Test-Path -LiteralPath $MetadataPath -PathType Leaf) {
            $Metadata = Get-Content -LiteralPath $MetadataPath -Raw | ConvertFrom-Json
            if ($Metadata.from_code -eq $Selection.From -and $Metadata.to_code -eq $Selection.To) {
                $Match = $Directory
                break
            }
        }
    }
    if ($null -eq $Match) {
        throw "Installed Argos package $($Selection.From) → $($Selection.To) was not found in $ArgosSource"
    }
    $SelectedArgos += $Match
}

$Stage = Join-Path $Root "build\model-stage"
$StageOcr = Join-Path $Stage "easyocr"
$StageArgos = Join-Path $Stage "argos"
$AppOutput = Join-Path $Root "dist\ScreenTranslator"
$InstallerOutput = Join-Path $Root "dist\ScreenTranslator-Setup.exe"
$SmokeInstall = Join-Path $Root "build\installer-smoke"
foreach ($Path in @($Stage, $AppOutput, $InstallerOutput, $SmokeInstall)) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}
New-Item -ItemType Directory -Force -Path $StageOcr, $StageArgos | Out-Null
foreach ($Model in $RequiredOcrModels) {
    Copy-Item -LiteralPath (Join-Path $EasyOcrSource $Model) -Destination $StageOcr
}
foreach ($Package in $SelectedArgos) {
    Copy-Item -LiteralPath $Package.FullName -Destination $StageArgos -Recurse
}

& $Python -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) {
    throw "Installing the PyInstaller build dependency failed."
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name ScreenTranslator `
    --collect-all easyocr `
    --collect-all argostranslate `
    --collect-all ctranslate2 `
    --collect-all cv2 `
    --collect-all torchvision `
    --hidden-import keyboard `
    --hidden-import mss `
    main.py
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$AppModels = Join-Path $AppOutput "models"
New-Item -ItemType Directory -Force -Path $AppModels | Out-Null
Copy-Item -LiteralPath $StageOcr -Destination (Join-Path $AppModels "easyocr") -Recurse
Copy-Item -LiteralPath $StageArgos -Destination (Join-Path $AppModels "argos") -Recurse
Copy-Item -LiteralPath (Join-Path $Root "THIRD-PARTY-NOTICES.txt") -Destination $AppOutput

$AppExecutable = Join-Path $AppOutput "ScreenTranslator.exe"
& $AppExecutable --self-test
if ($LASTEXITCODE -ne 0) {
    throw "Packaged application self-test failed."
}

& $InnoCompiler (Join-Path $Root "installer.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compilation failed."
}

$Installer = $InstallerOutput
$SmokeExe = Join-Path $SmokeInstall "ScreenTranslator.exe"
$InstallerProcess = Start-Process `
    -FilePath $Installer `
    -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=$SmokeInstall") `
    -PassThru `
    -Wait
if ($InstallerProcess.ExitCode -ne 0) {
    throw "Silent installer exited with code $($InstallerProcess.ExitCode)."
}
if (-not (Test-Path -LiteralPath $SmokeExe -PathType Leaf)) {
    throw "Silent installer did not create the expected application executable."
}
& $SmokeExe --self-test
if ($LASTEXITCODE -ne 0) {
    throw "Installed application self-test failed."
}

Write-Host "Installer build and installed-app smoke test succeeded:"
Write-Host "  $Installer"
Write-Host "  $([math]::Round((Get-Item -LiteralPath $Installer).Length / 1MB)) MB"
