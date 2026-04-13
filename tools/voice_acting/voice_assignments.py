"""
Voice actor assignments for Ultima VII: The Black Gate NPCs.

Maps speaker names to ElevenLabs voice IDs. Edit this file to change
which voice is used for each character.

Custom voices (cloned on ElevenLabs):
  - Iolo: aV8DLAt0Q9peDuTGGPx5
  - Finnigan: l1d1DlQ9BVMMQMoVx1oe

Stock ElevenLabs voices:
  Male:   Roger, Charlie, George, Callum, Harry, Liam, Will, Eric,
          Chris, Brian, Daniel, Adam, Bill
  Female: Sarah, Laura, Alice, Matilda, Jessica, Bella, Lily
  Neutral: River
"""

# ElevenLabs stock voice IDs
STOCK_VOICES = {
    "Roger":   "CwhRBWXzGAHq8TQ4Fs17",
    "Sarah":   "EXAVITQu4vr4xnSDxMaL",
    "Laura":   "FGY2WhTYpPnrIDTdsKH5",
    "Charlie": "IKne3meq5aSn9XLyUdCD",
    "George":  "JBFqnCBsd6RMkjVDRZzb",
    "Callum":  "N2lVS1w4EtoT3dr4eOWO",
    "River":   "SAz9YHcvj6GT2YYXdXww",
    "Harry":   "SOYHLrjzK2X1ezoPC6cr",
    "Liam":    "TX3LPaxmHKxFdv7VOQHJ",
    "Alice":   "Xb7hH8MSUJpSbSDYk0k2",
    "Matilda": "XrExE9yKIg1WjnnlVkGX",
    "Will":    "bIHbv24MWmeRgasZH58o",
    "Jessica": "cgSgspJ2msm6clMCkdW9",
    "Eric":    "cjVigY5qzO86Huf0OWal",
    "Bella":   "hpp4J3VqNfWAUOO0d1Us",
    "Chris":   "iP95p4xoKVk53GoZ742B",
    "Brian":   "nPczCjzI2devNBz1zQrb",
    "Daniel":  "onwK4e9ZLuTAKqWW03F9",
    "Lily":    "pFZP5JQG7iQjIQuC4Bku",
    "Adam":    "pNInz6obpgDQGcFmaJgB",
    "Bill":    "pqHfZKP75CvOlQylNhV4",
}

# Custom cloned voice IDs
CUSTOM_VOICES = {
    "Iolo_custom":     "aV8DLAt0Q9peDuTGGPx5",
    "Finnigan_custom": "l1d1DlQ9BVMMQMoVx1oe",
}

# Default voice for unassigned speakers
DEFAULT_VOICE_ACTOR = "Chris"
DEFAULT_VOICE_ID = STOCK_VOICES["Chris"]

# NPC speaker -> (voice_id, voice description)
# Edit the voice actor name to reassign a character's voice.
VOICE_MAP = {
    # --- Party members ---
    "Iolo":        (CUSTOM_VOICES["Iolo_custom"], "Iolo (custom)"),
    "Spark":       ("E95NigJoVU5BI8HjQeN3",       "Spark (custom)"),
    "Shamino":     (STOCK_VOICES["Chris"],        "Chris"),
    "Dupre":       (STOCK_VOICES["George"],       "George"),
    "Jaana":       (STOCK_VOICES["Laura"],        "Laura"),
    "Sentri":      (STOCK_VOICES["Callum"],       "Callum"),
    "Julia":       (STOCK_VOICES["Alice"],        "Alice"),
    "Katrina":     (STOCK_VOICES["Sarah"],        "Sarah"),
    "Tseramed":    (STOCK_VOICES["Liam"],         "Liam"),

    # --- Trinsic ---
    "Finnigan":    (CUSTOM_VOICES["Finnigan_custom"], "Finnigan (custom)"),
    "Petre":       ("chcMmmtY1cmQh2ye1oXi",       "Petre (custom)"),
    "Gilberto":    ("7rQX8r6PVq3gfJ8rZzyE",       "Gilberto (custom)"),
    "Johnson":     ("2OcnG4mH3jIMtWz3vKus",       "Johnson (custom)"),
    "Klog":        ("IRHApOXLvnW57QJPQH2P",       "Klog (custom)"),
    "Chantu":      ("BBfN7Spa3cqLPH1xAS22",       "Chantu (custom)"),
    "Dell":        ("M5E055lOUxMi0kJpGyE9",       "Dell (custom)"),
    "Apollonia":   ("XdflFrQO8wbGpWMNZHFr",       "Apollonia (custom)"),
    "Markus":      ("6sFKzaJr574YWVu4UuJF",       "Markus (custom)"),
    "Gargan":      ("Av4Fi2idMFuA8kTbVZgv",       "Gargan (custom)"),
    "Caroline":    ("4BAlflaQyhIcCfHiEI7x",       "Caroline (custom)"),
    "Ellen":       ("lUCNYQh2kqW2wiie85Qk",       "Ellen (custom)"),
    "Guard":       ("agL69Vji082CshT65Tcy",       "Guard (custom)"),

    # --- Britain ---
    "Lord British": (STOCK_VOICES["George"],      "George"),
    "Nystul":      (STOCK_VOICES["Bill"],         "Bill"),
    "Chuckles":    (STOCK_VOICES["Charlie"],      "Charlie"),
    "Batlin":      (STOCK_VOICES["Daniel"],       "Daniel"),
    "Raymundo":    (STOCK_VOICES["Eric"],         "Eric"),
    "Jesse":       (STOCK_VOICES["Liam"],         "Liam"),
    "Stuart":      (STOCK_VOICES["Callum"],       "Callum"),
    "Amber":       (STOCK_VOICES["Sarah"],        "Sarah"),
    "Kristy":      (STOCK_VOICES["Lily"],         "Lily"),
    "Max":         (STOCK_VOICES["Will"],         "Will"),
    "Nicholas":    (STOCK_VOICES["Will"],         "Will"),
    "Nanna":       (STOCK_VOICES["Matilda"],      "Matilda"),
    "Csil":        (STOCK_VOICES["Laura"],        "Laura"),
    "Zella":       (STOCK_VOICES["Alice"],        "Alice"),
    "Lucy":        (STOCK_VOICES["Jessica"],      "Jessica"),
    "Greg":        (STOCK_VOICES["Roger"],        "Roger"),
    "Neno":        (STOCK_VOICES["Adam"],         "Adam"),
    "Judith":      (STOCK_VOICES["Bella"],        "Bella"),
    "Candice":     (STOCK_VOICES["Sarah"],        "Sarah"),
    "Cynthia":     (STOCK_VOICES["Laura"],        "Laura"),
    "Patterson":   (STOCK_VOICES["Brian"],        "Brian"),
    "Carrocio":    (STOCK_VOICES["Eric"],         "Eric"),
    "Figg":        (STOCK_VOICES["Roger"],        "Roger"),
    "James":       (STOCK_VOICES["Harry"],        "Harry"),
    "Jeanette":    (STOCK_VOICES["Jessica"],      "Jessica"),
    "Denby":       (STOCK_VOICES["Callum"],       "Callum"),
    "Fred":        (STOCK_VOICES["Adam"],         "Adam"),
    "Kelly":       (STOCK_VOICES["Bella"],        "Bella"),
    "Willy":       (STOCK_VOICES["Charlie"],      "Charlie"),
    "Gaye":        (STOCK_VOICES["Alice"],        "Alice"),
    "Coop":        (STOCK_VOICES["Liam"],         "Liam"),
    "Grayson":     (STOCK_VOICES["Daniel"],       "Daniel"),
    "Diane":       (STOCK_VOICES["Matilda"],      "Matilda"),
    "Clint":       (STOCK_VOICES["Harry"],        "Harry"),
    "Gordon":      (STOCK_VOICES["Roger"],        "Roger"),
    "Sean":        (STOCK_VOICES["Eric"],         "Eric"),
    "Brownie":     (STOCK_VOICES["Brian"],        "Brian"),
    "Mack":        (STOCK_VOICES["Adam"],         "Adam"),
    "Snaz":        (STOCK_VOICES["Will"],         "Will"),
    "Millie":      (STOCK_VOICES["Laura"],        "Laura"),
    "Geoffrey":    (STOCK_VOICES["George"],       "George"),
    "Wislem":      (STOCK_VOICES["Callum"],       "Callum"),
    "Sherry":      (STOCK_VOICES["Lily"],         "Lily"),
    "Boots":       (STOCK_VOICES["Bella"],        "Bella"),
    "Bennie":      (STOCK_VOICES["Liam"],         "Liam"),
    "Weston":      (STOCK_VOICES["Harry"],        "Harry"),
    "Miranda":     (STOCK_VOICES["Alice"],        "Alice"),
    "Inwisloklem": (STOCK_VOICES["Daniel"],       "Daniel"),
    "Nell":        (STOCK_VOICES["Jessica"],      "Jessica"),
    "Charles":     (STOCK_VOICES["Eric"],         "Eric"),
    "Kessler":     (STOCK_VOICES["Adam"],         "Adam"),

    # --- Cove ---
    "Rudyom":      (STOCK_VOICES["Bill"],         "Bill"),
    "Nastassia":   (STOCK_VOICES["Sarah"],        "Sarah"),
    "Rayburt":     (STOCK_VOICES["Harry"],        "Harry"),
    "Lord Heather": (STOCK_VOICES["George"],      "George"),
    "Pamela":      (STOCK_VOICES["Laura"],        "Laura"),
    "Zinaida":     (STOCK_VOICES["Matilda"],      "Matilda"),
    "De Maria":    (STOCK_VOICES["Eric"],         "Eric"),

    # --- Minoc ---
    "Elynor":      (STOCK_VOICES["Bella"],        "Bella"),
    "Gregor":      (STOCK_VOICES["Roger"],        "Roger"),
    "Margareta":   (STOCK_VOICES["Jessica"],      "Jessica"),
    "Sasha":       (STOCK_VOICES["Alice"],        "Alice"),
    "Gladstone":   (STOCK_VOICES["Brian"],        "Brian"),
    "Xanthia":     (STOCK_VOICES["Laura"],        "Laura"),
    "Zorn":        (STOCK_VOICES["Daniel"],       "Daniel"),
    "Seara":       (STOCK_VOICES["Sarah"],        "Sarah"),
    "Karl":        (STOCK_VOICES["Liam"],         "Liam"),
    "Owen":        (STOCK_VOICES["Adam"],         "Adam"),
    "Burnside":    (STOCK_VOICES["George"],       "George"),
    "Rutherford":  (STOCK_VOICES["Charlie"],      "Charlie"),
    "William":     (STOCK_VOICES["Callum"],       "Callum"),
    "Karenna":     (STOCK_VOICES["Matilda"],      "Matilda"),
    "Jakher":      (STOCK_VOICES["Harry"],        "Harry"),

    # --- Yew ---
    "Trellek":     (STOCK_VOICES["River"],        "River"),
    "Nicodemus":   (STOCK_VOICES["Bill"],         "Bill"),
    "Reyna":       (STOCK_VOICES["Alice"],        "Alice"),
    "Perrin":      (STOCK_VOICES["Eric"],         "Eric"),

    # --- Jhelom ---
    "De Snel":     (STOCK_VOICES["Callum"],       "Callum"),
    "Joseph":      (STOCK_VOICES["George"],       "George"),

    # --- New Magincia ---
    "Alagner":     (STOCK_VOICES["Bill"],         "Bill"),
    "Rankin":      (STOCK_VOICES["Daniel"],       "Daniel"),

    # --- Skara Brae ---
    "Trent":       (STOCK_VOICES["Adam"],         "Adam"),
    "Mordra":      (STOCK_VOICES["Matilda"],      "Matilda"),

    # --- Moonglow ---
    "Mariah":      (STOCK_VOICES["Laura"],        "Laura"),
    "Brion":       (STOCK_VOICES["Liam"],         "Liam"),

    # --- Paws ---
    "Merrick":     (STOCK_VOICES["Brian"],        "Brian"),
    "Garritt":     (STOCK_VOICES["Will"],         "Will"),
    "Richter":     (STOCK_VOICES["Roger"],        "Roger"),

    # --- Serpent's Hold ---
    "Menion":      (STOCK_VOICES["Harry"],        "Harry"),
    "Leigh":       (STOCK_VOICES["Alice"],        "Alice"),
    "Tory":        (STOCK_VOICES["Sarah"],        "Sarah"),

    # --- Vesper ---
    "Inforlem":    (STOCK_VOICES["Daniel"],       "Daniel"),
    "Zaksam":      (STOCK_VOICES["Adam"],         "Adam"),

    # --- Buccaneer's Den ---
    "Lucky":       (STOCK_VOICES["Charlie"],      "Charlie"),
    "Danag":       (STOCK_VOICES["Eric"],         "Eric"),

    # --- Misc ---
    "Bradman":     (STOCK_VOICES["Callum"],       "Callum"),
    "Chad":        (STOCK_VOICES["Liam"],         "Liam"),
    "Jillian":     (STOCK_VOICES["Laura"],        "Laura"),
    "Penni":       (STOCK_VOICES["Bella"],        "Bella"),
}


def get_voice(speaker_name):
    """Get (voice_id, voice_description) for a speaker.
    Returns default voice if speaker is not in the map."""
    if speaker_name in VOICE_MAP:
        return VOICE_MAP[speaker_name]
    return (DEFAULT_VOICE_ID, f"{DEFAULT_VOICE_ACTOR} (default)")
