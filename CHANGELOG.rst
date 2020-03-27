Changelog
=========

The purpose of this document is to list all of the notable changes to this
project. The format was inspired by `Keep a Changelog`_. This project adheres
to `semantic versioning`_.

.. contents::
   :local:

.. _Keep a Changelog: http://keepachangelog.com/
.. _semantic versioning: http://semver.org/

`Release 4.0.3`_ (2020-03-27)
-----------------------------

Bug fix for the following :exc:`~exceptions.TypeError` exception raised by the Telegram backend:

.. code-block:: python

   Traceback (most recent call last):
     File "../lib/python3.5/site-packages/chat_archive/cli.py", line 199, in main
       command_fn(arguments)
     File "../lib/python3.5/site-packages/chat_archive/cli.py", line 286, in sync_cmd
       self.synchronize(*arguments)
     File "../lib/python3.5/site-packages/chat_archive/__init__.py", line 335, in synchronize
       self.initialize_backend(backend_name, account_name).synchronize()
     File "../lib/python3.5/site-packages/chat_archive/backends/telegram.py", line 97, in synchronize
       event_loop.run_until_complete(self.connect_then_sync())
     File "/usr/lib/python3.5/asyncio/base_events.py", line 467, in run_until_complete
       return future.result()
     File "/usr/lib/python3.5/asyncio/futures.py", line 294, in result
       raise self._exception
     File "/usr/lib/python3.5/asyncio/tasks.py", line 240, in _step
       result = coro.send(None)
     File "../lib/python3.5/site-packages/chat_archive/backends/telegram.py", line 124, in connect_then_sync
       elif dialog.date > conversation_in_db.last_modified:
   TypeError: can't compare offset-naive and offset-aware datetimes

.. _Release 4.0.3: https://github.com/xolox/python-chat-archive/compare/4.0.2...4.0.3

`Release 4.0.2`_ (2018-12-31)
-----------------------------

- Merged pull request `#1`_: Automatically create archive directory when it
  doesn't exist yet.

- Bumped hangups_ from 0.4.4 to 0.4.6 to improve Google Hangouts authentication
  compatibility.

.. note:: Hangups_ release 0.4.6 (the latest available) doesn't actually work
          for me, although I managed to get it to connect successfully after
          hacking in captcha support, which I've since submitted as pull
          request `#446`_ 🙂.

.. _Release 4.0.2: https://github.com/xolox/python-chat-archive/compare/4.0.1...4.0.2
.. _#1: https://github.com/xolox/python-chat-archive/pull/1
.. _hangups: https://pypi.org/project/hangups/
.. _#446: https://github.com/tdryer/hangups/pull/446

`Release 4.0.1`_ (2018-08-02)
-----------------------------

Just before publishing this project yesterday I propagated a rename throughout
the code base, rephrasing "password" as "secret" (my rationale being that
"naming things is important" 😇). Unfortunately that rename was propagated a
bit more thoroughly than I had intended, impacting the interaction with the
Hangups API. This should be fixed in release 4.0.1. For posterity, this relates
to the following exception::

  AttributeError: 'GoogleAccountCredentials' object has no attribute 'get_password'

.. _Release 4.0.1: https://github.com/xolox/python-chat-archive/compare/4.0...4.0.1

`Release 4.0`_ (2018-08-01)
---------------------------

The initial public release! 🎉

Because I love giving mixed signals I've decided to use the version number 4.0
for this release (because four chat service backends are supported) but I've
added the "beta" trove classifier to the ``setup.py`` script and I've added a
big fat disclaimer to the readme (see the status section) 😛.

While publishing the project I decided to be pragmatic and strip the version
control history, because in the first weeks of development I hard coded quite a
few secrets in the code base. Since then I've added support for configuration
files and even ``~/.password-store`` but of course those secrets remain in the
history...

Now I could have spent hours pouring through tens of thousands of lines of
patch output to remove those secrets without trashing the history. Instead I
decided to do something more useful with my time, hence "pragmatic" above 😇.

PS. This is that *"awesome new project"* that I've been `referring to`_ in the
humanfriendly changelog. Over the course of developing `chat-archive` I've
moved more than `six hundred lines`_ of code to the humanfriendly package due
to its general purpose nature (the HTML to ANSI conversion).

.. _Release 4.0: https://github.com/xolox/python-chat-archive/tree/4.0
.. _referring to: http://humanfriendly.readthedocs.io/en/latest/changelog.html#release-4-13-2018-07-09
.. _six hundred lines: https://github.com/xolox/python-humanfriendly/compare/4.12.1...4.16.1
