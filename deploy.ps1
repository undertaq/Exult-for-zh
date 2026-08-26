$ErrorActionPreference = "Stop"

$workspace = $PSScriptRoot
# Real game install location (per exult.cfg blackgate path); was ..\Ultima7_zh_voice_1.1
$dist = "D:\Game\Ultima7_VO_1.1"

Write-Host "=== Step 1: Copy .exe and .dll to Exult/ ==="
Get-ChildItem -Path $workspace -Filter *.exe | Copy-Item -Destination "$dist\Exult\" -Force
Get-ChildItem -Path $workspace -Filter *.dll | Copy-Item -Destination "$dist\Exult\" -Force

Write-Host "=== Step 2: Copy voice core files & usecode.zh ==="
$voiceDest = "$dist\Ultima_7\patch\voice_acting"
if (-not (Test-Path $voiceDest)) { New-Item -ItemType Directory -Path $voiceDest -Force | Out-Null }
Copy-Item -Path "$workspace\voice\*.idx" -Destination $voiceDest -Force
Copy-Item -Path "$workspace\voice\*.pak" -Destination $voiceDest -Force
Copy-Item -Path "$workspace\voice\bilingual_map.dat" -Destination $voiceDest -Force

$patchDest = "$dist\Ultima_7\patch"
if (-not (Test-Path $patchDest)) { New-Item -ItemType Directory -Path $patchDest -Force | Out-Null }
if (Test-Path "$workspace\tools\voice_acting\_live\usecode.zh") {
    Copy-Item -Path "$workspace\tools\voice_acting\_live\usecode.zh" -Destination "$patchDest\" -Force
}
if (Test-Path "$workspace\tools\voice_acting\_live\usecode.dual") {
    Copy-Item -Path "$workspace\tools\voice_acting\_live\usecode.dual" -Destination "$patchDest\" -Force
    Copy-Item -Path "$workspace\tools\voice_acting\_live\dual_map.dat" -Destination "$voiceDest\" -Force
}

Write-Host "=== Step 2b: Copy autonote files ==="
foreach ($file in @("autonotes.txt", "autonotes_zh.txt")) {
    $src = "$workspace\data\bg\$file"
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination "$patchDest\" -Force
        Write-Host "  Copied $file -> $patchDest"
    } else {
        Write-Host "  WARNING: $src not found, skipping"
    }
}

Write-Host "=== Step 3: 7z compress (exclude STATIC + gamedat) ==="
$dateTag = (Get-Date -Format "yyyyMMdd")
$out = Join-Path (Split-Path $dist -Parent) "U7_dual_$dateTag.7z"
if (Test-Path $out) { Remove-Item $out -Force }
& 7z a -t7z -mx=9 -mfb=273 -ms=on -r "$out" "$dist\*" "-x!Ultima_7\STATIC\*" "-x!Exult\blackgate\gamedat\*"
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 1) {
    throw "7z failed with exit code $LASTEXITCODE"
}

Write-Host "=== Done ==="
Write-Host "Archive: $out"
