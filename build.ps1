param(
    [string]$Python = "",
    [string]$Compiler = ""
)

$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    if (!$Python) {
        $Python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
        if (!(Test-Path -LiteralPath $Python)) {
            py -3.13 -m venv .venv
            if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
        }
        & $Python -m pip install -r requirements.txt 'pyinstaller==6.12.0' 'pyinstaller-hooks-contrib==2025.1'
        if ($LASTEXITCODE -ne 0) { throw 'Could not install the build dependencies.' }
    }
    if (!$Compiler) {
        $Compiler = @(
            (Join-Path $env:LOCALAPPDATA 'Programs/Inno Setup 6/ISCC.exe'),
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe')
        ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (!$Compiler) { $Compiler = (Get-Command ISCC.exe -ErrorAction Stop).Source }
    }
    $versionMatch = [regex]::Match((Get-Content -Raw -Encoding utf8 -LiteralPath 'main.py'), '(?m)^VERSION = "(\d+\.\d+\.\d+)"')
    if (!$versionMatch.Success) { throw 'Could not read the application version from main.py.' }
    $appVersion = $versionMatch.Groups[1].Value

    & $Python -m PyInstaller --noconfirm --clean --windowed --name LocalPDF --icon assets/app.ico `
        --add-data 'assets;assets' --collect-submodules fontTools.ttLib.tables `
        --exclude-module PyQt5 --exclude-module matplotlib --exclude-module scipy --exclude-module numpy `
        --exclude-module IPython --exclude-module tkinter main.py
    if ($LASTEXITCODE -ne 0) { throw 'Application packaging failed.' }

    New-Item -ItemType Directory -Force -Path 'dist/licenses' | Out-Null
    @'
from importlib.metadata import distribution
from pathlib import Path
from shutil import copyfile
import sys

out = Path('dist/licenses')
for name in ('PyMuPDF', 'fonttools', 'PyInstaller'):
    info = distribution(name)
    license_file = next(file for file in info.files if file.name.startswith(('LICENSE', 'COPYING')))
    copyfile(info.locate_file(license_file), out / f'{name}.txt')
copyfile(Path(sys.base_prefix) / 'LICENSE.txt', out / 'Python.txt')
'@ | & $Python -
    if ($LASTEXITCODE -ne 0) { throw 'Could not collect dependency licenses.' }
    foreach ($qtLicense in 'GPL-3.0-only', 'LGPL-3.0-only') {
        $destination = Join-Path 'dist/licenses' "Qt-$qtLicense.txt"
        if (!(Test-Path -LiteralPath $destination)) {
            Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/qt/qtbase/v6.11.1/LICENSES/$qtLicense.txt" -OutFile $destination
        }
    }

    & $Compiler "/DAppVersion=$appVersion" 'installer/LocalPDF.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Installer packaging failed.' }
} finally {
    Pop-Location
}
