## Goal
Add Chinese/English bilingual text, voice support. 
Add GUI settings in "Audio Options" to runtime switch "Text" language and "Voice" language independently. 


## Guide
1. Use codebase-memory to analysis the project first.
2. The Chinese text support is ready with patch in <project dir>\..\Ultima_7\patch\ 
3. Voice support for dialogue only, text support for all text, which is already done.
4. You can reference the current Chinese usecode in <project dir>\..\Ultima_7\patch\usecode.zh and English usecode in <project dir>\..\Ultima_7\STATIC\usecode
5. Dynamic switch the usecode, textmsg.txt, spellnames.txt, ...which related to translation at runtime.
6. Since the Chinese usecode and English usecode has different key and offset, build a mapping table for voice mapping.
