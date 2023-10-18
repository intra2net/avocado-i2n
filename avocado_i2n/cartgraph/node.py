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
from functools import cmp_to_key
import logging as log
logging = log.getLogger('avocado.job.' + __name__)

from aexpect.exceptions import ShellCmdError, ShellTimeoutError
from aexpect import remote
from aexpect import remote_door as door
from avocado.core.test_id import TestID
from avocado.core.nrunner.runnable import Runnable

from . import TestWorker, NetObject


door.DUMP_CONTROL_DIR = "/tmp"


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
        # TODO: cannot reuse long prefix since container is set at runtime
        #return TestID(self.long_prefix, self.params["name"])
        net_id = self.params.get("nets_gateway", "")
        net_id += "." if net_id else ""
        net_id += self.params.get("nets_host", "")
        net_id += self.params["vms"].replace(" ", "")
        full_prefix = self.prefix + "-" + net_id
        return TestID(full_prefix, self.params["name"])
    id_test = property(fget=id_test)

    _session_cache = {}

    def __init__(self, prefix, config):
        """
        Construct a test node (test) for any test objects (vms).

        :param str name: name of the test node
        :param config: variant configuration for the test node
        :type config: :py:class:`param.Reparsable`
        """
        self.prefix = prefix
        self.config = config
        self._params_cache = None

        self.should_run = self.default_run_decision
        self.should_clean = self.default_clean_decision

        self.workers = set()
        self.worker = None

        self.objects = []

        # lists of parent and children test nodes
        self.setup_nodes = []
        self.cleanup_nodes = []
        self.visited_setup_nodes = {}
        self.visited_cleanup_nodes = {}

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

        uri = self.params.get('name')
        vt_params = self.params.copy()

        # Flatten the vt_params, discarding the attributes that are not
        # scalars, and will not be used in the context of nrunner
        for key in ('_name_map_file', '_short_name_map_file', 'dep'):
            if key in self.params:
                del(vt_params[key])

        return Runnable('avocado-vt', uri, **vt_params)

    def set_environment(self, worker: TestWorker) -> None:
        """
        Set the environment for executing the test node.

        :param worker: set an optional worker or run serially if none given
                       for unisolated process spawners

        This isolating environment could be a container, a virtual machine, or
        a less-isolated process and is managed by a specialized spawner.
        """
        self.params["nets_gateway"] = worker.params["nets_gateway"]
        self.params["nets_host"] = worker.params["nets_host"]
        self.params["nets_spawner"] = worker.params["nets_spawner"]
        self.worker = worker

    def set_objects_from_net(self, net: NetObject) -> None:
        """
        Set all node's objects from a provided test net.

        :param net: test net to use as first and top object
        """
        # flattened list of objects (in composition) involved in the test
        self.objects = [net]
        # TODO: only three nesting levels from a test net are supported
        for test_object in net.components:
            self.objects += [test_object]
            self.objects += test_object.components
            # TODO: dynamically added additional images will not be detected here
            from . import ImageObject
            from .. import params_parser as param
            vm_name = test_object.suffix
            parsed_images = [c.suffix for c in test_object.components]
            for image_name in self.params.object_params(vm_name).objects("images"):
                if image_name not in parsed_images:
                    image_suffix = f"{image_name}_{vm_name}"
                    config = param.Reparsable()
                    config.parse_next_dict(test_object.params.object_params(image_name))
                    config.parse_next_dict({"object_suffix": image_suffix, "object_type": "images"})
                    image = ImageObject(image_suffix, config)
                    image.composites.append(test_object)
                    self.objects += [image]

    def is_occupied(self):
        return self.worker is not None

    def is_flat(self):
        """Check if the test node is flat and does not yet have objects and dependencies to evaluate."""
        return len(self.objects) == 0

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

    def is_unrolled(self, worker_id: str) -> bool:
        """
        Check if the test is unrolled as composite node with dependencies.

        :param worker: worker a flat node is unrolled for
        :raises: :py:class:`RuntimeError` if the current node is not flat (cannot be unrolled)
        """
        if not self.is_flat():
            raise RuntimeError(f"Only flat nodes can be unrolled, {self} is not flat")
        for node in self.cleanup_nodes:
            if self.params["name"] in node.id and worker_id in node.id:
                return True
        return False

    def is_setup_ready(self, worker: TestWorker) -> bool:
        """
        Check if all dependencies of the test were run or there were none.

        :param worker: relative setup readiness with respect to a worker ID
        """
        for node in self.setup_nodes:
            if worker not in self.visited_setup_nodes.get(node, set()):
                return False
        return True

    def is_cleanup_ready(self, worker: TestWorker) -> bool:
        """
        Check if all dependent tests were run or there were none.

        :param str worker: relative setup readiness with respect to a worker ID
        """
        for node in self.cleanup_nodes:
            if worker not in self.visited_cleanup_nodes.get(node, set()):
                return False
        return True

    def is_eagerly_finished(self, worker: TestWorker = None) -> bool:
        """
        The test was run by at least one worker of all or some scopes.

        :param worker: evaluate with respect to an optional worker ID scope or globally if none given
        :returns: whether the test was run by at least one worker of all or some scopes

        This happens in an eager manner so that any already available
        setup nodes are considered finished. If we instead wait for
        this setup to be cleaned up or synced, this would count most
        of the setup as finished in the very end of the traversal.
        """
        if worker and "swarm" not in self.params["pool_scope"] and self.params.get("nets_spawner") == "lxc":
            # is finished separately by each worker
            return worker.params["runtime_str"].split("/")[-1] in set(worker for worker in self.workers)
        elif worker and "cluster" not in self.params["pool_scope"] and self.params.get("nets_spawner") == "remote":
            # is finished for an entire swarm by at least one of its workers
            return worker.params["runtime_str"].split("/")[0] in set(worker.params["runtime_str"].split("/")[0] for worker in self.workers)
        else:
            # is finished globally by at least one worker
            return len(self.workers) > 0

    def is_fully_finished(self, worker: TestWorker = None) -> bool:
        """
        The test was run by all workers of a given scope.

        :param worker: evaluate with respect to an optional worker ID scope or globally if none given
        :returns: whether the test was run all workers of a given scope

        The consideration here is for fully traversed node by all workers
        unless restricted within some scope of setup reuse.
        """
        if worker and "swarm" not in self.params["pool_scope"] and self.params.get("nets_spawner") == "lxc":
            # is finished separately by each worker and for all workers
            return worker.params["runtime_str"].split("/")[-1] in set(worker for worker in self.workers)
        elif worker and "cluster" not in self.params["pool_scope"] and self.params.get("nets_spawner") == "remote":
            # is finished for an entire swarm by all of its workers
            slot_cluster = worker.params["runtime_str"].split("/")[0]
            all_cluster_hosts = set(host for host in TestWorker.run_slots[slot_cluster])
            node_cluster_hosts = set(worker.params["runtime_str"].split("/")[1] for worker in self.workers if worker.params["runtime_str"].split("/")[0] == slot_cluster)
            return all_cluster_hosts == node_cluster_hosts
        else:
            # is finished globally by all workers
            return len(self.workers) == sum([len([w for w in TestWorker.run_slots[s]]) for s in TestWorker.run_slots])

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
            # TODO: direct object compairson will not work for dynamically
            # (within node) created objects like secondary images
            node_object_suffices = [t.long_suffix for t in test_node.objects]
            if test_object in test_node.objects or test_object.long_suffix in node_object_suffices:
                if re.search("(\.|^)" + state + "(\.|$)", test_node.params.get("name")):
                    return True
                setup_object_params = test_object.object_typed_params(test_node.params)
                if state == setup_object_params.get("set_state"):
                    return True
        return False

    def default_run_decision(self, worker: TestWorker) -> bool:
        """
        Default decision policy on whether a test node should be run or skipped.

        :param worker: worker which makes the run decision
        :returns: whether the worker should run the test node
        """
        if not self.produces_setup():
            # most standard stateless behavior is to run each test node by exactly one worker
            should_run = len(self.workers) == 0
        else:
            # scanning will be triggered once for each worker on internal nodes
            should_scan = worker not in self.workers
            should_run = self.scan_states() if should_scan else False

        return should_run

    def default_clean_decision(self, worker: TestWorker) -> bool:
        """
        Default decision policy on whether a test node should be cleaned or skipped.

        :param worker: worker which makes the clean decision
        :returns: whether the worker should clean the test node
        """
        # no support for parallelism within reversible nodes since we might hit a race condition
        # whereby a node will be run for missing setup but its parent will be reversed before it
        # gets any parent-provided states
        is_reversible = True
        for test_object in self.objects:
            object_params = test_object.object_typed_params(self.params)
            is_reversible = object_params.get("unset_mode_images", object_params["unset_mode"])[0] == "f"
            is_reversible |= object_params.get("unset_mode_vms", object_params["unset_mode"])[0] == "f"
            if is_reversible:
                break
        if not is_reversible:
            return True
        else:
            # last one of a given scope should "close the door" for that scope
            return self.is_fully_finished(worker)

    @classmethod
    def prefix_priority(cls, prefix1, prefix2):
        """
        Class method for secondary prioritization using test prefixes.

        :param str prefix1: first prefix to use for the priority comparison
        :param str prefix2: second prefix to use for the priority comparison

        This function also does recursive calls of sub-prefixes.
        """
        match1, match2 = re.match(r"^(\d+)(\w)(.+)", prefix1), re.match(r"^(\d+)(\w)(.+)", prefix2)
        digit1, alpha1, else1 = (prefix1, None, None) if match1 is None else match1.group(1, 2, 3)
        digit2, alpha2, else2 = (prefix2, None, None) if match2 is None else match2.group(1, 2, 3)

        # compare order of parsing if simple leaf nodes
        if digit1.isdigit() and digit2.isdigit():
            digit1, digit2 = int(digit1), int(digit2)
            if digit1 != digit2:
                return digit1 - digit2
        # we no longer match and are at the end of the prefix
        else:
            if digit1 != digit2:
                return 1 if digit1 > digit2 else -1

        # compare the node type flags next
        if alpha1 != alpha2:
            if alpha1 is None:
                return 1 if alpha2 == "a" else -1  # reverse order for "c" (cleanup), "b" (byproduct), "d" (duplicate)
            if alpha2 is None:
                return -1 if alpha1 == "a" else 1  # reverse order for "c" (cleanup), "b" (byproduct), "d" (duplicate)
            return 1 if alpha1 > alpha2 else -1
        # redo the comparison for the next prefix part
        else:
            return cls.prefix_priority(else1, else2)

    @classmethod
    def setup_priority(cls, node1, node2):
        """
        Class method for setup traversal scheduling and prioritization.

        :param node1: first node to use for the priority comparison
        :type node1: :py:class:`TestNode`
        :param node2: first node to use for the priority comparison
        :type node2: :py:class:`TestNode`

        By default (if not externally set), it implements the divergent paths
        policy whereby workers will spread and explore the test space or
        equidistribute if confined within overlapping paths.
        """
        if len(node1.visited_setup_nodes) != len(node2.visited_setup_nodes):
            return len(node1.visited_setup_nodes) - len(node2.visited_setup_nodes)
        if len(node1.visited_cleanup_nodes) != len(node2.visited_cleanup_nodes):
            return len(node1.visited_cleanup_nodes) - len(node2.visited_cleanup_nodes)
        if len(node1.workers) != len(node2.workers):
            return len(node1.workers) - len(node2.workers)

        return cls.prefix_priority(node1.long_prefix, node2.long_prefix)

    @classmethod
    def cleanup_priority(cls, node1, node2):
        """
        Class method for cleanup traversal scheduling and prioritization.

        :param node1: first node to use for the priority comparison
        :type node1: :py:class:`TestNode`
        :param node2: first node to use for the priority comparison
        :type node2: :py:class:`TestNode`

        By default (if not externally set), it implements the divergent paths
        policy whereby workers will spread and explore the test space or
        equidistribute if confined within overlapping paths.
        """
        if len(node1.visited_cleanup_nodes) != len(node2.visited_cleanup_nodes):
            return len(node1.visited_cleanup_nodes) - len(node2.visited_cleanup_nodes)
        if len(node1.visited_setup_nodes) != len(node2.visited_setup_nodes):
            return len(node1.visited_setup_nodes) - len(node2.visited_setup_nodes)
        if len(node1.workers) != len(node2.workers):
            return len(node1.workers) - len(node2.workers)

        return cls.prefix_priority(node1.long_prefix, node2.long_prefix)

    def pick_parent(self, worker: TestWorker) -> "TestNode":
        """
        Pick the next available parent based on some priority.

        :param worker: worker for which the parent is selected
        :returns: the next parent node
        :raises: :py:class:`RuntimeError`

        The current order will prioritize less traversed test paths.
        """
        available_nodes = [n for n in self.setup_nodes if worker not in self.visited_setup_nodes.get(n, set())]
        nodes = sorted(available_nodes, key=cmp_to_key(TestNode.setup_priority))
        if len(nodes) == 0:
            raise RuntimeError("Picked a parent of a node without remaining parents")
        return nodes[0]

    def pick_child(self, worker: TestWorker) -> "TestNode":
        """
        Pick the next available child based on some priority.

        :param worker: worker for which the child is selected
        :returns: the next child node
        :raises: :py:class:`RuntimeError`

        The current order will prioritize less traversed test paths.
        """
        available_nodes = [n for n in self.cleanup_nodes if worker not in self.visited_cleanup_nodes.get(n, set())]
        nodes = sorted(available_nodes, key=cmp_to_key(TestNode.cleanup_priority))
        if len(nodes) == 0:
            raise RuntimeError("Picked a child of a node without remaining children")
        return nodes[0]

    def visit_parent(self, test_node: "TestNode", worker: TestWorker) -> None:
        """
        Add a parent node to the set of visited nodes for this test.

        :param test_node: visited node
        :param worker: worker visiting the node
        :raises: :py:class:`ValueError` if visited node is not directly dependent
        """
        if test_node not in self.setup_nodes:
            raise ValueError(f"Invalid parent to visit: {test_node} not a parent of {self}")
        visitors = self.visited_setup_nodes.get(test_node, set())
        visitors.add(worker)
        self.visited_setup_nodes[test_node] = visitors

    def visit_child(self, test_node: "TestNode", worker: TestWorker) -> None:
        """
        Add a child node to the set of visited nodes for this test.

        :param test_node: visited node
        :param worker: worker visiting the node
        :raises: :py:class:`ValueError` if visited node is not directly dependent
        """
        if test_node not in self.cleanup_nodes:
            raise ValueError(f"Invalid child to visit: {test_node} not a child of {self}")
        visitors = self.visited_cleanup_nodes.get(test_node, set())
        visitors.add(worker)
        self.visited_cleanup_nodes[test_node] = visitors

    def add_location(self, location):
        """
        Add a setup reuse location information to the current node and its children.

        :param str location: a special format string containing all information on the
                             location where the format must be "gateway/host:path"
        """
        # TODO: networks need further refactoring possibly as node environments
        object_suffix = self.params.get("object_suffix", "net1")
        # discard parameters if we are not talking about any specific non-net object
        object_suffix = "_" + object_suffix if object_suffix != "net1" else "_none"
        source_suffix = "_" + location
        source_object_suffix = source_suffix + object_suffix

        location_tuple = location.split(":")
        gateway, host = ("", "") if len(location_tuple) <= 1 else location_tuple[0].split("/")
        ip, port = NetObject.get_session_ip_port(host, gateway,
                                                 self.params['nets_ip_prefix'],
                                                 self.params["nets_shell_port"])

        if self.params.get("set_location"):
            self.params["set_location"] += " " + location
        else:
            self.params["set_location"] = location
        self.params[f"nets_shell_host{source_suffix}"] = ip
        self.params[f"nets_shell_port{source_suffix}"] = port
        self.params[f"nets_file_transfer_port{source_suffix}"] = port

        for node in self.cleanup_nodes:
            if node.params.get(f"get_location{object_suffix}"):
                node.params[f"get_location{object_suffix}"] += " " + location
            else:
                node.params[f"get_location{object_suffix}"] = location

            node.params[f"nets_shell_host{source_object_suffix}"] = ip
            node.params[f"nets_shell_port{source_object_suffix}"] = port
            node.params[f"nets_file_transfer_port{source_object_suffix}"] = port

    def regenerate_params(self, verbose=False):
        """
        Regenerate all parameters from the current reparsable config.

        :param bool verbose: whether to show generated parameter dictionaries
        """
        self._params_cache = self.config.get_params(show_dictionaries=verbose)

    def get_session_ip_port(self):
        """
        Get an IP address and a port to the current slot for the given test node.

        :returns: IP and port in string parameter format
        :rtype: (str, str)
        """
        return NetObject.get_session_ip_port(self.params['nets_host'],
                                             self.params['nets_gateway'],
                                             self.params['nets_ip_prefix'],
                                             self.params["nets_shell_port"])

    def get_session_to_net(self):
        """
        Get a remote session to the current slot for the given test node.

        :returns: remote session to the slot determined from current node environment
        :rtype: :type session: :py:class:`aexpect.ShellSession`
        """
        log.getLogger("aexpect").parent = log.getLogger("avocado.job")
        host, port = self.get_session_ip_port()
        address = host + ":" + port
        cache = type(self)._session_cache
        session = cache.get(address)
        if session:
            # check for corrupted sessions
            try:
                logging.debug("Remote session health check: " + session.cmd_output("date"))
            except ShellTimeoutError as error:
                logging.warning(f"Bad remote session health for {address}!")
                session = None
        if not session:
            session = remote.wait_for_login(self.params["nets_shell_client"],
                                            host, port,
                                            self.params["nets_username"], self.params["nets_password"],
                                            self.params["nets_shell_prompt"])
            cache[address] = session

        return session

    def scan_states(self):
        """
        Scan for present object states to reuse the test from previous runs.

        :returns: whether all required states are available
        :rtype: bool
        """
        should_run = True
        node_params = self.params.copy()

        slot, slothost = self.params["nets_host"], self.params["nets_gateway"]
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
                should_run = False
                break

            # ultimate consideration of whether the state is actually present
            object_suffix = f"_{test_object.key}_{test_object.long_suffix}"
            node_params[f"check_state{object_suffix}"] = object_state
            node_params[f"show_location{object_suffix}"] = object_params["set_location"]
            node_params[f"check_mode{object_suffix}"] = object_params.get("check_mode", "rf")
            # TODO: unfortunately we need env object with pre-processed vms in order
            # to provide ad-hoc root vm states so we use the current advantage that
            # all vm state backends can check for states without a vm boot (root)
            if test_object.key == "vms":
                node_params[f"use_env{object_suffix}"] = "no"
            node_params[f"soft_boot{object_suffix}"] = "no"

        if not is_leaf:
            session = self.get_session_to_net()
            control_path = os.path.join(self.params["suite_path"], "controls", "pre_state.control")
            mod_control_path = door.set_subcontrol_parameter(control_path, "action", "check")
            mod_control_path = door.set_subcontrol_parameter_dict(mod_control_path, "params", node_params)
            try:
                door.run_subcontrol(session, mod_control_path)
                should_run = False
            except ShellCmdError as error:
                if "AssertionError" in error.output:
                    should_run = True
                else:
                    raise RuntimeError("Could not complete state scan due to control file error")
        logging.info(f"The test node {self} %s run from a scan on {slothost + '/' + slot}",
                     "should" if should_run else "should not")
        return should_run

    def sync_states(self, params):
        """Sync or drop present object states to clean or later skip tests from previous runs."""
        node_params = self.params.copy()
        for key in list(node_params.keys()):
            if key.startswith("get_state") or key.startswith("unset_state"):
                del node_params[key]

        # the sync cleanup will be performed if at least one selected object has a cleanable state
        slot, slothost = self.params["nets_host"], self.params["nets_gateway"]
        should_clean = False
        for test_object in self.objects:
            object_params = test_object.object_typed_params(self.params)
            object_state = object_params.get("set_state")
            if not object_state:
                continue

            # avoid running any test unless the user really requires cleanup or setup is reusable
            unset_policy = object_params.get("unset_mode", "ri")
            if unset_policy[0] not in ["f", "r"]:
                continue
            # avoid running any test for unselected vms
            if test_object.key == "nets":
                logging.warning("Net state cleanup is not supported")
                continue
            # the object state has to be defined to reach this stage
            if object_state == "install" and test_object.is_permanent():
                should_clean = False
                break
            vm_name = test_object.suffix if test_object.key == "vms" else test_object.composites[0].suffix
            # TODO: is this needed?
            from .. import params_parser as param
            if vm_name in params.get("vms", param.all_objects("vms")):
                should_clean = True
            else:
                continue

            # TODO: cannot remove ad-hoc root states, is this even needed?
            if test_object.key == "vms":
                vm_params = object_params
                node_params["images_" + vm_name] = vm_params["images"]
                for image_name in vm_params.objects("images"):
                    image_params = vm_params.object_params(image_name)
                    node_params[f"image_name_{image_name}_{vm_name}"] = image_params["image_name"]
                    node_params[f"image_format_{image_name}_{vm_name}"] = image_params["image_format"]
                    if image_params.get_boolean("create_image", False):
                        node_params[f"remove_image_{image_name}_{vm_name}"] = "yes"
                        node_params["skip_image_processing"] = "no"

            suffixes = f"_{test_object.key}_{test_object.suffix}"
            suffixes += f"_{vm_name}" if test_object.key == "images" else ""
            # spread the state setup for the given test object
            location = object_params["set_location"]
            if unset_policy[0] == "f":
                # reverse the state setup for the given test object
                # NOTE: we are forcing the unset_mode to be the one defined for the test node because
                # the unset manual step behaves differently now (all this extra complexity starts from
                # the fact that it has different default value which is noninvasive
                node_params.update({f"unset_state{suffixes}": object_state,
                                    f"unset_location{suffixes}": location,
                                    f"unset_mode{suffixes}": object_params.get("unset_mode", "ri"),
                                    f"pool_scope": "own"})
                do = "unset"
                logging.info(f"Need to clean up {self} on {slot}")
            else:
                # spread the state setup for the given test object
                node_params.update({f"get_state{suffixes}": object_state,
                                    f"get_location{suffixes}": location})
                node_params[f"pool_scope{suffixes}"] = object_params.get("pool_scope", "swarm cluster shared")
                # NOTE: "own" may not be removed because we skip "own" scope here which is done for both
                # speed and the fact that it is not equivalent to reflexive download (actually getting a state)
                for sync_source in location.split():
                    if sync_source.startswith(slothost + '/' + slot):
                        logging.info(f"No need to sync {self} from {slot} to itself")
                        should_clean = False
                        break
                else:
                    logging.info(f"Need to sync {self} from {location.join(',')} to {slot}")
                do = "get"
            # TODO: unfortunately we need env object with pre-processed vms in order
            # to provide ad-hoc root vm states so we use the current advantage that
            # all vm state backends can check for states without a vm boot (root)
            if test_object.key == "vms":
                node_params[f"use_env_{test_object.key}_{test_object.suffix}"] = "no"

        if should_clean:
            action = "Cleaning up" if unset_policy[0] == "f" else "Syncing"
            logging.info(f"{action} {self} on {slot}")
            session = self.get_session_to_net()
            control_path = os.path.join(self.params["suite_path"], "controls", "pre_state.control")
            mod_control_path = door.set_subcontrol_parameter(control_path, "action", do)
            mod_control_path = door.set_subcontrol_parameter_dict(mod_control_path, "params", node_params)
            try:
                door.run_subcontrol(session, mod_control_path)
            except ShellCmdError as error:
                logging.warning(f"{action} {self} on {slot} could not be completed "
                                f"due to control file error: {error}")
        else:
            logging.info(f"No need to clean up or sync {self} on {slot}")

    def validate(self):
        """Validate the test node for sane attribute-parameter correspondence."""
        param_nets = self.params.objects("nets")
        attr_nets = list(o.suffix for o in self.objects if o.key == "nets")
        if len(attr_nets) > 1 or len(param_nets) > 1:
            raise AssertionError(f"Test node {self} can have only one net ({attr_nets}/{param_nets}")
        param_net_name, attr_net_name = attr_nets[0], param_nets[0]
        if self.objects and self.objects[0].suffix != attr_net_name:
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
