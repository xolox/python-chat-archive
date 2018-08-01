# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: August 1, 2018
# URL: https://github.com/xolox/python-chat-archive

"""
Utility functions to pre-process URLs before rendering on a terminal.

In web browsers and chat clients the URLs behind hyperlinks are usually hidden,
but in a terminal there's no "out of band" mechanism to communicate the URL
behind a hyperlink - the URL needs to appear literally in the text that is
rendered to the terminal.

Given this requirement, I've become rather annoyed at Google prefixing every
URL they can get their hands on with ``https://www.google.com/url?q=…`` because
this user hostile "encoding" obscures the intended URL with a lot of fluff that
I don't care for.

This module contains the :func:`expand_url()` function to transform redirect
URLs into their target URL, the :func:`strip_redirects()` function to
transform all redirect URLs in a given text and :class:`RedirectStripper` to
transform all redirect URLs in a given HTML fragment.
"""

# Standard library modules.
import html
import html.entities
import html.parser
import io
import re
import urllib.parse

# External dependencies.
from verboselogs import VerboseLogger

# Public identifiers that require documentation.
__all__ = (
    "GOOGLE_REDIRECT_URL",
    "RedirectStripper",
    "URL_PATTERN",
    "expand_url",
    "logger",
    "strip_redirects",
    "strip_redirects_callback",
)

GOOGLE_REDIRECT_URL = "www.google.com/url"
"""
The base URL of the Google redirect service (a string).

Note that the URL scheme is omitted on purpose, to enable a substring
search for the Google redirect service regardless of whether a given
URL is using the ``http://`` or ``https://`` scheme.
"""

URL_PATTERN = re.compile("http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")
"""
A compiled regular expression pattern to find URLs in text
(credit: taken from `urlregex.com <http://urlregex.com/>`_).
"""

# Initialize a logger for this module.
logger = VerboseLogger(__name__)


def expand_url(url):
    """
    Expand a redirect URL to its target URL.

    :param url: The URL to expand (a string).
    :returns: The expanded URL (a string).
    """
    if GOOGLE_REDIRECT_URL in url:
        logger.debug("Trying to expand redirect URL: %r", url)
        components = urllib.parse.urlparse(url)
        if components.netloc == "www.google.com" and components.path == "/url":
            parameters = urllib.parse.parse_qs(components.query)
            values = parameters.get("q")
            if values:
                logger.debug("Extracted redirect URL: %r", values[0])
                return values[0]
        logger.debug("Failed to expand redirect URL!")
    return url


def strip_redirects(text):
    """
    Expand redirect URLs in the given text.

    :param text: The text to process (a string).
    :returns: The processed text (a string).
    """
    return URL_PATTERN.sub(strip_redirects_callback, text)


def strip_redirects_callback(match):
    """Apply :func:`expand_url()` to the matched URL."""
    return expand_url(match.group(0))


class RedirectStripper(html.parser.HTMLParser):

    """
    Expand redirect URLs embedded in HTML.

    This class uses :class:`html.parser.HTMLParser` to parse HTML and expand
    any redirect URLs that it encounters to their target URL. The
    :func:`__call__()` method provides an easy way to use this functionality.
    """

    def __call__(self, data):
        """
        Pre-process the URLs in the given HTML fragment.

        :param data: The HTML to pre-process (a string).
        :returns: The pre-processed HTML (a string).
        """
        if GOOGLE_REDIRECT_URL in data:
            self.reset()
            self.feed(data)
            self.close()
            data = self.output.getvalue()
        return data

    def handle_charref(self, value):
        """Process a numeric character reference."""
        html_fragment = "&#%s;" % value
        if self.link_active:
            self.link_html.append(html_fragment)
            self.link_text.append(chr(int(value[1:], 16) if value.startswith("x") else int(value)))
        else:
            self.output.write(html_fragment)

    def handle_data(self, data):
        """Process textual data."""
        html_fragment = html.escape(data, quote=False)
        if self.link_active:
            self.link_html.append(html_fragment)
            self.link_text.append(data)
        else:
            self.output.write(html_fragment)

    def handle_endtag(self, tag):
        """Process an end tag."""
        if tag == "a":
            # Emit the (modified) link text.
            text_done = False
            link_text = "".join(self.link_text)
            if URL_PATTERN.match(link_text):
                expanded_text = expand_url(link_text)
                if expanded_text != link_text:
                    # It seems that the link text was a redirect URL that we
                    # expanded. Emit the modified URL on the output stream.
                    self.output.write(html.escape(expanded_text, quote=False))
                    text_done = True
            if not text_done:
                # When we fail to expand the link text as a redirect URL, we
                # emit the HTML that was originally contained in the link tag.
                self.output.write("".join(self.link_html))
            self.link_active = False
        # Generate and emit the HTML fragment.
        html_fragment = "</%s>" % tag
        if self.link_active:
            self.link_html.append(html_fragment)
        else:
            self.output.write(html_fragment)

    def handle_entityref(self, name):
        """Process a named character reference."""
        html_fragment = "&%s;" % name
        if self.link_active:
            self.link_html.append(html_fragment)
            self.link_text.append(chr(html.entities.name2codepoint[name]))
        else:
            self.output.write(html_fragment)

    def handle_starttag(self, tag, attrs):
        """Process a start tag."""
        if tag == "a":
            # Expand the URL in the 'href' attribute?
            attrs = dict(attrs)
            if attrs.get("href"):
                attrs["href"] = expand_url(attrs["href"])
            attrs = attrs.items()
        # Generate and emit the HTML fragment.
        html_fragment = self.render_tag(tag, attrs, False)
        if self.link_active:
            self.link_html.append(html_fragment)
        else:
            self.output.write(html_fragment)
        # Start collecting the content of an <a> tag?
        if tag == "a":
            self.link_active = True
            self.link_html = []
            self.link_text = []

    def handle_startendtag(self, tag, attrs):
        """Process a start tag without end tag."""
        html_fragment = self.render_tag(tag, attrs, True)
        if self.link_active:
            self.link_html.append(html_fragment)
        else:
            self.output.write(html_fragment)

    def render_tag(self, tag, attrs, close):
        """Process the attributes of a tag."""
        rendered = ["<", tag]
        for name, value in attrs:
            value = html.escape(value, quote=True)
            rendered.append(' %s="%s"' % (name, value))
        rendered.append("/>" if close else ">")
        return "".join(rendered)

    def reset(self):
        """
        Reset the state of the keyword highlighter.

        Clears the output buffer but preserves the keywords to be highlighted.
        This method is called implicitly during initialization.
        """
        # Reset our superclass.
        super(RedirectStripper, self).reset()
        # Reset our instance variables.
        self.output = io.StringIO()
        self.link_active = False
        self.link_text = []
        self.link_html = []
