$ErrorActionPreference = "Stop"

$workspace = "D:\Project\Exult-for-zh"
$dist = "D:\Project\Ultima7_zh_voice_1.1"

Write-Host "=== Step 1: Copy .exe and .dll to Exult/ ==="
Get-ChildItem -Path $workspace -Filter *.exe | Copy-Item -Destination "$dist\Exult\" -Force
Get-ChildItem -Path $workspace -Filter *.dll | Copy-Item -Destination "$dist\Exult\" -Force

Write-Host "=== Step 2: Copy voice core files ==="
$voiceDest = "$dist\Ultima_7\patch\voice_acting"
Copy-Item -Path "$workspace\voice\*.idx" -Destination $voiceDest -Force
Copy-Item -Path "$workspace\voice\*.pak" -Destination $voiceDest -Force
Copy-Item -Path "$workspace\voice\bilingual_map.dat" -Destination $voiceDest -Force

Write-Host "=== Step 3: 7z compress (exclude STATIC + gamedat) ==="
$out = "$dist.7z"
if (Test-Path $out) { Remove-Item $out -Force }
& 7z a -t7z -mx=9 -mfb=273 -ms=on -r "$out" "$dist\*" "-x!Ultima_7\STATIC\*" "-x!Exult\blackgate\gamedat\*"
if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 1) {
    throw "7z failed with exit code $LASTEXITCODE"
}

Write-Host "=== Done ==="
Write-Host "Archive: $out"
