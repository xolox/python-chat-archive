# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: July 22, 2018
# URL: https://github.com/xolox/python-chat-archive

"""
Database models for the `chat-archive` program based on SQLAlchemy_.

The :mod:`chat_archive.models` module defines the following database models for
the `chat-archive` program:

- :class:`Account`
- :class:`Contact`
- :class:`Conversation`
- :class:`EmailAddress`
- :class:`Message`
- :class:`TelephoneNumber`
"""

# External dependencies.
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, MetaData, String, Table, UnicodeText, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.orm.session import Session


# Public identifiers that require documentation.
__all__ = (
    "Account",
    "Base",
    "Contact",
    "Conversation",
    "EmailAddress",
    "Message",
    "TelephoneNumber",
    "address_mapping",
    "metadata",
    "telephone_number_mapping",
)

metadata = MetaData(
    naming_convention=dict(
        ix="ix_%(column_0_label)s",
        uq="uq_%(table_name)s_%(column_0_name)s",
        ck="ck_%(table_name)s_%(constraint_name)s",
        fk="fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        pk="pk_%(table_name)s",
    )
)
"""Define an explicit naming convention to simplify future database migrations."""

Base = declarative_base(metadata=metadata)
"""The base class for declarative models."""

address_mapping = Table(
    "email_address_mapping",
    Base.metadata,
    Column("contact_id", Integer, ForeignKey("contacts.id")),
    Column("address_id", Integer, ForeignKey("email_addresses.id")),
)
"""Mapping table for many-to-many relationship between contacts and email addresses."""

telephone_number_mapping = Table(
    "telephone_number_mapping",
    Base.metadata,
    Column("contact_id", Integer, ForeignKey("contacts.id")),
    Column("telephone_number_id", Integer, ForeignKey("telephone_numbers.id")),
)
"""Mapping table for many-to-many relationship between contacts and telephone numbers."""


class Account(Base):

    """Database model for chat accounts."""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    """The primary key of the account (an integer)."""

    backend = Column(String(50), index=True, nullable=False)
    """The name of the backend that manages this account (a string)."""

    name = Column(String(50), index=True, nullable=False)
    """A user defined name for the account (a string)."""

    contacts = relationship("Contact", back_populates="account")
    """The contacts that have been imported using this account."""

    conversations = relationship("Conversation", back_populates="account")
    """The conversations that have been imported using this account."""

    @property
    def name_is_significant(self):
        """
        :data:`True` if the database contains multiple accounts with this
        :attr:`backend`, :data:`False` otherwise.
        """
        session = Session.object_session(self)
        count_query = session.query(func.count(Account.id)).filter(Account.backend == self.backend)
        return count_query.scalar() > 1

    def __repr__(self):
        """Render a human friendly representation of an :class:`Account` object."""
        return friendly_repr(self, "id", "backend", "name")

    def __str__(self):
        """Render a human friendly representation of an :class:`Account` object."""
        return "%s (%s)" % (self.name, self.backend)


class EmailAddress(Base):

    """Database model for email addresses of chat contacts."""

    __tablename__ = "email_addresses"

    id = Column(Integer, primary_key=True)
    """The primary key of the email address (an integer)."""

    value = Column(String, index=True, nullable=False, unique=True)
    """The email address itself (a string)."""

    def __repr__(self):
        """Render a human friendly representation of an :class:`EmailAddress` object."""
        return friendly_repr(self, "id", "value")

    def __str__(self):
        """Render a human friendly representation of an :class:`EmailAddress` object."""
        return self.value


class TelephoneNumber(Base):

    """Database model for telephone numbers of chat contacts."""

    __tablename__ = "telephone_numbers"

    id = Column(Integer, primary_key=True)
    """The primary key of the telephone number (an integer)."""

    value = Column(String, nullable=False, unique=True)
    """The telephone number itself (a string)."""

    def __repr__(self):
        """Render a human friendly representation of an :class:`TelephoneNumber` object."""
        return friendly_repr(self, "id", "value")

    def __str__(self):
        """Render a human friendly representation of an :class:`TelephoneNumber` object."""
        return self.value


class Contact(Base):

    """Database model for chat contacts."""

    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True)
    """The primary key of the contact (an integer)."""

    account_id = Column(Integer, ForeignKey(Account.id), index=True, nullable=False)
    """A foreign key to associate contacts with accounts."""

    external_id = Column(String, index=True, nullable=True)
    """An optional backend specific identifier for contacts (an opaque string or :data:`None`)."""

    first_name = Column(String, nullable=True)
    """The contact's first name (a string or :data:`None`)."""

    last_name = Column(String, nullable=True)
    """The contact's last name (a string or :data:`None`)."""

    account = relationship(Account, back_populates="contacts")
    """The account that this contact belongs to (an :class:`Account` object)."""

    email_addresses = relationship(EmailAddress, secondary=address_mapping)
    """The email addresses of this contact."""

    telephone_numbers = relationship(TelephoneNumber, secondary=telephone_number_mapping)
    """The telephone numbers of this contact."""

    sent_messages = relationship("Message", back_populates="sender", foreign_keys="Message.sender_id")
    """The chat messages that were sent by this contact."""

    received_messages = relationship("Message", back_populates="recipient", foreign_keys="Message.recipient_id")
    """The chat messages that were received by this contact."""

    @property
    def first_name_is_unambiguous(self):
        """:data:`True` if this first name unambiguously refers to a single contact, :data:`False` otherwise."""
        if self.first_name:
            first_name = func.coalesce(Contact.first_name, "")
            last_name = func.coalesce(Contact.last_name, "")
            full_name = first_name + " " + last_name
            query = Session.object_session(self).query(full_name).filter(Contact.first_name == self.first_name)
            return len(set(row[0] for row in query)) == 1
        else:
            return False

    @hybrid_property
    def full_name(self):
        """The full name of the contact (a string)."""
        return ((self.first_name or "") + " " + (self.last_name or "")).strip()

    @full_name.expression
    def full_name(self):
        """The full name of the contact (as an SQL expression)."""
        return self.first_name + " " + self.last_name

    @property
    def unambiguous_name(self):
        """The shortest unambiguous name of the contact (a string or :data:`None`)."""
        return (self.first_name if self.first_name_is_unambiguous else self.full_name) or "Unknown"

    def __repr__(self):
        """Render a human friendly representation of a :class:`Contact` object."""
        return friendly_repr(
            self, "id", "account_id", "external_id", "full_name", "email_addresses", "telephone_numbers"
        )

    def __str__(self):
        """Render a human friendly representation of a :class:`Contact` object."""
        if self.first_name or self.last_name:
            return self.full_name
        for email_address in self.email_addresses:
            return email_address.value
        return "unknown contact"


class Conversation(Base):

    """Database model for chat conversations."""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    """The primary key of the conversation (an integer)."""

    account_id = Column(Integer, ForeignKey(Account.id), index=True, nullable=False)
    """A foreign key to associate conversations with accounts."""

    external_id = Column(String, index=True, nullable=True)
    """An optional backend specific identifier for conversations (an opaque string or :data:`None`)."""

    name = Column(String, nullable=True)
    """An optional name for the conversation (a string or :data:`None`)."""

    last_modified = Column(DateTime, nullable=True)
    """The time when the conversation was last modified (a :class:`~datetime.datetime` value or :data:`None`)."""

    import_complete = Column(Boolean(name="import_complete"), default=False)
    """Whether the full conversation has been imported (a boolean, defaults to :data:`False`)."""

    import_errors = Column(Boolean(name="import_errors"), default=False)
    """Whether errors were encountered during the import (a boolean, defaults to :data:`False`)."""

    is_group_conversation = Column(Boolean(name="is_group_conversation"), default=False)
    """Whether the conversation is a group conversation (a boolean, defaults to :data:`False`)."""

    account = relationship(Account, back_populates="conversations")
    """The account that this conversation belongs to (an :class:`Account` object)."""

    messages = relationship("Message", back_populates="conversation", order_by="Message.timestamp")
    """The chat messages that belong to this conversation."""

    @property
    def have_unknown_senders(self):
        """Whether this conversation includes messages from unknown senders (a boolean)."""
        return bool(
            Session.object_session(self)
            .query(Message)
            .filter(Message.conversation == self)
            .filter(Message.sender == None)
            .first()
        )

    @property
    def newest_message(self):
        """The newest message in the conversation (a :class:`Message` object or :data:`None`)."""
        return (
            Session.object_session(self)
            .query(Message)
            .filter(Message.conversation == self)
            .order_by(Message.timestamp.desc())
            .first()
        )

    @property
    def oldest_message(self):
        """The oldest message in the conversation (a :class:`Message` object or :data:`None`)."""
        return (
            Session.object_session(self)
            .query(Message)
            .filter(Message.conversation == self)
            .order_by(Message.timestamp.asc())
            .first()
        )

    @property
    def participants(self):
        """The :class:`Contact` objects that have participated in this conversation."""
        session = Session.object_session(self)
        senders = session.query(Contact).join(Contact.sent_messages).filter(Message.conversation_id == self.id)
        recipients = session.query(Contact).join(Contact.received_messages).filter(Message.conversation_id == self.id)
        return senders.union(recipients).all()

    def delete_messages(self):
        """Delete existing chat messages in the conversation."""
        session = Session.object_session(self)
        for message in self.messages:
            session.delete(message)
        self.import_complete = False

    def __str__(self):
        """Render a human friendly representation of a :class:`Contact` object."""
        if self.name:
            return "conversation %s (%s)" % (self.external_id, self.name)
        else:
            return "conversation %s" % self.external_id


class Message(Base):

    """
    Database model for chat messages.

    Note that the :class:`Message` model doesn't have a direct relationship to
    the :class:`Account` model because these two models already have an
    indirect relationship via the :class:`Conversation` model (in other words,
    messages are implicitly namespaced to accounts via conversations).
    """

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    """The primary key of the chat message (an integer)."""

    external_id = Column(String, index=True, nullable=True)
    """An optional backend specific identifier for chat messages (an opaque string or :data:`None`)."""

    timestamp = Column(DateTime, index=True, nullable=False)
    """The timestamp of the chat message (a :class:`~datetime.datetime` value)."""

    conversation_id = Column(Integer, ForeignKey(Conversation.id), index=True, nullable=False)
    """A foreign key to associate chat messages with conversations."""

    sender_id = Column(Integer, ForeignKey(Contact.id), index=True, nullable=True)
    """A foreign key that points to the contact who sent this message (an integer or :data:`None`)."""

    recipient_id = Column(Integer, ForeignKey(Contact.id), index=True, nullable=True)
    """A foreign key that points to the contact who received this message (an integer or :data:`None`)."""

    raw = Column(UnicodeText, nullable=True)
    """
    The raw message text in a backend specific format (a string or :data:`None`).

    The reason that this field was added to the database schema is because the
    Slack backend emits chat messages in the somewhat peculiar mrkdwn_ format
    which is "almost but not quite" human readable (in my opinion). When the
    Slack backend imports a new message, the following steps take place:

    1. The original message text is stored without any modifications in the
       :attr:`raw` column.

    2. A custom mrkdwn_ parser developed for the `chat-archive` program is used
       to convert :attr:`raw` to :attr:`html` (during the import).

    3. The value of :attr:`html` is used to generate the value of :attr:`text`
       (during the import).

       If this surprises you: I could have developed a second mrkdwn converter
       with a different output format, but that's 150 lines of code I don't
       care to repeat and :func:`~chat_archive.html.html_to_text()` works fine
       for this purpose 😇.

    If the custom mrkdwn_ parser (which is bound to contain bugs) receives bug
    fixes in a new release of the `chat-archive` program then :attr:`raw`
    values can be used to regenerate :attr:`text` and :attr:`html` values.

    .. _mrkdwn: https://api.slack.com/docs/message-formatting#message_formatting
    """

    text = Column(UnicodeText, index=True, nullable=False)
    """
    The human readable plain text of the chat message (a string).

    This field cannot be :data:`None` (``NULL``) and is expected to always
    contain a nonempty chat message text. This field is used during searches
    and when ``chat-archive --colors=never`` is run.
    """

    html = Column(UnicodeText, index=False, nullable=True)
    """
    The formatted text of the chat message (a string or :data:`None`).

    When a chat message doesn't contain text formatting or hyperlinks
    :attr:`html` will be :data:`None` and :attr:`text` should be used instead.
    This field will be used when ``chat-archive --color=yes`` is run.
    """

    conversation = relationship(Conversation, back_populates="messages")
    """The conversation that this chat message took place in (a :class:`Conversation` object or :data:`None`)."""

    sender = relationship(Contact, back_populates="sent_messages", foreign_keys="Message.sender_id")
    """The contact that sent the message (a :class:`Contact` object or :data:`None`)."""

    recipient = relationship(Contact, back_populates="received_messages", foreign_keys="Message.recipient_id")
    """The contact that received the message (a :class:`Contact` object or :data:`None`)."""

    @property
    def newer_messages(self):
        """Newer messages in the conversation (not yet sorted!)."""
        return (
            Session.object_session(self)
            .query(Message)
            .filter(Message.conversation == self.conversation)
            .filter(Message.timestamp >= self.timestamp)
            .filter(Message.id != self.id)
        )

    @property
    def next_message(self):
        """The next message in the conversation (or :data:`None`)."""
        return self.newer_messages.order_by(Message.timestamp).first()

    @property
    def older_messages(self):
        """Older messages in the conversation (not yet sorted!)."""
        return (
            Session.object_session(self)
            .query(Message)
            .filter(Message.conversation == self.conversation)
            .filter(Message.timestamp <= self.timestamp)
            .filter(Message.id != self.id)
        )

    @property
    def previous_message(self):
        """The previous message in the conversation (or :data:`None`)."""
        return self.older_messages.order_by(Message.timestamp.desc()).first()

    def find_distance(self, other_message):
        """Compute the distance between two messages."""
        return (
            Session.object_session(self)
            .query(func.count(Message.id))
            .filter(Message.conversation == self.conversation)
            .filter(Message.timestamp > min(self.timestamp, other_message.timestamp))
            .filter(Message.timestamp < max(self.timestamp, other_message.timestamp))
            .scalar()
        )

    def __repr__(self):
        """Render a human friendly representation of a :class:`Message` object."""
        return friendly_repr(self, "id", "timestamp", "sender", "recipient", "text")

    def __str__(self):
        """Render a human friendly representation of a :class:`Message` object."""
        if self.sender and self.text:
            return "message by %s on %s: %s" % (self.sender, self.timestamp.strftime("%Y-%m-%d"), self.text)
        else:
            return "message: %s" % self.text


# When rendering search results the gathering of context (surrounding chat
# messages) is a rather slow process. The following composite index is
# intended to speed things up a bit. For details about composite indexes
# in SQLite please refer to https://www.sqlite.org/queryplanner.html.
Index("ix_messages_conversation_id_timestamp", Message.conversation_id, Message.timestamp)


def friendly_repr(obj, *attributes):
    """Render a human friendly representation of a database model instance."""
    values = []
    for name in attributes:
        try:
            value = getattr(obj, name, None)
            if value is not None:
                values.append("%s=%r" % (name, value))
        except Exception:
            pass
    return "%s(%s)" % (obj.__class__.__name__, ", ".join(values))
