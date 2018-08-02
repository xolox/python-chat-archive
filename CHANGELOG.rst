Changelog
=========

The purpose of this document is to list all of the notable changes to this
project. The format was inspired by `Keep a Changelog`_. This project adheres
to `semantic versioning`_.

.. contents::
   :local:

.. _Keep a Changelog: http://keepachangelog.com/
.. _semantic versioning: http://semver.org/

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
