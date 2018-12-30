# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: December 31, 2018
# URL: https://github.com/xolox/python-chat-archive

"""SQLAlchemy based database helpers."""

# Standard library modules.
import os

# External dependencies.
from alembic.command import stamp, upgrade
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from coloredlogs import get_level, set_level
from humanfriendly import Timer
from property_manager import PropertyManager, cached_property, lazy_property, required_property, writable_property
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from verboselogs import VerboseLogger

# Modules included in our package.
from chat_archive.profiling import ProfileManager
from chat_archive.utils import ensure_directory_exists

# Initialize a logger for this module.
logger = VerboseLogger(__name__)


class DatabaseClient(ProfileManager):

    """Simple wrapper for SQLAlchemy that makes it easy to use with SQLite."""

    def __init__(self, *args, **kw):
        """
        Initialize a :class:`DatabaseClient` object.

        Please refer to the :class:`~property_manager.PropertyManager`
        documentation for details about the handling of arguments.
        """
        super(DatabaseClient, self).__init__(*args, **kw)
        if self.database_file:
            ensure_directory_exists(os.path.dirname(self.database_file))

    @lazy_property
    def database_engine(self):
        """An SQLAlchemy database engine connected to :attr:`database_url`."""
        return create_engine(self.database_url, echo=self.echo_queries)

    @writable_property
    def database_file(self):
        """The absolute pathname of an SQLite database file (a string or :data:`None`)."""

    @required_property
    def database_url(self):
        """
        A URL that indicates the database dialect and connection arguments to SQLAlchemy (a string).

        The value of :attr:`database_url` defaults to a URL that instructs
        SQLAlchemy to use an SQLite 3 database file located at the pathname
        given by :attr:`database_file`, but of course you are free to point
        SQLAlchemy to any supported database server.
        """
        if self.database_file:
            return "sqlite:///%s" % self.database_file

    @writable_property
    def echo_queries(self):
        """Whether queries should be logged to :data:`sys.stderr` (a boolean, defaults to :data:`False`)."""
        return False

    @lazy_property
    def session(self):
        """An SQLAlchemy session created by :attr:`session_factory`."""
        return self.session_factory()

    @lazy_property
    def session_factory(self):
        """An SQLAlchemy session factory connected to :attr:`database_engine`."""
        return sessionmaker(bind=self.database_engine)

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Automatically commit database changes when the :keyword:`with` block ends."""
        # Save database changes.
        if exc_type is None:
            self.commit_changes()
        # Save profile data.
        return super(DatabaseClient, self).__exit__(exc_type, exc_value, traceback)

    def commit_changes(self):
        """Commit database changes to disk."""
        # Commit the changes to disk and adjust the log verbosity of
        # the message afterwards based on the time it took to commit.
        logger.verbose("Committing database changes ..")
        timer = Timer()
        self.session.commit()
        if timer.elapsed_time > 0.5:
            logger.info("Committed database changes to disk (took %s).", timer)
        else:
            logger.verbose("Committed database changes to disk (took %s).", timer)


class SchemaManager(DatabaseClient):

    """Easy to use database schema upgrades based on Alembic."""

    def __init__(self, *args, **kw):
        """
        Initialize a :class:`SchemaManager` object.

        This method automatically calls :func:`run_migrations()` (and
        :func:`initialize_schema()` when the database is initially created) to
        ensure that the database schema is up to date.
        """
        super(SchemaManager, self).__init__(*args, **kw)
        if self.auto_create_schema or self.auto_upgrade_schema:
            timer = Timer()
            first_run = self.current_schema_revision is None
            if self.auto_upgrade_schema:
                self.run_migrations()
            if self.auto_create_schema and first_run:
                self.initialize_schema()
            logger.verbose("Took %s to initialize and/or upgrade database schema.", timer)

    @lazy_property
    def alembic_config(self):
        """
        A minimal Alembic configuration object.

        This configuration objects contains two options:

        - ``sqlalchemy.url`` is set to :attr:`.database_url`
        - ``script_location`` is set to :attr:`alembic_directory`

        :raises: :exc:`~exceptions.ValueError` when :attr:`alembic_directory` isn't set.
        """
        if not self.alembic_directory:
            raise ValueError("The 'alembic_directory' option hasn't been set!")
        config = Config()
        config.set_main_option("sqlalchemy.url", self.database_url)
        config.set_main_option("script_location", self.alembic_directory)
        return config

    @writable_property
    def alembic_directory(self):
        """The absolute pathname of the directory containing Alembic's ``env.py`` file (a string or :data:`None`)."""

    @writable_property
    def auto_create_schema(self):
        """
        :data:`True` if automatic database schema upgrades are enabled, :data:`False` otherwise.

        This defaults to :data:`True` when :attr:`declarative_base` is set, :data:`False` otherwise.
        """
        return self.declarative_base is not None

    @writable_property
    def auto_upgrade_schema(self):
        """
        :data:`True` if automatic database schema initialization is enabled, :data:`False` otherwise.

        This defaults to :data:`True` when :attr:`alembic_directory` is set, :data:`False` otherwise.
        """
        return self.alembic_directory is not None

    @cached_property
    def current_schema_revision(self):
        """The current database schema revision in the database that we're connected to (a string or :data:`None`)."""
        logger.debug("Finding Alembic current revision ..")
        with CustomVerbosity(level="warning"):
            context = MigrationContext.configure(self.database_engine.connect())
            revision = context.get_current_revision()
        if revision:
            logger.verbose("Schema revision in database is %s.", revision)
            return revision
        else:
            logger.verbose("No schema revision found in database!")

    @writable_property
    def declarative_base(self):
        """The base class for declarative models defined using SQLAlchemy."""

    @lazy_property
    def latest_schema_revision(self):
        """The current schema revision according to Alembic's migration scripts (a string)."""
        logger.debug("Finding Alembic head revision ..")
        migrations = ScriptDirectory.from_config(self.alembic_config)
        revision = migrations.get_current_head()
        logger.verbose("Current head (code base) database schema revision is %s.", revision)
        return revision

    @property
    def schema_up_to_date(self):
        """:data:`True` if the database schema is up to date, :data:`False` otherwise."""
        return self.current_schema_revision == self.latest_schema_revision

    def initialize_schema(self):
        """
        Initialize the database schema using SQLAlchemy_.

        This method is automatically called when a :class:`SchemaManager`
        object is created. In order to initialize the database schema the
        :attr:`declarative_base` property needs to be set, but if it's not
        set then :func:`initialize_schema()` won't complain.

        .. _SQLAlchemy: https://www.sqlalchemy.org/
        """
        if self.declarative_base:
            timer = Timer()
            logger.verbose("Creating missing database tables and indexes ..")
            self.declarative_base.metadata.create_all(self.database_engine)
            logger.success("Initialized database schema in %s.", timer)

    def run_migrations(self):
        """
        Upgrade the database schema using Alembic_.

        This method is automatically called when a :class:`SchemaManager`
        object is created. In order to upgrade the database schema the
        :attr:`alembic_directory` property needs to be set, but if it's
        not set then :func:`run_migrations()` won't complain.

        .. _Alembic: http://alembic.zzzcomputing.com/
        """
        if self.alembic_directory:
            timer = Timer()
            logger.verbose("Checking whether database needs upgrading ..")
            if not self.current_schema_revision:
                logger.verbose("Stamping empty database with current schema revision ..")
                with CustomVerbosity(level="warning"):
                    stamp(self.alembic_config, "head")
                logger.success("Stamped initial database schema revision in %s.", timer)
                # Invalidate cached property.
                del self.current_schema_revision
            elif not self.schema_up_to_date:
                logger.info("Running database migrations ..")
                with CustomVerbosity(level="info"):
                    upgrade(self.alembic_config, "head")
                logger.info("Successfully upgraded database schema in %s.", timer)
                # Invalidate cached property.
                del self.current_schema_revision
            else:
                logger.verbose("Database schema already up to date! (took %s to check)", timer)


class CustomVerbosity(PropertyManager):

    """
    Easily customize logging verbosity for a given scope.

    This is used by :class:`SchemaManager` to silence Alembic_ because it's
    rather verbose by default, presumably because its primary purpose is to be
    a command line program and not a library embedded in an application.
    """

    @required_property
    def level(self):
        """The overridden logging verbosity level."""

    @writable_property
    def original_level(self):
        """The original logging verbosity level."""

    def __enter__(self):
        """Customize the logging verbosity when entering the :keyword:`with` block."""
        if self.original_level is None:
            self.original_level = get_level()
        set_level(self.level)

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Restore the original logging verbosity when leaving the :keyword:`with` block."""
        if self.original_level is not None:
            set_level(self.original_level)
            self.original_level = None
