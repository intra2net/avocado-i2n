# Copyright 2013-2020 Intranet AG and contributors
#
# avocado-i2n is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# avocado-i2n is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with avocado-i2n.  If not, see <http://www.gnu.org/licenses/>.

"""

SUMMARY
------------------------------------------------------
Utility for the main test suite substructures like test nodes.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import re

from avocado.core import test
from avocado_vt.test import VirtTest


class TestNode(object):
    """
    A wrapper for all test relevant parts like parameters, parser, used
    objects and dependencies to/from other test nodes (setup/cleanup).
    """

    def params(self):
        """Parameters (cache) property."""
        if self._params_cache is None:
            self.regenerate_params()
        return self._params_cache
    params = property(fget=params)

    def id(self):
        return self.name + "-" + self.params["vms"].replace(" ", "")
    id = property(fget=id)

    def count(self):
        """Node count property."""
        return self.name
    count = property(fget=count)

    def __init__(self, name, config, objects):
        """
        Construct a test node (test) for any test objects (vms).

        :param str name: name of the test node
        :param config: variant configuration for the test node
        :type config: :py:class:`param.Reparsable`
        :param objects: objects participating in the test node
        :type objects: [:py:class:`TestObject`]
        """
        self.name = name
        self.config = config
        self._params_cache = None

        self.should_run = True
        self.should_clean = True

        self.node_str = None

        # list of objects involved in the test
        self.objects = objects

        # lists of parent and children test nodes
        self.setup_nodes = []
        self.cleanup_nodes = []
        self.visited_setup_nodes = []
        self.visited_cleanup_nodes = []

    def __repr__(self):
        return self.params["shortname"]

    def get_test_factory(self, job=None):
        """
        Get test factory from which the test loader will get a runnable test instance.

        :param job: avocado job object to for running or None for reporting only
        :type job: :py:class:`avocado.core.job.Job`
        :return: test class and constructor parameters
        :rtype: (type, {str, obj})
        """
        test_constructor_params = {'name': test.TestID(self.id, self.params["shortname"]),
                                   'vt_params': self.params}
        if job is not None:
            test_constructor_params['job'] = job
            test_constructor_params['base_logdir'] = job.logdir
        return (VirtTest, test_constructor_params)

    def is_scan_node(self):
        """Check if the test node is the root of all test nodes for all test objects."""
        return self.name.endswith("0s")

    def is_create_node(self):
        """Check if the test node is the root of all test nodes for some test object."""
        return self.name.endswith("0r") and len(self.objects) == 1

    def is_install_node(self):
        """Check if the test node is the root of all test nodes for some test object."""
        return self.name.endswith("0p") and len(self.objects) == 1

    def is_shared_root(self):
        """Check if the test node is the root of all test nodes for all test objects."""
        return self.is_scan_node()

    def is_object_root(self):
        """Check if the test node is the root of all test nodes for some test object."""
        return self.is_create_node()

    def is_objectless(self):
        """Check if the test node is not defined with any test object."""
        return len(self.objects) == 0 or self.params["vms"] == ""

    def is_ephemeral(self):
        """
        If the test node is ephemeral its `set_state` cannot be preserved for
        longer than one cycle, i.e. if the next test stops reverting to it.

        Such test nodes are transitions from off to on states and
        must be repeated to reuse the on states that are their end states.
        """
        for test_object in self.objects:
            object_name = test_object.name
            object_params = self.params.object_params(object_name)
            object_state = object_params.get("set_state")

            # count only test objects left with saved states
            if object_state is None or object_state == "":
                continue

            # any off-on state transition marks the test as ephemeral
            if (object_params.get("get_type", "on") == "off" and
                    object_params.get("set_type", "on") == "on"):
                return True

        return False

    def is_setup_ready(self):
        """
        All dependencies of the test were run or there were none, so it can
        be run as well.
        """
        return len(self.setup_nodes) == 0

    def is_cleanup_ready(self):
        """
        All dependent tests were run or there were none, so the end states
        from the test can be removed.
        """
        return len(self.cleanup_nodes) == 0

    def is_finished(self):
        """
        The test and all its dependent tests were run and the test will not
        be run anymore.
        """
        return self.is_cleanup_ready() and not self.should_run

    def has_dependency(self, state, test_object):
        """
        Check if the test node has a dependency parsed and available.

        :param str state: name of the dependency (state or parent test set)
        :param test_object: object used for the dependency
        :type test_object: :py:class:`TestObject`
        :returns: whether the dependency was already found among the setup nodes
        :rtype: bool
        """
        for test_node in self.setup_nodes:
            if test_object in test_node.objects:
                setup_object_params = test_node.params.object_params(test_object.name)
                if re.search("(\.|^)" + state + "(\.|$)", setup_object_params.get("name")):
                    return True
                if state == setup_object_params.get("set_state"):
                    return True
        return False

    @staticmethod
    def comes_before(node1, node2):
        def compare_part(c1, c2):
            match1, match2 = re.match(r"^(\d+)(\w+)(.+)", c1), re.match(r"^(\d+)(\w+)(.+)", c2)
            if match1 is None and match2 is None:
                pass
            d1, b1, a1 = c1, None, None if match1 is None else match1.group(1, 2, 3)
            d2, b2, a2 = c2, None, None if match2 is None else match2.group(1, 2, 3)
            if not c1.isdigit() or not c2.isdigit():
                return str(c1) < str(c2)
            d1, d2 = int(d1), int(d2)
            if d1 != d2:
                return d1 < d2
            elif a1 != a2:
                if a1 is None:
                    return False if a2 == "a" else True  # reverse order for "c" and cleanup
                if a2 is None:
                    return True if a1 == "a" else False  # reverse order for "c" and cleanup
                return a1 < a2
            else:
                return compare_part(b1, b2)
        return compare_part(node1.count, node2.count)

    def pick_next_parent(self):
        """
        Pick the next available parent based on some priority.

        :returns: the next parent node
        :rtype: TestNode object

        The current basic priority is test name.
        """
        next_node = self.setup_nodes[0]
        for node in self.setup_nodes[1:]:
            if TestNode.comes_before(node, next_node):
                next_node = node
        return next_node

    def pick_next_child(self):
        """
        Pick the next available child based on some priority.

        :returns: the next child node
        :rtype: TestNode object

        The current basic priority is test name.

        .. todo:: more advanced scheduling can be based on different types of priority:

            1. priority to tests with objects at current states -> then at further states
               -> then at previous states;
            2. priority to tests that are leaves -> then internal;
            3. priority to tests using fewer objects -> then more objects;
        """
        next_node = self.cleanup_nodes[0]
        for node in self.cleanup_nodes[1:]:
            if TestNode.comes_before(node, next_node):
                next_node = node
        return next_node

    def visit_node(self, test_node):
        """
        Move a parent or child node to the set of visited nodes for this test.

        :param test_node: visited node
        :type test_node: TestNode object
        :raises: :py:class:`ValueError` if visited node is not directly dependent
        """
        if test_node in self.setup_nodes:
            self.setup_nodes.remove(test_node)
            self.visited_setup_nodes.append(test_node)
        elif test_node in self.cleanup_nodes:
            self.cleanup_nodes.remove(test_node)
            self.visited_cleanup_nodes.append(test_node)
        else:
            raise ValueError("Invalid test node - %s and %s are not directly dependent "
                             "in any way" % (test_node.params["shortname"], self.params["shortname"]))

    def regenerate_params(self, verbose=False):
        """
        Regenerate all parameters from the current reparsable config.

        :param bool verbose: whether to show generated parameter dictionaries
        """
        self._params_cache = self.config.get_params(show_dictionaries=verbose)
