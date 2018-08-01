# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: July 22, 2018
# URL: https://github.com/xolox/python-chat-archive

"""
Synchronization logic for the `Google Talk`_ backend of the `chat-archive` program.

The Google Talk backend uses the IMAP_ protocol to discover and download the
messages available in the :attr:`~GoogleTalkBackend.chats_folder` of your
Google Mail account. The following requirements need to be met in order to use
this backend:

- You need to enable IMAP access to your Google Mail account.

- You may need to specifically enable IMAP access to the
  :attr:`~GoogleTalkBackend.chats_folder` (this turned
  out to be necessary for me).

Before developing this module in June 2018 I had never implemented any IMAP
automation [#]_ so I wasn't that familiar with the protocol and I didn't know
about message UIDs. The `Unique ID in IMAP protocol`_ blog post provided me
with some useful details about the semantics of message UIDs.

This backend assumes and requires that the Google Mail servers provide message
UIDs that are stable across sessions (this enables discovery of new messages).
My testing implies that this is the case, because it seems to work fine! :-)

.. [#] Despite operating my own IMAP server for the past ten years, so I was
       already familiar with IMAP from the perspective of a user as well as
       server administrator.

.. _Google Talk: https://en.wikipedia.org/wiki/Google_Talk
.. _IMAP: https://en.wikipedia.org/wiki/Internet_Message_Access_Protocol
.. _Unique ID in IMAP protocol: https://www.limilabs.com/blog/unique-id-in-imap-protocol
"""

# Standard library modules.
import codecs
import datetime
import email
import email.utils
import imaplib
import os
import re
import xml.etree.ElementTree

# External dependencies.
from humanfriendly import Timer, format, format_path, pluralize
from property_manager import PropertyManager, lazy_property, mutable_property, required_property
from verboselogs import VerboseLogger

# Modules included in our package.
from chat_archive.backends import ChatArchiveBackend
from chat_archive.html import html_to_text
from chat_archive.models import Contact, Conversation, EmailAddress, Message
from chat_archive.utils import get_secret

FRIENDLY_NAME = "Google Talk"
"""A user friendly name for the chat service supported by this backend (a string)."""

NAMESPACED_TAG_PATTERN = re.compile(r"^{[^}]+}(\S+)$")
"""Compiled regular expression to match XML tag names with a name space."""

BOGUS_EMAIL_PATTERN = re.compile(r"^private-chat(-[0-9a-f]+)+@groupchat.google.com$", re.IGNORECASE)
"""Compiled regular expression to recognize private messages in group conversations."""


# Initialize a logger for this module.
logger = VerboseLogger(__name__)


class GoogleTalkBackend(ChatArchiveBackend):

    """
    The Google Talk backend for the `chat-archive` program.

    This backend supports the following configuration options:

    =================  ==============================================================
    Option             Description
    =================  ==============================================================
    ``chats-folder``   See :attr:`chats_folder`.
    ``imap-server``    See :attr:`imap_server`.
    ``email``          The email address used to sign in to your Google Mail account.
    ``password-name``  The name of a password in ``~/.password-store`` to use.
    ``password``       See :attr:`password`.
    =================  ==============================================================

    If you set ``password-name`` then ``password`` doesn't have to be set. If
    ``password`` nor ``password-name`` have been set then you will be prompted
    for your password every time you synchronize.
    """

    @mutable_property
    def chats_folder(self):
        """The folder that contains chat message archives (a string, defaults to '[Gmail]/Chats')."""
        return self.config.get("chats-folder", "[Gmail]/Chats")

    @lazy_property
    def client(self):
        """An IMAP client connection to :attr:`imap_server`."""
        logger.info("Connecting to %s ..", self.imap_server)
        return imaplib.IMAP4_SSL(self.imap_server)

    @lazy_property
    def conversation_map(self):
        """A mapping of conversations."""
        return {}

    @mutable_property
    def imap_server(self):
        """The domain name of the Google Mail IMAP server (a string, defaults to 'imap.gmail.com')."""
        return self.config.get("imap-server", "imap.gmail.com")

    @lazy_property
    def password(self):
        """The password used to sign in to the Google Mail account (a string)."""
        return get_secret(
            options=self.config,
            value_option="password",
            name_option="password-name",
            description="Google account password",
        )

    def synchronize(self):
        """Download RFC822 encoded Google Talk conversations using IMAP and import the embedded chat messages."""
        self.login_to_server()
        self.select_chats_folder()
        # Check for emails to download and/or import.
        to_download = self.find_uids_to_download()
        to_import = self.find_uids_to_import()
        to_process = to_download | to_import
        to_import |= to_download
        if to_process:
            summary = []
            if to_download:
                summary.append("downloading %s" % pluralize(len(to_download), "email"))
            if to_import:
                summary.append("importing %s" % pluralize(len(to_import), "email"))
            logger.info("%s ..", ", ".join(summary).capitalize())
            for i, uid in enumerate(sorted(to_process), start=1):
                logger.info("Processing email with UID %s (%.2f%%) ..", uid, i / (len(to_process) / 100.0))
                email = self.get_email_body(uid)
                if email.parsed_body:
                    with self.stats:
                        if email.parsed_body.is_multipart():
                            self.parse_multipart_email(email)
                        else:
                            self.parse_singlepart_email(email)
                else:
                    logger.verbose("Skipping conversation %s with empty mail body.", uid)
                self.archive.commit_changes()
        else:
            logger.info("Nothing to do! (no new messages)")
        self.client.logout()

    def login_to_server(self):
        """Log-in to the Google Mail account."""
        self.check_response(
            self.client.login(self.config["email"], self.password),
            "Failed to authenticate with IMAP server! (%s)",
            self.imap_server,
        )

    def select_chats_folder(self):
        """Select the IMAP folder with chat messages."""
        logger.verbose("Selecting %r folder ..", self.chats_folder)
        response = self.client.select(self.chats_folder, readonly=True)
        self.check_response(response, "Failed to select chats folder! (%s)", self.chats_folder)

    def find_uids_to_download(self):
        """Determine the UIDs of the email messages to be downloaded."""
        timer = Timer()
        # Load the UID values of the Google Talk conversations in the local database.
        logger.verbose("Discovering conversations available in local archive ..")
        conversation_uids = (
            self.session.query(Conversation.external_id)
            .filter(Conversation.account == self.account)
            .filter(Conversation.external_id != None)
        )
        message_uids = (
            self.session.query(Message.external_id)
            .join(Message.conversation)
            .filter(Conversation.account == self.account)
            .filter(Message.external_id != None)
        )
        logger.debug("Query: %s", conversation_uids.union(message_uids))
        local_uids = set(int(row[0]) for row in conversation_uids.union(message_uids))
        # Discover the UID values of the conversations available remotely.
        logger.verbose("Discovering conversations available on server ..")
        response = self.client.uid("search", None, "ALL")
        data = self.check_response(response, "Search for available messages failed!")
        remote_uids = set(map(int, data[0].split()))
        # Discover the UID values of the conversations that we're missing.
        missing_uids = remote_uids - local_uids
        logger.verbose(
            "Found %s, %s and %s (took %s).",
            pluralize(len(local_uids), "local conversation"),
            pluralize(len(remote_uids), "remote conversation"),
            pluralize(len(missing_uids), "conversation to download", "conversations to download"),
            timer,
        )
        return missing_uids

    def find_uids_to_import(self):
        """Determine which email messages need to be imported."""
        return set(
            int(row[0])
            for row in (
                self.archive.session.query(Conversation.external_id)
                .filter(Conversation.account == self.account)
                .filter(Conversation.external_id != None)
                .filter(Conversation.import_complete == False)
            )
        )

    def get_email_body(self, uid):
        """Get the body of an email from the local cache or the server."""
        local_copy = os.path.join(self.archive.data_directory, "gtalk", self.account_name, "%i.eml" % uid)
        formatted_path = format_path(local_copy)
        if os.path.isfile(local_copy):
            logger.verbose("Reading email with UID %s from %s ..", uid, formatted_path)
            with open(local_copy, encoding="ascii") as handle:
                return EmailMessageParser(raw_body=handle.read(), uid=uid)
        else:
            logger.verbose("Downloading email with UID %s to ..", uid, formatted_path)
            response = self.client.uid("fetch", str(uid), "(RFC822)")
            data = self.check_response(response, "Failed to download conversation with UID %s!", uid)
            raw_body = data[0][1].decode("ascii")
            with open(local_copy, "w") as handle:
                handle.write(raw_body)
            return EmailMessageParser(raw_body=raw_body, uid=uid)

    def parse_singlepart_email(self, email):
        """Extract a chat message from a single-part email downloaded from :attr:`chats_folder`."""
        logger.verbose("Parsing single-part email with UID %s ..", email.uid)
        # Determine the sender and recipient.
        sender = self.contact_from_header(email.parsed_body["from"])
        recipient = self.contact_from_header(email.parsed_body["to"])
        # Look for an existing conversation to add the message to.
        conversation = self.find_conversation(sender, recipient)
        # Create a new conversation if we didn't find one.
        if not conversation:
            conversation = Conversation(account=self.account)
            self.session.add(conversation)
        # Get the message text.
        binary_html = email.parsed_body.get_payload(decode=True)
        unicode_html = binary_html.decode(email.parsed_body.get_content_charset())
        # Import the message.
        self.get_or_create_message(
            conversation=conversation,
            external_id=email.uid,
            html=unicode_html,
            recipient=recipient,
            sender=sender,
            text=html_to_text(unicode_html),
            timestamp=email.timestamp,
        )

    def parse_multipart_email(self, email):
        """Find the ``text/xml`` payload in an RFC 822 multi-part email message."""
        conversation = self.get_or_create_conversation(external_id=email.uid, last_modified=email.timestamp)
        # Delete any existing messages in the conversation
        # so that repeated importing of the email doesn't
        # create duplicate messages.
        conversation.delete_messages()
        # Now we're ready to import the embedded messages.
        logger.verbose("Parsing multi-part email with UID %s ..", conversation.external_id)
        for nested_message in email.parsed_body.get_payload():
            nested_payload = nested_message.get_payload(decode=True)
            content_type = nested_message.get_content_type()
            if content_type == "text/xml":
                logger.verbose("Parsing embedded text/xml message ..")
                self.parse_xml(nested_payload, conversation)
        conversation.import_complete = True

    def parse_xml(self, xml_body, conversation):
        """Extract chat messages from the ``text/xml`` payload."""
        logger.verbose("Parsing XML fragment:\n%s", xml_body)
        tree = xml.etree.ElementTree.fromstring(xml_body)
        for message_node in tree.findall("{jabber:client}message"):
            body_node = message_node.find("{jabber:client}body")
            node_text = getattr(body_node, "text", None)
            if node_text and not node_text.isspace():
                node_text = node_text.rstrip()
                attributes = dict(
                    conversation=conversation,
                    html=self.extract_html(message_node),
                    text=node_text,
                    timestamp=self.extract_timestamp(message_node),
                )
                logger.verbose(
                    "Importing XML message node with body text %r:\n%s", node_text, LazyXMLFormatter(message_node)
                )
                if message_node.attrib.get("type") == "groupchat":
                    conversation.is_group_conversation = True
                    if message_node.attrib.get("jid"):
                        logger.verbose("Importing group message based on 'jid' attribute ..")
                        attributes["sender"] = self.contact_from_jid(message_node.attrib["jid"])
                    elif message_node.attrib.get("from"):
                        logger.verbose("Importing group message based on 'from' attribute ('jid' not available) ..")
                        attributes["sender"] = self.contact_from_jid(message_node.attrib["from"])
                    else:
                        logger.warning("Importing group message without sender information ..")
                elif conversation.is_group_conversation and message_node.attrib.get("jid"):
                    # This is a somewhat weird edge case that I encountered in
                    # a group conversation from 2011 whose IMAP representation
                    # contained mostly group messages, but also some private
                    # messages (that were sent inside of the group conversation
                    # but to an individual). It's funny to note that the
                    # rudimentary Google Talk archive available in Google Mail
                    # using the in:chat label renders these messages wrong. I
                    # actually looked into personal laptop backups from 2011 to
                    # verify my recollection of how that conversation went :-).
                    logger.verbose("Importing private message in group conversation based on 'jid' attribute ..")
                    attributes["sender"] = self.contact_from_jid(message_node.attrib["jid"])
                    attributes["recipient"] = self.contact_from_jid(message_node.attrib["to"])
                else:
                    logger.verbose("Importing private message based on 'from' and 'to' attributes ..")
                    attributes["sender"] = self.contact_from_jid(message_node.attrib["from"])
                    attributes["recipient"] = self.contact_from_jid(message_node.attrib["to"])
                self.get_or_create_message(**attributes)

    def find_conversation(self, *participants):
        """Find a conversation (without an external ID) that involves the given participants."""
        # Check for a cache hit.
        required_participants = frozenset(p.id for p in participants)
        if required_participants in self.conversation_map:
            return self.conversation_map[required_participants]
        # Do a full lookup on every cache miss.
        for conversation in self.account.conversations:
            if not conversation.external_id:
                participants = frozenset(c.id for c in conversation.participants)
                if participants == required_participants:
                    self.conversation_map[participants] = conversation
                    return conversation

    def extract_timestamp(self, message_node):
        """
        Extract a timestamp from a ``<message>`` node.

        :param message_node: A ``<message>`` node.
        :returns: A :class:`datetime.datetime` object.
        """
        timestamp_node = message_node.find("{google:timestamp}time")
        timestamp_as_float = float(timestamp_node.attrib["ms"]) / 1000
        return datetime.datetime.utcfromtimestamp(timestamp_as_float)

    def extract_html(self, message_node):
        """
        Try to extract HTML from a ``<message>`` node.

        :param message_node: A ``<message>`` node.
        :returns: The extracted HTML (a string) or :data:`None`.
        """
        html_node = message_node.find("{http://jabber.org/protocol/xhtml-im}html")
        if html_node is not None:
            # Remove XML name spaces from the HTML node and its children.
            for nested_node in html_node.getiterator():
                match = NAMESPACED_TAG_PATTERN.match(nested_node.tag)
                if match:
                    nested_node.tag = match.group(1)
            # Render the <html> element and its children to a binary string.
            binary_html = xml.etree.ElementTree.tostring(html_node, encoding="utf-8", method="html")
            # Decode and sanitize the binary string.
            return binary_html.decode("utf-8")

    def contact_from_jid(self, value):
        """Convert a Jabber ID to an email address and use that to find or create a contact."""
        if "/" in value:
            components = value.split("/")
            if len(components) == 2 and BOGUS_EMAIL_PATTERN.match(components[0]):
                # In this case the first part of the JID is a bogus email address like
                # private-chat-abcdef01-abcd-abcd-abcd-abcdef123456@groupchat.google.com
                # and the second part is something resembling a nickname or
                # username. That username or nickname may not occur anywhere
                # else in the XML encoded conversation so strictly speaking we
                # can't infer who we're dealing with. However in practice
                # we can try to make an educated guess...
                tokens = re.split(r"\W+", components[1])
                return self.contact_from_keywords(tokens)
            logger.verbose("Translated JID (%s) to email address: %s", value, components[0])
            value = components[0]
        return self.get_or_create_contact(email_address=value)

    def contact_from_keywords(self, keywords):
        """Try to find a unique contact based on the given keywords."""
        logger.verbose("Looking up contact based on keywords (%s) ..", keywords)
        query = self.session.query(Contact).outerjoin((EmailAddress, Contact.email_addresses))
        for kw in keywords:
            pattern = "%" + kw + "%"
            query = query.filter(
                Contact.first_name.like(pattern) | Contact.last_name.like(pattern) | EmailAddress.value.like(pattern)
            )
        if query.count() == 1:
            contact = query.first()
            logger.verbose("Lookup successful, found exactly one contact: %s", contact)
            return contact
        logger.notice(
            "Failed to lookup sender/recipient of private message" " in group chat based on keywords! (%s)", keywords
        )

    def contact_from_header(self, value):
        """Get or create a contact based on the ``From:`` or ``To:`` header of an email."""
        logger.verbose("Looking up contact based on header %r ..", value)
        name, email_address = email.utils.parseaddr(value)
        if not email_address:
            raise Exception("Failed to parse contact from header! (%r)" % value)
        return self.get_or_create_contact(full_name=name, email_address=email_address)

    def check_response(self, response, message, *args, **kw):
        """Validate an IMAP server response."""
        logger.debug("IMAP response: rv=%r, data=%r", response[0], response[1])
        if response[0] != "OK":
            raise Exception(format(message, *args, **kw))
        return response[1]


class EmailMessageParser(PropertyManager):

    """Lazy evaluation of :func:`email.message_from_string()`."""

    @lazy_property
    def parsed_body(self):
        """The result of :func:`email.message_from_string()`."""
        if self.raw_body:
            return email.message_from_string(self.raw_body)

    @required_property
    def raw_body(self):
        """The raw message body of the email (a string)."""

    @lazy_property
    def timestamp(self):
        """Convert the ``Date:`` header of the email message to a :class:`~datetime.datetime` object."""
        if self.parsed_body:
            date_tuple = email.utils.parsedate_tz(self.parsed_body["date"])
            unix_timestamp = email.utils.mktime_tz(date_tuple)
            return datetime.datetime.utcfromtimestamp(unix_timestamp)

    @required_property
    def uid(self):
        """The UID of the email message."""


class LazyXMLFormatter(object):

    """Lazy evaluation of :func:`xml.etree.ElementTree.tostring()`."""

    def __init__(self, node):
        """
        Initialize a :class:`LazyXMLFormatter` object.

        :param node: The XML node to render.
        """
        self.node = node

    def __bytes__(self):
        """Convert the XML node to a byte string."""
        return xml.etree.ElementTree.tostring(self.node)

    def __str__(self):
        """Convert the XML node to a string."""
        return codecs.decode(self.__bytes__(), encoding="ascii", errors="ignore")
