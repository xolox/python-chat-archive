# Easy to use offline chat archive.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: July 22, 2018
# URL: https://github.com/xolox/python-chat-archive

"""
Namespace for chat archive backends.

The following chat archive backends have been implemented so far:

- Google Hangouts: :mod:`chat_archive.backends.hangouts`
- Google Talk: :mod:`chat_archive.backends.gtalk`
- Slack: :mod:`chat_archive.backends.slack`
- Telegram: :mod:`chat_archive.backends.telegram`
"""

# External dependencies.
from property_manager import PropertyManager, lazy_property, required_property
from verboselogs import VerboseLogger

# Modules included in our package.
from chat_archive.html.redirects import RedirectStripper, strip_redirects
from chat_archive.models import Account, Contact, Conversation, EmailAddress, Message, TelephoneNumber

# Initialize a logger for this module.
logger = VerboseLogger(__name__)


class ChatArchiveBackend(PropertyManager):

    """Abstract base class for ``chat-archive`` backends."""

    @lazy_property
    def account(self):
        """The :class:`.Account` object corresponding to :attr:`account_name` and :attr:`backend_name`."""
        obj = (
            self.session.query(Account)
            .filter(Account.backend == self.backend_name)
            .filter(Account.name == self.account_name)
            .one_or_none()
        )
        if not obj:
            obj = Account(backend=self.backend_name, name=self.account_name)
            self.session.add(obj)
            self.session.flush()
        return obj

    @required_property
    def account_name(self):
        """
        The name of the chat account that is being synchronized (a string).

        The value of :attr:`account_name` needs to be set by the caller and is
        used to "get or create" the :attr:`account` object on demand.
        """

    @required_property
    def archive(self):
        """The :class:`~chat_archive.ChatArchive` that is using this backend."""

    @required_property
    def backend_name(self):
        """
        The name of the chat archive backend (a short alphanumeric string).

        The value of :attr:`backend_name` is used to "get or create" the
        :attr:`account` object on demand.
        """

    @lazy_property
    def config(self):
        """The configuration options for this backend and account (a dictionary)."""
        section_name = "%s:%s" % (self.backend_name, self.account_name)
        if section_name in self.archive.config_loader.section_names:
            return self.archive.config_loader.get_options(section_name)
        return {}

    @lazy_property
    def external_id_cache(self):
        """A dictionary mapping external IDs to :class:`.Contact` objects."""
        return {}

    @lazy_property
    def redirect_stripper(self):
        """An :class:`.RedirectStripper` object."""
        return RedirectStripper()

    @lazy_property
    def session(self):
        """Shortcut for the :attr:`~chat_archive.database.DatabaseClient.session` property of :attr:`archive`."""
        return self.archive.session

    @required_property
    def stats(self):
        """A :class:`~chat_archive.BackendStats` object."""

    def find_contact_by_attributes(self, attributes):
        """
        Find a contact based on their external ID, an email address or a telephone number.

        :param attributes: A dictionary with any of the following keys:

                           - ``external_id`` (string value)
                           - ``email_addresses`` (list of strings)
                           - ``telephone_numbers`` (list of strings)
        :returns: A :class:`.Contact` object or :data:`None`.
        """
        for name, method, multiple_values_expected in (
            ("external_id", self.find_contact_by_external_id, False),
            ("email_addresses", self.find_contact_by_email_address, True),
            ("telephone_numbers", self.find_contact_by_telephone_number, True),
        ):
            value = attributes.get(name)
            if value:
                if multiple_values_expected:
                    # Lookup by one of the given values.
                    for subkey in value:
                        contact = method(subkey)
                        if contact:
                            return contact
                else:
                    # Lookup by the given value.
                    contact = method(value)
                    if contact:
                        return contact

    def find_contact_by_email_address(self, value):
        """
        Find a contact based on their email address.

        :param value: An email address (a string).
        :returns: A :class:`.Contact` object or :data:`None`.
        """
        logger.verbose("Searching for contact by email address (%s) ..", value)
        return (
            self.session.query(Contact)
            .join(Contact.email_addresses)
            .filter(Contact.account == self.account)
            .filter(EmailAddress.value == value)
            .one_or_none()
        )

    def find_contact_by_external_id(self, external_id):
        """
        Find a contact based on their 'external ID'.

        :param external_id: The external ID (a string).
        :returns: A :class:`.Contact` object or :data:`None`.

        This method uses :attr:`external_id_cache` to speed up lookup of
        contacts by their external ID.
        """
        logger.verbose("Searching for contact by external ID (%s) ..", external_id)
        value = self.external_id_cache.get(external_id)
        if value is None:
            logger.verbose("Querying database for contact by external ID ..")
            value = (
                self.session.query(Contact)
                .filter(Contact.account == self.account)
                .filter(Contact.external_id == external_id)
                .one_or_none()
            )
            self.external_id_cache[external_id] = value
        return value

    def find_contact_by_telephone_number(self, value):
        """
        Find a contact based on their telephone number.

        :param value: A telephone number (a string).
        :returns: A :class:`.Contact` object or :data:`None`.
        """
        logger.verbose("Searching for contact by telephone number (%s) ..", value)
        return (
            self.session.query(Contact)
            .join(Contact.telephone_numbers)
            .filter(Contact.account == self.account)
            .filter(EmailAddress.value == value)
            .one_or_none()
        )

    def get_or_create_contact(self, **attributes):
        """
        Get or create a contact object.

        :param attributes: The names and values of model attributes, used
                           to find existing contacts and create new ones.
        :returns: A :class:`.Contact` object.

        This method serves three distinct purposes:

        1. Finding existing contacts by their 'external ID' or one of their
           email addresses or telephone numbers.
        2. Creating new contacts (based on the given `attributes`).
        3. Updating existing contacts (based on the given `attributes`).

        Here's an overview of supported `attributes`:

        - The ``external_id`` attribute (whose value is expected to be string).
        - The ``full_name`` attribute (whose value is expected to be string) is
          split into separate ``first_name`` and ``last_name`` attributes.
        - The attributes ``email_address`` and ``telephone_number`` (whose
          value is expected to be string) are converted to their plural forms
          ``email_addresses`` and ``telephone_numbers`` (a list of strings).
        """
        contact = None
        changes_made = False
        # Translate 'email_address' to 'email_addresses' and 'telephone_number'
        # to 'telephone_numbers' as a convenience to callers that don't have
        # multiple email addresses or telephone numbers per contact (they can
        # just use the singular form and ignore the plural form).
        for singular, plural in (("email_address", "email_addresses"), ("telephone_number", "telephone_numbers")):
            if singular in attributes:
                singular_value = attributes.pop(singular)
                collection = attributes.setdefault(plural, [])
                if singular_value:
                    collection.append(singular_value)
        # Try to find an existing contact based on their 'external ID'
        # or one of their email addresses or telephone numbers.
        with self.session.no_autoflush:
            contact = self.find_contact_by_attributes(attributes)
        # Prepare to create a new account or update an existing account. First
        # we split the 'full_name' attribute (if given) into separate
        # 'first_name' and 'last_name' attributes.
        if "full_name" in attributes:
            words = attributes.pop("full_name").split()
            if words:
                attributes["first_name"] = words.pop(0)
                if words:
                    attributes["last_name"] = " ".join(words)
        # Remove email addresses and telephone numbers from the attributes
        # because they're stored in our local database as relationships instead
        # of columns.
        email_addresses = attributes.pop("email_addresses", [])
        telephone_numbers = attributes.pop("telephone_numbers", [])
        if contact:
            # Update the attributes of an existing contact.
            logger.verbose("Updating existing contact ..")
            for attribute_name, value in attributes.items():
                value_in_db = getattr(contact, attribute_name)
                if value and not value_in_db:
                    setattr(contact, attribute_name, value)
                    changes_made = True
        else:
            # Create a new contact with the given attributes.
            logger.verbose("Creating new contact ..")
            attributes.setdefault("account", self.account)
            contact = Contact(**attributes)
            self.session.add(contact)
            self.session.flush()
            logger.info("Importing %s", contact)
            self.stats.contacts_added += 1
        # Associate the given email addresses with the contact.
        for value in email_addresses:
            object = self.get_or_create_email_address(value)
            if object not in contact.email_addresses:
                contact.email_addresses.append(object)
                self.session.flush()
                changes_made = True
        # Associate the given telephone numbers with the contact.
        for value in telephone_numbers:
            object = self.get_or_create_telephone_number(value)
            if object not in contact.telephone_numbers:
                contact.telephone_numbers.append(object)
                self.session.flush()
                changes_made = True
        if changes_made:
            logger.verbose("Actually made changes to contact ..")
            self.stats.contacts_changed += 1
        else:
            logger.verbose("No actual changes to contact made ..")
        return contact

    def get_or_create_conversation(self, external_id, **attributes):
        """
        Get or create a :class:`.Conversation` object.

        :param external_id: The external ID of the conversation (a string).
        :param attributes: Any optional attributes to set when creating a new conversation.
        :returns: Refer to :func:`get_or_create_object()`.
        """
        created, object = self.get_or_create_object(
            model=Conversation, required=dict(account=self.account, external_id=str(external_id)), optional=attributes
        )
        if created:
            logger.info("Importing %s ..", object)
            self.stats.conversations_added += 1
        return object

    def get_or_create_message(self, conversation, **attributes):
        """
        Get or create a :class:`.Message` object.

        :param conversation: The :class:`.Conversation` in which the message originated.
        :param attributes: Any optional attributes to set when creating a new message.
        :returns: Refer to :func:`get_or_create_object()`.
        """
        self.pre_process_text(attributes)
        # Define the lookup criteria.
        required = dict(conversation=conversation)
        if attributes.get("external_id"):
            # Look up existing messages by their external ID when available.
            required["external_id"] = attributes.pop("external_id")
        else:
            # Fall back to a lookup by sender and timestamp.
            required["sender"] = attributes.pop("sender")
            required["timestamp"] = attributes.pop("timestamp")
        created, object = self.get_or_create_object(model=Message, required=required, optional=attributes)
        if created:
            logger.info(
                "Importing message by %s on %s: %s", object.sender, object.timestamp.strftime("%Y-%m-%d"), object.text
            )
            self.stats.messages_added += 1
        return created, object

    def get_or_create_email_address(self, email_address):
        """
        Get or create an :class:`.EmailAddress` object.

        :param email_address: The email address (a string).
        :returns: An :class:`.EmailAddress` object.
        """
        created, object = self.get_or_create_object(model=EmailAddress, required=dict(value=email_address))
        if created:
            logger.info("Importing %s", object)
            self.stats.email_addresses_added += 1
        return object

    def get_or_create_object(self, model, required, optional=None):
        """
        Find an existing object in the local database or create a new object.

        :param model: The model to query.
        :param required: A dictionary with the key/value pairs that should be
                         used to search for an existing object.
        :param optional: Any optional attributes to set when creating a new
                         object.
        :returns: A tuple with two values:

                  1. :data:`True` if the object was created, :data:`False` if it already existed.
                  2. The object (an instance of `model`).
        """
        new = False
        query = self.session.query(model)
        for name, value in required.items():
            query = query.filter(getattr(model, name) == value)
        with self.session.no_autoflush:
            obj = query.one_or_none()
        if not obj:
            kw = {}
            if optional:
                kw.update(optional)
            kw.update(required)
            obj = model(**kw)
            self.session.add(obj)
            self.session.flush()
            new = True
        return new, obj

    def get_or_create_telephone_number(self, telephone_number):
        """
        Get or create a :class:`.TelephoneNumber` object.

        :param telephone_number: The telephone number (a string containing a number).
        :returns: A :class:`.TelephoneNumber` object.
        """
        created, object = self.get_or_create_object(model=TelephoneNumber, required=dict(value=telephone_number))
        if created:
            logger.info("Importing %s", object)
            self.stats.telephone_numbers_added += 1
        return object

    def have_message(self, conversation, external_id):
        """
        Check if a message exists in the local database.

        :param conversation: The :class:`.Conversation` that contains the message.
        :param external_id: The unique id of the message (a string).
        :returns: :data:`True` when the message exists, :data:`False` if it doesn't.
        """
        logger.verbose(
            "Checking if we know the message with conversation_id=%s and external_id=%s ..",
            conversation.id,
            external_id,
        )
        return bool(
            self.session.query(
                self.session.query(Message)
                .filter(Message.conversation == conversation)
                .filter(Message.external_id == external_id)
                .exists()
            ).scalar()
        )

    def pre_process_text(self, attributes):
        """
        Pre-process the text and HTML of a chat message.

        :param attributes: A dictionary with :class:`.Message` attributes.

        This method works as follows:

        1. The `text` is pre-processed using :func:`.strip_redirects()`.
        2. The `html` is pre-processed using :class:`.RedirectStripper`.
        3. When the resulting HTML exactly equals the plain text chat message,
           the `html` key in `attributes` is removed.
        """
        # Pre-process the plain text chat message.
        original_text = attributes["text"]
        modified_text = strip_redirects(original_text)
        if modified_text != original_text:
            attributes["text"] = modified_text
        # Pre-process the HTML chat message?
        original_html = attributes.get("html")
        if original_html:
            modified_html = self.redirect_stripper(original_html)
            if modified_html != modified_text:
                attributes["html"] = modified_html
            else:
                attributes.pop("html")

    def synchronize(self):
        """This instance method must be implemented by subclasses."""
        raise NotImplementedError
