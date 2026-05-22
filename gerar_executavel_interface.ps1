param(
    [string]$PythonExe = ".\\venv\\Scripts\\python.exe",
    [string]$DistDir = ".\\dist-interface",
    [string]$ExeName = "promos_interface"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Push-Location $PSScriptRoot

try {
    if (-not (Test-Path $PythonExe)) {
        throw "Python nao encontrado em '$PythonExe'. Ajuste o parametro -PythonExe."
    }

    $workDir = Join-Path $PSScriptRoot ".build\\pyinstaller-work-interface"
    $specDir = Join-Path $PSScriptRoot ".build\\spec-interface"

    New-Item -ItemType Directory -Path $workDir -Force | Out-Null
    New-Item -ItemType Directory -Path $specDir -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot $DistDir) -Force | Out-Null

    Write-Host "Gerando $ExeName.exe..." -ForegroundColor Cyan

    $pyinstallerArgs = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--noconsole",
        "--clean",
        "--name", $ExeName,
        "--distpath", $DistDir,
        "--workpath", $workDir,
        "--specpath", $specDir,
        "--collect-all", "playwright",
        "--hidden-import", "main",
        "--hidden-import", "parsers.mercadolivre",
        ".\\gui_promos.py"
    )

    & $PythonExe @pyinstallerArgs

    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao gerar o executavel da interface."
    }

    Write-Host "Concluido. Executavel gerado em '$DistDir\\$ExeName.exe'." -ForegroundColor Green
}
finally {
    Pop-Location
}
