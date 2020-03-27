# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: March 27, 2020
# URL: https://github.com/xolox/python-chat-archive

"""Utility functions for the `chat-archive` program."""

# Standard library modules.
import datetime
import getpass
import logging
import os
import pwd
import time

# External dependencies.
from humanfriendly import format
from qpass import PasswordStore

# Initialize a logger for this module.
logger = logging.getLogger(__name__)


def ensure_directory_exists(pathname):
    """
    Create a directory if it doesn't exist yet.

    :param pathname: The pathname of the directory (a string).
    """
    if not os.path.isdir(pathname):
        os.makedirs(pathname)


def get_full_name():
    """
    Find the full name of the current user on the local system based on ``/etc/passwd``.

    :returns: A string with the full name of the current user or an empty
              string when this information is not available.
    """
    try:
        entry = pwd.getpwuid(os.getuid())
        gecos = entry.pw_gecos.split(",")
        return gecos[0]
    except Exception:
        return ""


def get_secret(options, value_option, name_option, description):
    """
    Get a secret needed to connect to a chat service (like a password or API token).

    :param options: A dictionary with configuration options.
    :param value_option: The name of the configuration option that defines the
                         value of a secret (a string).
    :param name_option: The name of the configuration option that defines the
                        name of a secret in ``~/.password-store`` (a string).
                        See also :func:`get_secret_from_store()`.
    :param description: A description of the type of secret that the operator
                        will be prompted for (a string).
    :returns: The password (a string).
    """
    if value_option in options:
        logger.debug("Getting password from configuration option %r ..", value_option)
        return options[value_option]
    elif name_option in options:
        logger.debug("Getting password from password store (%s) ..", options[name_option])
        return get_secret_from_store(name=options[name_option], directory=options.get("password-store"))
    else:
        logger.debug("Prompting operator for interactive password entry ..")
        return prompt_for_password("Please enter %s: " % description)


def get_secret_from_store(name, directory=None):
    """
    Use :mod:`qpass` to get a secret from ``~/.password-store``.

    :param name: The name of a password or a search pattern that matches a
                 single entry in the password store (a string).
    :param directory: The directory to use (a string, defaults to
                      ``~/.password-store``).
    :returns: The secret (a string).
    :raises: :exc:`exceptions.ValueError` when the given `name` doesn't match
             any entries or matches multiple entries in the password store.
    """
    kw = dict(directory=directory) if directory else {}
    store = PasswordStore(**kw)
    matches = store.smart_search(name)
    if len(matches) != 1:
        msg = "Expected exactly one match in password database! (input: %s)"
        raise ValueError(format(msg, name))
    return matches[0].password


def prompt_for_password(prompt_text):
    """Interactively prompt the operator for a password."""
    return getpass.getpass(prompt_text)


def strip_tzinfo(value):
    """Strip timezone information from :class:`datetime.datetime` objects to enable comparison."""
    return value if value.tzinfo is None else value.replace(tzinfo=None)


def utc_to_local(utc_value):
    """Convert a UTC :class:`~datetime.datetime` object to the local timezone."""
    epoch = time.mktime(utc_value.timetuple())
    offset = datetime.datetime.fromtimestamp(epoch) - datetime.datetime.utcfromtimestamp(epoch)
    return utc_value + offset
