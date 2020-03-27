chat-archive: Easy to use offline chat archive
==============================================

The Python_ program `chat-archive` provides a local archive of chat messages
that can be viewed and searched on the command line. Supported chat services
include `Google Talk`_, `Google Hangouts`_, Slack_ and Telegram_. The program
was developed on Linux and currently assumes a UNIX command line environment,
although this is not fundamental to the program's design (for example I could
imagine someone building a GUI or web interface using the Python API).

When you add a new account the initial synchronization will download your full
conversation history from the chat service in question, this can take quite a
while. Later synchronization runs will be much quicker because only updates
(new messages and conversations) are downloaded.

Chat messages are downloaded as plain text and when possible also with
formatting (encoded as HTML). When viewing chat messages on the terminal
the formatted text will be shown.

Python 3.5+ is required due to the asynchronous nature of some of the backends.

.. contents::
   :local:

Status
------

This is very young software, developed in a couple of sprints in the summer of
2018, so it's bound to be full of bugs! The fact that it doesn't have a test
suite doesn't help. However since creating this program I've started using it
on a daily basis, so I may very well be the first one to run into most if not
all bugs 😇.

There's a lot of implementation details in the code base that I'm not proud of
and there's a ton of features that I would like to add, for example right now
the command line is still rather bare bones (minimal). I've decided to
nevertheless publish what I have right now, because in its current state this
project is already very useful for me, so it might be useful to others.

I consider the first release to be representative of the functional goals I had
in mind when I set out to build this, but I'd love to find the time to refactor
the code base once or twice more 😋. Before publishing the first release I had
already gone through three or four complete rewrites and each of those rewrites
improved the quality of the code, yet I'm still not fully satisfied... Oh well,
at least it seems to work 😉.

Installation
------------

The `chat-archive` package is available on PyPI_ which means installation
should be as simple as:

.. code-block:: sh

   $ pip3 install chat-archive

Make sure you're using Python 3.5+ because this is required by dependencies of
the `chat-archive` program.

There's actually a multitude of ways to install Python packages (e.g. the `per
user site-packages directory`_, `virtual environments`_ or just installing
system wide) and I have no intention of getting into that discussion here, so
if this intimidates you then read up on your options before returning to these
instructions 😉.

Usage
-----

The command line interface is documented below. For more details about the
Python API please refer to the API documentation available on `Read the
Docs`_.

.. contents::
   :local:

Command line
~~~~~~~~~~~~

.. A DRY solution to avoid duplication of the `chat-archive --help' text:
..
.. [[[cog
.. from humanfriendly.usage import inject_usage
.. inject_usage('chat_archive.cli')
.. ]]]

**Usage:** `chat-archive [OPTIONS] [COMMAND]`

Easy to use offline chat archive that can gather chat message
history from Google Talk, Google Hangouts, Slack and Telegram.

Supported commands:

- The 'sync' command downloads new chat messages from supported chat
  services and stores them in the local archive (an SQLite database).

- The 'search' command searches the chat messages in the local archive
  for the given keyword(s) and lists matching messages.

- The 'list' command lists all messages in the local archive.

- The 'stats' command shows statistics about the local archive.

- The 'unknown' command searches for conversations that contain messages from
  an unknown sender and allows you to enter the name of a new contact to
  associate with all of the messages from an unknown sender. Conversations
  involving multiple unknown sender are not supported.

**Supported options:**

.. csv-table::
   :header: Option, Description
   :widths: 30, 70


   "``-C``, ``--context=COUNT``","Print ``COUNT`` messages of output context during 'chat-archive search'. This
   works similarly to 'grep ``-C``'. The default value of ``COUNT`` is 3."
   "``-f``, ``--force``","Retry synchronization of conversations where errors were previously
   encountered. This option is currently only relevant to the Google Hangouts
   backend, because I kept getting server errors when synchronizing a few
   specific conversations and I didn't want to keep seeing each of those
   errors during every synchronization run :-)."
   "``-c``, ``--color=CHOICE,`` ``--colour=CHOICE``","Specify whether ANSI escape sequences for text and background colors and
   text styles are to be used or not, depending on the value of ``CHOICE``:
   
   - The values 'always', 'true', 'yes' and '1' enable colors.
   - The values 'never', 'false', 'no' and '0' disable colors.
   - When the value is 'auto' (this is the default) then colors will
     only be enabled when an interactive terminal is detected."
   "``-l``, ``--log-file=LOGFILE``","Save logs at DEBUG verbosity to the filename given by ``LOGFILE``. This option
   was added to make it easy to capture the log output of an initial
   synchronization that will be downloading thousands of messages."
   "``-p``, ``--profile=FILENAME``","Enable profiling of the chat-archive application to make it possible to
   analyze performance problems. Python profiling data will be saved to
   ``FILENAME`` every time database changes are committed (making it possible to
   inspect the profile while the program is still running)."
   "``-v``, ``--verbose``",Increase logging verbosity (can be repeated).
   "``-q``, ``--quiet``",Decrease logging verbosity (can be repeated).
   "``-h``, ``--help``",Show this message and exit.

.. [[[end]]]

The 'sync' command
++++++++++++++++++

The command ``chat-archive sync`` downloads new chat messages using the
configured backends and stores the messages in the local SQLite database.
Positional arguments can be used to synchronize specific backends or accounts.
For example I have two Telegram accounts, a personal account and a work
account. The following command will synchronize both of these accounts::

 $ chat-archive sync telegram

When I'm only interested in a specific account I can instead do this::

 $ chat-archive sync telegram:personal

You can make this as complex as you want::

 $ chat-archive sync hangouts slack:work telegram:personal

The command above will synchronize all configured Google Hangouts accounts, the
Slack work account and the Telegram personal account. The following table shows
the backend names you can use like this:

============  ==================
Backend name  Chat service
============  ==================
``gtalk``     `Google Talk`_
``hangouts``  `Google Hangouts`_
``slack``     Slack_
``telegram``  Telegram_
============  ==================

The 'search' command
++++++++++++++++++++

The command ``chat-archive search`` performs a keyword search through the chat
messages in the local SQLite database and renders the search results on the
terminal. Keywords are provided as positional arguments to the ``search``
command and trigger a case insensitive AND search through the following message
metadata:

- The name of the backend (see the table above).
- The name of the account (``default`` or a user defined name).
- The name of the conversation (relevant for group conversations).
- The full name of the contact that sent the message.
- The email address of the contact that sent the message.
- The timestamp of the message. Any prefix of the date format ``YYYY-MM-DD
  HH:MM:SS`` should work, judging by the date/time searches that I've tried so
  far. So for example the keyword ``2018`` will match all messages from that
  year, ``2018-08`` will match all messages in a specific month, etc.
- The text of the message. The plain text chat message as well as the HTML
  formatted chat message (when available) are searched, this enables searching
  for semantically meaningful HTML data like hyperlink targets.

The search results reported on the terminal include surrounding chat messages
from the matching conversations, to provide additional context. You can control
how many surrounding chat messages are rendered using the ``-C``, ``--context``
command line option, the value 0 can be used to omit the context.

The 'list' command
++++++++++++++++++

The command ``chat-archive list`` renders a listing of all chat messages in the
database on the terminal.

Due to the gathering of context the ``chat-archive search`` command can be
rather slow and this is why I added the ``chat-archive list`` command early in
the development of the project (it's faster because it doesn't have to gather
context). Since then I've collected 226.941 chat messages, completely negating
the usefulness of the ``chat-archive list`` command 😇.

In any case this can be considered a very simple form of export functionality,
so I've decided to keep the ``chat-archive list`` command for now, despite its
limited usefulness once one actively starts using the ``chat-archive`` program.

The 'stats' command
+++++++++++++++++++

The command ``chat-archive stats`` reports some statistics about the contents
of the local SQLite database. Here's what that looks like for me at the time of
writing::

 Statistics about ~/.local/share/chat-archive/database.sqlite3:

  - Number of contacts: 284
  - Number of conversations: 5803
  - Number of messages: 226941
  - Database file size: 90.81 MB
  - Size of 226941 plain text chat messages: 18.7 MB
  - Size of 13409 HTML formatted chat messages: 4.25 MB

The 'unknown' command
+++++++++++++++++++++

The first time I synchronized the thousands of chat messages in my Google
Hangouts account I was very disappointed to find out that all metadata about
contacts whose accounts had since been deleted was lost (no names, no email
addresses, nothing).

This is why I added the ``chat-archive unknown`` command. It searches the local
database for private conversations that contain messages from an unknown sender
and prompts you to enter a name for the contact. When you enter a (nonempty)
name a new contact is created and the messages in the conversation which have
no sender are associated to the new contact.

Weirdly enough the Google Mail archive of chat messages was able to show me
names for most of the contacts for which the Google Hangouts API no longer
reported any useful information, this is how I was able to (manually)
reconstruct this bit of history.

If the Google Mail archive had not provided me with this information I still
would have been able to reconstruct the senders of 90% of these conversations
simply by the fact that quite a few conversations start with "Hi $name" and I
still have "client side chat archive backups" (Pidgin) from 2011-2015.

Configuration files
~~~~~~~~~~~~~~~~~~~

If you're going to be synchronizing your chat message history frequently you
can define credentials for the chat services that you are interested in using a
configuration file.

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

The special configuration file section ``chat-archive`` defines general
options. Right now only the ``operator-name`` option is supported here. All
other sections are specific to a chat account and encode the name of the
backend and the name of the account in the name of the section by delimiting
the two values with a colon. Here's an example based on my configuration, that
shows the supported options:

.. code-block:: ini

   [chat-archive]
   operator-name = ...

   [hangouts:work]
   email-address = ...
   password = ...
   # Alternatively:
   password-name = ...

   [slack:work]
   api-token = ...
   # Alternatively:
   api-token-name = ...

   [gtalk:work]
   email = ...
   password = ...
   # Alternatively:
   password-name = ...

   [telegram:personal]
   api-hash = ...
   api-id = ...
   phone-number = ...

   [telegram:work]
   api-hash = ...
   api-id = ...
   phone-number = ...
   # Alternatively:
   api-hash-name = ...
   api-id-name = ...

When an account is configured but the configuration doesn't define a required
secret then you will be prompted to provide that secret every time you run the
``chat-archive sync`` command.

The values of the ``api-token-name``, ``password-name``, ``api-hash-name`` and
``api-id-name`` options identify secrets in ``~/.password-store`` to use, this
provides an alternative somewhere in between the following two extremes:

- Always typing your secrets interactively (because you don't want them to be
  stored in the ``chat-archive`` configuration file, which is understandable
  from a security perspective of security).

- Storing your secrets directly in the ``chat-archive`` configuration files (so
  you don't have to type secrets interactively) thereby exposing them to all
  software running on your computer.

Because pass_ can use gpg-agent_ you only have to type a single master password
to unlock the secrets required to synchronize any number of chat accounts.

The local database
------------------

The `chat-archive` program uses an SQLite_ database to store the chat messages
that it collects. Because the whole point of the program is to safeguard the
long term archival of chat messages, SQLAlchemy_ and Alembic_ are used to
support database schema migrations. This is intended to ensure a reliable
upgrade path for future enhancements without data loss.

There's one significant exception I can think of: The current version of the
`chat-archive` program doesn't synchronize images and other multimedia files,
only text messages are stored in the local database. If support for images is
added in a later release (I'm not committing to this, but I am considering it)
and collecting these is important to you then you may have to rebuild your
database if and when this support is added.

You can change the location of the SQLite database and other datafiles by
setting the environment variable ``$CHAT_ARCHIVE_DIRECTORY``. Making a backup
of your chat archive is as simple as saving a copy of the database file
``~/.local/share/chat-archive/database.sqlite3`` to another storage medium.
Please keep in mind that this database has the potential to contain a lot of
sensitive data, so I strongly advise you to use disk encryption.

Supported chat services
-----------------------

The following backends are currently available:

==================  ===========================================================
Chat service        Description
==================  ===========================================================
`Google Talk`_      At one time this was the primary chat service of Google. It
                    was based on (or at least cooperated well with) XMPP. My
                    personal chat archive of Google Talk messages ends on
                    2013-12-12.
`Google Hangouts`_  The successor to Google Talk. Interestingly enough my
                    personal chat archive of Google Hangouts messages starts on
                    2013-10-30 (what's interesting to me is the overlap with
                    the date above).
Slack_              Love it or hate it, when all of your colleagues are using
                    it you can't really get around it. Actually now that I
                    write it down like that I can't help but think of WhatsApp_
                    (where the "peer pressure" comes from family instead of
                    colleagues).
Telegram_           A popular alternative to WhatsApp_ from Russia, without the
                    Facebook baggage 😇 (which is not to say that the company
                    behind Telegram can't be just as evil).
==================  ===========================================================

In the future more backends may be added:

- I've been contemplating scraping "WhatsApp_ Web" using something like
  Selenium. It would get ugly and nasty, the resulting backend would be fragile
  at best, but having those messages available might just be worth it...

- I'm considering writing a chat log parser for the HTML chat logs that Pidgin
  generated ten years ago (circa 2008) because I have megabytes of such chat
  logs stored in backups 🙂.

History
-------

The fragmented nature of digital communication, where messages come to you via
numerous channels (including multiple chat services), has bothered me for years
now. Finding things back can actually become a challenge 😇. Tangentially
related is the realization that these chat services come and go, taking with
them years of chat history, lost forever. I'm looking at you Google 😉.

Given that I am a programmer by trade and heart, It's been itching for several
years now to try and solve both of these problems at the same time by creating
a computer program that downloads and stores the chat message history of
multiple chat services into a single local database, available for searching
and trivially easy to back up.

For what it's worth I didn't start out with the goal of "full fidelity" chat
history backup including images and other multimedia, although I may eventually
decide to implement it anyway. What I initially set out to build was a local,
searchable database of textual chat messages collected from multiple chat
services, with an easy way to add support for new chat services.

Contact
-------

The latest version of `chat-archive` is available on PyPI_ and GitHub_. The
documentation is hosted on `Read the Docs`_ and includes a changelog_. For bug
reports please create an issue on GitHub_. If you have questions, suggestions,
etc. feel free to send me an e-mail at `peter@peterodding.com`_.

License
-------

This software is licensed under the `MIT license`_.

© 2020 Peter Odding.

Here's a quick overview of the licenses of the dependencies:

=============  =======================
Dependency     License
=============  =======================
Alembic_       MIT license
emoji_         BSD license
hangups_       MIT license
Slacker_       Apache Software License
SQLAlchemy_    MIT license
Telethon_      MIT license
=============  =======================

Shortly before publishing this project I got worried that I had included a GPL
dependency which (if I understand correctly) would require me to publish under
GPL as well, even though I've been consistently publishing my open source
projects under the MIT license since 2010.

After assembling the table above I can confidently say that this is not the
case 😇. The dependencies that are not listed in the table above are projects
of mine, all of them published under the same MIT license as the `chat-archive`
program (assuming I keep this up-to-date as new dependencies are added).

.. External references:
.. _Alembic: http://alembic.zzzcomputing.com/
.. _changelog: https://chat-archive.readthedocs.io/en/latest/changelog.html
.. _emoji: https://pypi.org/project/emoji/
.. _GitHub: https://github.com/xolox/python-chat-archive
.. _Google Hangouts: https://en.wikipedia.org/wiki/Google_Hangouts
.. _Google Talk: https://en.wikipedia.org/wiki/Google_Talk
.. _gpg-agent: https://manpages.debian.org/gpg-agent
.. _hangups: https://pypi.org/project/hangups/
.. _MIT license: http://en.wikipedia.org/wiki/MIT_License
.. _pass: https://en.wikipedia.org/wiki/Pass_(software)
.. _per user site-packages directory: https://www.python.org/dev/peps/pep-0370/
.. _peter@peterodding.com: peter@peterodding.com
.. _PyPI: https://pypi.python.org/pypi/chat-archive
.. _Python: https://www.python.org/
.. _Read the Docs: https://chat-archive.readthedocs.io/en/latest/
.. _Slack: https://en.wikipedia.org/wiki/Slack_(software)
.. _Slacker: https://pypi.org/project/slacker/
.. _SQLAlchemy: https://www.sqlalchemy.org/
.. _SQLite: https://sqlite.org/
.. _Telegram: https://en.wikipedia.org/wiki/Telegram_(service)
.. _Telethon: https://pypi.org/project/telethon/
.. _virtual environments: http://docs.python-guide.org/en/latest/dev/virtualenvs/
.. _WhatsApp: https://en.wikipedia.org/wiki/WhatsApp
