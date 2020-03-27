# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: March 27, 2020
# URL: https://github.com/xolox/python-chat-archive

"""
Synchronization logic for the Telegram backend of the `chat-archive` program.

The use of this backend requires the user to register on `my.telegram.org/apps
<https://my.telegram.org/apps>`_ to get an :attr:`~TelegramBackend.api_id` and
:attr:`~TelegramBackend.api_hash`.
"""

# Standard library modules.
import asyncio
import os

# External dependencies.
from property_manager import lazy_property, mutable_property, required_property
from telethon import TelegramClient
from telethon.extensions.html import unparse
from verboselogs import VerboseLogger

# Modules included in our package.
from chat_archive.backends import ChatArchiveBackend
from chat_archive.models import Account, Conversation
from chat_archive.utils import ensure_directory_exists, get_secret, strip_tzinfo

FRIENDLY_NAME = "Telegram"
"""A user friendly name for the chat service supported by this backend (a string)."""

# Initialize a logger for this module.
logger = VerboseLogger(__name__)


class TelegramBackend(ChatArchiveBackend):

    """Container for the Telegram chat archive backend."""

    @required_property
    def api_hash(self):
        """
        The API hash used to connect to the Telegram API (a string).

        The value of this property can be configured as follows:

        .. code-block:: ini

           [telegram]
           api-hash = ...

        You can use the ``api-hash-name`` configuration file option to specify
        the name of a secret in ``~/.password-store`` instead.
        """
        return get_secret(
            options=self.config, value_option="api-hash", name_option="api-hash-name", description="Telegram API hash"
        )

    @required_property
    def api_id(self):
        """
        The API ID used to connect to the Telegram API (an integer).

        The value of this property can be configured as follows:

        .. code-block:: ini

           [telegram]
           api-id = ...

        You can use the ``api-id-name`` configuration file option to specify
        the name of a secret in ``~/.password-store`` instead.
        """
        return int(
            get_secret(
                options=self.config, value_option="api-id", name_option="api-id-name", description="Telegram API ID"
            )
        )

    @lazy_property
    def client(self):
        """
        A :class:`telethon.TelegramClient` object constructed based on
        :attr:`api_id`,:attr:`api_hash` and :attr:`session_file`.
        """
        return TelegramClient(self.session_file, self.api_id, self.api_hash)

    @mutable_property
    def session_file(self):
        """The filename of the session file passed to :class:`telethon.TelegramClient`."""
        return os.path.join(self.archive.data_directory, "telegram", self.account_name)

    def synchronize(self):
        """Download chat contacts and messages and store them in the local archive."""
        event_loop = asyncio.get_event_loop()
        event_loop.run_until_complete(self.connect_then_sync())

    async def connect_then_sync(self):
        """Connect to the Telegram API and synchronize the available conversations."""
        # Make sure the directory with session files exists.
        ensure_directory_exists(os.path.dirname(self.session_file))
        # Establish a connection to the Telegram API.
        phone_number = self.config.get("phone-number")
        options = dict(phone=phone_number) if phone_number else {}
        await self.client.start(**options)
        # Discover available conversations (called 'dialogs' in the Telegram API).
        async for dialog in self.client.iter_dialogs():
            if not self.dialog_to_ignore(dialog):
                is_group_conversation = self.is_group_conversation(dialog)
                conversation_in_db = self.get_or_create_conversation(
                    external_id=dialog.id,
                    is_group_conversation=is_group_conversation,
                    last_modified=dialog.date,
                    # In Telegram the name of a private chat is the name of
                    # "the person on the other side" which isn't very useful
                    # given that we store that information separately (chat
                    # messages have a sender and recipient), this is why we
                    # specifically ignore such names.
                    name=dialog.name if is_group_conversation else None,
                )
                if not conversation_in_db.import_complete:
                    await self.perform_initial_sync(dialog, conversation_in_db)
                elif strip_tzinfo(dialog.date) > strip_tzinfo(conversation_in_db.last_modified):
                    logger.info("Conversation was updated (%s) ..", dialog.id)
                    await self.update_conversation(dialog, conversation_in_db)
                    conversation_in_db.last_modified = dialog.date
                else:
                    logger.info("Conversation hasn't changed (%s).", dialog.id)
                self.stats.show()

    def dialog_to_ignore(self, dialog):
        """
        Check if this conversation should be ignored.

        This method exists to exclude two types of conversations:

        - The conversation with the "Telegram" user, because I don't consider
          the service messages in this conversation to be relevant to my chat
          archive.

        - Group conversations that are being synchronized as part of a
          different Telegram account.
        """
        if self.is_service_dialog(dialog):
            logger.verbose("Skipping service dialog (%s) ..", dialog.id)
            return True
        elif self.is_duplicate_dialog(dialog):
            logger.verbose("Skipping dialog that is part of a different Telegram account (%s) ..", dialog.id)
            return True
        else:
            logger.verbose("Dialog not ignored, proceeding with synchronization (%s) ..", dialog.id)
            return False

    def is_duplicate_dialog(self, dialog):
        """Check if the given dialog is being synchronized as part of a different Telegram account."""
        return self.is_group_conversation(dialog) and bool(
            self.session.query(Conversation.id)
            .filter(Account.backend == self.backend_name)
            .filter(Account.name != self.account_name)
            .filter(Conversation.name == dialog.name)
            .first()
        )

    def is_group_conversation(self, dialog):
        """Determine whether the given dialog is a group conversation."""
        return dialog.is_channel or dialog.is_group

    def is_service_dialog(self, dialog):
        """Check if the given dialog is the dialog with the "Telegram" user, containing service messages."""
        return dialog.is_user and dialog.entity.first_name == "Telegram" and not dialog.entity.last_name

    async def perform_initial_sync(self, dialog, conversation_in_db):
        """Start or resume the initial synchronization."""
        options = dict()
        oldest_message = conversation_in_db.oldest_message
        if oldest_message:
            logger.info("Resuming initial synchronization of conversation %s ..", dialog.id)
            options["max_id"] = int(oldest_message.external_id)
        else:
            logger.info("Starting initial synchronization of conversation %s ..", dialog.id)
        if dialog.is_user:
            # TODO Would it be better to explicitly associate contacts to conversations?
            self.sender_to_contact(dialog.entity)
        await self.download_messages(dialog, conversation_in_db, **options)
        conversation_in_db.import_complete = True
        self.archive.commit_changes()

    async def update_conversation(self, dialog, conversation_in_db):
        """Download new messages in an existing conversation."""
        min_id = int(conversation_in_db.newest_message.external_id)
        await self.download_messages(dialog, conversation_in_db, min_id=min_id)

    async def download_messages(self, dialog, conversation_in_db, min_id=0, max_id=0):
        """Download messages in the given conversation."""
        options = dict(max_id=max_id, min_id=min_id)
        async for message in self.client.iter_messages(dialog, **options):
            # Ignore service messages like `User X was added to chat Y'.
            if message.message:
                self.get_or_create_message(
                    conversation=conversation_in_db,
                    external_id=message.id,
                    html=unparse(message.message, message.entities),
                    recipient=self.recipient_to_contact(message.to_id),
                    sender=self.sender_to_contact(message.sender),
                    text=message.message,
                    timestamp=message.date,
                )
                # Commit changes to disk every now and then.
                if self.stats.messages_added % 100 == 0:
                    self.archive.commit_changes()

    def sender_to_contact(self, user):
        """Create a contact in our local database for the given Telegram user."""
        return self.get_or_create_contact(
            external_id=user.id, first_name=user.first_name, last_name=user.last_name, telephone_number=user.phone
        )

    def recipient_to_contact(self, to_id):
        """Create a contact in our local database for the given ``to_id`` value."""
        return self.find_contact_by_external_id(to_id.user_id) if hasattr(to_id, "user_id") else None
