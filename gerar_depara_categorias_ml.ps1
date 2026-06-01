Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$rootUrl = "https://api.mercadolibre.com/sites/MLB/categories/all"
$outFile = "ml_categories_depara_full.json"

function Get-Slug {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return ""
    }

    $normalized = $Text.Normalize([Text.NormalizationForm]::FormD)
    $sb = New-Object System.Text.StringBuilder

    foreach ($ch in $normalized.ToCharArray()) {
        $cat = [Globalization.CharUnicodeInfo]::GetUnicodeCategory($ch)
        if ($cat -eq [Globalization.UnicodeCategory]::NonSpacingMark) {
            continue
        }
        [void]$sb.Append($ch)
    }

    $ascii = $sb.ToString().ToLowerInvariant()
    $ascii = $ascii -replace "[^a-z0-9]+", "-"
    $ascii = $ascii.Trim('-')
    return $ascii
}

$rootsRaw = Invoke-RestMethod -Method Get -Uri $rootUrl
$categories = @()

if ($rootsRaw -is [System.Array]) {
    $categories = @($rootsRaw)
}
elseif ($rootsRaw -is [System.Collections.IDictionary]) {
    $categories = @($rootsRaw.Values)
}
elseif ($rootsRaw -is [PSCustomObject]) {
    $props = $rootsRaw.PSObject.Properties
    if ($props.Name -contains "id" -and $props.Name -contains "name") {
        $categories = @($rootsRaw)
    }
    else {
        $categories = @($props | ForEach-Object { $_.Value })
    }
}

$categories = @($categories | Where-Object {
    $_ -and $_.PSObject.Properties.Name -contains "id" -and $_.PSObject.Properties.Name -contains "name"
})

if (-not $categories -or $categories.Count -eq 0) {
    throw "Resposta invalida da API de categorias raiz."
}

$nodes = @{}
$rootIds = @()

foreach ($cat in $categories) {
    $cid = [string]$cat.id
    $cname = [string]$cat.name
    if ([string]::IsNullOrWhiteSpace($cid) -or [string]::IsNullOrWhiteSpace($cname)) {
        continue
    }

    $pathParts = @()
    if ($cat.path_from_root) {
        foreach ($p in $cat.path_from_root) {
            $pname = [string]$p.name
            if (-not [string]::IsNullOrWhiteSpace($pname)) {
                $pathParts += $pname
            }
        }
    }
    if ($pathParts.Count -eq 0) {
        $pathParts = @($cname)
    }

    $parentId = $null
    if ($cat.path_from_root -and $cat.path_from_root.Count -ge 2) {
        $parentId = [string]$cat.path_from_root[$cat.path_from_root.Count - 2].id
        if ([string]::IsNullOrWhiteSpace($parentId)) {
            $parentId = $null
        }
    }

    $childrenIds = @()
    if ($cat.children_categories) {
        foreach ($child in $cat.children_categories) {
            $childId = [string]$child.id
            if (-not [string]::IsNullOrWhiteSpace($childId)) {
                $childrenIds += $childId
            }
        }
    }

    $pathText = ($pathParts -join " > ")
    $pathSlug = (($pathParts | ForEach-Object { Get-Slug $_ }) -join "-").Trim('-')
    $urlPath = (($pathParts | ForEach-Object { Get-Slug $_ }) -join "/").Trim('/')
    $url = [string]$cat.permalink
    if ([string]::IsNullOrWhiteSpace($url) -and -not [string]::IsNullOrWhiteSpace($urlPath)) {
        $url = "https://lista.mercadolivre.com.br/$urlPath"
    }
    $urlTestada = -not [string]::IsNullOrWhiteSpace([string]$cat.permalink)

    $nodes[$cid] = [ordered]@{
        id = $cid
        name = $cname
        parent_id = $parentId
        path = $pathText
        path_slug = $pathSlug
        url_path = $urlPath
        url = $url
        url_testada = $urlTestada
        navegavel = -not [string]::IsNullOrWhiteSpace($url)
        children_ids = @($childrenIds)
    }

    if (-not $parentId) {
        $rootIds += $cid
    }
}

$rootIds = @($rootIds | Sort-Object -Unique)

$pathToId = [ordered]@{}
$idToMeta = [ordered]@{}

foreach ($nodeId in ($nodes.Keys | Sort-Object)) {
    $node = $nodes[$nodeId]
    if (-not [string]::IsNullOrWhiteSpace([string]$node.path)) {
        $pathToId[[string]$node.path] = [string]$node.id
    }

    $idToMeta[[string]$node.id] = [ordered]@{
        name = [string]$node.name
        parent_id = $node.parent_id
        path = [string]$node.path
        path_slug = [string]$node.path_slug
        url_path = [string]$node.url_path
        url = [string]$node.url
        url_testada = [bool]$node.url_testada
        navegavel = [bool]$node.navegavel
        children_ids = @($node.children_ids)
    }
}

$payload = [ordered]@{
    generated_at = (Get-Date).ToString("s")
    site_id = "MLB"
    root_ids = $rootIds
    path_to_id = $pathToId
    id_to_meta = $idToMeta
}

$payload | ConvertTo-Json -Depth 12 | Set-Content -Encoding UTF8 $outFile
Write-Host "DePara gerado com sucesso em: $outFile"
Write-Host "Total de categorias mapeadas:" $idToMeta.Count
