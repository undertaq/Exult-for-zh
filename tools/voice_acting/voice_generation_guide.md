replace the <> with best one, and after replacement, check the fluence of the text
delimiter balance: if single text is split into multiple lines, make sure th the dilimiter is blanaced. It will be used for TTS to identify narrator or speaker.
Update 'Twould => It would, 'Tis => It is ... to make TTS generate correct pronouncation.

After each update, you need to verify the correctness in different way.

X Morfin => 「在這裡。」沒聲音 2
X Ferryman, Rudyom => 中文有前綴話
Anmanivas => index:6146「"聖者！」聖者 「是造成我們不快樂的原因。」請依照en_text 調整成較順的語句
Jesse => 中英文旁白應該為男生
Dracothraxus => 143 vs 134 duplicate en_text, zh_text: Dracothraxus sniffs the air distastefully, 「我聞到了毀滅的氣息。或許，我終於要獲得自由了。祝你好運，凡人。自求多福吧！」說完，巨龍便撲向了你。 沒有完全翻譯到

Some zh_text is not translated or fully trasnslated to Chinese, update the translation script, tranlate. e.g. index:2699, 143, 134

Full all the above fix, , update the corresponding patch script, marked them, and regeneration these voice only. DO NOT modify other voices.


請檢查以上問題的來源，請先列出對應的聲音檔，提供解法。不要重新產生。