# Ultima VII 語音功能新增指南

## 概述

Exult 支援為遊戲對話加入語音功能。語音系統會在 NPC 說話時，根據對話的 usecode 函式 ID、addsi offset 和分段編號，自動尋找對應的 `.ogg` 或 `.wav` 檔案來播放。

## 目錄結構

語音檔案統一放在 `<PATCH>/voice_acting/` 目錄下，以語言分類：

```
<patch目錄>/voice_acting/
├── zh/                      # 中文語音
│   ├── 009a_12df_0_npc286.ogg
│   ├── 009a_12df_0.ogg
│   └── second_source/       # 備用語音來源
├── en/                      # 英文語音
│   ├── 009a_10a2_0_npc292.ogg
│   ├── 009a_10a2_0.ogg
│   └── second_source/
├── en_voices.pak            # 英文語音封裝檔
├── en_voices.idx            # 英文語音索引
├── zh_voices.pak            # 中文語音封裝檔
├── zh_voices.idx            # 中文語音索引
└── voice_acting_log.csv     # 執行時期日誌
```

`<PATCH>` 預設指向 `../Ultima_7/patch`（相對於 Exult 執行檔目錄），可在 `exult.cfg` 中設定：

```xml
<blackgate>
  <path>..\Ultima_7</path>
  <patch>..\Ultima_7\patch</patch>
</blackgate>
```

## 語音檔案命名規則

語音檔案的檔名由 usecode 資訊自動組合而成，格式如下：

```
<funcID>_<offsetKey>_<segment>[_(npc<N>|avatar_<gender>)][.ogg|.wav]
```

各欄位說明：

| 欄位 | 說明 | 範例 |
|------|------|------|
| `funcID` | usecode 函式 ID，4 位十六進位 | `009a` |
| `offsetKey` | 對話 usecode 的 addsi offset 鍵值，由 `UCOffsetKey` 演算法產生 | `12df` |
| `segment` | 分段編號（從 0 開始），一段對話可能被分割成多個語音 | `0` |
| `npc<N>` | NPC 專屬語音，N 為 NPC 編號 | `npc286` |
| `avatar_<gender>` | Avatar 專屬語音，依角色性別 | `avatar_male` 或 `avatar_female` |

### 搜索優先順序

當 NPC 說話時，系統依以下順序嘗試播放語音：

1. **封裝檔（pack）**：先從 `<lang>_voices.pak` 中搜尋（avatar → NPC → generic）
2. **各別目錄檔案**：若封裝檔中找不到，再到 `<PATCH>/voice_acting/<lang>/` 目錄下搜尋：
   - NPC 專屬語音（`009a_12df_0_npc286.ogg`）
   - 通用語音（`009a_12df_0.ogg`）
   - 若以上皆無，切換到 `second_source/` 子目錄再次嘗試
3. **跨語言備援**：若目前語言目錄都找不到，嘗試另一語言的目錄（重複上述流程）

## 如何產生語音檔案

### 方法一：使用 TTS 批次產生

專案提供了批次產生工具，可從執行時期日誌取得所有需要的語音列表：

1. **啟用語音日誌**：在遊戲中對話一次，`voice_acting_log.csv` 會記錄所有遇到的語音。
2. **使用批次產生腳本**：
   ```
   python tools/voice_acting/batch_generate.py \
       --csv voice_acting_log.csv \
       --lang zh \
       --output-dir /path/to/patch/voice_acting/zh/ \
       --tts-engine qwen3-tts \
       --api-url http://localhost:5001/v1/audio/speech
   ```
   目前使用的 TTS 引擎為 **Qwen3-TTS**。若使用其他引擎，請修改 `--tts-engine` 參數及 `batch_generate.py` 中的 API 呼叫格式。

### 方法二：自行放入檔案

直接將 `.ogg` 或 `.wav` 檔案放入對應的語言目錄下即可。支援的格式：
- Ogg Vorbis (`.ogg`) — 優先使用，較小頻寬
- WAV (`.wav`) — 備用格式

## 語音包封裝系統（Packed Archive）

為提升載入速度與減少檔案數量，可將大量 `.ogg` 檔案打包成單一封裝檔。

### 檔案格式

- **`.pak`**：所有 `.ogg` 檔案按檔名排序後直接串接
- **`.idx`**：索引檔案，記錄每個檔案的偏移量和大小

`.idx` 檔案格式：
```
Magic:    "VAIX" (4 bytes)
Version:  uint32 LE (currently 1)
Count:    uint32 LE (entry count)

Entries (repeating):
  NameLen:  uint16 LE (N)
  Name:     N bytes (UTF-8 filename without extension)
  Offset:   uint64 LE (byte offset in .pak)
  Size:     uint32 LE (byte count)
```

### 使用打包工具

```
python tools/voice_acting/pack_voice.py pack \
    --input-dir /path/to/voice/zh/ \
    --output-dir /path/to/patch/voice_acting/ \
    --lang zh
```

參數說明：
- `pack`：打包模式
- `--input-dir`：包含 `.ogg` 檔案的目錄
- `--output-dir`：輸出 `.pak`/`.idx` 的目錄
- `--lang`：語言代碼（決定輸出檔名，如 `zh_voices.pak`）

其他模式：
- `unpack`：解包 `--pak zh_voices.pak --idx zh_voices.idx --output-dir output/`
- `verify`：驗證包完整性 `--pak zh_voices.pak --idx zh_voices.idx`

### 注意事項

- 打包前請先備份原始 `.ogg` 檔案；打包後不需要保留原始目錄（除非需要 second_source 或跨語言備援）
- 打包後請確保 `.pak`/`.idx` 檔案在遊戲讀得到的 `<PATCH>/voice_acting/` 目錄中
- 若同時有封裝檔和目錄檔案，封裝檔優先

### 封裝與目錄檔案的互動

遊戲載入流程：
1. 首次播放語音時，嘗試載入 `<lang>_voices.pak` + `<lang>_voices.idx`
2. 若成功，先從封裝檔中搜尋
3. 若封裝檔中找不到該語音，自動降級到目錄檔案搜索
4. 切換語言時自動重新載入對應語言的封裝檔

## 設定檔（exult.cfg）

```xml
<audio>
  <speech>
    <enabled>yes</enabled>
    <speech_volume>100</speech_volume>
    <with_subs>yes</with_subs>      <!-- 播放語音時同時顯示字幕 -->
    <voice>
      <enabled>yes</enabled>
      <language>zh</language>       <!-- 預設語音語言 -->
    </voice>
  </speech>
  <voice>
    <language>zh</language>         <!-- 舊版相容設定 -->
  </voice>
</audio>
```

**語言設定優先順序**：
1. `config/audio/speech/voice/language`（新版）
2. `config/gameplay/language`（遊戲語言，作為備援）
3. 預設值：`"zh"`

## 在遊戲中切換語音語言

1. 開啟 **Audio Options** 選單（Esc → Audio Options）
2. 找到 **Speech Language** 設定項
3. 選擇 `zh`（中文）或 `en`（英文）
4. 遊戲會立即切換語音語言，後續對話將使用新語言的語音

切換語言時，系統會自動重新載入對應語言的封裝檔（如 `en_voices.pak` ↔ `zh_voices.pak`）。

## 跨語言語音支援

當使用雙語模式時（`bilingual_manager`），語音系統會自動對應中英文 usecode 的差異：

- 若語音語言設定為 `"zh"`，但文字語言為英文，系統會將 usecode 函式 ID 與 offset key 進行轉換，找出對應的中文語音檔案
- 若主要語言找不到語音，會自動嘗試備用語言
- 此功能需啟用雙語支援（`config/gameplay/enhancements = yes`）

## 執行時期除錯

在遊戲啟動時觀察以下訊息：

```
[VoiceActing] Language: zh
[VoiceActing] Trying packed archive: lang=zh pak=.../patch/voice_acting/zh_voices.pak idx=.../patch/voice_acting/zh_voices.idx
[VoiceActing] Loaded packed archive: .../zh_voices.pak (13278 entries)
[VoiceActing] Checking: .../patch/voice_acting/zh/009a_12df_0_npc286.ogg - FOUND
[VoiceActing] Checking: .../patch/voice_acting/zh/009a_12df_0_npc286.ogg - not found
```

## 常見問題

### Q: 語音沒有播放
- 確認 `exult.cfg` 中語音已啟用（`<speech><enabled>yes</enabled>`）
- 確認語音目錄路徑正確（`<PATCH>/voice_acting/<lang>/`）
- 檢查遊戲視窗是否獲得焦點
- 檢查音訊驅動是否正常

### Q: 播放錯誤的語音
- 通常是 usecode offset 漂移導致，需要重新產生 `bilingual_map.dat`

### Q: 打包後找不到語音
- 確認 `.pak`/`.idx` 檔案在 `<PATCH>/voice_acting/` 目錄中
- 確認語言設定與打包時使用的語言一致
- 查看啟動時 `[VoiceActing]` 輸出確認路徑
