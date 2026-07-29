# Voice Regeneration — Completion & 7-NPC Recovery Plan

**Branch:** `voice_acting3`
**Date:** 2026-07-19
**Status:** ZH generation COMPLETE (9,661 files). EN still running on GPU1. Plan covers: recovering 7 unvoiced NPCs (user chose Option B), and post-completion verification (user chose "yes" on Morfin/Ferryman/Rudyom checks).

---

## Context (verified, read-only)

- **ZH (GPU0) finished cleanly:** log shows `Phase C complete. Generated: 4791, Skipped: 4221, Errors: 138`. Process 228788 exited normally. GPU0 idle at 0% (expected — no more ZH work).
- **The 138 "errors" are NOT TTS failures.** They are 138 lines skipped because 7 NPCs have **no voice design** in `npc_voice_designs.json`. Breakdown (from gpu0 log):
  | NPC | Lines skipped |
  |---|---|
  | Dark Core | 45 |
  | Shandu | 33 |
  | Hook | 29 |
  | Shanda | 14 |
  | Shando | 10 |
  | Avatar | 6 (verified in mapping, zh=6/en=6) |
  | Arcadion | 2 |
  | Bollux | 1 (noncanonical runtime key, not missing design) |
  | **Total** | **138** |
- **EN (GPU1) still running:** PID 228789 alive, active through `T` NPCs, newest file ~11:19. Will end with the same ~138 errors (same 7 NPCs). No ZH-rerun needed.
- **Reference voices used:** Phase A regenerated `voice/refs/` (572 clips) before Phase C; both phases share `REFS_DIR = voice/refs`. Confirmed ZH used updated refs.
- **Morfin (npc172 / func 04ac):** stale files `04ac_761_0_npc172.ogg`, `04ac_866_0_npc172.ogg`, `04ac_a65_a8a_0_npc172.ogg` **already regenerated this session** (present in `voice/zh/`). EN side to be verified.
- **Clone prompts** are keyed by design id (`npc_<name>`), 268 entries in `clone_prompts.pkl`. The 7 NPCs have NO key → need both a design AND a clone prompt.

---

## Step 1 — Let EN finish (no action)

- Monitor: `grep "Phase C complete" tools/voice_acting/logs/regen_gpu1_20260718-223645.log`
- Expected: ~3–8 more hours (bursty seeded-generator rate).
- Do not kill the orchestrator (PID 184865) or EN worker (PID 228789) yet.

## Step 2 — Add voice designs for the 7 NPCs (user: Option B)

For each of `Arcadion, Avatar, Dark Core, Hook, Shanda, Shando, Shandu`:
1. **Exact-token lookup first:** grep `bilingual_mapping_review.json` for the precise `npc` token (the 6 non-Avatar NPCs use a form not caught by naive substring — inspect raw JSON directly). Record each NPC's `zh_text`/`en_text` sample and `voice_gender` to pick a fitting voice.
2. **Pick a donor reference voice** per NPC — choose an existing NPC in `npc_voice_designs.json` with matching gender/tone, and reuse its `voice_desc_zh`/`voice_desc_en` + its `voice/refs/npc_<donor>_{zh,en}_ref.ogg` clip. (This avoids recording new references.)
3. **Append a design entry** to `tools/voice_acting/npc_voice_designs.json`, modeled on the sample (`npc_addom`):
   - `npc`, `type:"individual"`, `npcs:[<exact token>]`
   - `voice_desc_en`, `voice_desc_zh` (copied from donor)
   - `ref_zh_text`, `ref_en_text` (a short line for that NPC, or reuse donor's)
4. **Generate the clone prompt** for the new design id (`npc_<name>`):
   - Run `generate_qwen3_voice.py --phase prompts` (Phase B) — it builds `clone_prompts.pkl` from designs. Confirm the 7 new keys appear.
   - *Note:* a full Phase B rebuild overwrites `clone_prompts.pkl`; that's fine (268→275 entries). Verify no existing prompt is lost.

## Step 3 — Regenerate the 7 NPCs (ZH + EN)

After designs + clone prompts exist:
```
python3 generate_qwen3_voice.py --reference-workflow legacy \
  --phase voice --lang zh --device cuda:0
python3 generate_qwen3_voice.py --reference-workflow legacy \
  --phase voice --lang en --device cuda:1
```
- The skip logic (`voice_file_matches_text`) means all already-good files are skipped; only the 7 NPCs' ~138 lines regenerate.
- Verify post-run: ZH and EN logs show `Generated:` for the 7 NPCs with `Errors: 0` (Bollux's 1 noncanonical row excluded).
- Route ZH→cuda:0, EN→cuda:1 (true parallel; note: current run launched both with `--device cuda:0` but EN landed on GPU1 — keep EN on GPU1 to avoid contention).

## Step 4 — Post-completion verification (user: yes on all checks)

1. **File counts:** `find voice/zh -name '*.ogg' | wc -l` and `voice/en`. Expect both ≈ 8,708 (± legacy/backup extras). EN errors should equal ZH's 138 (same 7 NPCs), now reduced to ~1 (Bollux) after Step 3.
2. **7-NPC recovery confirmed:** ZH + EN each contain `npc_<name>_*.ogg` for all 7; log `Generated:` > 0, `Errors:` ≤ 1.
3. **Session fixes audible:**
   - Anmanivas dedup (`圣者！` double-name) in ZH/EN.
   - Archaic normalization (`'Twould`→`It would`, etc.) in generated text/audio.
   - Deterministic name pronunciation (seeded `TTS_SEED`) — same name sounds identical across lines.
4. **Morfin EN (npc172 / 04ac):** confirm `voice/en/04ac_761_0_npc172.ogg`, `04ac_866_0_npc172.ogg`, `04ac_a65_a8a_0_npc172.ogg` exist and are fresh (mtime ≈ this session). ZH side already confirmed present.
5. **Ferryman / Rudyom 33-file overwrite:** verify by NPC token (not filename) — grep mapping for `Ferryman` and `Rudyom`, confirm their `voice/{zh,en}/*.ogg` were overwritten this session (fresh mtime), resolving the prior 33 stale files.
6. **Reference voices:** `voice/refs/` = 572 clips (regenerated this session, used as clone source). Confirmed.
 7. **Review pages:**
    - `tools/voice_acting/voice_review/index.html` — **NOTE: this page is written ONLY by the ZH worker** (orchestrator adds `--review-out-dir` only to GPU0/ZH). ZH finished at 10:27:27, so the page is **frozen at the final ZH snapshot** and does NOT reflect EN's ongoing progress (EN runs without `--review-out-dir`). This is expected, not a bug.
    - **Manual final rebuild** (non-destructive) after EN + Step 3 complete, to snapshot ALL of `voice/{zh,en}` including EN progress + 7 recovered NPCs:
      ```
      python3 generate_voice_review_html.py \
        --mode full \
        --voice-dir voice \
        --mapping tools/voice_acting/bilingual_mapping_review.json \
        --out-dir tools/voice_acting/voice_review
      ```
    - (Optional live EN refresh: relaunch EN with `--review-out-dir tools/voice_acting/voice_review` — but this restarts EN and risks the seeded-generator stall; NOT recommended while EN is mid-run. Skip in favor of the final manual rebuild.)
    - `tools/voice_acting/reference_voice_review.html` — current (periodic loop PID 199093 still running; stop it after verification: `kill 199093`).

## Step 5 — Cleanup

- Stop periodic `reference_voice_review.html` rebuild loop: `kill $(cat /tmp/opencode/ref_review_loop.pid)` (PID 199093).
- After EN `Phase C complete` + Step 3 + Step 4 pass: kill orchestrator `kill 184865` (and any stray workers).
- Do NOT commit unless user requests. (`voice/bilingual_map.dat` is gitignored.)

---

## Open questions resolved by user
- **Q1 (7 NPCs):** Option B — add voice designs + clone prompts, regenerate. ✅
- **Q2 (Morfin/Ferryman/Rudyom):** Yes, verify explicitly in Step 4. ✅

## Risks / notes
- Step 2 donor-voice choice is a content/quality decision; pick donors with matching gender & tone. If a better bespoke voice is desired later, record new `voice/refs/` clips (Phase A for just those NPCs via `--npc`).
- Seeded `TTS_SEED` can cause slow/degenerate generation on hard prompts (observed as long per-call gaps). If Step 3 stalls on a 7-NPC line, add an empty-output retry fallback (unseeded) before declaring failure.
- The 6 non-Avatar NPC tokens must be extracted from raw JSON during implementation (naive match missed them); treat exact token as a sub-task, not an assumption.
