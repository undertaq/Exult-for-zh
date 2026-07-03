# One-command pipeline: regenerate bilingual_map.dat from EN and ZH usecode
# Usage: .\tools\generate_all.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$EN_USECODE = "D:/Project/Ultima_7/STATIC/usecode"
$ZH_USECODE = "D:/Project/Ultima_7/patch/usecode.zh"
$ZH_EXTRACTED = "D:/Project/Ultima_7/patch/usecode_standard.bin"
$MAP_OUT = "D:/Project/Ultima_7/patch/voice_acting/bilingual_map.dat"

Write-Output "=== Step 1: Extract standard usecode from ZH file ==="
python tools/extract_zh_usecode2.py

Write-Output "=== Step 2: Disassemble EN usecode to CSV ==="
python -X utf8 tools/voice_acting/disassemble_usecode.py "$EN_USECODE" --all --format csv 2>$null | Out-File -FilePath en_voice_lines.csv -Encoding utf8

Write-Output "=== Step 3: Disassemble ZH usecode to CSV ==="
python -X utf8 tools/voice_acting/disassemble_usecode.py "$ZH_EXTRACTED" --all --format csv 2>$null | Out-File -FilePath zh_voice_lines.csv -Encoding utf8

Write-Output "=== Step 4: Generate offset mapping ==="
python -X utf8 tools/voice_acting/generate_offset_mapping.py --en en_voice_lines.csv --zh zh_voice_lines.csv -o offset_mapping.csv 2>&1

Write-Output "=== Step 5: Convert to BLMP binary ==="
python tools/csv_to_blmp.py

Write-Output "=== Cleanup temporary files ==="
Remove-Item -LiteralPath en_voice_lines.csv,zh_voice_lines.csv,offset_mapping.csv -ErrorAction SilentlyContinue

Write-Output "=== Done! ==="
Get-Item $MAP_OUT | Format-List Name,Length,LastWriteTime
