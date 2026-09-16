from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DynamicDialogueTemplate:
    function: int
    name: str
    source: str
    anchors: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"dialogue:0x{self.function:04x}:template_{self.name}:0"


# These lines are assembled by U6 usecode from static strings and addsv values.
# Keep the semantic placeholders stable: the runtime translator uses the same
# names when it replaces values in the translated template.
DYNAMIC_DIALOGUE_TEMPLATES = (
    DynamicDialogueTemplate(
        0x0401,
        "iolo_greeting",
        "@Well, <PLAYER_NAME>, do you need help with something? Or maybe "
        "you've got time for a story, eh?@",
        (
            "@Well, ",
            ", do you need help with something? Or maybe you've got time for a story, eh?@",
        ),
    ),
    DynamicDialogueTemplate(
        0x0404,
        "dupre_greeting",
        "@Yes, <PLAYER_NAME>?@",
        ("@Yes, ", "?@"),
    ),
    DynamicDialogueTemplate(
        0x0464,
        "gypsy_path",
        "@The path of the Avatar lies beneath thy feet, worthy "
        "<PLAYER_NAME>@, the gypsy intones. With a mysterious smile, "
        "she passes you the flask of shimmering liquids.",
        (
            "@The path of the Avatar lies beneath thy feet, worthy ",
            "@, the gypsy intones. With a mysterious smile, she passes you the flask of shimmering liquids.",
        ),
    ),
    DynamicDialogueTemplate(
        0x0494,
        "lord_british_greeting",
        "@Good <TIME_OF_DAY>, <PLAYER_NAME>. What wouldst thou speak of?@",
        ("@Good ", ". What wouldst thou speak of?@"),
    ),
    DynamicDialogueTemplate(
        0x0494,
        "lord_british_return_greeting",
        "@<PLAYER_NAME>! 'Tis good to see thee again. Much hath happened since "
        "thou last departed our realm.@",
        (
            "! 'Tis good to see thee again. Much hath happened since thou last departed our realm.@",
        ),
    ),
    DynamicDialogueTemplate(
        0x0494,
        "lord_british_honesty",
        "@<PLAYER_NAME>, I knowest Honesty is one of the virtues and all..@",
        (", I knowest Honesty is one of the virtues and all..@",),
    ),
)
