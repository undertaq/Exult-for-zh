#!/usr/bin/env python3
import json
import unittest
from pathlib import Path


MAPPING_PATH = Path(__file__).with_name("bilingual_mapping_review.json")


class PlayerNameAvatarReplacementTest(unittest.TestCase):
    def test_known_player_name_avatar_replacements_are_natural(self):
        with open(MAPPING_PATH, encoding="utf-8") as f:
            rows = json.load(f)

        expected = {
            (0x0401, "af_151_254", 1): (
                "\"My friend! If I did not trust the infallibility of mine own eyes, I would not believe it! I was just thinking to myself, 'If only the Avatar were here!' Then...\"",
                "「 喂，你可知道，老朋友。從上次見面到現在，Britannia 已經過兩百年了，怎麼你都沒老？」",
            ),
            (0x0401, "817_847", 0): (
                "\"Why, there is no doubt -thou- art the Avatar! However, thou mayest have some trouble convincing those who do not know thy face.\"",
                "「毫無疑問，-你- 就是聖者！不過，你可能很難說服那些不認識你長相的人。」",
            ),
            (0x040C, "3a3_433", 0): (
                "\"Why, this is the Avatar!\" Iolo proudly proclaims. \"Canst thou believe it? May I introduce thee? This is Finnigan, the Town Mayor. And this is our friend, the Avatar!\"",
                "「哎呀，這位是聖者！」 Iolo 自豪地宣布。「你敢相信嗎？請容我為你介紹？這位是 Trinsic 的鎮長 Finnigan。而這位是我們的朋友，聖者！」",
            ),
            (0x0436, "3c5_3db", 0): (
                "\"Hello, lad! This is the Avatar! This is my young apprentice, Coop. How go things, Coop?\"",
                "「你好啊，小夥子！這位是聖者！這是我的年輕學徒， Coop 。最近好嗎， Coop ？」",
            ),
            (0x0442, "d_89", 1): (
                "\"Avatar!\" she exclaims. \"I cannot believe thou art here!\"",
                "「聖者！」她驚呼道。「我不敢相信你在這裡！」",
            ),
            (0x048D, "6ca_70b", 1): (
                "\"Yes, mortal. The dead will rule! I will be their leader and thou canst become an Avatar... to ME!\"",
                "「是的，凡人。死者將會統治！我將成為他們的領袖，而你可以成為一個聖者……為我服務！」",
            ),
            (0x048F, "2e3_2ec_342", 1): (
                "\"And thou must be the Avatar.\" She looks you over thoroughly.",
                "「而你一定就是聖者。」她從頭到腳打量著你。",
            ),
            (0x04AA, "212_238", 0): (
                "\"I do most humbly apologize to thee. As I am certain thou art aware, there have been many who have claimed to be the one and only true Avatar ever since thou hast last visited us.\"",
                "「我最謙卑地向你道歉。我相信你一定知道，自從你上次造訪我們以來，有許多人聲稱自己是唯一真正的聖者。」",
            ),
            (0x04C3, "130_162", 0): (
                "\"I am Lord John-Paul of Serpent's Hold. Thou art the Avatar, correct?\"",
                "「我是 Serpent's Hold 的 John-Paul 領主。你就是聖者，對吧？」",
            ),
            (0x08F4, "11d_130_133", 0): (
                "\"How may I assist thee, Avatar?\"",
                "「我該如何協助你，聖者？」",
            ),
        }

        by_key = {}
        for row in rows:
            func = row.get("en_func_id", "")
            if isinstance(func, str) and func.lower().startswith("0x"):
                func = int(func, 16)
            by_key[(func, row.get("en_offset_key"), row.get("en_segment"))] = row

        for key, (en_text, zh_text) in expected.items():
            row = by_key[key]
            self.assertEqual(row["en_text"], en_text)
            self.assertEqual(row["zh_text"], zh_text)

    def test_no_obvious_avatar_title_duplicates_remain(self):
        with open(MAPPING_PATH, encoding="utf-8") as f:
            rows = json.load(f)

        bad_fragments = [
            "Avatar, the Avatar",
            "Avatar, Avatar",
            "聖者，聖者",
            "聖者，是聖者",
        ]
        offenders = []
        for index, row in enumerate(rows):
            text = "\n".join([row.get("en_text", ""), row.get("zh_text", "")])
            if any(fragment in text for fragment in bad_fragments):
                offenders.append(index)

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
