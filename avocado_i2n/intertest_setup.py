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
import logging
import contextlib
import importlib
from collections import namedtuple

from avocado.core import job
from avocado.core import output
from avocado.core import data_dir
from avocado.core import dispatcher
from avocado.core.output import LOG_UI

from . import params_parser as param
from .cartgraph import TestGraph, TestNode
from .loader import CartesianLoader
from .runner import CartesianRunner


#: list of all available manual steps or simply semi-automation tools
__all__ = ["noop", "unittest", "full", "update", "run", "list",
           "install", "deploy", "internal",
           "boot", "download", "upload", "shutdown",
           "check", "pop", "push", "get", "set", "unset", "create", "clean"]


def load_addons_tools():
    """Load all custom manual steps defined in the test suite tools folder."""
    tools_path = os.path.join(param.suite_path, "tools")
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
    with job.Job(config) as job_instance:

        pre_post_dispatcher = dispatcher.JobPrePostDispatcher()
        try:
            # run job pre plugins
            output.log_plugin_failures(pre_post_dispatcher.load_failures)
            pre_post_dispatcher.map_method('pre', job_instance)

            # second initiation stage (as a test runner)
            yield job_instance

        finally:
            # run job post plugins
            pre_post_dispatcher.map_method('post', job_instance)

    result_dispatcher = dispatcher.ResultDispatcher()
    if result_dispatcher.extensions:
        result_dispatcher.map_method('render',
                                     job_instance.result,
                                     job_instance)


def with_cartesian_graph(fn):
    """
    Run a given function with a job-enabled loader-runner hybrid graph.

    :param fn: function to run with a job
    :type fn: function
    :returns: same function with job resource included
    :rtype: function
    """
    def wrapper(config, tag=""):
        with new_job(config) as job:

            loader = CartesianLoader(config, {"logdir": job.logdir})
            runner = CartesianRunner()
            # TODO: need to decide what is more reusable between jobs and graphs
            # e.g. by providing job and result in a direct traversal call
            runner.job = job
            runner.result = job.result
            CartesianGraph = namedtuple('CartesianGraph', 'l r')
            config["graph"] = CartesianGraph(l=loader, r=runner)

            fn(config, tag=tag)

            config["graph"] = None
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

    root_path = param.suite_path
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
def full(config, tag=""):
    """
    Perform all the setup needed to achieve a certain state and save the state.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    The state can be achieved all the way from the test object creation. The
    performed setup depends entirely on the state's dependencies which can
    be completely different than the regular create->install->deploy path.

    Only singleton test setup is supported within the full setup path since
    we cannot guarantee other setup involved vms exist.
    """
    l, r = config["graph"].l, config["graph"].r
    selected_vms = sorted(config["vm_strs"].keys())
    LOG_UI.info("Starting full setup for %s (%s)",
                ", ".join(selected_vms), os.path.basename(r.job.logdir))

    for vm_name in selected_vms:
        vm_params = config["vms_params"].object_params(vm_name)
        logging.info("Creating the full state '%s' of %s", vm_params.get("state", "customize"), vm_name)

        state = vm_params.get("state", "customize")
        state = "0root" if state == "root" else state
        state = "0preinstall" if state == "install" else state

        # in case of permanent vms, support creation and other otherwise dangerous operations
        setup_dict = config["param_dict"].copy()
        setup_dict["create_permanent_vm"] = "yes"
        setup_dict["main_vm"] = vm_name
        # overwrite any existing test objects
        create_graph = l.parse_object_trees(setup_dict, param.re_str("all.." + state),
                                            {vm_name: config["vm_strs"][vm_name]}, prefix=tag)
        create_graph.flag_parent_intersection(create_graph, flag_type="run", flag=False)
        create_graph.flag_parent_intersection(create_graph, flag_type="run", flag=True, skip_shared_root=True)

        # NOTE: this makes sure that any present states are overwritten and no created
        # states are removed, skipping any state restoring for better performance
        setup_dict = config["param_dict"].copy()
        setup_dict.update({"get_mode": "ia", "set_mode": "ff", "unset_mode": "ra"})
        r.run_traversal(create_graph, setup_dict)

    LOG_UI.info("Finished full setup")


@with_cartesian_graph
def update(config, tag=""):
    """
    Update all states (run all tests) from the state defined as
    ``from_state=<state>`` to the state defined as ``to_state=<state>``.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    Thus, a change in a state can be reflected in all the dependent states.

    Only singleton test setup is supported within the update setup path since
    we cannot guarantee other setup involved vms exist.

    .. note:: If you want to update the install state, you also need to change the default
        'from_state=install' to 'from_state=root'. You cannot update the root as this is
        analogical to running the full manual step.
    """
    l, r = config["graph"].l, config["graph"].r
    selected_vms = sorted(config["vm_strs"].keys())
    LOG_UI.info("Starting update setup for %s (%s)",
                ", ".join(selected_vms), os.path.basename(r.job.logdir))

    for vm_name in selected_vms:
        vm_params = config["vms_params"].object_params(vm_name)
        logging.info("Updating state '%s' of %s", vm_params.get("to_state", "customize"), vm_name)

        from_state = vm_params.get("from_state", "install")
        to_state = vm_params.get("to_state", "customize")
        if to_state == "root":
            logging.warning("The root state of %s cannot be updated - use 'setup=full' instead.", vm_name)
            continue

        logging.info("Tracing and removing all old states depending on the updated '%s'...", to_state)
        to_state = "0preinstall" if to_state == "install" else to_state
        setup_dict = config["param_dict"].copy()
        setup_dict["unset_mode"] = "fi"
        setup_str = vm_params.get("remove_set", "leaves")
        for restriction in config["available_restrictions"]:
            if restriction in setup_str:
                break
        else:
            setup_str = "all.." + setup_str
        setup_str = param.re_str(setup_str)
        # remove all test nodes depending on the updated node if present (unset mode is "ignore otherwise")
        remove_graph = l.parse_object_trees(setup_dict,
                                            setup_str,
                                            config["available_vms"],
                                            prefix=tag, verbose=False)
        remove_graph.flag_children(flag_type="run", flag=False)
        remove_graph.flag_children(flag_type="clean", flag=False)
        remove_graph.flag_children(to_state, vm_name, flag_type="clean", flag=True, skip_roots=True)
        r.run_traversal(remove_graph, {"vms": vm_name, **config["param_dict"]})

        logging.info("Updating all states before '%s'", to_state)
        setup_dict = config["param_dict"].copy()
        setup_dict["main_vm"] = vm_name
        update_graph = l.parse_object_trees(setup_dict,
                                            param.re_str("all.." + to_state),
                                            {vm_name: config["vm_strs"][vm_name]}, prefix=tag)
        update_graph.flag_parent_intersection(update_graph, flag_type="run", flag=False)
        update_graph.flag_parent_intersection(update_graph, flag_type="run", flag=True,
                                              skip_object_roots=True, skip_shared_root=True)

        logging.info("Preserving all states before '%s'", from_state)
        from_state = "0preinstall" if from_state == "install" else from_state
        if from_state != "root":
            setup_dict = config["param_dict"].copy()
            setup_dict["main_vm"] = vm_name
            reuse_graph = l.parse_object_trees(setup_dict,
                                               param.re_str("all.." + from_state),
                                               {vm_name: config["vm_strs"][vm_name]},
                                               prefix=tag, verbose=False)
            update_graph.flag_parent_intersection(reuse_graph, flag_type="run", flag=False)

        # NOTE: this makes sure that no new states are created and the updated
        # states are not removed, aborting in any other case
        setup_dict = config["param_dict"].copy()
        setup_dict.update({"get_mode": "ra", "set_mode": "fa", "unset_mode": "ra"})
        setup_dict["vms"] = vm_name
        r.run_traversal(update_graph, setup_dict)

    LOG_UI.info("Finished update setup")


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
    config["run.test_runner"] = "traverser"

    config["sysinfo.collect.enabled"] = config.get("sysinfo.collect.enabled", "on")
    config["run.html.job_result"] = config.get("run.html.job_result", "on")
    config["run.json.job_result"] = config.get("run.json.job_result", "on")
    config["run.xunit.job_result"] = config.get("run.xunit.job_result", "on")
    config["run.tap.job_result"] = config.get("run.tap.job_result", "on")
    config["run.journal.enabled"] = config.get("run.journal.enabled", "on")

    # essentially we imitate the auto plugin to make the tool plugin a superset
    with new_job(config) as job:

        loader = CartesianLoader(config, {"logdir": job.logdir})
        runner = CartesianRunner()
        # TODO: need to decide what is more reusable between jobs and graphs
        # e.g. by providing job and result in a direct traversal call
        runner.job = job
        runner.result = job.result
        CartesianGraph = namedtuple('CartesianGraph', 'l r')
        config["graph"] = CartesianGraph(l=loader, r=runner)

        job.run()

        config["graph"] = None


def list(config, tag=""):
    """
    List a set of tests from the command line.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    This is equivalent to but more powerful than the loader plugin.
    """
    loader = CartesianLoader(config, {"logdir": data_dir.get_base_dir()})
    prefix = tag + "l" if len(re.findall("run", config["vms_params"]["setup"])) > 1 else ""
    graph = loader.parse_object_trees(config["param_dict"], config["tests_str"], config["vm_strs"],
                                      prefix=prefix, verbose=True)
    graph.visualize(data_dir.get_base_dir())


############################################################
# VM creation manual user steps
############################################################


@with_cartesian_graph
def install(config, tag=""):
    """
    Configure installation of each virtual machine and install it,
    taking the respective 'install' snapshot.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    l, r = config["graph"].l, config["graph"].r
    selected_vms = sorted(config["vm_strs"].keys())
    LOG_UI.info("Installing %s (%s)",
                ", ".join(selected_vms), os.path.basename(r.job.logdir))
    graph = TestGraph()
    graph.objects = l.parse_objects(config["param_dict"], config["vm_strs"])
    for vm in graph.objects:
        graph.nodes.append(l.parse_install_node(vm, config["param_dict"], prefix=tag))
        r.run_install_node(graph, vm.name, config["param_dict"])
    LOG_UI.info("Finished installation")


@with_cartesian_graph
def deploy(config, tag=""):
    """
    Deploy customized data and utilities to the guest vms,
    to one or to more of their states, either temporary (``stateless=no``)
    or taking a respective 'customize' snapshot.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    l, r = config["graph"].l, config["graph"].r
    selected_vms = sorted(config["vm_strs"].keys())
    LOG_UI.info("Deploying data to %s (%s)",
                ", ".join(selected_vms), os.path.basename(r.job.logdir))
    for vm in l.parse_objects(config["param_dict"], config["vm_strs"]):

        states = vm.params.objects("states")
        if len(states) == 0:
            states = ["current_state"]
            stateless = vm.params.get("stateless", "yes") == "yes"
        else:
            stateless = False

        for i, state in enumerate(states):
            setup_dict = config["param_dict"].copy()
            if state != "current_state":
                setup_dict.update({"get_state": state, "set_state": state,
                                   "get_type": "any", "set_type": "any"})
            setup_dict.update({"skip_image_processing": "yes", "kill_vm": "no",
                               "redeploy_only": config["vms_params"].get("redeploy_only", "yes")})
            if stateless:
                setup_dict["get_state"] = ""
                setup_dict["set_state"] = ""
            setup_tag = "%s%s" % (tag, i+1 if i > 0 else "")
            setup_str = param.re_str("all..internal..customize")
            test_node = l.parse_node_from_object(vm, setup_dict, setup_str, prefix=setup_tag)
            r.run_test_node(test_node)

    LOG_UI.info("Finished data deployment")


@with_cartesian_graph
def internal(config, tag=""):
    """
    Run an internal test node, thus performing a particular automated
    setup on the desired vms.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    l, r = config["graph"].l, config["graph"].r
    selected_vms = sorted(config["vm_strs"].keys())
    LOG_UI.info("Performing internal setup on %s (%s)",
                ", ".join(selected_vms), os.path.basename(r.job.logdir))
    for vm in l.parse_objects(config["param_dict"], config["vm_strs"]):
        setup_dict = config["param_dict"].copy()
        if vm.params.get("stateless", "yes") == "yes":
            setup_dict.update({"get_state": "", "set_state": "",
                               "skip_image_processing": "yes", "kill_vm": "no"})
        setup_str = param.re_str("all..internal.." + vm.params["node"])
        test_node = l.parse_node_from_object(vm, setup_dict, setup_str, prefix=tag)
        r.run_test_node(test_node)
    LOG_UI.info("Finished internal setup")


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
    op_type = "set_type"
    op_state = "set_state"

    l, r = config["graph"].l, config["graph"].r
    setup_dict = config["param_dict"].copy()
    for vm in l.parse_objects(config["param_dict"], config["vm_strs"]):
        vm_op_type = op_type + "_" + vm.name
        state_type = vm_op_type if vm_op_type in setup_dict else op_type
        if state_type not in setup_dict:
            vm_op_state = op_state + "_" + vm.name
            state_name = setup_dict.get(vm_op_state, setup_dict.get(op_state))
            if state_name == "root":
                node = l.parse_create_node(vm, config["param_dict"], prefix=tag)
                setup_dict[vm_op_type] = node.params["set_type"]
            elif state_name == "install":
                node = l.parse_install_node(vm, config["param_dict"], prefix=tag)
                setup_dict[vm_op_type] = node.params["set_type"]
            else:
                pass  # will use default set type
    setup_dict.update({"vm_action": operation, "skip_image_processing": "yes"})

    _parse_all_objects_then_iterate_for_nodes(config, tag,
                                              setup_dict, "state " + operation)


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
    op_type = "unset_type"
    op_state = "unset_state"

    l, r = config["graph"].l, config["graph"].r
    setup_dict = config["param_dict"].copy()
    for vm in l.parse_objects(config["param_dict"], config["vm_strs"]):

        # since the default unset_mode is passive (ri) we need a better
        # default value for that case but still modifiable by the user
        vm_op_mode = op_mode + "_" + vm.name
        state_mode = vm_op_mode if vm_op_mode in setup_dict else op_mode
        if state_mode not in setup_dict:
            setup_dict[vm_op_mode] = "fi"

        vm_op_type = op_type + "_" + vm.name
        state_type = vm_op_type if vm_op_type in setup_dict else op_type
        if state_type not in setup_dict:
            vm_op_state = op_state + "_" + vm.name
            state_name = setup_dict.get(vm_op_state, setup_dict.get(op_state))
            if state_name == "root":
                node = l.parse_create_node(vm, config["param_dict"], prefix=tag)
                setup_dict[vm_op_type] = node.params["set_type"]
            elif state_name == "install":
                node = l.parse_install_node(vm, config["param_dict"], prefix=tag)
                setup_dict[vm_op_type] = node.params["set_type"]
            else:
                pass  # will use default unset type

    setup_dict.update({"vm_action": operation, "skip_image_processing": "yes"})

    _parse_all_objects_then_iterate_for_nodes(config, tag,
                                              setup_dict, "state " + operation)


def create(config, tag=""):
    """
    Create a new test object (vm, root state).

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    _reuse_tool_with_param_dict(config, tag,
                                {"set_state": "root",
                                 "set_mode": "af"},
                                set)


def clean(config, tag=""):
    """
    Remove a test object (vm, root state).

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    _reuse_tool_with_param_dict(config, tag,
                                {"unset_state": "root",
                                 "unset_mode": "fa"},
                                unset)


############################################################
# Private templates reused by all tools above
############################################################


def _parse_one_node_for_all_objects(config, tag, verb):
    """
    Wrapper for setting state/snapshot, same as :py:func:`set`.

    :param verb: verb forms in a tuple (gerund form, variant, test name, present)
    :type verb: (str, str, str, str)
    :param str tag: extra name identifier for the test to be run
    """
    l, r = config["graph"].l, config["graph"].r
    selected_vms = sorted(config["vm_strs"].keys())
    LOG_UI.info("%s virtual machines %s (%s)", verb[0],
                ", ".join(selected_vms), os.path.basename(r.job.logdir))
    vms = " ".join(selected_vms)
    setup_dict = config["param_dict"].copy()
    setup_dict.update({"vms": vms, "main_vm": selected_vms[0]})
    setup_str = param.re_str("all..internal..manage.%s" % verb[1])
    tests, vms = l.parse_object_nodes(setup_dict, setup_str, config["vm_strs"], prefix=tag)
    assert len(tests) == 1, "There must be exactly one %s test variant from %s" % (verb[2], tests)
    r.run_test_node(TestNode(tag, tests[0].config, vms))
    LOG_UI.info("%s complete", verb[3])


def _parse_all_objects_then_iterate_for_nodes(config, tag, param_dict, operation):
    """
    Wrapper for setting state/snapshot, same as :py:func:`set`.

    :param param_dict: additional parameters to overwrite the previous dictionary with
    :type param_dict: {str, str}
    :param str operation: operation description to use when logging
    :param str tag: extra name identifier for the test to be run
    """
    l, r = config["graph"].l, config["graph"].r
    selected_vms = sorted(config["vm_strs"].keys())
    LOG_UI.info("Starting %s for %s with job %s and params:\n%s", operation,
                ", ".join(selected_vms), os.path.basename(r.job.logdir),
                param.ParsedDict(config["param_dict"]).reportable_form().rstrip("\n"))
    for vm in l.parse_objects(config["param_dict"], config["vm_strs"]):
        setup_dict = config["param_dict"].copy()
        setup_dict.update(param_dict)
        setup_str = param.re_str("all..internal..manage.unchanged")
        test_node = l.parse_node_from_object(vm, setup_dict, setup_str, prefix=tag)
        r.run_test_node(test_node)
    LOG_UI.info("Finished %s", operation)


def _reuse_tool_with_param_dict(config, tag, param_dict, tool):
    """
    Reuse a previously defined tool with temporary updated parameter dictionary.

    :param param_dict: additional parameters to overwrite the previous dictionary with
    :type param_dict: {str, str}
    :param tool: tool to reuse
    :type tool: function
    """
    setup_dict = config["param_dict"].copy()
    config["param_dict"].update(param_dict)
    tool(config, tag=tag)
    config["param_dict"] = setup_dict
