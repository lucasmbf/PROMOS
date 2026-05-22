param(
    [string]$PythonExe = ".\\venv\\Scripts\\python.exe",
    [string]$CategoriasArquivo = ".\\categorias_exec.txt",
    [string]$DistDir = ".\\dist-categorias"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Push-Location $PSScriptRoot

try {
    if (-not (Test-Path $PythonExe)) {
        throw "Python nao encontrado em '$PythonExe'. Ajuste o parametro -PythonExe."
    }

    if (-not (Test-Path $CategoriasArquivo)) {
        throw "Arquivo de categorias nao encontrado em '$CategoriasArquivo'."
    }

    $launcherDir = Join-Path $PSScriptRoot ".build\\launchers"
    $workDir = Join-Path $PSScriptRoot ".build\\pyinstaller-work"
    $specDir = Join-Path $PSScriptRoot ".build\\spec"

    New-Item -ItemType Directory -Path $launcherDir -Force | Out-Null
    New-Item -ItemType Directory -Path $workDir -Force | Out-Null
    New-Item -ItemType Directory -Path $specDir -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot $DistDir) -Force | Out-Null

    $linhas = Get-Content -Path $CategoriasArquivo

    $categorias = foreach ($linha in $linhas) {
        $linhaLimpa = $linha.Trim()

        if ([string]::IsNullOrWhiteSpace($linhaLimpa) -or $linhaLimpa.StartsWith("#")) {
            continue
        }

        $partes = $linhaLimpa -split "\\|", 2

        if ($partes.Count -ne 2) {
            throw "Linha invalida em '$CategoriasArquivo': '$linha'. Use o formato slug|Categoria"
        }

        [pscustomobject]@{
            Slug = $partes[0].Trim()
            Categoria = $partes[1].Trim()
        }
    }

    if (-not $categorias) {
        throw "Nenhuma categoria valida encontrada em '$CategoriasArquivo'."
    }

    foreach ($item in $categorias) {
        if ([string]::IsNullOrWhiteSpace($item.Slug) -or [string]::IsNullOrWhiteSpace($item.Categoria)) {
            throw "Slug ou categoria vazios no arquivo '$CategoriasArquivo'."
        }

        if ($item.Slug -notmatch '^[a-z0-9_-]+$') {
            throw "Slug invalido '$($item.Slug)'. Use apenas letras minusculas, numeros, underline ou hifen."
        }

        $categoriaPy = $item.Categoria.Replace('\\', '\\\\').Replace("'", "\\'")
        $launcherPath = Join-Path $launcherDir ("launcher_{0}.py" -f $item.Slug)

        $launcherContent = @"
import sys

# Injeta a categoria fixa no argv e preserva parametros extras informados no executavel.
sys.argv = ["main.py", "--categoria", '$categoriaPy', *sys.argv[1:]]
import main  # noqa: F401
"@

        Set-Content -Path $launcherPath -Value $launcherContent -Encoding UTF8

        $nomeExe = "promos_{0}" -f $item.Slug

        Write-Host "`nGerando $nomeExe.exe para categoria '$($item.Categoria)'..." -ForegroundColor Cyan

        $pyinstallerArgs = @(
            "-m", "PyInstaller",
            "--noconfirm",
            "--onefile",
            "--clean",
            "--name", $nomeExe,
            "--distpath", $DistDir,
            "--workpath", $workDir,
            "--specpath", $specDir,
            "--collect-all", "playwright",
            $launcherPath
        )

        & $PythonExe @pyinstallerArgs

        if ($LASTEXITCODE -ne 0) {
            throw "Falha ao gerar o executavel para '$($item.Categoria)'."
        }
    }

    Write-Host "`nConcluido. Executaveis gerados em '$DistDir'." -ForegroundColor Green
}
finally {
    Pop-Location
}
