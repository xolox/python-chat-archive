# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: August 1, 2018
# URL: https://github.com/xolox/python-chat-archive

"""Utility functions for working with the HTML encoded text."""

# Standard library modules.
import html
import html.entities
import html.parser
import io
import re

# External dependencies.
from humanfriendly.text import compact_empty_lines
from verboselogs import VerboseLogger

# Public identifiers that require documentation.
__all__ = (
    "BLOCK_TAGS",
    "HTMLStripper",
    "URL_PATTERN",
    "html_to_text",
    "text_to_html",
)

BLOCK_TAGS = ["div", "p", "pre"]
"""
A list of strings with HTML tags that are considered block-level elements. The
:class:`HTMLStripper` emits an empty line before and after each block-level
element that it encounters.
"""

URL_PATTERN = re.compile("(http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+)")
"""
A compiled regular expression pattern to find URLs in text
(credit: taken from `urlregex.com <http://urlregex.com/>`_).
"""

# Initialize a logger for this module.
logger = VerboseLogger(__name__)


def html_to_text(html_text):
    """
    Convert HTML to plain text.

    :param html_text: A fragment of HTML (a string).
    :returns: The plain text (a string).

    This function uses the :class:`HTMLStripper` class that builds on top of
    the :class:`html.parser.HTMLParser` class in the Python standard library.
    """
    parser = HTMLStripper()
    parser.feed(html_text)
    parser.close()
    return parser.output.getvalue()


def text_to_html(text, callback=None):
    """
    Convert plain text to HTML.

    :param text: A fragment of plain text (a string).
    :param callback: An optional callback that provides the caller a chance
                     to pre-process text before it is encoded as HTML.
    :returns: The HTML encoded text (a string).

    This function replaces URLs with ``<a href="...">`` tags
    and escapes special characters, that's it, nothing more.
    """
    as_html = []
    for token in URL_PATTERN.split(text):
        if URL_PATTERN.match(token):
            href = html.escape(token, quote=True)
            text = html.escape(token, quote=False)
            as_html.append('<a href="%s">%s</a>' % (href, text))
        else:
            if callback:
                token = callback(token)
            as_html.append(html.escape(token, quote=False))
    return "".join(as_html)


class HTMLStripper(html.parser.HTMLParser):

    """A simple HTML to text converter based on :class:`html.parser.HTMLParser`."""

    def __call__(self, data):
        """
        Convert HTML to text.

        :param data: The HTML to convert to text (a string).
        :returns: The converted text (a string).

        This method calls :func:`~humanfriendly.text.compact_empty_lines()`
        on the converted text to normalize superfluous empty lines caused
        by vertical whitespace emitted around block level elements like
        ``<div>``, ``<p>`` and ``<pre>``.
        """
        self.reset()
        self.feed(data)
        self.close()
        text = self.output.getvalue()
        return compact_empty_lines(text)

    def handle_charref(self, value):
        """
        Process a decimal or hexadecimal numeric character reference.

        :param value: The decimal or hexadecimal value (a string).
        """
        self.output.write(chr(int(value[1:], 16) if value.startswith("x") else int(value)))

    def handle_data(self, data):
        """Capture decoded text data."""
        self.output.write(data)

    def handle_endtag(self, tag):
        """Emit empty lines around block level elements."""
        if tag in BLOCK_TAGS:
            self.output.write("\n\n")

    def handle_entityref(self, name):
        """
        Process a named character reference.

        :param name: The name of the character reference (a string).
        """
        self.output.write(chr(html.entities.name2codepoint[name]))

    def handle_starttag(self, tag, attrs):
        """Translate ``<br>`` tags to line breaks."""
        if tag == "br":
            self.output.write("\n")
        elif tag in BLOCK_TAGS:
            self.output.write("\n\n")

    def reset(self):
        """Reset the state of the :class:`HTMLStripper` instance."""
        # Reset the state of the superclass.
        super(HTMLStripper, self).reset()
        # Reset our instance variables.
        self.output = io.StringIO()
