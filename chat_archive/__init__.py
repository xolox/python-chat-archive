# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: March 27, 2020
# URL: https://github.com/xolox/python-chat-archive

"""Python API for the `chat-archive` program."""

# Standard library modules.
import collections
import importlib
import os

# External dependencies.
from humanfriendly import concatenate, format, parse_path, pluralize
from pkg_resources import iter_entry_points
from property_manager import lazy_property, mutable_property
from sqlalchemy import func
from update_dotdee import ConfigLoader
from verboselogs import VerboseLogger

# Modules included in our package.
from chat_archive.backends import ChatArchiveBackend
from chat_archive.database import SchemaManager
from chat_archive.models import Account, Base, Contact, Conversation, EmailAddress, Message
from chat_archive.utils import get_full_name

DEFAULT_ACCOUNT_NAME = "default"
"""The name of the default account (a string)."""

# Semi-standard package versioning.
__version__ = "4.0.3"

# Initialize a logger for this module.
logger = VerboseLogger(__name__)


class ChatArchive(SchemaManager):

    """Python API for the `chat-archive` program."""

    @property
    def alembic_directory(self):
        """
        The pathname of the directory containing Alembic migration scripts (a string).

        The value of this property is computed at runtime based on the value of
        ``__file__`` inside of the ``chat_archive/__init__.py`` module.
        """
        return os.path.join(os.path.dirname(__file__), "alembic")

    @lazy_property
    def backends(self):
        """
        A dictionary of available backends (names and dotted paths).

        >>> from chat_archive import ChatArchive
        >>> archive = ChatArchive()
        >>> print(archive.backends)
        {'gtalk': 'chat_archive.backends.gtalk',
         'hangouts': 'chat_archive.backends.hangouts',
         'slack': 'chat_archive.backends.slack',
         'telegram': 'chat_archive.backends.telegram'}
        """
        return dict((ep.name, ep.module_name) for ep in iter_entry_points("chat_archive.backends"))

    @lazy_property
    def config(self):
        """A dictionary with general user defined configuration options."""
        if "chat-archive" in self.config_loader.section_names:
            return self.config_loader.get_options("chat-archive")
        return {}

    @lazy_property
    def config_loader(self):
        r"""
        A :class:`~update_dotdee.ConfigLoader` object that provides access to the configuration.

        .. [[[cog
        .. from update_dotdee import inject_documentation
        .. inject_documentation(program_name='chat-archive')
        .. ]]]

        Configuration files are text files in the subset of `ini syntax`_ supported by
        Python's configparser_ module. They can be located in the following places:

        =========  ==========================  ===============================
        Directory  Main configuration file     Modular configuration files
        =========  ==========================  ===============================
        /etc       /etc/chat-archive.ini       /etc/chat-archive.d/\*.ini
        ~          ~/.chat-archive.ini         ~/.chat-archive.d/\*.ini
        ~/.config  ~/.config/chat-archive.ini  ~/.config/chat-archive.d/\*.ini
        =========  ==========================  ===============================

        The available configuration files are loaded in the order given above, so that
        user specific configuration files override system wide configuration files.

        .. _configparser: https://docs.python.org/3/library/configparser.html
        .. _ini syntax: https://en.wikipedia.org/wiki/INI_file

        .. [[[end]]]
        """
        return ConfigLoader(program_name="chat-archive")

    @property
    def declarative_base(self):
        """The base class for declarative models defined using SQLAlchemy_."""
        return Base

    @mutable_property(cached=True)
    def data_directory(self):
        """
        The pathname of the directory where data files are stored (a string).

        The environment variable ``$CHAT_ARCHIVE_DIRECTORY`` can be used to set
        the value of this property. When the environment variable isn't set the
        default value ``~/.local/share/chat-archive`` is used (where ``~`` is
        expanded to the profile directory of the current user).
        """
        return parse_path(os.environ.get("CHAT_ARCHIVE_DIRECTORY", "~/.local/share/chat-archive"))

    @mutable_property
    def database_file(self):
        """
        The absolute pathname of the SQLite_ database file (a string).

        This defaults to ``~/.local/share/chat-archive/database.sqlite3`` (with
        ``~`` expanded to the home directory of the current user) based on
        :attr:`data_directory`.

        .. _SQLite: https://sqlite.org/
        """
        return os.path.join(self.data_directory, "database.sqlite3")

    @mutable_property
    def force(self):
        """
        Retry synchronization of conversations where errors were previously
        encountered (a boolean, defaults to :data:`False`).
        """
        return False

    @lazy_property
    def import_stats(self):
        """Statistics about objects imported by backends (a :class:`BackendStats` object)."""
        return BackendStats()

    @property
    def num_contacts(self):
        """The total number of chat contacts in the local archive (a number)."""
        return self.session.query(func.count(Contact.id)).scalar()

    @property
    def num_conversations(self):
        """The total number of chat conversations in the local archive (a number)."""
        return self.session.query(func.count(Conversation.id)).scalar()

    @property
    def num_html_messages(self):
        """The total number of chat messages with HTML formatting in the local archive (a number)."""
        return self.session.query(func.count(Message.id)).filter(Message.html != None).scalar()

    @property
    def num_messages(self):
        """The total number of chat messages in the local archive (a number)."""
        return self.session.query(func.count(Message.id)).scalar()

    @lazy_property
    def operator_name(self):
        """
        The full name of the person using the `chat-archive` program (a string or :data:`None`).

        The value of :attr:`operator_name` is used to address the operator of
        the `chat-archive` program in first person instead of third person. You
        can change the value in the configuration file:

        .. code-block:: ini

           [chat-archive]
           operator-name = ...

        The default value in case none has been specified in the configuration
        file is taken from ``/etc/passwd`` using :func:`.get_full_name()`.
        """
        value = self.config.get("my-name")
        if not value:
            value = get_full_name()
        return value

    def commit_changes(self):
        """Show import statistics when committing database changes to disk."""
        # Show import statistics just before every commit, to give the
        # operator something nice to look at while they're waiting 😇.
        self.import_stats.show()
        # Commit database changes to disk (and possibly save profile data).
        return super(ChatArchive, self).commit_changes()

    def get_accounts_for_backend(self, backend_name):
        """Select the configured and/or previously synchronized account names for the given backend."""
        from_config = set(self.get_accounts_from_config(backend_name))
        from_database = set(self.get_accounts_from_database(backend_name))
        return sorted(from_config | from_database)

    def get_accounts_from_database(self, backend_name):
        """Get the names of the accounts that are already in the database for the given backend."""
        return [a.name for a in self.session.query(Account).filter(Account.backend == backend_name)]

    def get_accounts_from_config(self, backend_name):
        """Get the names of the accounts configured for the given backend in the configuration file."""
        for section_name in self.config_loader.section_names:
            configured_backend, configured_account = self.parse_account_expression(section_name)
            if backend_name == configured_backend:
                yield configured_account or DEFAULT_ACCOUNT_NAME

    def get_backend_name(self, backend_name):
        """Get a human friendly name for the given backend."""
        module = self.load_backend_module(backend_name)
        return getattr(module, "FRIENDLY_NAME", backend_name)

    def get_backends_and_accounts(self, *backends):
        """Select backends and accounts to synchronize."""
        if backends:
            for expression in backends:
                backend_name, account_name = self.parse_account_expression(expression)
                if backend_name and account_name:
                    # Synchronize the given (backend, account) pair.
                    yield backend_name, account_name
                else:
                    # Synchronize all accounts for the given backend.
                    for account_name in self.get_accounts_for_backend(backend_name):
                        yield backend_name, account_name
        else:
            # Synchronize all accounts for all backends.
            for backend_name in sorted(self.backends):
                for account_name in self.get_accounts_for_backend(backend_name):
                    yield backend_name, account_name

    def initialize_backend(self, backend_name, account_name):
        """
        Load a chat archive backend module.

        :param backend_name: The name of the backend (one of the strings
                             'gtalk', 'hangouts', 'slack' or 'telegram').
        :param account_name: The name of the account (a string).
        :returns: A :class:`~chat_archive.backends.ChatArchiveBackend` object.
        :raises: :exc:`Exception` when the backend doesn't define a subclass of
                 :class:`~chat_archive.backends.ChatArchiveBackend`.
        """
        module = self.load_backend_module(backend_name)
        for value in module.__dict__.values():
            if isinstance(value, type) and issubclass(value, ChatArchiveBackend) and value is not ChatArchiveBackend:
                return value(
                    account_name=account_name, archive=self, backend_name=backend_name, stats=self.import_stats
                )
        msg = "Failed to locate backend class! (%s)"
        raise Exception(msg % backend_name)

    def is_operator(self, contact):
        """Check whether the full name of the given contact matches :attr:`operator_name`."""
        return self.operator_name and contact.full_name == self.operator_name

    def load_backend_module(self, backend_name):
        """
        Load a chat archive backend module.

        :param backend_name: The name of the backend (one of the strings
                             'gtalk', 'hangouts', 'slack' or 'telegram').
        :returns: The loaded module.
        """
        dotted_path = self.backends[backend_name]
        logger.verbose("Importing %s backend module: %s", backend_name, dotted_path)
        return importlib.import_module(dotted_path)

    def parse_account_expression(self, value):
        """
        Parse a ``backend:account`` expression.

        :param value: The ``backend:account`` expression (a string).
        :returns: A tuple with two values:

                  1. The name of a backend (a string).
                  2. The name of an account (a string, possibly empty).
        """
        backend_name, _, account_name = value.partition(":")
        return backend_name, account_name

    def search_messages(self, keywords):
        """Search the chat messages in the local archive for the given keyword(s)."""
        query = (
            self.session.query(Message)
            .join(Conversation)
            .join(Account)
            .outerjoin((Contact, Contact.id == Message.sender_id))
            .outerjoin((EmailAddress, Contact.email_addresses))
        )
        for kw in keywords:
            search_term = format(u"%{kw}%", kw=kw)
            query = query.filter(
                Account.backend.like(search_term)
                | Account.name.like(search_term)
                | Conversation.name.like(search_term)
                | Contact.full_name.like(search_term)
                | EmailAddress.value.like(search_term)
                | Message.timestamp.like(search_term)
                | Message.text.like(search_term)
            )
        return query.order_by(Message.timestamp)

    def synchronize(self, *backends):
        """
        Download new chat messages.

        :param backends: Any positional arguments limit the synchronization to
                         backends whose name matches one of the strings
                         provided as positional arguments.

        If the name of a backend contains a colon the name is split into two:

        1. The backend name.
        2. An account name.

        This way one backend can synchronize multiple named accounts into the
        same local database without causing confusion during synchronization
        about which conversations, contacts and messages belong to which
        account.
        """
        # Synchronize the selected (backend, account) pairs.
        for backend_name, account_name in self.get_backends_and_accounts(*backends):
            # Provide backends their own import statistics without losing
            # aggregate statistics collected about all backends together.
            with self.import_stats:
                logger.info(
                    "Synchronizing %s messages in %r account ..", self.get_backend_name(backend_name), account_name
                )
                self.initialize_backend(backend_name, account_name).synchronize()
        # Commit any outstanding database changes.
        self.commit_changes()


class BackendStats(object):

    """Statistics about chat message synchronization backends."""

    def __init__(self):
        """Initialize a :class:`BackendStats` object."""
        object.__setattr__(self, "stack", [collections.defaultdict(int)])

    def __enter__(self):
        """Alias for :attr:`push()`."""
        self.push()

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Alias for :attr:`pop()`."""
        self.pop()

    def __getattr__(self, name):
        """Get the value of a counter from the current scope."""
        return self.scope[name]

    def __setattr__(self, name, value):
        """Set the value of a counter in the current scope."""
        self.scope[name] = value

    def pop(self):
        """Remove the inner scope and merge its counters into the outer scope."""
        counters = self.stack.pop(-1)
        for name, value in counters.items():
            self.scope[name] += value

    def push(self):
        """Create a new inner scope with all counters reset to zero."""
        self.stack.append(collections.defaultdict(int))

    def show(self):
        """Show statistics about imported conversations, messages, contacts, etc."""
        additions = []
        if self.conversations_added > 0:
            additions.append(pluralize(self.conversations_added, "conversation"))
        if self.messages_added > 0:
            additions.append(pluralize(self.messages_added, "message"))
        if self.contacts_added > 0:
            additions.append(pluralize(self.contacts_added, "contact"))
        if self.email_addresses_added > 0:
            additions.append(pluralize(self.contacts_added, "email address", "email addresses"))
        if self.telephone_numbers_added > 0:
            additions.append(pluralize(self.telephone_numbers_added, "telephone number"))
        if additions:
            logger.info("Imported %s.", concatenate(additions))

    @property
    def scope(self):
        """The current scope (a :class:`collections.defaultdict` object)."""
        return self.stack[-1]
