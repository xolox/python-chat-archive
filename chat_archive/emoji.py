# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: July 15, 2018
# URL: https://github.com/xolox/python-chat-archive

"""Utility functions to translate between various forms of smilies and emoji."""

# Standard library modules.
import re

# External dependencies.
import emoji

# Public identifiers that require documentation.
__all__ = ("normalize_emoji",)

TEXT_TO_EMOJI_MAPPING = {
    ":'-)": "😂",
    ":(": "😞",
    ":)": "🙂",
    ":-(": "😞",
    ":-)": "🙂",
    ":-/": "😕",
    ":-\\": "😕",
    ":-p": "😛",
    ":-|": "😐️",
    ":p": "😛",
    ":|": "😐️",
    ";-)": "😉",
}
"""Mapping of textual smilies to color emoji."""

WHITE_TO_EMOJI_MAPPING = {"☺": "🙂", "😊︎": "😊️", "😐︎": "😐️", "☹": "☹️"}
"""Mapping of white (hollow/outlined) smilies to color emoji."""

# Compile regular expressions that we can use to find the keys in the
# dictionaries above and replace them with the corresponding values.
TEXT_TO_EMOJI_PATTERN = re.compile(
    r"(?:^|(?<=\s))(?:%s)(?=(?:\s|$))" % "|".join(map(re.escape, TEXT_TO_EMOJI_MAPPING)), re.IGNORECASE
)
WHITE_TO_EMOJI_PATTERN = re.compile("|".join(WHITE_TO_EMOJI_MAPPING))


def normalize_emoji(text):
    """Translate textual smilies, hollow smilies and macros to color emoji."""
    # Translate textual smilies to color emoji.
    text = re.sub(TEXT_TO_EMOJI_PATTERN, text_to_emoji_callback, text)
    # Translate hollow smilies to color emoji.
    text = re.sub(WHITE_TO_EMOJI_PATTERN, white_to_emoji_callback, text)
    # Translate text macros to color emoji.
    return emoji.emojize(text, use_aliases=True)


def text_to_emoji_callback(match):
    """Translate a textual smiley to a color emoji."""
    return TEXT_TO_EMOJI_MAPPING[match.group(0).lower()]


def white_to_emoji_callback(match):
    """Translate a white smiley to a color emoji."""
    return WHITE_TO_EMOJI_MAPPING[match.group(0)]
