# Bilingual Text & Voice Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Chinese/English bilingual text and voice support with runtime switching in Audio Options.

**Architecture:** Dual Usecode Machine approach — two `Usecode_machine` instances loaded simultaneously, a `BilingualManager` singleton swaps the active pointer. Text vectors stored per-language. GUI adds two click-to-toggle rows in AudioOptions_gump.

**Tech Stack:** C++17, SDL3, Exult autotools build system, Python for bilingual map generation tool.

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `bilingual_manager.h` | BilingualManager class declaration |
| Create | `bilingual_manager.cc` | BilingualManager implementation |
| Create | `tools/gen_bilingual_map.py` | Python tool to generate bilingual_map.dat |
| Modify | `fnames.h:98-99` | Add `ZH_USECODE` define |
| Modify | `shapes/items.h:54` | Add `Reload_text()` declaration |
| Modify | `shapes/items.cc:56-60,295-409` | Language-indexed text vectors, `Reload_text()` |
| Modify | `gumps/Spellbook_gump.cc:77-108` | Language-indexed spell names |
| Modify | `gumps/AudioOptions_gump.h:34-54` | Add button IDs and member variables |
| Modify | `gumps/AudioOptions_gump.cc` | Add text/voice language rows, load/save |
| Modify | `audio/VoiceActingManager.cc:48-59,214-235` | Cross-language voice lookup |
| Modify | `gamewin.cc:567-568` | Initialize BilingualManager |
| Modify | `Makefile.am` | Add bilingual_manager.cc to build |

---

## Self-Review

**1. Spec coverage:**
- [x] BilingualManager singleton (Task 1)
- [x] Dual usecode loading (Task 1)
- [x] Language-indexed text vectors (Task 2)
- [x] Language-indexed spell names (Task 3)
- [x] GUI rows for text/voice language (Task 4)
- [x] Bilingual map generation tool (Task 5)
- [x] Bilingual map loading (Task 6)
- [x] Cross-language voice lookup (Task 7)
- [x] Initialization (Task 8)
- [x] Runtime verification (Task 9)

**2. Placeholder scan:** No TBD/TODO in final plan. All code blocks complete.

**3. Type consistency:** `TextLanguage` enum used consistently. `BilingualManager::get()` singleton pattern consistent.
