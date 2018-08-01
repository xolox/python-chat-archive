# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: August 1, 2018
# URL: https://github.com/xolox/python-chat-archive

"""
Test suite for the `chat-archive` project.

Over the years I've learned that the development of large software projects
from my hands without tests eventually comes to a grinding halt. At the same
time creating and maintaining a proper test suite can double the workload.

Right now this isn't really a test suite to speak of. I'd like to improve on
that, but this will take time, and it's definitely not high on my list of
priorities 😇.
"""

# Standard library modules.
import logging
import urllib.parse

# External dependencies.
from humanfriendly.testing import TestCase

# Modules included in our package.
from chat_archive import ChatArchive
from chat_archive.html.redirects import expand_url

# Ugly way to raise coverage.
import chat_archive.cli
import chat_archive.html.keywords
import chat_archive.emoji

# Initialize a logger for this module.
logger = logging.getLogger(__name__)


class ChatArchiveTestCase(TestCase):

    """Container for the `chat-archive` tests."""

    def get_test_archive(self):
        return ChatArchive(database_file=':memory:')

    def test_expand_url(self):
        """Test the :func:`~chat_archive.html.redirects.expand_url()` function."""
        target_url = 'https://www.python.org/'
        for scheme in 'http', 'https':
            redirect_url = '%s://www.google.com/url?q=%s' % (scheme, urllib.parse.quote(target_url))
            assert expand_url(redirect_url) == target_url

    def test_backend_discovery(self):
        """Test the discovery of backends through entry points."""
        archive = self.get_test_archive()
        assert len(archive.backends) >= 4
        assert 'gtalk' in archive.backends
        assert 'hangouts' in archive.backends
        assert 'slack' in archive.backends
        assert 'telegram' in archive.backends

    def test_backend_loading(self):
        """Test the importing of backend modules."""
        archive = self.get_test_archive()
        for name in sorted(archive.backends):
            archive.load_backend_module(name)
