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
logging = log.getLogger('avocado.test.' + __name__)

from aexpect.exceptions import ShellCmdError
from aexpect import remote
from aexpect import remote_door as door
from avocado.core.test_id import TestID
from avocado.core.nrunner.runnable import Runnable
from avocado.core.dispatcher import SpawnerDispatcher


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
        net_id = self.params["hostname"]
        net_id += self.params["vms"].replace(" ", "")
        full_prefix = self.prefix + "-" + net_id
        return TestID(full_prefix, self.params["name"])
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
        # TODO: also allow caching among container sessions?
        #self._session_cache = {}

        # flattened list of objects (in composition) involved in the test
        self.objects = [object]
        # TODO: only three nesting levels from a test net are supported
        if object.key != "nets":
            raise AssertionError("Test node could be initialized only from test objects "
                                 "of the same composition level, currently only test nets")
        for test_object in object.components:
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
        # NOTE: at present handle the lack of slots as an indicator of using
        # non-isolated serial runs via the old process environment spawner
        spawner_name = "lxc" if job.config["param_dict"].get("slots") else "process"

        # TODO: move cid in constructor in the upstream PR
        self.spawner = SpawnerDispatcher(job.config, job)[spawner_name].obj
        self.spawner.cid = env_id

        self.params["hostname"] = env_id if env_id else self.params["hostname"]

    @staticmethod
    def start_environment(env_id):
        """
        Start the environment for executing a test node.

        :returns: whether the environment is available after current or previous start
        :rtype: bool

        ..todo:: As we can start containers this code will have to differentiate
            between a remote host and a remote or local container later on with a
            wake-on-lan implementation for the latter.
        """
        import lxc
        container = lxc.Container(env_id)
        if not container.running:
            logging.info(f"Starting bootable environment {env_id}")
            return container.start()
        return container.running

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

    def is_setup_ready(self, worker):
        """
        Check if all dependencies of the test were run or there were none.

        :param str worker: relative setup readiness with respect to a worker ID
        """
        for node in self.setup_nodes:
            if worker not in self.visited_setup_nodes.get(node, set()):
                return False
        return True

    def is_cleanup_ready(self, worker):
        """
        Check if all dependent tests were run or there were none.

        :param str worker: relative setup readiness with respect to a worker ID
        """
        for node in self.cleanup_nodes:
            if worker not in self.visited_cleanup_nodes.get(node, set()):
                return False
        return True

    def is_finished(self):
        """
        The test was run by at least one worker.

        This choice of criterion makes sure that already available
        setup nodes are considered finished. If we instead wait for
        this setup to be cleaned up or synced, this would count most
        of the setup as finished in the end of the traversal while
        we would prefer to do so in an eager manner.
        """
        return len(self.workers) > 0 and not self.should_run

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

    def pick_parent(self, slot):
        """
        Pick the next available parent based on some priority.

        :returns: the next parent node
        :rtype: :py:class:`TestNode`
        :raises: :py:class:`RuntimeError`

        The current order will prioritize less traversed test paths.
        """
        available_nodes = [n for n in self.setup_nodes if slot not in self.visited_setup_nodes.get(n, set())]
        nodes = sorted(available_nodes, key=cmp_to_key(TestNode.setup_priority))
        if len(nodes) == 0:
            raise RuntimeError("Picked a parent of a node without remaining parents")
        return nodes[0]

    def pick_child(self, slot):
        """
        Pick the next available child based on some priority.

        :returns: the next child node
        :rtype: :py:class:`TestNode`
        :raises: :py:class:`RuntimeError`

        The current order will prioritize less traversed test paths.
        """
        available_nodes = [n for n in self.cleanup_nodes if slot not in self.visited_cleanup_nodes.get(n, set())]
        nodes = sorted(available_nodes, key=cmp_to_key(TestNode.cleanup_priority))
        if len(nodes) == 0:
            raise RuntimeError("Picked a child of a node without remaining children")
        return nodes[0]

    def visit_parent(self, test_node, worker):
        """
        Add a parent node to the set of visited nodes for this test.

        :param test_node: visited node
        :type test_node: TestNode object
        :param str worker: slot ID of worker visiting the node
        :raises: :py:class:`ValueError` if visited node is not directly dependent
        """
        if test_node not in self.setup_nodes:
            raise ValueError(f"Invalid parent to visit: {test_node} not a parent of {self}")
        visitors = self.visited_setup_nodes.get(test_node, set())
        visitors.add(worker)
        self.visited_setup_nodes[test_node] = visitors

    def visit_child(self, test_node, worker):
        """
        Add a child node to the set of visited nodes for this test.

        :param test_node: visited node
        :type test_node: TestNode object
        :param str worker: slot ID of worker visiting the node
        :raises: :py:class:`ValueError` if visited node is not directly dependent
        """
        if test_node not in self.cleanup_nodes:
            raise ValueError(f"Invalid child to visit: {test_node} not a child of {self}")
        visitors = self.visited_cleanup_nodes.get(test_node, set())
        visitors.add(worker)
        self.visited_cleanup_nodes[test_node] = visitors

    def regenerate_params(self, verbose=False):
        """
        Regenerate all parameters from the current reparsable config.

        :param bool verbose: whether to show generated parameter dictionaries
        """
        self._params_cache = self.config.get_params(show_dictionaries=verbose)

    def get_session_ip(self, slot):
        """
        Get an IP to a slot for the given test node's IP prefix.

        :param str slot: slot to restrict the IP prefix to
        :returns: IP in string parameter format for the given slot
        :rtype: str
        """
        node_host = slot
        node_nets = self.params["nets_ip_prefix"]
        return f"{node_nets}.{node_host[1:]}" if node_host else ""

    def get_session_to_net(self, slot):
        """
        Get a remote session to a slot for the given test node's IP prefix.

        :param str slot: slot to connect to
        :returns: remote session to the slot
        :rtype: :type session: :py:class:`aexpect.ShellSession`
        """
        log.getLogger("aexpect").parent = log.getLogger("avocado.extlib")
        return remote.wait_for_login(self.params["nets_shell_client"],
                                     self.get_session_ip(slot),
                                     self.params["nets_shell_port"],
                                     self.params["nets_username"], self.params["nets_password"],
                                     self.params["nets_shell_prompt"])

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
            object_suffix = f"_{test_object.key}_{test_object.long_suffix}"
            node_params[f"check_state{object_suffix}"] = object_state
            node_params[f"check_location{object_suffix}"] = object_params.get("set_location",
                                                                              object_params.get("image_pool", ""))
            node_params[f"check_mode{object_suffix}"] = object_params.get("check_mode", "rf")
            # TODO: unfortunately we need env object with pre-processed vms in order
            # to provide ad-hoc root vm states so we use the current advantage that
            # all vm state backends can check for states without a vm boot (root)
            if test_object.key == "vms":
                node_params[f"use_env{object_suffix}"] = "no"
            node_params[f"soft_boot{object_suffix}"] = "no"

        if not is_leaf:
            session = self.get_session_to_net(self.params["hostname"])
            control_path = os.path.join(self.params["suite_path"], "controls", "pre_state.control")
            mod_control_path = door.set_subcontrol_parameter(control_path, "action", "check")
            mod_control_path = door.set_subcontrol_parameter_dict(mod_control_path, "params", node_params)
            try:
                door.run_subcontrol(session, mod_control_path)
                self.should_run = False
            except ShellCmdError as error:
                if "AssertionError" in error.output:
                    self.should_run = True
                else:
                    raise RuntimeError("Could not complete state scan due to control file error")
        logging.info("The test node %s %s run from a scan on %s", self,
                     "should" if self.should_run else "should not", self.params["hostname"])

    def sync_states(self, params):
        """Sync or drop present object states to clean or later skip tests from previous runs."""
        node_params = self.params.copy()
        for key in list(node_params.keys()):
            if key.startswith("get_state") or key.startswith("unset_state"):
                del node_params[key]

        # the sync cleanup will be performed if at least one selected object has a cleanable state
        slot = self.params["hostname"]
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

            unset_suffixes = f"_{test_object.key}_{test_object.suffix}"
            unset_suffixes += f"_{vm_name}" if test_object.key == "images" else ""
            if unset_policy[0] == "f":
                # reverse the state setup for the given test object
                # NOTE: we are forcing the unset_mode to be the one defined for the test node because
                # the unset manual step behaves differently now (all this extra complexity starts from
                # the fact that it has different default value which is noninvasive
                node_params.update({f"unset_state{unset_suffixes}": object_state,
                                    f"unset_mode{unset_suffixes}": object_params.get("unset_mode", "ri"),
                                    # TODO: force use only of local operations is still too indirect
                                    f"use_pool": "no"})
                do = "unset"
            else:
                # spread the state setup for the given test object
                sync_location = object_params.get("set_location", object_params.get("image_pool", ""))
                node_params.update({f"get_state{unset_suffixes}": object_state,
                                    f"get_location{unset_suffixes}": sync_location,
                                    # TODO: force use only of transport is still too indirect
                                    f"update_pool": "yes"})
                do = "get"
                # TODO: this won't work with links
                if sync_location.startswith(self.get_session_ip(slot)):
                    logging.info(f"No need to sync {self} from {slot} to itself")
                    should_clean = False
                else:
                    logging.info(f"Need to sync {self} from {sync_location} to {slot}")
            # TODO: unfortunately we need env object with pre-processed vms in order
            # to provide ad-hoc root vm states so we use the current advantage that
            # all vm state backends can check for states without a vm boot (root)
            if test_object.key == "vms":
                node_params[f"use_env_{test_object.key}_{test_object.suffix}"] = "no"

        if should_clean:
            action = "Cleaning up" if unset_policy[0] == "f" else "Syncing"
            logging.info(f"{action} {self} on {slot}")
            session = self.get_session_to_net(slot)
            control_path = os.path.join(self.params["suite_path"], "controls", "pre_state.control")
            mod_control_path = door.set_subcontrol_parameter(control_path, "action", do)
            mod_control_path = door.set_subcontrol_parameter_dict(mod_control_path, "params", node_params)
            try:
                door.run_subcontrol(session, mod_control_path)
            except ShellCmdError as error:
                logging.warning(f"Could not sync/clean {self} due to control file error: {error}")
        else:
            logging.info(f"No need to clean up or sync {self} on {slot}")

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
