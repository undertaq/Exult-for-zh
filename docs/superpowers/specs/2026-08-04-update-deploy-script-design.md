# Design: Update deploy.ps1 with Relative Paths and usecode.zh

## Overview
Update `deploy.ps1` to use relative paths for the workspace and distribution output directory, and copy `tools\voice_acting\_live\usecode.zh` into the output `Ultima_7\patch\` directory.

## Requirements
1. Use relative folder paths for `$workspace` (`$PSScriptRoot`) and `$dist` (`$PSScriptRoot\..\Ultima7_zh_voice_1.1`).
2. Copy `tools\voice_acting\_live\usecode.zh` to `$dist\Ultima_7\patch\`.
3. Ensure parent directories exist before copying.

## Changes
- Modify `deploy.ps1`:
  - Set `$workspace = $PSScriptRoot`.
  - Set `$dist = Join-Path $PSScriptRoot "..\Ultima7_zh_voice_1.1"`.
  - Add copying of `tools\voice_acting\_live\usecode.zh` to `$dist\Ultima_7\patch\`.
