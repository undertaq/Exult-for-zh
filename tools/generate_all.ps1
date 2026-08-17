# One-command pipeline: regenerate bilingual_map.dat from reviewed mappings
# Usage: .\tools\generate_all.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$REVIEW_JSON = if ($env:REVIEW_JSON) { $env:REVIEW_JSON } else { "tools/voice_acting/bilingual_mapping_review.json" }
$LOCAL_MAP = if ($env:LOCAL_MAP) { $env:LOCAL_MAP } else { "voice/bilingual_map.dat" }
$MAP_OUT = if ($env:MAP_OUT) { $env:MAP_OUT } else { "D:/Project/Ultima_7/patch/voice_acting/bilingual_map.dat" }

Write-Output "=== Generate canonical BLMP from reviewed mapping JSON ==="
python -X utf8 tools/voice_acting/generate_bilingual_map.py --input "$REVIEW_JSON" --output "$LOCAL_MAP"

Write-Output "=== Copy BLMP to patch voice_acting directory ==="
$MapDir = Split-Path -Parent $MAP_OUT
New-Item -ItemType Directory -Force -Path $MapDir | Out-Null
Copy-Item -LiteralPath $LOCAL_MAP -Destination $MAP_OUT -Force

Write-Output "=== Done! ==="
Get-Item $MAP_OUT | Format-List Name,Length,LastWriteTime
