param(
    [string]$PythonExe = ".\\venv\\Scripts\\python.exe",
    [string]$DistDir = ".\\dist-interface",
    [string]$ExeName = "promos_interface",
    [switch]$ForceCloseRunning
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Stop-TargetProcesses {
    param(
        [string]$ProcessName,
        [string]$TargetPath
    )

    $running = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue
    foreach ($proc in $running) {
        try {
            $procPath = $proc.Path
        }
        catch {
            $procPath = $null
        }

        if ((-not $procPath) -or ($procPath -eq $TargetPath)) {
            Stop-Process -Id $proc.Id -Force -ErrorAction Stop
            Write-Host "Processo em execucao finalizado: PID $($proc.Id)" -ForegroundColor Yellow
        }
    }
}

Push-Location $PSScriptRoot

try {
    if (-not (Test-Path $PythonExe)) {
        throw "Python nao encontrado em '$PythonExe'. Ajuste o parametro -PythonExe."
    }

    $distDirFull = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $DistDir))
    $targetExe = Join-Path $distDirFull ("{0}.exe" -f $ExeName)

    $buildRoot = Join-Path ([System.IO.Path]::GetTempPath()) "promos-pyinstaller-interface"
    $workDir = Join-Path $buildRoot "work"
    $specDir = Join-Path $buildRoot "spec"
    $buildDistDir = Join-Path $buildRoot "dist"
    $tempExeName = "{0}__tmpbuild" -f $ExeName
    $builtExe = Join-Path $buildDistDir ("{0}.exe" -f $tempExeName)

    if (Test-Path $buildRoot) {
        Remove-Item -Path $buildRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $workDir -Force | Out-Null
    New-Item -ItemType Directory -Path $specDir -Force | Out-Null
    New-Item -ItemType Directory -Path $buildDistDir -Force | Out-Null
    New-Item -ItemType Directory -Path $distDirFull -Force | Out-Null

    if ($ForceCloseRunning) {
        Stop-TargetProcesses -ProcessName $ExeName -TargetPath $targetExe
    }

    Write-Host "Gerando $ExeName.exe (build temporario local)..." -ForegroundColor Cyan

    $pyinstallerArgs = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--noconsole",
        "--clean",
        "--name", $tempExeName,
        "--distpath", $buildDistDir,
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

    if (-not (Test-Path $builtExe)) {
        throw "Build concluido, mas o arquivo esperado nao foi encontrado: '$builtExe'."
    }

    $tentativas = 10
    $atualizado = $false

    for ($i = 1; $i -le $tentativas; $i++) {
        try {
            if ($ForceCloseRunning) {
                Stop-TargetProcesses -ProcessName $ExeName -TargetPath $targetExe
            }

            if (Test-Path $targetExe) {
                Remove-Item -Path $targetExe -Force -ErrorAction Stop
            }

            Copy-Item -Path $builtExe -Destination $targetExe -Force -ErrorAction Stop
            $atualizado = $true
            break
        }
        catch {
            if ($i -eq $tentativas) {
                break
            }

            [System.Threading.Thread]::Sleep(400)
        }
    }

    if (-not $atualizado) {
        throw "Build concluido, mas nao foi possivel atualizar '$targetExe'. Use o arquivo temporario '$builtExe' ou tente novamente com -ForceCloseRunning."
    }

    Write-Host "Concluido. Executavel gerado em '$DistDir\\$ExeName.exe'." -ForegroundColor Green
}
finally {
    Pop-Location
}
