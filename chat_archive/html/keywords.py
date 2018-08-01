# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: July 22, 2018
# URL: https://github.com/xolox/python-chat-archive

"""Utility functions for working with the HTML encoded text."""

# Standard library modules.
import html
import html.entities
import html.parser
import io
import re

# Public identifiers that require documentation.
__all__ = ("KeywordHighlighter",)


class KeywordHighlighter(html.parser.HTMLParser):

    """A simple keyword highlighter for HTML based on :class:`html.parser.HTMLParser`."""

    def __init__(self, *args, **kw):
        """
        Initialize a :class:`KeywordHighlighter` object.

        :param keywords: A list of strings with keywords to highlight.
        :param highlight_template: A template string with the ``{text}``
                                   placeholder that's used to highlight keyword
                                   matches.
        """
        # Hide keyword arguments from our superclass.
        self.highlight_template = kw.pop("highlight_template")
        # Generate a regular expression to find keywords.
        regex = "(%s)" % "|".join(map(re.escape, kw.pop("keywords")))
        self.pattern = re.compile(regex, re.IGNORECASE)
        # Initialize our superclass.
        super(KeywordHighlighter, self).__init__(*args, **kw)

    def __call__(self, data):
        """
        Highlight keywords in the given HTML fragment.

        :param data: The HTML in which to highlight keywords (a string).
        :returns: The highlighted HTML (a string).
        """
        self.reset()
        self.feed(data)
        self.close()
        return self.output.getvalue()

    def handle_charref(self, value):
        """Process a numeric character reference."""
        self.output.write("&#%s;" % value)

    def handle_data(self, data):
        """Process textual data."""
        for token in self.pattern.split(data):
            escaped = html.escape(token)
            if self.pattern.match(token):
                self.output.write(self.highlight_template.format(text=escaped))
            else:
                self.output.write(escaped)

    def handle_endtag(self, tag):
        """Process an end tag."""
        self.output.write("</%s>" % tag)

    def handle_entityref(self, name):
        """Process a named character reference."""
        self.output.write("&%s;" % name)

    def handle_starttag(self, tag, attrs):
        """Process a start tag."""
        self.output.write("<%s" % tag)
        self.render_attrs(attrs)
        self.output.write(">")

    def handle_startendtag(self, tag, attrs):
        """Process a start tag without end tag."""
        self.output.write("<%s" % tag)
        self.render_attrs(attrs)
        self.output.write("/>")

    def render_attrs(self, attrs):
        """Process the attributes of a tag."""
        for name, value in attrs:
            value = html.escape(value, quote=True)
            self.output.write(' %s="%s"' % (name, value))

    def reset(self):
        """
        Reset the state of the keyword highlighter.

        Clears the output buffer but preserves the keywords to be highlighted.
        This method is called implicitly during initialization.
        """
        # Reset our superclass.
        super(KeywordHighlighter, self).reset()
        # Clear the output buffer.
        self.output = io.StringIO()
