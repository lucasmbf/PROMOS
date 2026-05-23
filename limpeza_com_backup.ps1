[CmdletBinding()]
param(
    [int]$DiasRetencao = 10
)

$ErrorActionPreference = "Stop"

$WorkspaceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackupBaseDir = Join-Path $WorkspaceRoot "backup_limpeza"
$BackupExecDir = Join-Path $BackupBaseDir (Get-Date -Format "yyyyMMdd_HHmmss")

[int]$ArquivosMovidos = 0
[int]$HistoricosAparados = 0

function Ensure-Dir {
    param([string]$DirPath)

    if (-not (Test-Path $DirPath)) {
        New-Item -Path $DirPath -ItemType Directory -Force | Out-Null
    }
}

function Relative-FromWorkspace {
    param([string]$FullPath)

    $root = (Resolve-Path $WorkspaceRoot).Path
    $full = (Resolve-Path $FullPath).Path

    if ($full.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $full.Substring($root.Length).TrimStart('\\', '/')
    }

    return Split-Path $full -Leaf
}

function Move-ToBackup {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

    $relative = Relative-FromWorkspace -FullPath $Path
    $dest = Join-Path $BackupExecDir $relative
    $destParent = Split-Path -Parent $dest
    Ensure-Dir -DirPath $destParent

    Move-Item -Path $Path -Destination $dest -Force
    $script:ArquivosMovidos++
}

function Write-BackupText {
    param(
        [string]$RelativePath,
        [string]$Content
    )

    if ([string]::IsNullOrWhiteSpace($Content)) {
        return
    }

    $dest = Join-Path $BackupExecDir $RelativePath
    $parent = Split-Path -Parent $dest
    Ensure-Dir -DirPath $parent

    Set-Content -Path $dest -Value $Content -Encoding UTF8
}

function Get-TimestampFromName {
    param([string]$Name)

    $m = [regex]::Match($Name, '(\d{8}_\d{6})')
    if (-not $m.Success) {
        return $null
    }

    try {
        return [datetime]::ParseExact($m.Groups[1].Value, 'yyyyMMdd_HHmmss', $null)
    }
    catch {
        return $null
    }
}

function Process-Metadata {
    $metaDir = Join-Path $WorkspaceRoot "metadados_coleta"
    if (-not (Test-Path $metaDir)) {
        return
    }

    $jsonFiles = Get-ChildItem -Path $metaDir -File -Filter *.json -ErrorAction SilentlyContinue
    if (-not $jsonFiles) {
        return
    }

    $grupos = @{}

    foreach ($file in $jsonFiles) {
        if ($file.Name -eq "controle_execucoes.json") {
            continue
        }

        $m = [regex]::Match($file.Name, '^metadados_(?<fluxo>.+?)_exec_(?<exec>\d+)_')
        if (-not $m.Success) {
            Move-ToBackup -Path $file.FullName
            continue
        }

        $fluxo = $m.Groups['fluxo'].Value
        $execId = [int]$m.Groups['exec'].Value

        if (-not $grupos.ContainsKey($fluxo)) {
            $grupos[$fluxo] = @()
        }

        $grupos[$fluxo] += [pscustomobject]@{
            File = $file
            ExecId = $execId
            LastWrite = $file.LastWriteTime
        }
    }

    foreach ($fluxo in $grupos.Keys) {
        $ordenado = $grupos[$fluxo] | Sort-Object ExecId, LastWrite -Descending
        $descartar = $ordenado | Select-Object -Skip 1

        foreach ($item in $descartar) {
            Move-ToBackup -Path $item.File.FullName
        }
    }
}

function Process-HtmlFolder {
    param([string]$FolderRelative)

    $dir = Join-Path $WorkspaceRoot $FolderRelative
    if (-not (Test-Path $dir)) {
        return
    }

    $txtFiles = Get-ChildItem -Path $dir -File -Filter *.txt -ErrorAction SilentlyContinue
    if (-not $txtFiles -or $txtFiles.Count -le 1) {
        return
    }

    $consolidados = $txtFiles | Where-Object { $_.Name -match 'consolidado' }

    if ($consolidados.Count -eq 0) {
        $latest = $txtFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        foreach ($f in $txtFiles) {
            if ($f.FullName -ne $latest.FullName) {
                Move-ToBackup -Path $f.FullName
            }
        }
        return
    }

    $consolidadoComTempo = @()
    foreach ($c in $consolidados) {
        $t = Get-TimestampFromName -Name $c.Name
        if ($null -ne $t) {
            $consolidadoComTempo += [pscustomobject]@{ File = $c; Time = $t }
        }
    }

    if ($consolidadoComTempo.Count -eq 0) {
        $latest = $txtFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        foreach ($f in $txtFiles) {
            if ($f.FullName -ne $latest.FullName) {
                Move-ToBackup -Path $f.FullName
            }
        }
        return
    }

    $ord = $consolidadoComTempo | Sort-Object Time
    $latestExecTime = ($ord | Select-Object -Last 1).Time
    $prevExecTime = if ($ord.Count -gt 1) {
        ($ord | Select-Object -SkipLast 1 | Select-Object -Last 1).Time
    }
    else {
        [datetime]::MinValue
    }

    foreach ($f in $txtFiles) {
        $t = Get-TimestampFromName -Name $f.Name

        if ($null -eq $t) {
            Move-ToBackup -Path $f.FullName
            continue
        }

        if ($t -le $prevExecTime -or $t -gt $latestExecTime) {
            Move-ToBackup -Path $f.FullName
        }
    }
}

function Move-ExtraResultFiles {
    param(
        [string]$FolderRelative,
        [string]$CanonicalName
    )

    $dir = Join-Path $WorkspaceRoot $FolderRelative
    if (-not (Test-Path $dir)) {
        return
    }

    $txtFiles = Get-ChildItem -Path $dir -File -Filter *.txt -ErrorAction SilentlyContinue
    foreach ($f in $txtFiles) {
        if ($f.Name -ne $CanonicalName) {
            Move-ToBackup -Path $f.FullName
        }
    }
}

function Trim-HistoryFile {
    param(
        [string]$HistoryRelative,
        [string]$BackupOlderRelative
    )

    $historyPath = Join-Path $WorkspaceRoot $HistoryRelative
    if (-not (Test-Path $historyPath)) {
        return
    }

    $raw = Get-Content -Path $historyPath -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return
    }

    $matches = [regex]::Matches($raw, '(?ms)^===== EXECUCAO .*?(?=^===== EXECUCAO |\z)')
    if ($matches.Count -le 1) {
        return
    }

    $latest = $matches[$matches.Count - 1].Value
    $olderBuilder = New-Object System.Text.StringBuilder

    for ($i = 0; $i -lt $matches.Count - 1; $i++) {
        [void]$olderBuilder.Append($matches[$i].Value)
    }

    $older = $olderBuilder.ToString()

    Write-BackupText -RelativePath $BackupOlderRelative -Content $older
    Set-Content -Path $historyPath -Value $latest -Encoding UTF8

    $script:HistoricosAparados++
}

function Purge-OldBackups {
    param([int]$RetentionDays)

    if (-not (Test-Path $BackupBaseDir)) {
        return
    }

    $limite = (Get-Date).AddDays(-1 * [math]::Abs($RetentionDays))

    $oldDirs = Get-ChildItem -Path $BackupBaseDir -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $limite }

    foreach ($d in $oldDirs) {
        Remove-Item -Path $d.FullName -Recurse -Force
    }
}

Ensure-Dir -DirPath $BackupExecDir

# Metadados: manter apenas a execucao mais recente por fluxo.
Process-Metadata

# HTML: manter apenas arquivos da ultima execucao detectada.
Process-HtmlFolder -FolderRelative "ofertas_relampago\html"
Process-HtmlFolder -FolderRelative "ofertas_afiliados\html"

# Compatibilidade com arquivos legados na raiz.
Process-HtmlFolder -FolderRelative "ofertas_relampago"
Process-HtmlFolder -FolderRelative "ofertas_afiliados"

# Resultados: manter arquivo consolidado e mover extras para backup.
Move-ExtraResultFiles -FolderRelative "ofertas_relampago\Historico de anuncios" -CanonicalName "historico_relampago.txt"
Move-ExtraResultFiles -FolderRelative "ofertas_afiliados\Historico de anuncios" -CanonicalName "historico_afiliados.txt"
Move-ExtraResultFiles -FolderRelative "ofertas_relampago\resultados" -CanonicalName "historico_relampago.txt"
Move-ExtraResultFiles -FolderRelative "ofertas_afiliados\resultados" -CanonicalName "historico_afiliados.txt"

# Historico consolidado: manter so a ultima secao na pasta principal.
Trim-HistoryFile `
    -HistoryRelative "ofertas_relampago\Historico de anuncios\historico_relampago.txt" `
    -BackupOlderRelative "ofertas_relampago\Historico de anuncios\historico_relampago_anteriores.txt"

Trim-HistoryFile `
    -HistoryRelative "ofertas_afiliados\Historico de anuncios\historico_afiliados.txt" `
    -BackupOlderRelative "ofertas_afiliados\Historico de anuncios\historico_afiliados_anteriores.txt"

# Limpa backups antigos.
Purge-OldBackups -RetentionDays $DiasRetencao

Write-Output "Limpeza concluida."
Write-Output "Arquivos movidos para backup: $ArquivosMovidos"
Write-Output "Historicos aparados: $HistoricosAparados"
Write-Output "Backup da execucao atual: $BackupExecDir"
