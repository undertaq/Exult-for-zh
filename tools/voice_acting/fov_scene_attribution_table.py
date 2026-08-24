"""FoV mirror-scene speaker-attribution curation (func 0x009A).

Companion table to arcadion_attribution_table.py. The Erethian conversation
shows the Dark Core portrait mid-dialogue, so face-based inference tagged
Erethian's lines as Dark Core and Arcadion's gem-speech as Hook. Same entry
schema as arcadion_attribution_table.TABLE:
  (en_func_id, en_offset_key, en_segment, target_npc,
   expected_current_npc, expected_en_text_prefix)
"""

TABLE = [
    # Erethian's scroll/library dialogue misattributed to Dark Core
    ("0x009A", "c10", 0, "Erethian", "Erethian",
     "\"Very well. I shall need the scroll to give you further information.\""),
    ("0x009A", "c57", 0, "Erethian", "Erethian",
     "\"do you have the Scroll of Infinity amongst your possessions?\""),
    ("0x009A", "c98", 0, "Erethian", "Erethian",
     "\"I needs must touch the scroll to glean its meaning."),
    ("0x009A", "111e", 0, "Erethian", "Erethian",
     "\"If you bringest the scroll to me I can aid the in finding the meaning"),
    ("0x009A", "11a3", 0, "Erethian", "Erethian",
     "\"I once attempted to create a sword of great power.\" Erethian frowns"),
    ("0x009A", "d01", 0, "Erethian", "Erethian",
     "\"Here we are. Now then, it appears to be written in a strange format."),
    # Arcadion speaking from the bonded gem, misattributed to Hook
    ("0x009A", "140f", 0, "Arcadion", "Erethian",
     "The little gem sparks up at this turn of the conversation."),
    ("0x009A", "3ecb", 0, "Arcadion", "Erethian",
     "The gem glows brighter,"),
    # Pure cutscene narration of the bonding ceremony (gem/sword fusion);
    # face inference tagged them Hook via the gem portrait. They describe
    # Arcadion's own transformation -> attribute to Arcadion.
    ("0x06F6", "18c7", 0, "Arcadion", "UNKNOWN",
     "As the gem touches the crosspiece of the sword, the sound of tearing"),
    ("0x06F6", "195f", 0, "Arcadion", "UNKNOWN",
     "Slowly, the sword settles into its original shape, except for the blue"),
    ("0x06F6", "19bf", 0, "Arcadion", "UNKNOWN",
     "There is a flash of what can only be described as black light and the"),
]
