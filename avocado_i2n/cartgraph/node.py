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

from avocado.core.test_id import TestID
from avocado.core.nrunner import Runnable
from avocado.core.dispatcher import SpawnerDispatcher


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

    def final_restr(self):
        """Final restriction to make the object parsing variant unique."""
        return self.config.steps[-2].parsable_form()
    final_restr = property(fget=final_restr)

    def id(self):
        """Sufficiently unique ID to identify a test node."""
        return self.name + "-" + self.params["vms"].replace(" ", "")
    id = property(fget=id)

    def id_long(self):
        """Long and still unique ID to use for state machine tasks."""
        return TestID(self.id, self.params["name"])
    id_long = property(fget=id_long)

    def count(self):
        """Node count property."""
        return self.name
    count = property(fget=count)

    def __init__(self, name, config, object):
        """
        Construct a test node (test) for any test objects (vms).

        :param str name: name of the test node
        :param config: variant configuration for the test node
        :type config: :py:class:`param.Reparsable`
        :param object: node-level object participating in the test node
        :type object: :py:class:`NetObject`
        """
        self.name = name
        self.config = config
        self._params_cache = None

        self.should_run = True
        self.should_clean = True

        self.spawner = None

        # flattened list of objects (in composition) involved in the test
        self.objects = [object]
        # TODO: only three nesting levels from a test net are supported
        if object.key != "nets":
            raise AssertionError("Test node could be initialized only from test objects "
                                 "of the same composition level, currently only test nets")
        for test_object in object.components:
            self.objects += [test_object]
            self.objects += test_object.components

        # lists of parent and children test nodes
        self.setup_nodes = []
        self.cleanup_nodes = []
        self.visited_setup_nodes = []
        self.visited_cleanup_nodes = []

    def __repr__(self):
        obj_tuple = (self.id, self.params.get("shortname", "<unknown>"))
        return "[node] id='%s', name='%s'" % obj_tuple

    def get_runnable(self):
        """
        Get test factory from which the test loader will get a runnable test instance.

        :return: test class and constructor parameters
        :rtype: :py:class:`Runnable`
        """
        self.params['short_id'] = self.id
        self.params['id'] = self.id_long.str_uid + "_" + self.id_long.name

        uri = self.params["shortname"]
        vt_params = self.params.copy()

        # Flatten the vt_params, discarding the attributes that are not
        # scalars, and will not be used in the context of nrunner
        for key in ('_name_map_file', '_short_name_map_file', 'dep'):
            if key in self.params:
                del(vt_params[key])

        return Runnable('avocado-vt', uri, **vt_params)

    def set_environment(self, job, env_id):
        """
        Set the environment for executing the test node.

        :param job: job that includes the test suite
        :type job: :py:class:`avocado.core.job.Job`
        :param str env_id: name or ID to uniquely identiy the environment

        This isolating environment could be a container, a virtual machine, or
        a less-isolated process and is managed by a specialized spawner.
        """
        spawner_name = job.config.get('nrunner.spawner', 'lxc')
        # TODO: move cid in constructor in the upstream PR
        self.spawner = SpawnerDispatcher(job.config)[spawner_name].obj
        self.spawner.cid = env_id

        hostname = self.params["hostname"]
        # prepend affected test parameters
        for key, value in self.params.items():
            if isinstance(value, str):
                self.params[key] = value.replace(hostname, hostname + env_id)
        self.params["hostname"] = env_id if env_id else hostname

    def is_scan_node(self):
        """Check if the test node is the root of all test nodes for all test objects."""
        return self.name.endswith("0s")

    def is_terminal_node(self):
        """Check if the test node is the root of all test nodes for some test object."""
        return self.name.endswith("0t")

    def is_shared_root(self):
        """Check if the test node is the root of all test nodes for all test objects."""
        return self.is_scan_node()

    def is_object_root(self):
        """Check if the test node is the root of all test nodes for some test object."""
        return self.is_terminal_node()

    def is_objectless(self):
        """Check if the test node is not defined with any test object."""
        return len(self.objects) == 0 or self.params["vms"] == ""

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

    def is_terminal_node_for(self):
        """
        Determine any object that this node is a root of.

        :returns: object that this node is a root of if any
        :rtype: :py:class:`TestObject` or None
        """
        object_root = self.params.get("object_root")
        if not object_root:
            return object_root
        for test_object in self.objects:
            if test_object.id == object_root:
                return test_object

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

    def validate(self):
        """Validate the test node for sane attribute-parameter correspondence."""
        param_nets = self.params.objects("nets")
        attr_nets = list(o.name for o in self.objects if o.key == "nets")
        if len(attr_nets) > 1 or len(param_nets) > 1:
            raise AssertionError(f"Test node {self} can have only one net ({attr_nets}/{param_nets}")
        param_net_name, attr_net_name = attr_nets[0], param_nets[0]
        if self.objects[0].name != attr_net_name:
            raise AssertionError(f"The net {attr_net_name} must be the first node object {self.objects[0]}")
        if param_net_name != attr_net_name:
            raise AssertionError(f"Parametric and attribute nets differ {param_net_name} != {attr_net_name}")

        param_vms = set(self.params.objects("vms"))
        attr_vms = set(o.name for o in self.objects if o.key == "vms")
        if len(param_vms - attr_vms) > 0:
            raise ValueError("Additional parametric objects %s not in %s" % (param_vms, attr_vms))
        if len(attr_vms - param_vms) > 0:
            raise ValueError("Missing parametric objects %s from %s" % (param_vms, attr_vms))

        # TODO: images can currently be ad-hoc during run and thus cannot be validated

        if self in self.setup_nodes or self in self.cleanup_nodes:
            raise ValueError("Detected reflexive dependency of %s to itself" % self)
