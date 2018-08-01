# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: August 1, 2018
# URL: https://github.com/xolox/python-chat-archive

"""
Usage: chat-archive [OPTIONS] [COMMAND]

Easy to use offline chat archive that can gather chat message
history from Google Talk, Google Hangouts, Slack and Telegram.

Supported commands:

- The 'sync' command downloads new chat messages from supported chat
  services and stores them in the local archive (an SQLite database).

- The 'search' command searches the chat messages in the local archive
  for the given keyword(s) and lists matching messages.

- The 'list' command lists all messages in the local archive.

- The 'stats' command shows statistics about the local archive.

- The 'unknown' command searches for conversations that contain messages from
  an unknown sender and allows you to enter the name of a new contact to
  associate with all of the messages from an unknown sender. Conversations
  involving multiple unknown sender are not supported.

Supported options:

  -C, --context=COUNT

    Print COUNT messages of output context during 'chat-archive search'. This
    works similarly to 'grep -C'. The default value of COUNT is 3.

  -f, --force

    Retry synchronization of conversations where errors were previously
    encountered. This option is currently only relevant to the Google Hangouts
    backend, because I kept getting server errors when synchronizing a few
    specific conversations and I didn't want to keep seeing each of those
    errors during every synchronization run :-).

  -c, --color=CHOICE, --colour=CHOICE

    Specify whether ANSI escape sequences for text and background colors and
    text styles are to be used or not, depending on the value of CHOICE:

    - The values 'always', 'true', 'yes' and '1' enable colors.
    - The values 'never', 'false', 'no' and '0' disable colors.
    - When the value is 'auto' (this is the default) then colors will
      only be enabled when an interactive terminal is detected.

  -l, --log-file=LOGFILE

    Save logs at DEBUG verbosity to the filename given by LOGFILE. This option
    was added to make it easy to capture the log output of an initial
    synchronization that will be downloading thousands of messages.

  -p, --profile=FILENAME

    Enable profiling of the chat-archive application to make it possible to
    analyze performance problems. Python profiling data will be saved to
    FILENAME every time database changes are committed (making it possible to
    inspect the profile while the program is still running).

  -v, --verbose

    Increase logging verbosity (can be repeated).

  -q, --quiet

    Decrease logging verbosity (can be repeated).

  -h, --help

    Show this message and exit.
"""

# Standard library modules.
import getopt
import html
import logging
import os
import sys

# External dependencies.
import coloredlogs
from humanfriendly import coerce_boolean, compact, concatenate, format_path, format_size, parse_path, pluralize
from humanfriendly.prompts import prompt_for_input
from humanfriendly.terminal import HTMLConverter, connected_to_terminal, find_terminal_size, output, usage, warning
from property_manager import lazy_property, mutable_property
from sqlalchemy import func
from verboselogs import VerboseLogger

# Modules included in our package.
from chat_archive import ChatArchive
from chat_archive.emoji import normalize_emoji
from chat_archive.html import HTMLStripper, text_to_html
from chat_archive.html.keywords import KeywordHighlighter
from chat_archive.html.redirects import RedirectStripper
from chat_archive.models import Contact, Conversation, Message
from chat_archive.utils import utc_to_local

FORMATTING_TEMPLATES = dict(
    conversation_delimiter='<span style="color: green">{text}</span>',
    conversation_name='<span style="font-weight: bold; color: #FCE94F">{text}</span>',
    keyword_highlight='<span style="color: black; background-color: yellow">{text}</span>',
    message_backend='<span style="color: #C4A000">({text})</span>',
    message_contacts='<span style="color: blue">{text}</span>',
    message_delimiter='<span style="color: #555753">{text}</span>',
    message_timestamp='<span style="color: green">{text}</span>',
)
"""The formatting of output, specified as HTML with placeholders."""

UNKNOWN_CONTACT_LABEL = "Unknown"
"""The label for contacts without a name or email address (a string)."""

# Initialize a logger for this module.
logger = VerboseLogger(__name__)


def main():
    """Command line interface for the ``chat-archive`` program."""
    # Enable logging to the terminal.
    coloredlogs.install()
    # Parse the command line options.
    program_opts = dict()
    command_name = None
    try:
        options, arguments = getopt.gnu_getopt(
            sys.argv[1:],
            "C:fl:c:p:vqh",
            [
                "context=",
                "force",
                "log-file=",
                "color=",
                "colour=",
                "profile=",
                "verbose",
                "quiet",
                "help",
            ],
        )
        for option, value in options:
            if option in ("-C", "--context"):
                program_opts["context"] = int(value)
            elif option in ("-f", "--force"):
                program_opts["force"] = True
            elif option in ("-l", "--log-file"):
                handler = logging.FileHandler(parse_path(value))
                handler.setFormatter(
                    logging.Formatter(
                        fmt="%(asctime)s %(name)s[%(process)d] %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
                    )
                )
                handler.setLevel(logging.DEBUG)
                logging.root.addHandler(handler)
                logging.root.setLevel(logging.NOTSET)
            elif option in ("-c", "--color", "--colour"):
                mapping = dict(always=True, never=False)
                program_opts["use_colors"] = mapping[value] if value in mapping else coerce_boolean(value)
            elif option in ("-p", "--profile"):
                program_opts["profile_file"] = parse_path(value)
            elif option in ("-v", "--verbose"):
                coloredlogs.increase_verbosity()
            elif option in ("-q", "--quiet"):
                coloredlogs.decrease_verbosity()
            elif option in ("-h", "--help"):
                usage(__doc__)
                sys.exit(0)
            else:
                assert False, "Unhandled option!"
        # Make sure the operator provided a command.
        if not arguments:
            usage(__doc__)
            sys.exit(0)
    except Exception as e:
        warning("Failed to parse command line arguments: %s", e)
        sys.exit(1)
    try:
        # We extract any search keywords from the command line arguments before
        # initializing an instance of the UserInterface class, to enable
        # initialization of the KeywordHighlighter class.
        if arguments[0] == "search":
            program_opts["keywords"] = arguments[1:]
        # Initialize the chat archive.
        with UserInterface(**program_opts) as program:
            # Validate the requested command.
            command_name = arguments.pop(0)
            method_name = "%s_cmd" % command_name
            if not hasattr(program, method_name):
                warning("Error: Invalid command name '%s'!", command_name)
                sys.exit(1)
            # Execute the requested command.
            command_fn = getattr(program, method_name)
            command_fn(arguments)
    except KeyboardInterrupt:
        logger.notice("Interrupted by Control-C ..")
        sys.exit(1)
    except Exception:
        logger.exception("Aborting due to unexpected exception!")
        sys.exit(1)


class UserInterface(ChatArchive):

    """The Python API for the command line interface for the ``chat-archive`` program."""

    @mutable_property
    def context(self):
        """The number of messages of output context to print during searches (defaults to 3)."""
        return 3

    @mutable_property(cached=True)
    def use_colors(self):
        """Whether to output ANSI escape sequences for text colors and styles (a boolean)."""
        return connected_to_terminal()

    @lazy_property
    def html_to_ansi(self):
        """
        An :class:`~humanfriendly.terminal.HTMLConverter` object that uses
        :func:`.normalize_emoji()` as a text pre-processing callback.
        """
        return HTMLConverter(callback=normalize_emoji)

    @lazy_property
    def redirect_stripper(self):
        """An :class:`.RedirectStripper` object."""
        return RedirectStripper()

    @lazy_property
    def html_to_text(self):
        """An :class:`.HTMLStripper` object."""
        return HTMLStripper()

    @lazy_property
    def keyword_highlighter(self):
        """A :class:`.KeywordHighlighter` object based on :attr:`keywords`."""
        return KeywordHighlighter(highlight_template=FORMATTING_TEMPLATES["keyword_highlight"], keywords=self.keywords)

    @mutable_property
    def keywords(self):
        """A list of strings with search keywords."""
        return []

    @mutable_property
    def timestamp_format(self):
        """The format of timestamps (defaults to ``%Y-%m-%d %H:%M:%S``)."""
        return "%Y-%m-%d %H:%M:%S"

    def list_cmd(self, arguments):
        """List all messages in the local archive."""
        self.render_messages(self.session.query(Message).order_by(Message.timestamp))

    def search_cmd(self, arguments):
        """Search the chat messages in the local archive for the given keyword(s)."""
        results = self.search_messages(arguments)
        if self.context > 0:
            results = self.gather_context(results)
        self.render_messages(results)

    def stats_cmd(self, arguments):
        """Show some statistics about the local chat archive."""
        logger.info("Statistics about %s:", format_path(self.database_file))
        logger.info(" - Number of contacts: %i", self.num_contacts)
        logger.info(" - Number of conversations: %i", self.num_conversations)
        logger.info(" - Number of messages: %i", self.num_messages)
        logger.info(" - Database file size: %s", format_size(os.path.getsize(self.database_file)))
        logger.info(
            " - Size of %s: %s",
            pluralize(self.num_messages, "plain text chat message"),
            format_size(self.session.query(func.coalesce(func.sum(func.length(Message.text)), 0)).scalar()),
        )
        logger.info(
            " - Size of %s: %s",
            pluralize(self.num_html_messages, "HTML formatted chat message"),
            format_size(self.session.query(func.coalesce(func.sum(func.length(Message.html)), 0)).scalar()),
        )

    def sync_cmd(self, arguments):
        """Download new chat messages from the supported services."""
        self.synchronize(*arguments)

    def unknown_cmd(self, arguments):
        """
        Find private conversations with messages from an unknown sender and
        interactively prompt the operator to provide a name for a new contact
        to associate the messages with.
        """
        logger.info("Searching for private conversations with unknown sender ..")
        for conversation in self.session.query(Conversation).filter(Conversation.is_group_conversation == False):
            if conversation.have_unknown_senders:
                logger.info("Private conversation %i includes messages from unknown senders:", conversation.id)
                self.render_messages(conversation.messages[:10])
                full_name = prompt_for_input("Name for new contact (leave empty to skip): ")
                if full_name:
                    words = full_name.split()
                    kw = dict(account=conversation.account, first_name=words.pop(0))
                    if words:
                        kw["last_name"] = " ".join(words)
                    contact = Contact(**kw)
                    self.session.add(contact)
                    for message in conversation.messages:
                        if not message.sender:
                            message.sender = contact
                    self.commit_changes()

    def generate_html(self, name, text):
        """
        Generate HTML based on a named format string.

        :param name: The name of an HTML format string in
                     :data:`FORMATTING_TEMPLATES` (a string).
        :param text: The text to interpolate (a string).
        :returns: The generated HTML (a string).

        This method does not escape the `text` given to it, in other words it
        is up to the caller to decide whether embedded HTML is allowed or not.
        """
        template = FORMATTING_TEMPLATES[name]
        return template.format(text=text)

    def gather_context(self, messages):
        """Enhance search results with context (surrounding messages)."""
        related = []
        for msg in messages:
            # Gather older messages.
            older_query = msg.older_messages.order_by(Message.timestamp.desc()).limit(self.context)
            logger.debug("Querying older messages: %s", older_query)
            for other_msg in reversed(older_query.all()):
                if other_msg not in related:
                    related.append(other_msg)
                    yield other_msg
            # Yield one of the given messages.
            if msg not in related:
                related.append(msg)
                yield msg
            # Gather newer messages.
            newer_query = msg.newer_messages.order_by(Message.timestamp).limit(self.context)
            logger.debug("Querying newer messages: %s", newer_query)
            for other_msg in newer_query.all():
                if other_msg not in related:
                    related.append(other_msg)
                    yield other_msg

    def render_messages(self, messages):
        """Render the given message(s) on the terminal."""
        previous_conversation = None
        previous_message = None
        # Render a horizontal bar as a delimiter between conversations.
        num_rows, num_columns = find_terminal_size()
        conversation_delimiter = self.generate_html("conversation_delimiter", "─" * num_columns)
        for i, msg in enumerate(messages):
            if msg.conversation != previous_conversation:
                # Mark context switches between conversations.
                logger.verbose("Rendering conversation #%i ..", msg.conversation.id)
                self.render_output(conversation_delimiter)
                self.render_output(self.render_conversation_summary(msg.conversation))
                self.render_output(conversation_delimiter)
            elif previous_message and self.keywords:
                # Mark gaps in conversations. This (find_distance()) is a rather
                # heavy check so we only do this when rendering search results.
                distance = msg.find_distance(previous_message)
                if distance > 0:
                    message_delimiter = "── %s omitted " % pluralize(distance, "message")
                    message_delimiter += "─" * int(num_columns - len(message_delimiter))
                    self.render_output(self.generate_html("message_delimiter", message_delimiter))
            # We convert the message metadata and the message text separately,
            # to avoid that a chat message whose HTML contains a single <p> tag
            # causes two newlines to be emitted in between the message metadata
            # and the message text.
            message_metadata = self.prepare_output(
                " ".join(
                    [
                        self.render_timestamp(msg.timestamp),
                        self.render_backend(msg.conversation.account.backend),
                        self.render_contacts(msg),
                    ]
                )
            )
            message_contents = self.normalize_whitespace(self.prepare_output(self.render_text(msg)))
            output(message_metadata + " " + message_contents)
            # Keep track of the previous conversation and message.
            previous_conversation = msg.conversation
            previous_message = msg

    def normalize_whitespace(self, text):
        """
        Normalize the whitespace in a chat message before rendering on the terminal.

        :param text: The chat message text (a string).
        :returns: The normalized text (a string).

        This method works as follows:

        - First leading and trailing whitespace is stripped from the text.
        - When the resulting text consists of a single line, it is processed
          using :func:`~humanfriendly.text.compact()` and returned.
        - When the resulting text contains multiple lines the text is prefixed
          with a newline character, so that the chat message starts on its own
          line. This ensures that messages requiring vertical alignment render
          properly (for example a table drawn with ``|`` and ``-`` characters).
        """
        # Check for multi-line chat messages.
        stripped = text.strip()
        if "\n" in stripped:
            # When the message contains "significant" newline
            # characters we start the message on its own line.
            return "\n" + stripped
        else:
            # When the message doesn't contain significant newline characters
            # we compact all whitespace in the message. I added this when I
            # found that quite a few of the HTML fragments in my personal chat
            # archive contain very inconsistent whitespace, which bothered me
            # when I viewed them on the terminal.
            return compact(text)

    def render_conversation_summary(self, conversation):
        """Render a summary of which conversation a message is part of."""
        # Gather the names of the participants in the conversation, but exclude the
        # operator's name from private conversations (we can safely assume they
        # know who they are 😇).
        participants = sorted(
            set(
                contact.unambiguous_name
                if conversation.is_group_conversation
                else (contact.full_name or UNKNOWN_CONTACT_LABEL)
                for contact in conversation.participants
                if conversation.is_group_conversation or not self.is_operator(contact)
            )
        )
        parts = [
            self.get_backend_name(conversation.account.backend),
            "group" if conversation.is_group_conversation else "private",
            "chat",
        ]
        if conversation.name:
            parts.append(self.generate_html("conversation_name", html.escape(conversation.name)))
        parts.append("with")
        participants_html = concatenate(map(html.escape, participants))
        if conversation.is_group_conversation:
            parts.append(pluralize(len(participants), "participant"))
            parts.append("(%s)" % participants_html)
        else:
            parts.append(self.generate_html("conversation_name", participants_html))
        if conversation.account.name_is_significant:
            parts.append("in %s account" % conversation.account.name)
        return " ".join(parts)

    def render_contacts(self, message):
        """Render a human friendly representation of a message's contact(s)."""
        contacts = [self.get_contact_name(message.sender)]
        if message.conversation.is_group_conversation and message.recipient:
            # In Google Talk group chats can contain private messages between
            # individuals. This is how we represent those messages.
            contacts.append(self.get_contact_name(message.recipient))
        return self.generate_html("message_contacts", "%s:" % " → ".join(contacts))

    def prepare_output(self, text):
        """
        Prepare text for rendering on the terminal.

        :param text: The HTML text to render (a string).
        :returns: The rendered text (a string).

        When :attr:`use_colors` is :data:`True` this method first uses
        :attr:`keyword_highlighter` to highlight search matches in the given
        text and then it converts the string from HTML to ANSI escape sequences
        using :attr:`html_to_ansi`.

        When :attr:`use_colors` is :data:`False` then :attr:`html_to_text` is
        used to convert the given HTML to plain text. In this case keyword
        highlighting is skipped.
        """
        # Log the HTML encoded output to enable debugging of issues in
        # the HTML to ANSI conversion process (it's rather nontrivial).
        logger.debug("Rendering HTML output: %r", text)
        if self.use_colors:
            if self.keywords:
                text = self.keyword_highlighter(text)
                logger.debug("HTML with keywords highlighted: %r", text)
            text = self.html_to_ansi(text)
            logger.debug("Text with ANSI escape sequences: %r", text)
        else:
            text = self.html_to_text(text)
            logger.debug("HTML converted to plain text: %r", text)
        return text

    def render_output(self, text):
        """
        Render text on the terminal.

        :param text: The HTML text to render (a string).

        Refer to :func:`prepare_output()` for details about how `text`
        is converted from HTML to text with ANSI escape sequences.
        """
        output(self.prepare_output(text))

    def get_contact_name(self, contact):
        """
        Get a short string describing a contact (preferably their first name,
        but if that is not available then their email address will have to do).
        If no useful information is available :data:`UNKNOWN_CONTACT_LABEL` is
        returned so as to explicitly mark the absence of more information.
        """
        if contact:
            if contact.first_name:
                return html.escape(contact.first_name)
            for email_address in contact.email_addresses:
                return html.escape(email_address.value)
        return UNKNOWN_CONTACT_LABEL

    def render_text(self, message):
        """Prepare the text of a chat message for rendering on the terminal."""
        return self.redirect_stripper(message.html or text_to_html(message.text, callback=normalize_emoji))

    def render_timestamp(self, value):
        """Render a human friendly representation of a timestamp."""
        return self.generate_html("message_timestamp", utc_to_local(value).strftime(self.timestamp_format))

    def render_backend(self, value):
        """Render a human friendly representation of a chat message backend."""
        return self.generate_html("message_backend", value)
