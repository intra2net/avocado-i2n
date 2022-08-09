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

import os
import re
import logging as log
logging = log.getLogger('avocado.test.' + __name__)

from aexpect.exceptions import ShellCmdError
from aexpect import remote
from aexpect import remote_door as door
from avocado.core.test_id import TestID
from avocado.core.nrunner.runnable import Runnable
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

    def long_prefix(self):
        """Sufficiently unique prefix to identify a diagram test node."""
        return self.prefix + "-" + self.params["vms"].replace(" ", "")
    long_prefix = property(fget=long_prefix)

    def id(self):
        """Unique ID to identify a test node."""
        return self.long_prefix + "-" + self.params["name"]
    id = property(fget=id)

    def id_test(self):
        """Unique test ID to identify a test node."""
        return TestID(self.long_prefix, self.params["name"])
    id_test = property(fget=id_test)

    def __init__(self, prefix, config, object):
        """
        Construct a test node (test) for any test objects (vms).

        :param str name: name of the test node
        :param config: variant configuration for the test node
        :type config: :py:class:`param.Reparsable`
        :param object: node-level object participating in the test node
        :type object: :py:class:`NetObject`
        """
        self.prefix = prefix
        self.config = config
        self._params_cache = None

        self.should_run = True
        self.should_clean = True
        self.should_scan = True

        self.spawner = None
        self.workers = set()

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
        shortname = self.params.get("shortname", "<unknown>")
        return f"[node] longprefix='{self.long_prefix}', shortname='{shortname}'"

    def get_runnable(self):
        """
        Get test factory from which the test loader will get a runnable test instance.

        :return: test class and constructor parameters
        :rtype: :py:class:`Runnable`
        """
        self.params['short_id'] = self.long_prefix
        self.params['id'] = self.id_test.str_uid + "_" + self.id_test.name

        uri = self.params["shortname"]
        vt_params = self.params.copy()

        # Flatten the vt_params, discarding the attributes that are not
        # scalars, and will not be used in the context of nrunner
        for key in ('_name_map_file', '_short_name_map_file', 'dep'):
            if key in self.params:
                del(vt_params[key])

        return Runnable('avocado-vt', uri, **vt_params)

    def set_environment(self, job, env_id=""):
        """
        Set the environment for executing the test node.

        :param job: job that includes the test suite
        :type job: :py:class:`avocado.core.job.Job`
        :param str env_id: name or ID to uniquely identify the environment, empty
                           for unisolated process spawners

        This isolating environment could be a container, a virtual machine, or
        a less-isolated process and is managed by a specialized spawner.
        """
        spawner_name = job.config.get('nrunner.spawner', 'lxc')
        # TODO: move cid in constructor in the upstream PR
        self.spawner = SpawnerDispatcher(job.config, job)[spawner_name].obj
        self.spawner.cid = env_id

        self.params["hostname"] = env_id if env_id else self.params["hostname"]

    def is_occupied(self):
        return self.spawner is not None

    def is_scan_node(self):
        """Check if the test node is the root of all test nodes for all test objects."""
        return self.prefix.endswith("0s1")

    def is_terminal_node(self):
        """Check if the test node is the root of all test nodes for some test object."""
        return self.prefix.endswith("t")

    def is_shared_root(self):
        """Check if the test node is the root of all test nodes for all test objects."""
        return self.params.get_boolean("shared_root", False)

    def is_object_root(self):
        """Check if the test node is the root of all test nodes for some test object."""
        return "object_root" in self.params

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

    def is_reachable_from(self, node):
        """The current node is setup or cleanup node for another node."""
        return self in node.setup_nodes or self in node.cleanup_nodes

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

    def produces_setup(self):
        """
        Check if the test node produces any reusable setup state.

        :returns: whether there are setup states to reuse from the test
        :rtype: bool
        """
        for test_object in self.objects:
            object_params = test_object.object_typed_params(self.params)
            object_state = object_params.get("set_state")
            if object_state:
                return True
        return False

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
                if re.search("(\.|^)" + state + "(\.|$)", test_node.params.get("name")):
                    return True
                setup_object_params = test_object.object_typed_params(test_node.params)
                if state == setup_object_params.get("set_state"):
                    return True
        return False

    @staticmethod
    def comes_before(node1, node2):
        def compare_part(prefix1, prefix2):
            match1, match2 = re.match(r"^(\d+)(\w)(.+)", prefix1), re.match(r"^(\d+)(\w)(.+)", prefix2)
            digit1, alpha1, else1 = (prefix1, None, None) if match1 is None else match1.group(1, 2, 3)
            digit2, alpha2, else2 = (prefix2, None, None) if match2 is None else match2.group(1, 2, 3)

            # compare order of parsing if simple leaf nodes
            if digit1.isdigit() and digit2.isdigit():
                digit1, digit2 = int(digit1), int(digit2)
                if digit1 != digit2:
                    return digit1 < digit2
            # we no longer match and are at the end ofthe prefix
            else:
                return digit1 < digit2

            # compare the node type flags next
            if alpha1 != alpha2:
                if alpha1 is None:
                    return False if alpha2 == "a" else True  # reverse order for "c" (cleanup), "b" (byproduct), "d" (duplicate)
                if alpha2 is None:
                    return True if alpha1 == "a" else False  # reverse order for "c" (cleanup), "b" (byproduct), "d" (duplicate)
                return alpha1 < alpha2
            # redo the comparison for the next prefix part
            else:
                return compare_part(else1, else2)
        return compare_part(node1.long_prefix, node2.long_prefix)

    def pick_next_parent(self):
        """
        Pick the next available parent based on some priority.

        :returns: the next parent node
        :rtype: TestNode object

        The current basic priority is test name.
        """
        nodes = [n for n in self.setup_nodes if self.is_reachable_from(n)]
        nodes = self.setup_nodes if len(nodes) == 0 else nodes
        next_node = nodes[0]
        for node in nodes[1:]:
            if node.is_occupied():
                continue
            if TestNode.comes_before(node, next_node):
                next_node = node
        return next_node

    def pick_next_child(self):
        """
        Pick the next available child based on some priority.

        :returns: the next child node
        :rtype: TestNode object

        The current order is defined by soft early fail then basic test name priority.
        """
        nodes = [n for n in self.cleanup_nodes if self.is_reachable_from(n)]
        nodes = self.cleanup_nodes if len(nodes) == 0 else nodes
        next_node = nodes[0]
        for node in nodes[1:]:
            if node.is_occupied():
                continue
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

    def scan_states(self):
        """Scan for present object states to reuse the test from previous runs."""
        self.should_run = True
        node_params = self.params.copy()

        is_leaf = True
        for test_object in self.objects:
            object_params = test_object.object_typed_params(self.params)
            object_state = object_params.get("set_state")

            # the test leaves an object undefined so it cannot be reused for this object
            if object_state is None or object_state == "":
                continue
            else:
                is_leaf = False

            # the object state has to be defined to reach this stage
            if object_state == "install" and test_object.is_permanent():
                self.should_run = False
                break

            # ultimate consideration of whether the state is actually present
            node_params[f"check_state_{test_object.key}_{test_object.suffix}"] = object_state
            node_params[f"check_mode_{test_object.key}_{test_object.suffix}"] = object_params.get("check_mode", "rf")
            # TODO: unfortunately we need env object with pre-processed vms in order
            # to provide ad-hoc root vm states so we use the current advantage that
            # all vm state backends can check for states without a vm boot (root)
            if test_object.key == "vms":
                node_params[f"use_env_{test_object.key}_{test_object.suffix}"] = "no"
            node_params[f"soft_boot_{test_object.key}_{test_object.suffix}"] = "no"

        if not is_leaf:
            log.getLogger("aexpect").parent = log.getLogger("avocado.extlib")
            node_host = self.params["hostname"]
            node_nets = self.params["nets_ip_prefix"]
            node_source_ip = f"{node_nets}.{node_host[1:]}" if node_host else ""
            session = remote.wait_for_login(self.params["nets_shell_client"],
                                            node_source_ip,
                                            self.params["nets_shell_port"],
                                            self.params["nets_username"], self.params["nets_password"],
                                            self.params["nets_shell_prompt"])

            control_path = os.path.join(self.params["suite_path"], "controls", "pre_state.control")
            mod_control_path = door.set_subcontrol_parameter_dict(control_path, "params", node_params)
            try:
                door.run_subcontrol(session, mod_control_path)
                self.should_run = False
            except ShellCmdError as error:
                if "AssertionError" in error.output:
                    self.should_run = True
                else:
                    raise RuntimeError("Could not complete state scan due to control file error")
        logging.info("The test node %s %s run", self, "should" if self.should_run else "should not")

    def validate(self):
        """Validate the test node for sane attribute-parameter correspondence."""
        param_nets = self.params.objects("nets")
        attr_nets = list(o.suffix for o in self.objects if o.key == "nets")
        if len(attr_nets) > 1 or len(param_nets) > 1:
            raise AssertionError(f"Test node {self} can have only one net ({attr_nets}/{param_nets}")
        param_net_name, attr_net_name = attr_nets[0], param_nets[0]
        if self.objects[0].suffix != attr_net_name:
            raise AssertionError(f"The net {attr_net_name} must be the first node object {self.objects[0]}")
        if param_net_name != attr_net_name:
            raise AssertionError(f"Parametric and attribute nets differ {param_net_name} != {attr_net_name}")

        param_vms = set(self.params.objects("vms"))
        attr_vms = set(o.suffix for o in self.objects if o.key == "vms")
        if len(param_vms - attr_vms) > 0:
            raise ValueError("Additional parametric objects %s not in %s" % (param_vms, attr_vms))
        if len(attr_vms - param_vms) > 0:
            raise ValueError("Missing parametric objects %s from %s" % (param_vms, attr_vms))

        # TODO: images can currently be ad-hoc during run and thus cannot be validated

        if self in self.setup_nodes or self in self.cleanup_nodes:
            raise ValueError("Detected reflexive dependency of %s to itself" % self)
