# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: August 2, 2018
# URL: https://github.com/xolox/python-chat-archive

"""Synchronization logic for the Google Hangouts backend of the `chat-archive` program."""

# Standard library modules.
import asyncio
import getpass
import html
import os
import time

# External dependencies.
import hangups
from hangups import Client
from hangups.auth import RefreshTokenCache, get_auth
from hangups.conversation_event import ChatMessageEvent
from hangups.hangouts_pb2 import CONVERSATION_TYPE_GROUP
from hangups.user import DEFAULT_NAME
from humanfriendly import Timer, concatenate, format_timespan, pluralize
from property_manager import PropertyManager, lazy_property, mutable_property, required_property
from verboselogs import VerboseLogger

# Modules included in our package.
from chat_archive.backends import ChatArchiveBackend
from chat_archive.utils import ensure_directory_exists, get_secret

FRIENDLY_NAME = "Google Hangouts"
"""A user friendly name for the chat service supported by this backend (a string)."""

# Initialize a logger for this module.
logger = VerboseLogger(__name__)


class HangoutsBackend(ChatArchiveBackend):

    """
    The Google Hangouts backend for the `chat-archive` program.

    This backend supports the following configuration options:

    =================  =========================================================
    Option             Description
    =================  =========================================================
    ``email-address``  The email address used to sign in to your Google account.
    ``password-name``  The name of a password in ``~/.password-store`` to use.
    ``password``       The password used to sign in to your Google account.
    =================  =========================================================

    If you set ``password-name`` then ``password` doesn't have to be set. If
    ``password`` nor ``password-name`` have been set then you will be prompted
    for your password every time you synchronize.
    """

    @lazy_property
    def bogus_user_ids(self):
        """A :class:`set` of strings with 'gaia_id' values of "bogus" users."""
        return set()

    @mutable_property
    def cookie_file(self):
        """The pathname of the ``*.json`` file with cached credentials (a string)."""
        return os.path.join(self.archive.data_directory, "hangouts", "%s.json" % self.account_name)

    @lazy_property
    def client(self):
        """The hangups client object."""
        # Make sure the directory with cached credentials exists.
        ensure_directory_exists(os.path.dirname(self.cookie_file))
        return Client(
            get_auth(
                GoogleAccountCredentials(
                    email_address=self.config["email-address"],
                    password=get_secret(
                        options=self.config,
                        value_option="password",
                        name_option="password-name",
                        description="Google account password",
                    ),
                ),
                RefreshTokenCache(self.cookie_file),
            )
        )

    @mutable_property
    def retry_count(self):
        """The number of times that a batch of messages will be requested (a number, defaults to 5)."""
        return 5

    def synchronize(self):
        """Download chat contacts and messages and store them in the local archive."""
        event_loop = asyncio.get_event_loop()
        event_loop.run_until_complete(self.connect_then_sync())

    async def connect_then_sync(self):
        """Connect to the Hangouts service and start the synchronization."""
        # Spawn a task for hangups to run in parallel with the coroutine.
        logger.verbose("Spawning task to connect ..")
        task = asyncio.ensure_future(self.client.connect())
        # Wait for hangups to either finish connecting or raise an exception.
        logger.verbose("Waiting for connect task to succeed ..")
        on_connect = asyncio.Future()
        self.client.on_connect.add_observer(lambda: on_connect.set_result(None))
        done, _ = await asyncio.wait((on_connect, task), return_when=asyncio.FIRST_COMPLETED)
        await asyncio.gather(*done)
        logger.verbose("Finished waiting for connection.")
        # Run the synchronization coroutine. Afterwards, disconnect hangups
        # gracefully and yield the hangups task to handle any exceptions.
        try:
            # Get the user and conversation lists.
            logger.verbose("Building user / conversation list ..")
            user_list, conversation_list = await hangups.build_user_conversation_list(self.client)
            self.download_all_contacts(user_list)
            await self.download_all_conversations(conversation_list)
            self.stats.show()
        except asyncio.CancelledError:
            pass
        finally:
            logger.verbose("Disconnecting ..")
            await self.client.disconnect()
            await task

    def download_all_contacts(self, user_list):
        """Download contact details from Google Hangouts."""
        for user in user_list.get_all():
            if self.is_bogus_user(user):
                self.bogus_user_ids.add(user.id_.gaia_id)
            else:
                self.get_or_create_contact(
                    email_addresses=user.emails, external_id=user.id_.gaia_id, full_name=user.full_name
                )

    async def download_all_conversations(self, conversation_list):
        """Download conversations from Google Hangouts."""
        timer = Timer()
        for conversation in conversation_list.get_all(include_archived=True):
            try:
                await self.download_conversation(conversation)
            except Exception:
                logger.warning("Skipping conversation due to synchronization error ..", exc_info=True)
                self.stats.failed_conversations += 1
            self.stats.show()
        summary = []
        if self.stats.conversations_added > 0:
            summary.append(pluralize(self.stats.conversations_added, "conversation"))
        if self.stats.messages_added > 0:
            summary.append(pluralize(self.stats.messages_added, "message"))
        if summary:
            logger.info("Added %s in %s.", concatenate(summary), timer)
        else:
            logger.info("No new conversations or messages found (took %s to check).", timer)
        if self.stats.failed_conversations > 0:
            logger.warning(
                "Skipped %s due to synchronization %s!",
                pluralize(self.stats.failed_conversations, "conversation"),
                "errors" if self.stats.failed_conversations > 1 else "error",
            )
        if self.stats.skipped_conversations > 0:
            logger.notice(
                "Skipped %s due to previous synchronization %s! (use --force to retry %s)",
                pluralize(self.stats.skipped_conversations, "conversation"),
                "errors" if self.stats.skipped_conversations > 1 else "error",
                "them" if self.stats.skipped_conversations > 1 else "it",
            )

    async def download_conversation(self, conversation):
        """Download a single Google Hangouts conversation."""
        # Remove the timezone from the last modified date to enable equality
        # comparison with the values we get back from the database.
        last_modified = conversation.last_modified.replace(tzinfo=None)
        logger.verbose("Checking if we know conversation (%s) ..", conversation.id_)
        conversation_in_db = self.get_or_create_conversation(
            external_id=conversation.id_,
            import_complete=False,
            is_group_conversation=(conversation._conversation.type == CONVERSATION_TYPE_GROUP),
            last_modified=last_modified,
            import_errors=False,
        )
        if conversation_in_db.import_errors and not self.archive.force:
            logger.verbose("Skipping conversation with synchronization errors (use --force to override).")
            self.stats.skipped_conversations += 1
        elif conversation_in_db.import_complete:
            logger.verbose("Checking if conversation has been updated ..")
            if last_modified > conversation_in_db.last_modified:
                logger.info("Conversation has updates available.")
                await self.handle_import_errors(conversation, conversation_in_db)
                conversation_in_db.last_modified = last_modified
            else:
                logger.verbose("Skipping conversation without updates.")
        else:
            await self.perform_initial_sync(conversation, conversation_in_db)

    async def perform_initial_sync(self, conversation, conversation_in_db):
        """Perform the initial synchronization to the start of a conversation."""
        oldest_message = conversation_in_db.oldest_message
        if oldest_message:
            logger.info("Resuming initial synchronization of conversation ..")
            await self.handle_import_errors(conversation, conversation_in_db, oldest_message.external_id)
        else:
            logger.info("Starting initial synchronization of conversation ..")
            await self.handle_import_errors(conversation, conversation_in_db)
        # Mark a successful synchronization (all the way to the start
        # of the conversation) and commit the results to disk.
        conversation_in_db.import_complete = True
        self.archive.commit_changes()

    async def handle_import_errors(self, conversation, conversation_in_db, event_id=None):
        """Download messages in a conversation, handling synchronization errors."""
        try:
            with self.stats:
                await self.download_all_messages(conversation, conversation_in_db, event_id)
        except Exception:
            # Remember that we encountered a synchronization error for this conversation.
            conversation_in_db.import_errors = True
            # Propagate the exception to the caller.
            raise
        else:
            # Forget about previous synchronization errors.
            conversation_in_db.import_errors = False

    async def download_all_messages(self, conversation, conversation_in_db, event_id=None):
        """Download the messages in a specific Hangouts conversation."""
        while True:
            downloaded_messages = []
            new_messages = []
            # Filter out message types that we're not interested in.
            for event in await self.download_message_batch(conversation, event_id):
                if isinstance(event, ChatMessageEvent):
                    downloaded_messages.append(event)
                else:
                    logger.verbose("Ignoring unsupported message type (%s) ..", type(event))
            # Process the messages in reverse chronological order because this
            # is how the Google Hangouts API works and staying as consistent
            # as possible with that should guarantee that we don't cause gaps.
            for event in sorted(downloaded_messages, key=lambda e: event.timestamp, reverse=True):
                attributes = dict(
                    conversation=conversation_in_db,
                    external_id=event.id_,
                    html=self.get_message_html(event),
                    text=event.text,
                    timestamp=event.timestamp,
                )
                # Messages from unknown senders (without unique identification)
                # are stored in the local database without an associated contact.
                if event.user_id.gaia_id not in self.bogus_user_ids:
                    attributes["sender"] = self.find_contact_by_external_id(event.user_id.gaia_id)
                created, message = self.get_or_create_message(**attributes)
                if created:
                    new_messages.append(message)
            if not new_messages:
                return
            # Continue searching for older messages based on the event id
            # of the oldest message in the set of new messages that we've
            # just downloaded.
            new_messages = sorted(new_messages, key=lambda m: m.timestamp)
            event_id = new_messages[0].external_id
            logger.verbose("Searching for new messages older than %s ..", event_id)
            # Commit every set of newly downloaded chat messages to disk
            # immediately, so that we don't have to download messages more
            # than once when we crash due to rate limiting or other API
            # errors emitted by the Hangouts API.
            self.archive.commit_changes()
            # FIXME Poor man's rate limiting :-).
            logger.info("Sleeping for a second ..")
            time.sleep(1)

    async def download_message_batch(self, conversation, event_id):
        """Try to download a batch of messages (retrying according to :attr:`retry_count`)."""
        back_off = 0.5
        for request_nr in range(1, self.retry_count):
            try:
                logger.verbose(
                    "Attempt %i/%i: Requesting messages in conversation (%s) before given message id (%s) ..",
                    request_nr,
                    self.retry_count,
                    conversation.id_,
                    event_id,
                )
                return await conversation.get_events(event_id=event_id)
            except hangups.exceptions.NetworkError:
                if request_nr < self.retry_count:
                    logger.notice(
                        "Attempt %i/%i: Sleeping for %s before retrying failed request ..",
                        request_nr,
                        self.retry_count + 1,
                        format_timespan(back_off),
                    )
                    time.sleep(back_off)
                    back_off = min(back_off * 2, 10)
                else:
                    logger.warning("Giving up on conversation after %i failed requests!", request_nr)
                    raise

    def get_message_html(self, event):
        """Get the formatted text of a chat message as HTML."""
        html_message = []
        for segment in event.segments:
            text = html.escape(segment.text, quote=False)
            if segment.is_bold:
                text = "<b>%s</b>" % text
            if segment.is_italic:
                text = "<i>%s</i>" % text
            if segment.is_strikethrough:
                text = "<s>%s</s>" % text
            if segment.is_underline:
                text = "<u>%s</u>" % text
            if segment.link_target:
                href = html.escape(segment.link_target, quote=True)
                text = '<a href="%s">%s</a>' % (href, text)
            html_message.append(text)
        return "".join(html_message)

    def is_bogus_user(self, user):
        """Ignore default / unknown users made up by :mod:`hangups`."""
        if user.full_name == DEFAULT_NAME:
            logger.verbose("Ignoring default user (based on name %r) ..", DEFAULT_NAME)
            return True
        elif not user.id_.gaia_id:
            logger.verbose("Ignoring user without unique id (missing 'gaia_id') ..")
            return True
        else:
            return False


class GoogleAccountCredentials(PropertyManager):

    """Used to non-interactively provide Google Account credentials to :mod:`hangups`."""

    @required_property
    def email_address(self):
        """The Google account email address (a string)."""

    @required_property
    def password(self):
        """The Google account password (a string)."""

    def get_email(self):
        """Feed the configured :attr:`email_address` to :mod:`hangups`."""
        return self.email_address

    def get_password(self):
        """Feed the configured :attr:`password` to :mod:`hangups`."""
        return self.password

    def get_verification_code(self):
        """Prompt the operator for a verification code."""
        logger.info("Please provide 2FA code to login to your Google account ..")
        return getpass.getpass("Verification code: ")
