"""

SUMMARY
------------------------------------------------------
Utility for the main test suite substructures like test objects.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import logging

from .. import params_parser as param


class TestObject(object):
    """A wrapper for a test object used in one or more test nodes."""

    def params(self):
        """Parameters (cache) property."""
        if self._params_cache is None:
            self.regenerate_params()
        return self._params_cache
    params = property(fget=params)

    def id(self):
        return self.name
    id = property(fget=id)

    def __init__(self, name, config):
        """
        Construct a test object (vm) for any test nodes (tests).

        :param str name: name of the test object
        :param config: variant configuration for the test object
        :type config: :py:class:`param.Reparsable`
        """
        self.name = name
        self.config = config
        self._params_cache = None

        self.current_state = "unknown"

        # TODO: integrate these features better
        self.object_str = None

    def is_permanent(self):
        """
        If the test object is permanent, it can only be created manually
        (possibly through the use of manual setup steps).

        Online states on permanent test object are treated differently than
        online states on normal test object since they are preserved through
        test runs and even host shutdowns.
        """
        return self.params.get("permanent_vm", "no") == "yes"

    def regenerate_params(self, verbose=False):
        """
        Regenerate all parameters from the current reparsable config.

        :param bool verbose: whether to show generated parameter dictionaries
        """
        self._params_cache = self.config.get_params(show_dictionaries=verbose)
