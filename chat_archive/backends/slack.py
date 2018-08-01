# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: July 21, 2018
# URL: https://github.com/xolox/python-chat-archive

"""Synchronization logic for the Slack backend of the `chat-archive` program."""

# Standard library modules.
import datetime
import decimal
import html

# External dependencies.
from humanfriendly import Spinner
from humanfriendly.terminal import HIGHLIGHT_COLOR, ansi_wrap
from property_manager import lazy_property, mutable_property
from requests.sessions import Session
from slacker import Slacker
from verboselogs import VerboseLogger

# Modules included in our package.
from chat_archive.backends import ChatArchiveBackend
from chat_archive.html import html_to_text
from chat_archive.utils import get_secret

FRIENDLY_NAME = "Slack"
"""A user friendly name for the chat service supported by this backend (a string)."""

# Initialize a logger for this module.
logger = VerboseLogger(__name__)


class SlackBackend(ChatArchiveBackend):

    """Container for the Slack chat archive backend."""

    @lazy_property
    def api_token(self):
        """The Slack API token (a string)."""
        return get_secret(
            options=self.config, value_option="api-token", name_option="api-token-name", description="Slack API token"
        )

    @lazy_property
    def client(self):
        """A ``slacker.Slacker`` instance initialized with :attr:`api_token` and :attr:`http_session`."""
        return Slacker(self.api_token, session=self.http_session)

    @mutable_property
    def is_limited(self):
        """Whether result sets have been limited due to the free plan."""
        return False

    @lazy_property
    def mrkdwn_to_html(self):
        """An :class:`HTMLConverter` object."""
        return HTMLConverter(expand_reference_callback=self.expand_reference_callback)

    @lazy_property
    def http_session(self):
        """A ``requests.Session`` object used for HTTP connection re-use."""
        return Session()

    @lazy_property
    def spinner(self):
        """An interactive spinner to provide feedback to the user (because the Slack backend is slow)."""
        return Spinner()

    def synchronize(self):
        """Download chat contacts and messages and store them in the local archive."""
        with self.spinner:
            self.synchronize_users()
            self.synchronize_direct_messages()
            self.synchronize_channels()

    def synchronize_users(self):
        """Download information about the users in the organization on Slack."""
        logger.verbose("Synchronizing users ..")
        response = self.client.users.list()
        for user in response.body["members"]:
            profile = user.get("profile", {})
            self.get_or_create_contact(
                email_address=profile.get("email"),
                external_id=user["id"],
                first_name=profile.get("first_name"),
                last_name=profile.get("last_name"),
            )
            self.spinner.step(label="Synchronizing users")

    def synchronize_direct_messages(self):
        """Download the latest direct messages from Slack."""
        logger.verbose("Importing direct messages ..")
        response = self.client.im.list()
        num_ims = len(response.body["ims"])
        for i, dm in enumerate(response.body["ims"], start=1):
            progress = "%i/%i" % (i, num_ims)
            logger.verbose("Synchronizing direct message channel %s (%s) ..", progress, dm["id"])
            self.spinner.label = "Synchronizing direct message channel %s" % progress
            self.import_messages(
                self.client.im, self.get_or_create_conversation(external_id=dm["id"], is_group_conversation=False)
            )

    def synchronize_channels(self):
        """Download messages from named channels."""
        response = self.client.channels.list()
        num_channels = len(response.body["channels"])
        for i, channel in enumerate(response.body["channels"], start=1):
            logger.verbose("Synchronizing #%s channel (%s) ..", channel["name"], channel["id"])
            self.spinner.label = "Synchronizing channel %s: %s" % (
                "%i/%i" % (i, num_channels),
                ansi_wrap("#%s" % channel["name"], color=HIGHLIGHT_COLOR),
            )
            self.import_messages(
                self.client.channels,
                self.get_or_create_conversation(
                    external_id=channel["id"], is_group_conversation=True, name=("#" + channel["name"])
                ),
            )

    def import_messages(self, source, conversation_in_db):
        """Import the history of the given Slack channel."""
        # Page backward on the initial synchronization, forward afterwards.
        oldest = 0
        if conversation_in_db.import_complete and conversation_in_db.newest_message:
            oldest = conversation_in_db.newest_message.external_id
            logger.verbose("Searching for messages newer than %s ..", oldest)
        for message in self.get_history(source, conversation_in_db.external_id, oldest=oldest):
            # We perform a lightweight check for previously imported messages
            # before processing the message text to avoid unnecessary work.
            if not self.have_message(conversation_in_db, message["ts"]):
                html = self.mrkdwn_to_html(message["text"])
                self.get_or_create_message(
                    conversation=conversation_in_db,
                    external_id=message["ts"],
                    html=html,
                    raw=message["text"],
                    sender=self.get_or_create_contact(external_id=message["user"]),
                    text=html_to_text(html),
                    timestamp=datetime.datetime.utcfromtimestamp(float(message["ts"])),
                )
        if not conversation_in_db.import_complete:
            conversation_in_db.import_complete = True

    def get_history(self, source, channel_id, latest=None, oldest=0, page_size=100):
        """Get the history of the given Slack channel."""
        while True:
            logger.verbose(
                "Requesting history (channel=%s, latest=%s, oldest=%s, count=%s) ..",
                channel_id,
                latest,
                oldest,
                page_size,
            )
            self.spinner.step()
            response = source.history(channel=channel_id, latest=latest, oldest=oldest, count=page_size)
            logger.verbose("Processing response with %s message(s) ..", len(response.body["messages"]))
            for message in response.body["messages"]:
                # We use decimals instead of floats to avoid rounding errors.
                message_ts = decimal.Decimal(message["ts"])
                if oldest != 0:
                    # When 'oldest' is given we page forward (with an increasing value of 'oldest').
                    if message_ts > decimal.Decimal(oldest):
                        oldest = message["ts"]
                else:
                    # When 'oldest' isn't given we page backward (with a decreasing value of 'latest').
                    if latest is None or message_ts < decimal.Decimal(latest):
                        latest = message["ts"]
                # Only user generated messages are import.
                if message["type"] == "message" and message.get("subtype") != "bot_message":
                    self.spinner.step()
                    yield message
            if not self.is_limited and response.body.get("is_limited", False):
                logger.notice("Conversation history is being limited by Slack's free plan.")
                self.is_limited = True
            if not response.body["has_more"]:
                break

    def expand_reference_callback(self, external_id):
        """Expand a ``@reference`` to a Slack user in a chat message with the name of that user."""
        contact = self.find_contact_by_external_id(external_id)
        return contact.unambiguous_name


class HTMLConverter(object):

    """
    Convert Slack chat messages from mrkdwn_ format to HTML.

    .. _mrkdwn: https://api.slack.com/docs/message-formatting#message_formatting
    """

    def __init__(self, expand_reference_callback=None):
        """Initialize an :class:`HTMLConverter` object."""
        self.expand_reference_callback = expand_reference_callback
        self.parse_methods = {
            "&": self.parse_entity,
            "*": self.parse_bold,
            "<": self.parse_reference,
            "_": self.parse_italic,
            "`": self.parse_preformatted,
            "~": self.parse_strike_through,
        }

    def __call__(self, text):
        """
        Convert a Slack chat message to HTML.

        :param text: The text of a Slack message (a string).
        :returns: The generated HTML (a string).
        """
        output = []
        self.parse_text(text, 0, len(text), output)
        return "".join(output)

    def followed_by_alphanumeric(self, input, index, limit):
        """Check if the given position is followed by an alphanumeric character."""
        return index + 1 < limit and input[index + 1].isalnum()

    def parse_bold(self, input, index, length, output):
        """Parse *bold* text."""
        if not self.preceded_by_alphanumeric(input, index):
            match = input.find("*", index + 1)
            if match > 0 and not self.followed_by_alphanumeric(input, match, length):
                output.append("<b>")
                nested = input[index + 1 : match]
                self.parse_text(nested, 0, len(nested), output)
                output.append("</b>")
                return match + 1

    def parse_entity(self, input, index, length, output):
        """Parse an HTML entity."""
        match = input.find(";", index + 1)
        if match > 0:
            output.append(input[index : match + 1])
            return match + 1

    def parse_italic(self, input, index, length, output):
        """Parse _italic_ text."""
        if not self.preceded_by_alphanumeric(input, index):
            match = input.find("_", index + 1)
            if match > 0 and not self.followed_by_alphanumeric(input, match, length):
                output.append("<i>")
                nested = input[index + 1 : match]
                self.parse_text(nested, 0, len(nested), output)
                output.append("</i>")
                return match + 1

    def parse_preformatted(self, input, index, length, output):
        """Parse `pre-formatted` text."""
        if not self.preceded_by_alphanumeric(input, index):
            if index + 2 < length and input[index + 1] == "`" and input[index + 2] == "`":
                match = input.find("```", index + 3)
                if match > 0 and not self.followed_by_alphanumeric(input, match + 2, length):
                    output.append("<pre>")
                    nested = input[index + 3 : match].strip("\r\n")
                    self.parse_preformatted_body(nested, 0, len(nested), output)
                    output.append("</pre>")
                    return match + 3
            else:
                match = input.find("`", index + 1)
                if match > 0 and not self.followed_by_alphanumeric(input, match, length):
                    output.append("<code>")
                    nested = input[index + 1 : match]
                    self.parse_preformatted_body(nested, 0, len(nested), output)
                    output.append("</code>")
                    return match + 1

    def parse_preformatted_body(self, input, index, length, output):
        """Parse the body of a pre-formatted text fragment."""
        while index < length:
            character = input[index]
            if character == "<":
                # Replace references with their visible text. Why does
                # Slack embed these in pre-formatted text?! Argh! 😋
                match = input.find(">", index + 1)
                url, _, label = input[index + 1 : match].partition("|")
                output.append(html.escape(label or url, quote=False))
                index = match + 1
            elif character == "&":
                # HTML entities pass through unchanged.
                match = input.find(";", index + 1)
                output.append(input[index : match + 1])
                index = match + 1
            else:
                # Plain text is encoded as HTML.
                output.append(html.escape(input[index], quote=False))
                index += 1

    def parse_reference(self, input, index, length, output):
        """Parse a reference to a URL, user or channel."""
        if not self.preceded_by_alphanumeric(input, index):
            match = input.find(">", index + 1)
            if match > 0 and not self.followed_by_alphanumeric(input, match, length):
                nested = input[index + 1 : match]
                url, _, label = nested.partition("|")
                if url.startswith("@"):
                    # Convert internal references to bold text.
                    url = url.lstrip("@")
                    if self.expand_reference_callback is not None:
                        label = self.expand_reference_callback(url)
                    else:
                        label = label or url
                    output.append("<b>@%s</b>" % html.escape(label, quote=False))
                else:
                    # Convert external references to hyperlinks.
                    output.append('<a href="%s">' % html.escape(url, quote=True))
                    output.append(html.escape(label or url, quote=False))
                    output.append("</a>")
                return match + 1

    def parse_strike_through(self, input, index, length, output):
        """Parse ~strike-through~ text."""
        if not self.preceded_by_alphanumeric(input, index):
            match = input.find("~", index + 1)
            if match > 0 and not self.followed_by_alphanumeric(input, match, length):
                output.append("<s>")
                nested = input[index + 1 : match]
                self.parse_text(nested, 0, len(nested), output)
                output.append("</s>")
                return match + 1

    def parse_text(self, input, index, length, output):
        """Parse inline text."""
        while index < length:
            character = input[index]
            method = self.parse_methods.get(character)
            if method:
                result = method(input, index, length, output)
                if result:
                    index = result
                    continue
            # Consume one character when no token could be matched.
            output.append(html.escape(character, quote=False))
            index += 1

    def preceded_by_alphanumeric(self, input, index):
        """Check if the given position is preceded by an alphanumeric character."""
        return index > 0 and input[index - 1].isalnum()
