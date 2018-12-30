#!/usr/bin/env python

# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: December 31, 2018
# URL: https://github.com/xolox/python-chat-archive

"""Setup script for the `chat-archive` package."""

# Standard library modules.
import codecs
import os
import re

# De-facto standard solution for Python packaging.
from setuptools import setup, find_packages


def get_readme():
    """Get the contents of the ``README.rst`` file as a Unicode string."""
    with codecs.open(get_absolute_path("README.rst"), "r", "utf-8") as handle:
        return handle.read()


def get_version(*args):
    """Get the package's version (by extracting it from the source code)."""
    module_path = get_absolute_path(*args)
    with open(module_path) as handle:
        for line in handle:
            match = re.match(r'^__version__\s*=\s*["\']([^"\']+)["\']$', line)
            if match:
                return match.group(1)
    raise Exception("Failed to extract version from %s!" % module_path)


def get_requirements(*args):
    """Get requirements from pip requirement files."""
    requirements = set()
    with open(get_absolute_path(*args)) as handle:
        for line in handle:
            # Strip comments.
            line = re.sub(r"^#.*|\s#.*", "", line)
            # Ignore empty lines
            if line and not line.isspace():
                requirements.add(re.sub(r"\s+", "", line))
    return sorted(requirements)


def get_absolute_path(*args):
    """Transform relative pathnames into absolute pathnames."""
    directory = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(directory, *args)


setup(
    name="chat-archive",
    version=get_version("chat_archive", "__init__.py"),
    description="Easy to use offline chat archive",
    long_description=get_readme(),
    url="https://github.com/xolox/python-chat-archive",
    author="Peter Odding",
    author_email="peter@peterodding.com",
    license="MIT",
    packages=find_packages(),
    include_package_data=True,
    entry_points={
        "chat_archive.backends": [
            "gtalk = chat_archive.backends.gtalk",
            "hangouts = chat_archive.backends.hangouts",
            "slack = chat_archive.backends.slack",
            "telegram = chat_archive.backends.telegram",
        ],
        "console_scripts": ["chat-archive = chat_archive.cli:main"],
    },
    install_requires=get_requirements("requirements.txt"),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Information Technology",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Topic :: Software Development",
        "Topic :: Software Development :: Libraries",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Text Processing",
        "Topic :: Text Processing :: Indexing",
    ],
)
