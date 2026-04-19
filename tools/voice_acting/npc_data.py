"""
Shared NPC data for Ultima VII: The Black Gate voice acting tools.

Auto-generated from content/bgkeyring/src/headers/bg/bg_npcs.uc
"""

# NPC name -> positive NPC number
# Function IDs for NPCs are 0x400 + npc_number
NPC_NUMBERS = {
    "Abraham": 299, "Addom": 164, "Aimi": 114, "Alagner": 246,
    "Alina": 169, "Amanda": 48, "Amber": 30, "Andrew": 176,
    "Anmanivas": 217, "Ansikart": 215, "Anton": 240, "Apollonia": 19,
    "Aurvidlem": 219, "Auston": 209, "Avatar": 356, "Balayna": 156,
    "Batlin": 26, "Battles": 135, "Ben": 116, "Bennie": 68, "Betra": 190,
    "Beverlea": 173, "Blacktooth": 226, "Blorn": 208, "Boots": 67,
    "Boris": 130, "Bradman": 104, "Brion": 248, "Brita": 168,
    "Brownie": 60, "Budo": 229, "Burnside": 91, "Cador": 203,
    "Caine": 247, "Cairbre": 244, "Camille": 177, "Candice": 41,
    "Carlyn": 118, "Caroline": 22, "Carrocio": 44, "Catherine": 213,
    "Chad": 161, "Chantu": 17, "Charles": 73, "Chuckles": 25, "Clint": 57,
    "Constance": 133, "Coop": 54, "Cosmo": 253, "Csil": 35, "Cubolt": 155,
    "Cynthia": 42, "D Rel": 112, "Danag": 251, "Daphne": 123,
    "De Maria": 80, "De Snel": 119, "Dell": 18, "Denby": 49,
    "Denton": 199, "Diane": 56, "Draxinusom": 180, "Dupre": 4,
    "Dustin": 235, "Effrem": 160, "Eiko": 15, "Elad": 162, "Eldroth": 206,
    "Elizabeth": 300, "Ellen": 236, "Elynor": 81, "Fenn": 175,
    "Feridwyn": 167, "Figg": 45, "Finnigan": 12, "Fodus": 99,
    "For Lem": 214, "Foranamo": 218, "Forbrak": 189, "Forskis": 298,
    "Forsythe": 147, "Frank": 165, "Fred": 50, "Gargan": 21, "Garok": 110,
    "Garritt": 171, "Gaye": 53, "Geoffrey": 64, "Gharl": 111,
    "Gilberto": 13, "Gladstone": 85, "Glenno": 222, "Gordon": 58,
    "Gordy": 230, "Gorn": 138, "Goth": 117, "Grayson": 55, "Greg": 38,
    "Gregor": 82, "Grod": 154, "Henry": 132, "Hook": 291, "Horance": 141,
    "Horffe": 197, "Hydra": 149, "Ian": 202, "Inforlem": 181,
    "Inmanilem": 182, "Inwisloklem": 71, "Iolo": 1, "Iriale": 128,
    "Iskander": 107, "Jaana": 5, "Jakher": 95, "James": 46,
    "Jeanette": 47, "Jehanne": 194, "Jergi": 96, "Jesse": 28,
    "Jillian": 159, "John Paul": 195, "Johnson": 14, "Jordan": 198,
    "Joseph": 120, "Judith": 40, "Julia": 8, "Kallibrus": 252,
    "Karenna": 94, "Karl": 89, "Katrina": 9, "Kelly": 51, "Kessler": 237,
    "Kissme": 151, "Kliftin": 121, "Klog": 16, "Komor": 174, "Kreg": 245,
    "Kristy": 31, "Lap Lem": 211, "Lasher": 254, "Leavell": 136,
    "Leigh": 201, "Liana": 210, "Lord British": 23, "Lord Heather": 77,
    "Lucky": 228, "Lucy": 37, "Mack": 61, "Magenta": 131, "Malloy": 243,
    "Mama": 255, "Mandy": 231, "Mara": 204, "Margareta": 83, "Mariah": 153,
    "Markham": 140, "Markus": 20, "Martine": 223, "Martingo": 191,
    "Max": 32, "Menion": 192, "Merrick": 170, "Meryl": 234, "Mikos": 97,
    "Millie": 63, "Miranda": 70, "Mole": 227, "Mordra": 143, "Morfin": 172,
    "Morz": 158, "Nanna": 34, "Nastassia": 75, "Nell": 72, "Nelson": 249,
    "Neno": 39, "Nicholas": 33, "Nicodemus": 102, "Nystul": 24,
    "Ophelia": 122, "Owen": 90, "Owings": 239, "Pamela": 78, "Papa": 241,
    "Patterson": 43, "Paul": 233, "Paulette": 145, "Pendaran": 193,
    "Penni": 115, "Penumbra": 150, "Perrin": 238, "Petre": 11,
    "Phearcy": 163, "Polly": 179, "Quaeven": 186, "Quan": 185,
    "Quenton": 146, "Rankin": 250, "Rayburt": 76, "Raymundo": 27,
    "Regal": 271, "Reyna": 108, "Richter": 196, "Roberto": 224,
    "Robin": 134, "Rowena": 144, "Rudyom": 74, "Runeb": 184,
    "Russell": 129, "Rutherford": 92, "Salamon": 101, "Sam": 137,
    "Saralek": 98, "Sarpling": 188, "Sasha": 84, "Sean": 59, "Seara": 88,
    "Sentri": 7, "Shamino": 3, "Sherry": 66, "Silamo": 187, "Sintag": 225,
    "Sir Jeff": 105, "Smith": 113, "Smithy": 232, "Snaz": 62, "Spark": 2,
    "Sprellic": 124, "Stuart": 29, "Sullivan": 220, "Syria": 126,
    "Tavenor": 100, "Taylor": 242, "Teregus": 183, "Thad": 103,
    "Thurston": 166, "Tiery": 106, "Timmons": 127, "Tobias": 178,
    "Tolemac": 157, "Tory": 200, "Trellek": 6, "Trent": 142,
    "Tseramed": 10, "Vokes": 125, "Wayne": 109, "Wench": 221,
    "Weston": 69, "William": 93, "Willy": 52, "Wislem": 65,
    "Wis Sur": 216, "Xanthia": 86, "Xorinia": 256, "Yongi": 207,
    "Yvella": 212, "Zaksam": 205, "Zelda": 152, "Zella": 36,
    "Zinaida": 79, "Zorn": 87,
    # Forge of Virtue expansion NPCs
    "Erethian": 286, "Ferryman": 285, "Time Lord": 284,
    "Stone Guardian": 277, "Shrine": 287,
    "Bollux": 288, "Adjhar": 289, "Dark Core": 292,
    "Dracothraxus": 293,
    # Guards and misc NPCs (not in bgkeyring)
    "Guard": 259, "Palace Guard": 258,
    "Arcadion": 273,
    # Hydra heads (Ambrosia)
    "Shandu": 280, "Shando": 281, "Shanda": 282,
}

# Reverse lookup: NPC number -> name
NPC_NAMES = {v: k for k, v in NPC_NUMBERS.items()}

# Function ID (0x400 + npc_num) -> NPC name
# Used by the disassembler for speaker detection
BG_NPC_FUNC_NAMES = {0x400 + num: name for name, num in NPC_NUMBERS.items()}


def get_npc_name_by_func(func_id):
    """Get NPC name for a usecode function ID, or empty string if unknown."""
    return BG_NPC_FUNC_NAMES.get(func_id, "")


def get_npc_name_by_num(npc_num):
    """Get NPC name for a positive NPC number, or empty string if unknown."""
    return NPC_NAMES.get(npc_num, "")


def get_npc_number(name):
    """Get positive NPC number for a name, or None if unknown."""
    return NPC_NUMBERS.get(name)
