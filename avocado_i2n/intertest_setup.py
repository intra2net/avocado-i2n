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
Utility to manage all needed virtual machines.

Copyright: Intra2net AG


CONTENTS
------------------------------------------------------
This utility can be used by any host control to manage one or more virtual machines.
It in turn uses some other host utilities.

Use the tag argument to add more details to generated test variant name in
case you are running any of the manual step functions here more than once.

**IMPORTANT**: If you don't want to perform the given setup with all virtual machines,
defined by your parameters then just overwrite the parameter `vms` as a space
separated list of the selected virtual machine names. The setup then is going to be
performed only on those machines and not on all. Example is 'vms = vm1 vm2 vm3\n'
to create only vm1 and vm3 add to the overwrite string 'vms = vm1 vm3\n' in order
to overwrite the vms parameter. Of course you can do this with any parameter
to manage other aspects of the virtual environment setup process.


INTERFACE
------------------------------------------------------

"""

import sys
import os
import re
import logging as log
logging = log.getLogger('avocado.job.' + __name__)
import contextlib
import importlib
import asyncio
from collections import namedtuple

from avocado.core import job
from avocado.core import data_dir
from avocado.core.suite import TestSuite
from avocado.core.settings import settings
from avocado.core.output import LOG_UI

from . import params_parser as param
from .cartgraph import TestGraph, TestNode
from .loader import CartesianLoader
from .runner import CartesianRunner


#: list of all available manual steps or simply semi-automation tools
__all__ = ["noop", "unittest", "update", "run", "list",
           "boot", "download", "control", "upload", "shutdown",
           "check", "pop", "push", "get", "set", "unset",
           "collect", "create", "clean"]


def load_addons_tools():
    """Load all custom manual steps defined in the test suite tools folder."""
    suite_path = settings.as_dict().get('i2n.common.suite_path')
    tools_path = os.path.join(suite_path, "tools")
    sys.path.append(tools_path)
    # we have no other choice to avoid loading at intertest import
    global __all__
    for tool in os.listdir(tools_path):
        if tool.endswith(".py") and not tool.endswith("_unittest.py"):
            module_name = tool.replace(".py", "")
            logging.debug("Loading tools in %s", module_name)
            try:
                module = importlib.import_module(module_name)
            except Exception as error:
                logging.error("Could not load tool %s: %s", module_name, error)
                continue

            if "__all__" not in module.__dict__:
                logging.warning("Detected tool module doesn't contain publicly defined tools")
                continue

            names = module.__dict__["__all__"]
            globals().update({k: getattr(module, k) for k in names})
            __all__ += module.__all__

            logging.info("Loaded custom tools: %s", ", ".join(module.__all__))


@contextlib.contextmanager
def new_job(config):
    """
    Produce a new job object and thus a job.

    :param config: command line arguments
    :type config: {str, str}
    """
    suite = TestSuite('suite', {}, tests=[], job_config=config)
    with job.Job(config, [suite]) as job_instance:

        loader, runner = config["graph"].l, config["graph"].r
        loader.logdir = job_instance.logdir
        runner.job = job_instance

        yield job_instance


def with_cartesian_graph(fn):
    """
    Run a given function with a job-enabled loader-runner hybrid graph.

    :param fn: function to run with a job
    :type fn: function
    :returns: same function with job resource included
    :rtype: function
    """
    def wrapper(config, tag=""):
        loader = TestGraph
        runner = CartesianRunner()
        CartesianGraph = namedtuple('CartesianGraph', 'l r')
        config["graph"] = CartesianGraph(l=loader, r=runner)

        with new_job(config) as job:
            fn(config, tag=tag)

            config["graph"] = None
            return 0 if runner.all_tests_ok else 1

    return wrapper


############################################################
# Main manual user steps
############################################################


def noop(config, tag=""):
    """
    Empty setup step to invoke plugin without performing anything.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    LOG_UI.info("NOOP")


def unittest(config, tag=""):
    """
    Perform self testing for sanity and test result validation.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    import unittest
    util_unittests = unittest.TestSuite()
    util_testrunner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2)

    root_path = settings.as_dict().get('i2n.common.suite_path')
    subtests_filter = config["tests_params"].get("ut_filter", "*_unittest.py")

    subtests_path = os.path.join(root_path, "utils")
    subtests_suite = unittest.defaultTestLoader.discover(subtests_path,
                                                         pattern=subtests_filter,
                                                         top_level_dir=subtests_path)
    util_unittests.addTest(subtests_suite)

    subtests_path = os.path.join(root_path, "tools")
    subtests_suite = unittest.defaultTestLoader.discover(subtests_path,
                                                         pattern=subtests_filter,
                                                         top_level_dir=subtests_path)
    util_unittests.addTest(subtests_suite)

    util_testrunner.run(util_unittests)


@with_cartesian_graph
def update(config, tag=""):
    """
    Update all states (run all tests) from the state defined as
    ``from_state=<state>`` to the state defined as ``to_state=<state>``.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    The state can be achieved all the way from the test object creation. The
    performed setup depends entirely on the state's dependencies which can
    be completely different than the regular create->install->deploy path.

    Thus, a change in a state can be reflected in all the dependent states.

    Only singleton test setup is supported within the update setup path since
    we cannot guarantee other setup involved vms exist.

    .. note:: If you want to update the install state, you also need to change the
        starting state to 'from_state=root'. Using 'from_state=install' will keep
        the install test and update all of its derivatives as it does with any value
        specified in 'from_state'.
    """
    l, r = config["graph"].l, config["graph"].r
    selected_vms = sorted(config["vm_strs"].keys())
    LOG_UI.info("Update state cache for %s (%s)",
                ", ".join(selected_vms), os.path.basename(r.job.logdir))

    graph = TestGraph()
    flat_net = l.parse_net_from_object_strs("net1", config["vm_strs"])
    initial_objects = l.parse_components_for_object(flat_net, "nets", params=config["param_dict"], unflatten=True)
    for i, vm_name in enumerate(selected_vms):
        vm_params = config["vms_params"].object_params(vm_name)
        from_state = vm_params.get("from_state", "install")
        to_state = vm_params.get("to_state", "customize")
        logging.info("Updating state '%s' of %s", to_state, vm_name)

        # pick the test objects corresponding to the current vm
        for test_object in initial_objects:
            if test_object.key != "vms":
                continue
            vm = test_object
            if vm.suffix != vm_name:
                continue
            if len(vm.components) > 1:
                logging.warning(f"Multiple images used by {vm.suffix}, installing on first one")
            break
        else:
            raise ValueError(f"Cannot find test object for {vm_name} to update")
        # install only on first image as RAID and other configurations are customizations
        image = vm.components[0]
        # parse individual net only for the current vm
        net = l.parse_object_from_objects("net1", "nets", [vm], params=config["param_dict"])

        logging.info(f"Parsing a standard initial graph for '{to_state}'")
        setup_dict = config["param_dict"].copy()
        # in case of permanent vms, support creation and other otherwise dangerous operations
        setup_dict["create_permanent_vm"] = "yes"
        setup_dict["main_vm"] = vm_name
        setup_dict["vms"] = vm_name
        # NOTE: this makes sure that any present states are overwritten and no recreated
        # states are removed, aborting in any other case
        setup_dict.update({"get_mode": "ra", "set_mode": "ff", "unset_mode": "fi"})
        setup_str = vm_params.get("remove_set", "leaves")
        for restriction in config["available_restrictions"]:
            if restriction in setup_str:
                break
        else:
            setup_str = "all.." + setup_str
        setup_str = param.re_str(setup_str)
        vm_graph = l.parse_object_trees(setup_dict,
                                        setup_str,
                                        config["available_vms"],
                                        prefix=f"{tag}m{i+1}", verbose=False, with_shared_root=False)
        # flagging children will require connected graphs while flagging intersection can also handle disconnected ones
        vm_graph.flag_intersection(vm_graph, flag_type="run", flag=lambda self, slot: False)
        vm_graph.flag_intersection(vm_graph, flag_type="clean", flag=lambda self, slot: False)

        logging.info(f"Flagging for removing all old states depending on the updated '{to_state}'")
        flag_state = None if to_state == "install" else to_state
        try:
            vm_graph.flag_children(flag_state, vm_name, flag_type="clean", flag=lambda self, slot: True, skip_parents=True)
        except AssertionError as error:
            logging.error(error)
            raise ValueError(f"Could not identify a test node from {vm_name}'s to_state='{flag_state}', "
                             f"is it compatible with the default or specified remove_set?")

        logging.info(f"Flagging for updating all states between and including '{from_state}' and '{to_state}'")
        if to_state == "install":
            update_graph = TestGraph()
            update_graph.objects = vm_graph.objects
            # figure out the install node to compare against
            start_node = l.parse_node_from_object(net, "all..internal..customize", prefix=tag, params=config["param_dict"])
            install_node = l.parse_node_from_object(net, "all..original.." + start_node.params["get_images"],
                                                    prefix=tag, params=config["param_dict"])
            install_node.params["object_root"] = image.id
            update_graph.nodes.append(install_node)
        else:
            update_graph = l.parse_object_trees(setup_dict,
                                                param.re_str("all.." + to_state),
                                                {vm_name: config["vm_strs"][vm_name]},
                                                prefix=tag)
        vm_graph.flag_intersection(update_graph, flag_type="run", flag=lambda self, slot: len(self.workers) == 0,
                                   skip_shared_root=True)

        if from_state != "install":
            logging.info(f"Flagging for preserving all states before the updated '{from_state}'")
            reuse_graph = l.parse_object_trees(setup_dict,
                                               param.re_str("all.." + from_state),
                                               {vm_name: config["vm_strs"][vm_name]},
                                               prefix=tag, verbose=False)
            vm_graph.flag_intersection(reuse_graph, flag_type="run", flag=lambda self, slot: False)
            try:
                vm_graph.flag_children(from_state, flag_type="run", flag=lambda self, slot: len(self.workers) == 0,
                                    skip_children=True)
            except AssertionError as error:
                logging.error(error)
                raise ValueError(f"Could not identify a test node from {vm_name}'s from_state='{from_state}', "
                                 f"is it compatible with the default or specified remove_set?")

        graph.new_workers(l.parse_workers(config["param_dict"]))
        graph.objects += vm_graph.objects
        graph.nodes += vm_graph.nodes

    graph.parse_shared_root_from_object_trees(config["param_dict"])
    r.run_workers(graph, config["param_dict"])
    LOG_UI.info("Finished updating cache")


def run(config, tag=""):
    """
    Run a set of tests without any automated setup.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    This is equivalent to but more powerful than the runner plugin.
    """
    # NOTE: each run expects already incremented count in the beginning but this prefix
    # is preferential to setup chains with a single "run" step since this is usually the case
    config["prefix"] = tag + "n" if len(re.findall("run", config["vms_params"]["setup"])) > 1 else ""

    loader = TestGraph
    runner = CartesianRunner()
    CartesianGraph = namedtuple('CartesianGraph', 'l r')
    config["graph"] = CartesianGraph(l=loader, r=runner)

    # essentially we imitate the auto plugin to make the tool plugin a superset
    with new_job(config) as job:

        params, restriction = config["param_dict"], config["tests_str"]
        runnables = [n.get_runnable() for n in TestGraph.parse_flat_nodes(restriction, params)]
        job.test_suites[0].tests = runnables

        retcode = job.run()
        # runner.run_traversal(graph, config["param_dict"].copy())

        config["graph"] = None
        return retcode


def list(config, tag=""):
    """
    List a set of tests from the command line.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    This is equivalent to but more powerful than the loader plugin.
    """
    loader = TestGraph
    runner = CartesianRunner()
    CartesianGraph = namedtuple('CartesianGraph', 'l r')
    config["graph"] = CartesianGraph(l=loader, r=runner)

    with new_job(config) as job:

        prefix = tag + "l" if len(re.findall("run", config["vms_params"]["setup"])) > 1 else ""
        # provide the logdir in advance in order to visualize parsed graph there
        TestGraph.logdir = runner.job.logdir
        graph = loader.parse_object_trees(config["param_dict"], config["tests_str"], config["vm_strs"],
                                          prefix=prefix, verbose=True)
        graph.visualize(job.logdir)


############################################################
# VM management manual user steps
############################################################


@with_cartesian_graph
def boot(config, tag=""):
    """
    Boot all given vms.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    The boot test always takes care of any other vms so we can do it all in one test
    which is a bit of a hack but is much faster than the standard per-vm handling.
    """
    _parse_one_node_for_all_objects(config, tag, ("Booting", "start", "boot", "Boot"))


@with_cartesian_graph
def download(config, tag=""):
    """
    Download a set of files from the given vms.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    The set of files is specified using a "files" parameter.

    The download test always takes care of any other vms so we can do it all in one test
    which is a bit of a hack but is much faster than the standard per-vm handling.
    """
    _parse_one_node_for_all_objects(config, tag, ("Downloading from", "download", "download", "Download"))


@with_cartesian_graph
def control(config, tag=""):
    """
    Run a control file on the given vms.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    The control file is specified using a "control_file" parameter.
    """
    _parse_one_node_for_all_objects(config, tag, ("Running on", "run", "run", "Run"))


@with_cartesian_graph
def upload(config, tag=""):
    """
    Upload a set of files to the given vms.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    The set of files is specified using a `files` parameter.

    The upload test always takes care of any other vms so we can do it all in one test
    which is a bit of a hack but is much faster than the standard per-vm handling.
    """
    _parse_one_node_for_all_objects(config, tag, ("Uploading to", "upload", "upload", "Upload"))


@with_cartesian_graph
def shutdown(config, tag=""):
    """
    Shutdown gracefully or kill living vms.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    The shutdown test always takes care of any other vms so we can do it all in one test
    which is a bit of a hack but is much faster than the standard per-vm handling.
    """
    _parse_one_node_for_all_objects(config, tag, ("Shutting down", "stop", "shutdown", "Shutdown"))


############################################################
# State manipulation manual user steps
############################################################


@with_cartesian_graph
def check(config, tag=""):
    """
    Check whether a given state (setup snapshot) exists.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    operation = "check"
    _parse_all_objects_then_iterate_for_nodes(config, tag,
                                              {"vm_action": operation,
                                               "skip_image_processing": "yes"},
                                              "state " + operation)


@with_cartesian_graph
def pop(config, tag=""):
    """
    Get to a state/snapshot disregarding the current changes
    loosing the it afterwards.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    operation = "pop"
    _parse_all_objects_then_iterate_for_nodes(config, tag,
                                              {"vm_action": operation,
                                               "skip_image_processing": "yes"},
                                              "state " + operation)


@with_cartesian_graph
def push(config, tag=""):
    """
    Wrapper for setting state/snapshot, same as :py:func:`set`.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    operation = "push"
    _parse_all_objects_then_iterate_for_nodes(config, tag,
                                              {"vm_action": operation,
                                               "skip_image_processing": "yes"},
                                              "state " + operation)


@with_cartesian_graph
def get(config, tag=""):
    """
    Get to a state/snapshot disregarding the current changes.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    This method could be implemented in identical way to the push/pop
    methods but we use different approach for illustration.
    """
    operation = "get"
    _parse_all_objects_then_iterate_for_nodes(config, tag,
                                              {"vm_action": operation,
                                               "skip_image_processing": "yes"},
                                              "state " + operation)


@with_cartesian_graph
def set(config, tag=""):
    """
    Create a new state/snapshot from the current state/snapshot.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    This method could be implemented in identical way to the push/pop
    methods but we use different approach for illustration.
    """
    operation = "set"
    _parse_all_objects_then_iterate_for_nodes(config, tag,
                                              {"vm_action": operation,
                                               "skip_image_processing": "yes"},
                                              "state " + operation)


@with_cartesian_graph
def unset(config, tag=""):
    """
    Remove a state/snapshot.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    This method could be implemented in identical way to the push/pop
    methods but we use different approach for illustration.
    """
    operation = "unset"
    op_mode = "unset_mode"

    l, r = config["graph"].l, config["graph"].r
    setup_dict = config["param_dict"].copy()
    flat_net = l.parse_net_from_object_strs("net1", config["vm_strs"])
    for test_object in l.parse_components_for_object(flat_net, "nets", params=config["param_dict"], unflatten=True):
        if test_object.key != "vms":
            continue
        vm = test_object

        # since the default unset_mode is passive (ri) we need a better
        # default value for that case but still modifiable by the user
        vm_op_mode = op_mode + "_" + vm.suffix
        state_mode = vm_op_mode if vm_op_mode in setup_dict else op_mode
        if state_mode not in setup_dict:
            setup_dict[vm_op_mode] = "fi"

    setup_dict.update({"vm_action": operation, "skip_image_processing": "yes"})

    _parse_all_objects_then_iterate_for_nodes(config, tag,
                                              setup_dict, "state " + operation)


def collect(config, tag=""):
    """
    Get a new test object (vm, root state) from a pool.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    ..todo:: With later refactoring of the root check implicitly getting a
        pool rool state, we can refine the parameters here.
    """
    _reuse_tool_with_param_dict(config, tag,
                                {"get_state_images": "root",
                                 "get_mode_images": "ii",
                                 # don't touch root states in any way
                                 "check_mode_images": "rr",
                                 # this manual tool is compatible only with pool
                                 "pool_scope": "swarm cluster shared"},
                                get)


def create(config, tag=""):
    """
    Create a new test object (vm, root state).

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    _reuse_tool_with_param_dict(config, tag,
                                {"set_state_images": "root",
                                 "set_mode_images": "af",
                                 # don't touch root states in any way
                                 "check_mode_images": "rr",
                                 # this manual tool is not compatible with pool
                                 "pool_scope": "own"},
                                set)


def clean(config, tag=""):
    """
    Remove a test object (vm, root state).

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    _reuse_tool_with_param_dict(config, tag,
                                {"unset_state_images": "root",
                                 "unset_mode_images": "fa",
                                 # make use of off switch if vm is running
                                 "check_mode_images": "rf",
                                 # this manual tool is not compatible with pool
                                 "pool_scope": "own"},
                                unset)


############################################################
# Private templates reused by all tools above
############################################################


def _parse_one_node_for_all_objects(config, tag, verb):
    """
    Wrapper for setting state/snapshot, same as :py:func:`set`.

    :param verb: verb forms in a tuple (gerund form, variant, test name, present)
    :type verb: (str, str, str, str)

    The rest of the arguments match the public functions.
    """
    l, r = config["graph"].l, config["graph"].r
    selected_vms = sorted(config["vm_strs"].keys())
    LOG_UI.info("%s virtual machines %s (%s)", verb[0],
                ", ".join(selected_vms), os.path.basename(r.job.logdir))
    vms = " ".join(selected_vms)
    setup_dict = config["param_dict"].copy()
    setup_dict.update({"vms": vms, "main_vm": selected_vms[0]})
    tests, objects = l.parse_object_nodes("all..internal..manage.%s" % verb[1], tag, config["vm_strs"], params=setup_dict)
    assert len(tests) == 1, "There must be exactly one %s test variant from %s" % (verb[2], tests)
    graph = TestGraph()
    graph.new_workers(l.parse_workers(config["param_dict"]))
    graph.objects = objects
    test_node = TestNode(tag, tests[0].config)
    test_node.set_objects_from_net(objects[-1])
    graph.nodes = [test_node]
    graph.parse_shared_root_from_object_trees(config["param_dict"])
    graph.flag_children(flag_type="run", flag=lambda self, slot: True)
    r.run_workers(graph, config["param_dict"])
    LOG_UI.info("%s complete", verb[3])


def _parse_all_objects_then_iterate_for_nodes(config, tag, param_dict, operation):
    """
    Wrapper for getting/setting/unsetting/... state/snapshot.

    :param param_dict: additional parameters to overwrite the previous dictionary with
    :type param_dict: {str, str}
    :param str operation: operation description to use when logging

    The rest of the arguments match the public functions.
    """
    l, r = config["graph"].l, config["graph"].r
    selected_vms = sorted(config["vm_strs"].keys())
    LOG_UI.info("Starting %s for %s with job %s and params:\n%s", operation,
                ", ".join(selected_vms), os.path.basename(r.job.logdir),
                param.ParsedDict(config["param_dict"]).reportable_form().rstrip("\n"))
    graph = TestGraph()
    graph.new_workers(l.parse_workers(config["param_dict"]))
    flat_net = l.parse_net_from_object_strs("net1", config["vm_strs"])
    graph.objects = l.parse_components_for_object(flat_net, "nets", params=config["param_dict"], unflatten=True)
    for test_object in graph.objects:
        if test_object.key != "vms":
            continue
        vm = test_object
        # parse individual net only for the current vm
        net = l.parse_object_from_objects("net1", "nets", [vm], params=config["param_dict"])

        setup_dict = config["param_dict"].copy()
        setup_dict.update(param_dict)
        test_node = l.parse_node_from_object(net, "all..internal..manage.unchanged", prefix=tag, params=setup_dict)
        # TODO: traversal relies explicitly on object_suffix which only indicates
        # where a parent node was parsed from, i.e. which test object of the child node
        test_node.params["object_suffix"] = test_object.long_suffix
        graph.nodes += [test_node]

    graph.parse_shared_root_from_object_trees(config["param_dict"])
    graph.flag_children(flag_type="run", flag=lambda self, slot: slot not in self.workers)
    r.run_workers(graph, config["param_dict"])
    LOG_UI.info("Finished %s", operation)


def _reuse_tool_with_param_dict(config, tag, param_dict, tool):
    """
    Reuse a previously defined tool with temporary updated parameter dictionary.

    :param param_dict: additional parameters to overwrite the previous dictionary with
    :type param_dict: {str, str}
    :param tool: tool to reuse
    :type tool: function

    The rest of the arguments match the public functions.
    """
    setup_dict = config["param_dict"].copy()
    config["param_dict"].update(param_dict)
    tool(config, tag=tag)
    config["param_dict"] = setup_dict
