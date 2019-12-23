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
from avocado.core.settings import settings

from . import params_parser as param
from .cartgraph import TestGraph, TestNode
from .loader import CartesianLoader
from .runner import CartesianRunner


#: list of all available manual steps or simply semi-automation tools
__all__ = ["noop", "unittest", "full", "update", "run", "list",
           "develop", "install", "deploy", "internal",
           "boot", "download", "upload", "shutdown",
           "check", "pop", "push", "get", "set", "unset", "create", "clean"]
root_path = settings.get_value('i2n.common', 'suite_path', default=None)
tools_path = os.path.join(root_path, "tools")
sys.path.append(tools_path)
for tool in os.listdir(tools_path):
    if tool.endswith(".py") and not tool.endswith("_unittest.py"):
        module_name = tool.replace(".py", "")
        logging.debug("Loading tools in %s", module_name)
        module = importlib.import_module(module_name)

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
    def wrapper(config, run_params, tag=""):
        with new_job(config) as job:

            loader = CartesianLoader(config, {"logdir": job.logdir})
            runner = CartesianRunner()
            # TODO: need to decide what is more reusable between jobs and graphs
            # e.g. by providing job and result in a direct traversal call
            runner.job = job
            runner.result = job.result
            CartesianGraph = namedtuple('CartesianGraph', 'l r')
            config["graph"] = CartesianGraph(l=loader, r=runner)

            fn(config, run_params, tag=tag)

            config["graph"] = None
    return wrapper


############################################################
# Main manual user steps
############################################################


def noop(config, run_params, tag=""):
    """
    Empty setup step to invoke plugin without performing anything.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    pass


def unittest(config, run_params, tag=""):
    """
    Perform self testing for sanity and test result validation.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    import unittest
    util_unittests = unittest.TestSuite()
    util_testrunner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2)

    subtests_filter = run_params.get("ut_filter", "*_unittest.py")

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
def full(config, run_params, tag=""):
    """
    Perform all the setup needed to achieve a certain state and save the state.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    The state can be achieved all the way from the test object creation. The
    performed setup depends entirely on the state's dependencies which can
    be completely different than the regular create->install->deploy path.
    """
    l, r = config["graph"].l, config["graph"].r
    clean(config, run_params, tag=tag + "mm")
    for vm_name in run_params.objects("vms"):
        vm_params = run_params.object_params(vm_name)
        logging.info("Creating the full state '%s' of %s", vm_params.get("state", "customize"), vm_name)
        if vm_params.get("state", "customize") == "root":
            vm_params["vms"] = vm_name
            create(config, vm_params, tag=tag)
            continue

        # overwrite any existing test objects
        vm_params["force_create"] = "yes"
        create_graph = l.parse_object_trees(config["param_str"], param.re_str("nonleaves.." + vm_params.get("state", "customize")),
                                            {vm_name: config["vm_strs"][vm_name]},
                                            prefix=tag, object_names=vm_name, objectless=True)
        create_graph.flag_parent_intersection(create_graph, flag_type="run", flag=False)
        create_graph.flag_parent_intersection(create_graph, flag_type="run", flag=True, skip_shared_root=True)

        # NOTE: this makes sure that any present states are overwritten and no created
        # states are removed, skipping any state restoring for better performance
        setup_str = config["param_str"] + param.ParsedDict({"force_create": "yes", "get_mode": "ia",
                                                          "set_mode": "ff", "unset_mode": "ra"}).parsable_form()
        r.run_traversal(create_graph, setup_str)


@with_cartesian_graph
def update(config, run_params, tag=""):
    """
    Update all states (run all tests) from the state defined as
    ``from_state=<state>`` to the state defined as ``to_state=<state>``.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    Thus, a change in a state can be reflected in all the dependent states.

    .. note:: If you want to update the install state, you also need to change the default
        'from_state=install' to 'from_state=root'. You cannot update the root as this is
        analogical to running the full manual step.
    """
    l, r = config["graph"].l, config["graph"].r
    for vm_name in run_params.objects("vms"):
        vm_params = run_params.object_params(vm_name)
        logging.info("Updating state '%s' of %s", vm_params.get("to_state", "customize"), vm_name)

        if vm_params.get("to_state", "customize") == "root":
            logging.warning("The root state of %s cannot be updated - use 'setup=full' instead.", vm_name)
            continue

        logging.info("Tracing and removing all old states depending on the updated '%s'...",
                     vm_params.get("to_state", "customize"))
        # remove all test nodes depending on the updated node if present (unset mode is "ignore otherwise")
        remove_graph = l.parse_object_trees(config["param_str"] + param.ParsedDict({"unset_mode": "fi"}).parsable_form(),
                                            param.re_str(vm_params.get("remove_set", "all")), config["vm_strs"],
                                            prefix=tag, object_names=vm_name, objectless=False, verbose=False)
        remove_graph.flag_children(flag_type="run", flag=False)
        remove_graph.flag_children(flag_type="clean", flag=False)
        remove_graph.flag_children(vm_params.get("to_state", "customize"), vm_name,
                                   flag_type="clean", flag=True, skip_roots=True)
        r.run_traversal(remove_graph, config["param_str"])

        logging.info("Updating all states before '%s'", vm_params.get("to_state", "customize"))
        update_graph = l.parse_object_trees(config["param_str"], param.re_str("nonleaves.." + vm_params.get("to_state", "customize")),
                                            {vm_name: config["vm_strs"][vm_name]}, prefix=tag,
                                            object_names=vm_name, objectless=True)
        update_graph.flag_parent_intersection(update_graph, flag_type="run", flag=False)
        update_graph.flag_parent_intersection(update_graph, flag_type="run", flag=True,
                                              skip_object_roots=True, skip_shared_root=True)

        logging.info("Preserving all states before '%s'", vm_params.get("from_state", "customize"))
        if vm_params.get("from_state", "install") != "root":
            reuse_graph = l.parse_object_trees(config["param_str"], param.re_str("nonleaves.." + vm_params.get("from_state", "install")),
                                               {vm_name: config["vm_strs"][vm_name]}, prefix=tag,
                                               object_names=vm_name, objectless=True, verbose=False)
            update_graph.flag_parent_intersection(reuse_graph, flag_type="run", flag=False)

        # NOTE: this makes sure that no new states are created and the updated
        # states are not removed, aborting in any other case
        setup_str = config["param_str"] + param.ParsedDict({"get_mode": "ra", "set_mode": "fa", "unset_mode": "ra"}).parsable_form()
        r.run_traversal(update_graph, setup_str)


def run(config, run_params, tag=""):
    """
    Run a set of tests without any automated setup.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    This is equivalent to but more powerful than the runner plugin.
    """
    # NOTE: each run expects already incremented count in the beginning but this prefix
    # is preferential to setup chains with a single "run" step since this is usually the case
    config["prefix"] = tag + "n" if len(re.findall("run", run_params["setup"])) > 1 else ""
    config["test_runner"] = "traverser"

    config["sysinfo"] = config.get("sysinfo", "on")
    config["html_job_result"] = config.get("html_job_result", "on")
    config["json_job_result"] = config.get("json_job_result", "on")
    config["xunit_job_result"] = config.get("xunit_job_result", "on")
    config["tap_job_result"] = config.get("tap_job_result", "on")

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


def list(config, run_params, tag=""):
    """
    List a set of tests from the command line.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    This is equivalent to but more powerful than the loader plugin.
    """
    loader = CartesianLoader(config, {"logdir": data_dir.get_base_dir()})
    prefix = tag + "l" if len(re.findall("run", run_params["setup"])) > 1 else ""
    graph = loader.parse_object_trees(config["param_str"], config["tests_str"], config["vm_strs"], prefix=prefix)
    graph.visualize(data_dir.get_base_dir())


############################################################
# Custom manual user steps
############################################################


@with_cartesian_graph
def develop(config, run_params, tag=""):
    """
    Run manual tests specialized at development speedup.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    Current modes that can be supplied from the command line
    can be found in the "develop" test set.

    As with all manual tests, providing setup and making sure
    that all the vms exist is a user's responsibility.
    """
    vms = run_params["vms"]
    mode = run_params.get("devmode", "generator")
    setup_dict = {"vms": vms, "main_vm": run_params.objects("vms")[0]}
    setup_str = param.re_str("nonleaves..develop.%s" % mode) + param.ParsedDict(setup_dict).parsable_form() + config["param_str"]
    tests, _ = config["graph"].l.parse_object_nodes(setup_str, config["vm_strs"], prefix=tag, object_names=vms)
    assert len(tests) == 1, "There must be exactly one develop test variant from %s" % tests
    logging.info("Developing on virtual machines %s", vms)
    config["graph"].r.run_test_node(TestNode(tag, tests[0].config, []))


############################################################
# VM creation manual user steps
############################################################


@with_cartesian_graph
def install(config, run_params, tag=""):
    """
    Configure installation of each virtual machine and install it,
    taking the respective 'install' snapshot.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    graph = TestGraph()
    graph.nodes, graph.objects = config["graph"].l.parse_object_nodes(param.re_str("nonleaves..install"),
                                                                      config["vm_strs"],
                                                                      prefix=tag, object_names=run_params.get("vms", ""),
                                                                      objectless=True)
    for vm_name in sorted(graph.test_objects.keys()):
        config["graph"].r.run_install_node(graph, vm_name, config["param_str"])


@with_cartesian_graph
def deploy(config, run_params, tag=""):
    """
    Deploy customized data and utilities to the guest vms,
    to one or to more of their states, either temporary (``stateless=no``)
    or taking a respective 'customize' snapshot.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    vms = config["graph"].l.parse_objects(config["vm_strs"], run_params.get("vms", ""))
    for vm in vms:

        states = vm.params.objects("states")
        if len(states) == 0:
            states = ["current_state"]
            stateless = vm.params.get("stateless", "yes") == "yes"
        else:
            stateless = False

        for i, state in enumerate(states):
            setup_str = config["param_str"]
            if state != "current_state":
                setup_str += param.ParsedDict({"get_state": state, "set_state": state,
                                               "get_type": "any", "set_type": "any"}).parsable_form()
            ovrwrt_dict = {"skip_image_processing": "yes", "kill_vm": "no",
                           "redeploy_only": run_params.get("redeploy_only", "yes")}
            if stateless:
                ovrwrt_dict["get_state"] = ""
                ovrwrt_dict["set_state"] = ""
            setup_tag = "%s%s" % (tag, i+1 if i > 0 else "")
            ovrwrt_str = param.re_str("nonleaves..customize", setup_str)
            reparsable = vm.config.get_copy()
            reparsable.parse_next_batch(base_file="sets.cfg",
                                        ovrwrt_file=param.tests_ovrwrt_file,
                                        ovrwrt_str=ovrwrt_str,
                                        ovrwrt_dict=ovrwrt_dict)
            config["graph"].r.run_test_node(TestNode(setup_tag, reparsable, []))


@with_cartesian_graph
def internal(config, run_params, tag=""):
    """
    Run an internal test node, thus performing a particular automated
    setup on the desired vms.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    vms = config["graph"].l.parse_objects(config["vm_strs"], run_params.get("vms", ""))
    for vm in vms:
        if vm.params.get("stateless", "yes") == "yes":
            ovrwrt_dict = {"get_state": "", "set_state": "",
                           "skip_image_processing": "yes", "kill_vm": "no"}
        else:
            ovrwrt_dict = {}
        forced_setup = "nonleaves.." + vm.params["node"]
        ovrwrt_str = param.re_str(forced_setup, config["param_str"])
        reparsable = vm.config.get_copy()
        reparsable.parse_next_batch(base_file="sets.cfg",
                                    ovrwrt_file=param.tests_ovrwrt_file,
                                    ovrwrt_str=ovrwrt_str,
                                    ovrwrt_dict=ovrwrt_dict)
        config["graph"].r.run_test_node(TestNode(tag, reparsable, []))


############################################################
# VM management manual user steps
############################################################


@with_cartesian_graph
def boot(config, run_params, tag=""):
    """
    Boot all given vms.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    The boot test always takes care of any other vms so we can do it all in one test
    which is a bit of a hack but is much faster than the standard per-vm handling.
    """
    vms = run_params["vms"]
    setup_dict = {"vms": vms, "main_vm": run_params.objects("vms")[0]}
    setup_str = param.re_str("nonleaves..manage.start") + param.ParsedDict(setup_dict).parsable_form() + config["param_str"]
    tests, _ = config["graph"].l.parse_object_nodes(setup_str, config["vm_strs"], prefix=tag, object_names=vms)
    assert len(tests) == 1, "There must be exactly one boot test variant from %s" % tests
    logging.info("Booting virtual machines %s", vms)
    config["graph"].r.run_test_node(TestNode(tag, tests[0].config, []))


@with_cartesian_graph
def download(config, run_params, tag=""):
    """
    Download a set of files from the given vms.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    The set of files is specified using a "files" parameter.

    The download test always takes care of any other vms so we can do it all in one test
    which is a bit of a hack but is much faster than the standard per-vm handling.
    """
    vms = run_params["vms"]
    setup_dict = {"vms": vms, "main_vm": run_params.objects("vms")[0]}
    setup_str = param.re_str("nonleaves..manage.download") + param.ParsedDict(setup_dict).parsable_form() + config["param_str"]
    tests, _ = config["graph"].l.parse_object_nodes(setup_str, config["vm_strs"], prefix=tag, object_names=vms)
    assert len(tests) == 1, "There must be exactly one download test variant from %s" % tests
    logging.info("Downloading from virtual machines %s", vms)
    config["graph"].r.run_test_node(TestNode(tag, tests[0].config, []))


@with_cartesian_graph
def upload(config, run_params, tag=""):
    """
    Upload a set of files to the given vms.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    The set of files is specified using a `files` parameter.

    The upload test always takes care of any other vms so we can do it all in one test
    which is a bit of a hack but is much faster than the standard per-vm handling.
    """
    vms = run_params["vms"]
    setup_dict = {"vms": vms, "main_vm": run_params.objects("vms")[0]}
    setup_str = param.re_str("nonleaves..manage.upload") + param.ParsedDict(setup_dict).parsable_form() + config["param_str"]
    tests, _ = config["graph"].l.parse_object_nodes(setup_str, config["vm_strs"], prefix=tag, object_names=vms)
    assert len(tests) == 1, "There must be exactly one upload test variant from %s" % tests
    logging.info("Uploading to virtual machines %s", vms)
    config["graph"].r.run_test_node(TestNode(tag, tests[0].config, []))


@with_cartesian_graph
def shutdown(config, run_params, tag=""):
    """
    Shutdown gracefully or kill living vms.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    The shutdown test always takes care of any other vms so we can do it all in one test
    which is a bit of a hack but is much faster than the standard per-vm handling.
    """
    vms = run_params["vms"]
    setup_dict = {"vms": vms, "main_vm": run_params.objects("vms")[0]}
    setup_str = param.re_str("nonleaves..manage.stop") + param.ParsedDict(setup_dict).parsable_form() + config["param_str"]
    tests, _ = config["graph"].l.parse_object_nodes(setup_str, config["vm_strs"], prefix=tag, object_names=vms)
    assert len(tests) == 1, "There must be exactly one shutdown test variant from %s" % tests
    logging.info("Shutting down virtual machines %s", vms)
    config["graph"].r.run_test_node(TestNode(tag, tests[0].config, []))


############################################################
# State manipulation manual user steps
############################################################


@with_cartesian_graph
def check(config, run_params, tag=""):
    """
    Check whether a given state (setup snapshot) exists.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    setup_str = config["param_str"]
    setup_str += param.re_str("nonleaves..manage.unchanged")
    setup_str += param.ParsedDict({"vm_action": "check",
                                   "skip_image_processing": "yes"}).parsable_form()
    tests, _ = config["graph"].l.parse_object_nodes(setup_str, config["vm_strs"],
                                               object_names=run_params["vms"],
                                               objectless=True, prefix=tag)
    for test in tests:
        config["graph"].r.run_test_node(TestNode(tag, test.config, []))


@with_cartesian_graph
def pop(config, run_params, tag=""):
    """
    Get to a state/snapshot disregarding the current changes
    loosing the it afterwards.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    setup_str = config["param_str"]
    setup_str += param.re_str("nonleaves..manage.unchanged")
    setup_str += param.ParsedDict({"vm_action": "pop",
                                   "skip_image_processing": "yes"}).parsable_form()
    tests, _ = config["graph"].l.parse_object_nodes(setup_str, config["vm_strs"],
                                               object_names=run_params["vms"],
                                               objectless=True, prefix=tag)
    for test in tests:
        config["graph"].r.run_test_node(TestNode(tag, test.config, []))


@with_cartesian_graph
def push(config, run_params, tag=""):
    """
    Wrapper for setting state/snapshot, same as :py:func:`set`.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    setup_str = config["param_str"]
    setup_str += param.re_str("nonleaves..manage.unchanged")
    setup_str += param.ParsedDict({"vm_action": "push",
                                   "skip_image_processing": "yes"}).parsable_form()
    tests, _ = config["graph"].l.parse_object_nodes(setup_str, config["vm_strs"],
                                               object_names=run_params["vms"],
                                               objectless=True, prefix=tag)
    for test in tests:
        config["graph"].r.run_test_node(TestNode(tag, test.config, []))


@with_cartesian_graph
def get(config, run_params, tag=""):
    """
    Get to a state/snapshot disregarding the current changes.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    This method could be implemented in identical way to the push/pop
    methods but we use different approach for illustration.
    """
    for vm_name in run_params.objects("vms"):
        test_object = config["graph"].l.parse_objects(config["vm_strs"], vm_name)
        reparsable = test_object[0].config.get_copy()
        reparsable.parse_next_batch(base_file="sets.cfg",
                                    ovrwrt_file=param.tests_ovrwrt_file,
                                    ovrwrt_str=param.re_str("nonleaves..manage.unchanged",
                                                            config["param_str"]),
                                    ovrwrt_dict={"vm_action": "get",
                                                 "skip_image_processing": "yes"})
        config["graph"].r.run_test_node(TestNode(tag, reparsable, []))


@with_cartesian_graph
def set(config, run_params, tag=""):
    """
    Create a new state/snapshot from the current state/snapshot.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    This method could be implemented in identical way to the push/pop
    methods but we use different approach for illustration.
    """
    for vm_name in run_params.objects("vms"):
        test_object = config["graph"].l.parse_objects(config["vm_strs"], vm_name)
        reparsable = test_object[0].config.get_copy()
        reparsable.parse_next_batch(base_file="sets.cfg",
                                    ovrwrt_file=param.tests_ovrwrt_file,
                                    ovrwrt_str=param.re_str("nonleaves..manage.unchanged",
                                                            config["param_str"]),
                                    ovrwrt_dict={"vm_action": "set",
                                                 "skip_image_processing": "yes"})
        config["graph"].r.run_test_node(TestNode(tag, reparsable, []))


@with_cartesian_graph
def unset(config, run_params, tag=""):
    """
    Remove a state/snapshot.

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    This method could be implemented in identical way to the push/pop
    methods but we use different approach for illustration.
    """
    # since the default unset_mode is passive (ri) we need a better
    # default value for that case but still modifiable by the user
    if "unset_mode" not in config["param_str"]:
        setup_str = config["param_str"] + param.ParsedDict({"unset_mode": "fi"}).parsable_form()
    else:
        setup_str = config["param_str"]
    for vm_name in run_params.objects("vms"):
        test_object = config["graph"].l.parse_objects(config["vm_strs"], vm_name)
        reparsable = test_object[0].config.get_copy()
        reparsable.parse_next_batch(base_file="sets.cfg",
                                    ovrwrt_file=param.tests_ovrwrt_file,
                                    ovrwrt_str=param.re_str("nonleaves..manage.unchanged",
                                                            setup_str),
                                    ovrwrt_dict={"vm_action": "unset",
                                                 "skip_image_processing": "yes"})
        config["graph"].r.run_test_node(TestNode(tag, reparsable, []))


def create(config, run_params, tag=""):
    """
    Create a new test object (vm, root state).

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    setup_str = config["param_str"]
    config["param_str"] += param.ParsedDict({"set_state": "root", "set_mode": "af", "set_type": "off"}).parsable_form()
    set(config, run_params, tag=tag)
    config["param_str"] = setup_str


def clean(config, run_params, tag=""):
    """
    Remove a test object (vm, root state).

    :param config: command line arguments
    :type config: {str, str}
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    setup_str = config["param_str"]
    config["param_str"] += param.ParsedDict({"unset_state": "root", "unset_mode": "fi", "unset_type": "off"}).parsable_form()
    unset(config, run_params, tag=tag)
    config["param_str"] = setup_str
