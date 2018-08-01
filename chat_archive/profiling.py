# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: July 16, 2018
# URL: https://github.com/xolox/python-chat-archive

"""Easy to use Python code profiling support."""

# Import the fastest available profiling module.
try:
    import cProfile as profile
except ImportError:
    import profile

# External dependencies.
from humanfriendly import Timer
from property_manager import PropertyManager, writable_property
from verboselogs import VerboseLogger

# Initialize a logger for this module.
logger = VerboseLogger(__name__)


class ProfileManager(PropertyManager):

    """
    Base class for easy to use Python code profiling support.

    This class makes it easy to enable and disable Python code profiling and
    save the results to a file. You can use it in a :keyword:`with` statement
    to guarantee that the profile is saved even when your program is
    interrupted with Control-C, so when your program is too slow and you're
    wondering why you can just restart the program with profiling enabled, wait
    for it to get slow, give it a while to collect profile statistics and then
    interrupt it with Control-C.

    When :attr:`profile_file` is set the class initializer method will
    automatically call :func:`enable_profiling()`.
    """

    def __init__(self, *args, **kw):
        """
        Initialize a :class:`ProfileManager` object.

        Please refer to the :class:`~property_manager.PropertyManager`
        documentation for details about the handling of arguments.
        """
        super(ProfileManager, self).__init__(*args, **kw)
        if self.profile_file:
            self.enable_profiling()

    def __enter__(self):
        """Automatically enable code profiling when the :keyword:`with` block starts."""
        if self.can_save_profile:
            self.enable_profiling()
        return self

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Disable code profiling and save the profile statistics when the :keyword:`with` block ends."""
        if self.profiling_enabled:
            self.disable_profiling()
            if self.can_save_profile:
                self.save_profile()

    @property
    def can_save_profile(self):
        """:data:`True` if :func:`save_profile()` is expected to work, :data:`False` otherwise."""
        return self.profile_file is not None

    @writable_property
    def profile_file(self):
        """The pathname of a file where Python profile statistics should be saved (a string or :data:`None`)."""

    @writable_property
    def profiler(self):
        """A :class:`profile.Profile` object (if :attr:`profile_file` is set) or :data:`None`."""

    @writable_property
    def profiling_enabled(self):
        """:data:`True` if code profiling is enabled, :data:`False` otherwise."""

    def enable_profiling(self):
        """Enable Python code profiling."""
        if self.profiler is None:
            logger.verbose("Initializing Python code profiler ..")
            self.profiler = profile.Profile()
        if not self.profiling_enabled:
            logger.info("Enabling Python code profiling ..")
            self.profiler.enable()
            self.profiling_enabled = True

    def disable_profiling(self):
        """Disable Python code profiling."""
        if self.profiler is not None and self.profiling_enabled:
            logger.verbose("Disabling Python code profiling ..")
            self.profiler.disable()
            self.profiling_enabled = False

    def save_profile(self, filename=None):
        """
        Save gathered profile statistics to a file.

        :param filename: The pathname of the profile file (a string or
                         :data:`None`). Defaults to the value of
                         :attr:`profile_file`.
        :raises: :exc:`~exceptions.ValueError` when profiling was never enabled
                 or `filename` isn't given and :attr:`profile_file` also isn't
                 set.
        """
        filename = filename or self.profile_file
        if not filename:
            raise TypeError("Missing 'filename' argument!")
        elif self.profiler is None:
            raise ValueError("Code profiling isn't enabled!")
        timer = Timer()
        logger.info("Saving profile statistics to %s ..", self.profile_file)
        if self.profiling_enabled:
            self.profiler.disable()
            self.profiling_enabled = False
            profiling_disabled = True
        else:
            profiling_disabled = False
        self.profiler.dump_stats(self.profile_file)
        if profiling_disabled:
            self.profiler.enable()
        logger.verbose("Took %s to save profile statistics.", timer)
