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
from collections import namedtuple

from avocado.core import job
from avocado.core import output
from avocado.core import data_dir
from avocado.core import dispatcher
from avocado.core.settings import settings
from avocado.utils import process

from . import params_parser as param
from .cartesian_graph import TestGraph, TestNode
from .loader import CartesianLoader
from .runner import CartesianRunner


@contextlib.contextmanager
def new_job(args):
    """
    Produce a new job object and thus a job.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    """
    with job.Job(args) as job_instance:

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
    def wrapper(args, run_params, tag=""):
        with new_job(args) as job:

            loader = CartesianLoader(args, {"logdir": job.logdir})
            runner = CartesianRunner(job, job.result)
            CartesianGraph = namedtuple('CartesianGraph', 'l r')
            args.graph = CartesianGraph(l=loader, r=runner)

            fn(args, run_params, tag=tag)

            args.graph = None
    return wrapper


############################################################
# Main manual user steps
############################################################


def noop(args, run_params, tag=""):
    """
    Empty setup step to invoke plugin without performing anything.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    pass


def unittest(args, run_params, tag=""):
    """
    Perform self testing for sanity and test result validation.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    import unittest
    util_unittests = unittest.TestSuite()
    util_testrunner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2)

    root_path = settings.get_value('i2n.common', 'suite_path', default=None)

    subtests_filter = run_params.get("ut_filter", "*_unittest.py")
    subtests_path = os.path.join(root_path, "utils")
    subtests_suite = unittest.defaultTestLoader.discover(subtests_path,
                                                         pattern=subtests_filter,
                                                         top_level_dir=subtests_path)
    util_unittests.addTest(subtests_suite)

    util_testrunner.run(util_unittests)


def full(args, run_params, tag=""):
    """
    Crude method to fully setup a vm. Compared with the newer Cartesian
    based method, this is not faster but could be safer in case of already
    running vms and combinations with other manual steps.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    clean(args, run_params, tag=tag + "mm")
    create(args, run_params, tag=tag + "m")
    install(args, run_params, tag=tag)
    run_params["redeploy_only"] = "no"
    deploy(args, run_params, tag=tag)
    setup_str = args.param_str
    args.param_str += param.dict_to_str({"set_state": "customize_vm", "set_type": "offline"})
    set(args, run_params, tag=tag)
    args.param_str = setup_str


def update(args, run_params, tag=""):
    """
    Crude method to clean up LVM volumes of the virtual machines.
    The VMs will be reverted back to the "install" state and all
    test files will be redeployed afterwards.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    :raises: :py:class:`exceptions.ValueError` if vm is unknown

    If the `dry_run` parameter is set to "yes", this will not actually
    remove, but just show affected volumes.

    .. note:: The code for this step was taken from an external python script
        and could be replaced later on if the newer update step becomes faster.
    """
    lvscan_bin = '/usr/sbin/lvscan'
    lvremove_bin = '/usr/sbin/lvremove'

    vms = {}

    vm_whitelist = ['vm1', 'vm2', 'vm3', 'vm4', 'vm5']
    whitelist = ['thin_pool', 'LogVol', 'install', 'current_state']

    def parse_active_vms():
        lvscan_output = process.run(lvscan_bin).stdout_text
        for line in lvscan_output.split('\n'):
            prefix = os.environ['PREFIX'] if 'PREFIX' in os.environ else 'at'
            match = re.match(" +ACTIVE +'(/dev/%s_(vm\d+)_ramdisk/(.*))' +" % prefix, line)
            if match is None:
                continue

            fullpath = match.group(1)
            vm = match.group(2)
            volname = match.group(3)

            if vm not in vm_whitelist:
                logging.info("Ignoring volume %s from %s", volname, vm)
                continue

            logging.info('Found volume %s from %s', volname, vm)

            if vm not in vms:
                vms[vm] = [(volname, fullpath)]
            else:
                vms[vm].append((volname, fullpath))

    def clean_volumes(dry_run):
        for vm in vms:
            for volume, fullpath in vms[vm]:
                if volume in whitelist:
                    continue

                if dry_run:
                    logging.info('Would remove volume %s from %s', volume, vm)
                    continue

                logging.info('Removing volume %s from %s', volume, vm)
                try:
                    output = process.run("%s --force %s" % (lvremove_bin, fullpath)).stdout_text
                except Exception as e:
                    output = str(e)
                for line in output.split('\n'):
                    logging.info(line)

    new_whitelist = run_params.objects("vms")
    for vmname in new_whitelist:
        if vmname not in vm_whitelist:
            raise ValueError('Unknown VM "{0}". Aborting'.format(vmname))

    vm_whitelist = new_whitelist
    logging.info('Working on VM %s only', ','.join(vm_whitelist))

    parse_active_vms()
    dry_run = True if run_params.get("dry_run", "no") == "yes" else False
    clean_volumes(dry_run)

    # now redeploy data
    setup_str = args.param_str
    args.param_str = setup_str + param.dict_to_str({"get_state": "install", "get_type": "offline"})
    get(args, run_params, tag=tag + "m")
    run_params["redeploy_only"] = "no"
    deploy(args, run_params, tag=tag)
    args.param_str = setup_str + param.dict_to_str({"set_state": "customize_vm", "set_type": "offline"})
    set(args, run_params, tag=tag)
    args.param_str = setup_str


@with_cartesian_graph
def graphfull(args, run_params, tag=""):
    """
    Perform all the setup needed to achieve a certain state and save the state.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    The state can be achieved all the way from the test object creation. The
    performed setup depends entirely on the state's dependencies which can
    be completely different than the regular create->install->deploy path.
    """
    l, r = args.graph.l, args.graph.r
    clean(args, run_params, tag=tag + "mm")
    for vm_name in run_params.objects("vms"):
        vm_params = run_params.object_params(vm_name)
        logging.info("Creating the full state '%s' of %s", vm_params.get("state", "customize_vm"), vm_name)
        if vm_params.get("state", "customize_vm") == "root":
            vm_params["vms"] = vm_name
            create(args, vm_params, tag=tag)
            continue

        # overwrite any existing test objects
        vm_params["force_create"] = "yes"
        create_graph = l.parse_object_trees(args.param_str, param.re_str(vm_params.get("state", "customize_vm")),
                                            {vm_name: args.vm_strs[vm_name]},
                                            prefix=tag, object_names=vm_name, objectless=True)
        create_graph.flag_parent_intersection(create_graph, flag_type="run", flag=False)
        create_graph.flag_parent_intersection(create_graph, flag_type="run", flag=True, skip_shared_root=True)

        # NOTE: this makes sure that any present states are overwritten and no created
        # states are removed, skipping any state restoring for better performance
        setup_str = args.param_str + param.dict_to_str({"force_create": "yes", "get_mode": "ia",
                                                        "set_mode": "ff", "unset_mode": "ra"})
        r.run_traversal(create_graph, setup_str)


@with_cartesian_graph
def graphupdate(args, run_params, tag=""):
    """
    Update all states (run all tests) from the state defined as
    ``from_state=<state>`` to the state defined as ``to_state=<state>``.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    Thus, a change in a state can be reflected in all the dependent states.

    .. note:: If you want to update the install state, you also need to change the default
        'from_state=install' to 'from_state=root'. You cannot update the root as this is
        analogical to running the full manual step.
    """
    l, r = args.graph.l, args.graph.r
    for vm_name in run_params.objects("vms"):
        vm_params = run_params.object_params(vm_name)
        logging.info("Updating state '%s' of %s", vm_params.get("to_state", "customize_vm"), vm_name)

        if vm_params.get("to_state", "customize_vm") == "root":
            logging.warning("The root state of %s cannot be updated - use 'setup=full' instead.", vm_name)
            continue

        logging.info("Tracing and removing all old states depending on the updated '%s'...",
                     vm_params.get("to_state", "customize_vm"))
        # remove all test nodes depending on the updated node if present (unset mode is "ignore otherwise")
        remove_graph = l.parse_object_trees(args.param_str + param.dict_to_str({"unset_mode": "fi"}),
                                            param.re_str(vm_params.get("remove_set", "all")), args.vm_strs,
                                            prefix=tag, object_names=vm_name, objectless=False, verbose=False)
        remove_graph.flag_children(flag_type="run", flag=False)
        remove_graph.flag_children(flag_type="clean", flag=False)
        remove_graph.flag_children(vm_params.get("to_state", "customize_vm"), vm_name,
                                   flag_type="clean", flag=True, skip_roots=True)
        r.run_traversal(remove_graph, args.param_str)

        logging.info("Updating all states before '%s'", vm_params.get("to_state", "customize_vm"))
        update_graph = l.parse_object_trees(args.param_str, param.re_str(vm_params.get("to_state", "customize_vm")),
                                            {vm_name: args.vm_strs[vm_name]}, prefix=tag,
                                            object_names=vm_name, objectless=True)
        update_graph.flag_parent_intersection(update_graph, flag_type="run", flag=False)
        update_graph.flag_parent_intersection(update_graph, flag_type="run", flag=True,
                                              skip_object_roots=True, skip_shared_root=True)

        logging.info("Preserving all states before '%s'", vm_params.get("from_state", "customize_vm"))
        if vm_params.get("from_state", "install") != "root":
            reuse_graph = l.parse_object_trees(args.param_str, param.re_str(vm_params.get("from_state", "install")),
                                               {vm_name: args.vm_strs[vm_name]}, prefix=tag,
                                               object_names=vm_name, objectless=True, verbose=False)
            update_graph.flag_parent_intersection(reuse_graph, flag_type="run", flag=False)

        # NOTE: this makes sure that no new states are created and the updated
        # states are not removed, aborting in any other case
        setup_str = args.param_str + param.dict_to_str({"get_mode": "ra", "set_mode": "fa", "unset_mode": "ra"})
        r.run_traversal(update_graph, setup_str)


@with_cartesian_graph
def run(args, run_params, tag=""):
    """
    Run a set of tests without any automated setup.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    This is equivalent to but more powerful than the runner plugin.
    """
    # NOTE: each host control file expects already incremented count in the beginning
    # this prefix is preferential to setup chains with a single "run" step since this is usually the case
    args.prefix = tag + "n" if len(re.findall("run", run_params["setup"])) > 1 else ""
    # essentially we imitate the auto plugin to make the tool plugin a superset
    # loader = args.graph.l
    job = args.graph.r.job
    job.args.test_runner = CartesianRunner
    job.args.sysinfo = 'on'
    job.args.html_job_result = 'on'
    job.run()


def list(args, run_params, tag=""):
    """
    List a set of tests from the command line.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    This is equivalent to but more powerful than the loader plugin.
    """
    loader = CartesianLoader(args, {"logdir": data_dir.get_base_dir()})
    prefix = tag + "l" if len(re.findall("run", run_params["setup"])) > 1 else ""
    graph = loader.parse_object_trees(args.param_str, args.tests_str, args.vm_strs, prefix=prefix)
    graph.visualize(data_dir.get_base_dir())


############################################################
# Custom manual user steps
############################################################


@with_cartesian_graph
def windows(args, run_params, tag=""):
    """
    Perform all extra setup needed for the windows permanent vms.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    If the vm is still located on top of ramdisk (it is still not
    permanent) this setup is still possible in the form of online
    state setup, however you may risk running out of memory.
    """
    vms = args.graph.l.parse_objects(args.vm_strs, run_params.get("vms", ""))
    for vm in vms:
        logging.info("Performing extra setup for the permanent %s", vm.name)

        # consider this as a special kind of ephemeral test which concerns
        # permanent objects (i.e. instead of transition from customize_vm to online
        # root, it is a transition from supposedly "permanentized" vm to the root)
        logging.info("Booting %s for the first permanent online state", vm.name)
        parser = param.update_parser(vm.parser,
                                     ovrwrt_dict={"set_state": "windows_online"},
                                     ovrwrt_str=param.re_str("manage.start", args.param_str, objectless=True),
                                     ovrwrt_base_file="sets.cfg",
                                     ovrwrt_file=param.tests_ovrwrt_file)
        args.graph.r.run_test_node(TestNode(tag, parser, []))

        logging.info("Installing local virtuser at %s", vm.name)
        parser = param.update_parser(vm.parser,
                                     ovrwrt_dict={"skip_image_processing": "yes", "kill_vm": "no"},
                                     ovrwrt_str=param.re_str("windows_virtuser", args.param_str, objectless=True),
                                     ovrwrt_base_file="sets.cfg",
                                     ovrwrt_file=param.tests_ovrwrt_file)
        args.graph.r.run_test_node(TestNode(tag, parser, []))

        if run_params.get("with_outlook", "no") != "no":
            logging.info("Installing Outlook at %s", vm.name)
            year = run_params["with_outlook"]
            parser = param.update_parser(vm.parser,
                                         ovrwrt_dict={"skip_image_processing": "yes", "kill_vm": "no"},
                                         ovrwrt_str=param.re_str("outlook_prep..ol%s" % year, args.param_str, objectless=True),
                                         ovrwrt_base_file="sets.cfg",
                                         ovrwrt_file=param.tests_ovrwrt_file)
            args.graph.r.run_test_node(TestNode(tag, parser, []))


@with_cartesian_graph
def develop(args, run_params, tag=""):
    """
    Run manual tests specialized at development speedup.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
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
    setup_dict = {"vms": vms, "base_vm": run_params.objects("vms")[0]}
    setup_str = param.re_str("develop.%s" % mode) + param.dict_to_str(setup_dict) + args.param_str
    tests, _ = args.graph.l.parse_object_nodes(setup_str, args.vm_strs, prefix=tag, object_names=vms)
    assert len(tests) == 1, "There must be exactly one develop test variant from %s" % tests
    logging.info("Developing on virtual machines %s", vms)
    args.graph.r.run_test_node(TestNode(tag, tests[0].parser, []))


############################################################
# VM creation manual user steps
############################################################


@with_cartesian_graph
def install(args, run_params, tag=""):
    """
    Configure installation of each virtual machine and install it,
    taking the respective 'install' snapshot.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    graph = TestGraph()
    graph.nodes, graph.objects = args.graph.l.parse_object_nodes(param.re_str("install"), args.vm_strs,
                                                                 prefix=tag, object_names=run_params.get("vms", ""),
                                                                 objectless=True)
    for vm_name in sorted(graph.test_objects.keys()):
        args.graph.r.run_install_node(graph, vm_name, args.param_str)


@with_cartesian_graph
def deploy(args, run_params, tag=""):
    """
    Deploy customized data and utilities to the guest vms,
    to one or to more of their states, either temporary (``stateless=no``)
    or taking a respective 'customize_vm' snapshot.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    vms = args.graph.l.parse_objects(args.vm_strs, run_params.get("vms", ""))
    for vm in vms:

        states = vm.params.objects("states")
        if len(states) == 0:
            states = ["current_state"]
            stateless = vm.params.get("stateless", "yes") == "yes"
        else:
            stateless = False

        for i, state in enumerate(states):
            setup_str = args.param_str
            if state != "current_state":
                setup_str += param.dict_to_str({"get_state": state, "set_state": state,
                                                "get_type": "any", "set_type": "any"})
            ovrwrt_dict = {"skip_image_processing": "yes", "kill_vm": "no",
                           "redeploy_only": run_params.get("redeploy_only", "yes")}
            if stateless:
                ovrwrt_dict["get_state"] = ""
                ovrwrt_dict["set_state"] = ""
            setup_tag = "%s%s" % (tag, i+1 if i > 0 else "")
            ovrwrt_str = param.re_str("customize_vm", setup_str, objectless=True)
            parser = param.update_parser(vm.parser,
                                         ovrwrt_dict=ovrwrt_dict,
                                         ovrwrt_str=ovrwrt_str,
                                         ovrwrt_base_file="sets.cfg",
                                         ovrwrt_file=param.tests_ovrwrt_file)
            args.graph.r.run_test_node(TestNode(setup_tag, parser, []))


@with_cartesian_graph
def internal(args, run_params, tag=""):
    """
    Run an internal test node, thus performing a particular automated
    setup on the desired vms.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    vms = args.graph.l.parse_objects(args.vm_strs, run_params.get("vms", ""))
    for vm in vms:
        if vm.params.get("stateless", "yes") == "yes":
            ovrwrt_dict = {"get_state": "", "set_state": "",
                           "skip_image_processing": "yes", "kill_vm": "no"}
        else:
            ovrwrt_dict = {}
        forced_setup = vm.params["node"]
        ovrwrt_str = param.re_str(forced_setup, args.param_str, objectless=True)
        parser = param.update_parser(vm.parser,
                                     ovrwrt_dict=ovrwrt_dict,
                                     ovrwrt_str=ovrwrt_str,
                                     ovrwrt_base_file="sets.cfg",
                                     ovrwrt_file=param.tests_ovrwrt_file)
        args.graph.r.run_test_node(TestNode(tag, parser, []))


@with_cartesian_graph
def sysupdate(args, run_params, tag=""):
    """
    Update an intranator system and reset its install state.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    vms = args.graph.l.parse_objects(args.vm_strs, run_params.get("vms", ""))
    for vm in vms:

        states = vm.params.objects("states")
        if len(states) == 0:
            states = ["current_state"]
            stateless = vm.params.get("stateless", "yes") == "yes"
        else:
            stateless = False

        for i, state in enumerate(states):
            setup_str = ""
            if state != "current_state":
                setup_str = args.param_str + param.dict_to_str({"get_state": state, "set_state": state})

            if stateless:
                ovrwrt_dict = {"get_state": "", "set_state": "",
                               "skip_image_processing": "yes", "kill_vm": "no"}
            else:
                ovrwrt_dict = {}
            setup_tag = "%s%s" % (tag, i+1 if i > 0 else "")
            ovrwrt_str = param.re_str("system_update", setup_str, objectless=True)
            parser = param.update_parser(vm.parser,
                                         ovrwrt_dict=ovrwrt_dict,
                                         ovrwrt_str=ovrwrt_str,
                                         ovrwrt_base_file="sets.cfg",
                                         ovrwrt_file=param.tests_ovrwrt_file)
            args.graph.r.run_test_node(TestNode(setup_tag, parser, []))


############################################################
# VM management manual user steps
############################################################


@with_cartesian_graph
def boot(args, run_params, tag=""):
    """
    Boot all given vms.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    The boot test always takes care of any other vms so we can do it all in one test
    which is a bit of a hack but is much faster than the standard per-vm handling.
    """
    vms = run_params["vms"]
    setup_dict = {"vms": vms, "base_vm": run_params.objects("vms")[0]}
    setup_str = param.re_str("manage.start") + param.dict_to_str(setup_dict) + args.param_str
    tests, _ = args.graph.l.parse_object_nodes(setup_str, args.vm_strs, prefix=tag, object_names=vms)
    assert len(tests) == 1, "There must be exactly one boot test variant from %s" % tests
    logging.info("Booting virtual machines %s", vms)
    args.graph.r.run_test_node(TestNode(tag, tests[0].parser, []))


@with_cartesian_graph
def download(args, run_params, tag=""):
    """
    Download a set of files from the given vms.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    The set of files is specified using a "files" parameter.

    The download test always takes care of any other vms so we can do it all in one test
    which is a bit of a hack but is much faster than the standard per-vm handling.
    """
    vms = run_params["vms"]
    setup_dict = {"vms": vms, "base_vm": run_params.objects("vms")[0]}
    setup_str = param.re_str("manage.download") + param.dict_to_str(setup_dict) + args.param_str
    tests, _ = args.graph.l.parse_object_nodes(setup_str, args.vm_strs, prefix=tag, object_names=vms)
    assert len(tests) == 1, "There must be exactly one download test variant from %s" % tests
    logging.info("Downloading from virtual machines %s", vms)
    args.graph.r.run_test_node(TestNode(tag, tests[0].parser, []))


@with_cartesian_graph
def upload(args, run_params, tag=""):
    """
    Upload a set of files to the given vms.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    The set of files is specified using a `files` parameter.

    The upload test always takes care of any other vms so we can do it all in one test
    which is a bit of a hack but is much faster than the standard per-vm handling.
    """
    vms = run_params["vms"]
    setup_dict = {"vms": vms, "base_vm": run_params.objects("vms")[0]}
    setup_str = param.re_str("manage.upload") + param.dict_to_str(setup_dict) + args.param_str
    tests, _ = args.graph.l.parse_object_nodes(setup_str, args.vm_strs, prefix=tag, object_names=vms)
    assert len(tests) == 1, "There must be exactly one upload test variant from %s" % tests
    logging.info("Uploading to virtual machines %s", vms)
    args.graph.r.run_test_node(TestNode(tag, tests[0].parser, []))


@with_cartesian_graph
def shutdown(args, run_params, tag=""):
    """
    Shutdown gracefully or kill living vms.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    The shutdown test always takes care of any other vms so we can do it all in one test
    which is a bit of a hack but is much faster than the standard per-vm handling.
    """
    vms = run_params["vms"]
    setup_dict = {"vms": vms, "base_vm": run_params.objects("vms")[0]}
    setup_str = param.re_str("manage.stop") + param.dict_to_str(setup_dict) + args.param_str
    tests, _ = args.graph.l.parse_object_nodes(setup_str, args.vm_strs, prefix=tag, object_names=vms)
    assert len(tests) == 1, "There must be exactly one shutdown test variant from %s" % tests
    logging.info("Shutting down virtual machines %s", vms)
    args.graph.r.run_test_node(TestNode(tag, tests[0].parser, []))


############################################################
# State manipulation manual user steps
############################################################


@with_cartesian_graph
def check(args, run_params, tag=""):
    """
    Check whether a given state (setup snapshot) exists.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    setup_str = args.param_str
    setup_str += param.re_str("manage.unchanged")
    setup_str += param.dict_to_str({"vm_action": "check",
                                    "skip_image_processing": "yes"})
    tests, _ = args.graph.l.parse_object_nodes(setup_str, args.vm_strs,
                                               object_names=run_params["vms"],
                                               objectless=True, prefix=tag)
    for test in tests:
        args.graph.r.run_test_node(TestNode(tag, test.parser, []))


@with_cartesian_graph
def pop(args, run_params, tag=""):
    """
    Get to a state/snapshot disregarding the current changes
    loosing the it afterwards.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    setup_str = args.param_str
    setup_str += param.re_str("manage.unchanged")
    setup_str += param.dict_to_str({"vm_action": "pop",
                                    "skip_image_processing": "yes"})
    tests, _ = args.graph.l.parse_object_nodes(setup_str, args.vm_strs,
                                               object_names=run_params["vms"],
                                               objectless=True, prefix=tag)
    for test in tests:
        args.graph.r.run_test_node(TestNode(tag, test.parser, []))


@with_cartesian_graph
def push(args, run_params, tag=""):
    """
    Wrapper for setting state/snapshot, same as :py:func:`set`.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    setup_str = args.param_str
    setup_str += param.re_str("manage.unchanged")
    setup_str += param.dict_to_str({"vm_action": "push",
                                   "skip_image_processing": "yes"})
    tests, _ = args.graph.l.parse_object_nodes(setup_str, args.vm_strs,
                                                     object_names=run_params["vms"],
                                                     objectless=True, prefix=tag)
    for test in tests:
        args.graph.r.run_test_node(TestNode(tag, test.parser, []))


@with_cartesian_graph
def get(args, run_params, tag=""):
    """
    Get to a state/snapshot disregarding the current changes.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    This method could be implemented in identical way to the push/pop
    methods but we use different approach for illustration.
    """
    for vm_name in run_params.objects("vms"):
        parser = param.update_parser(args.graph.l.parse_objects(args.vm_strs, vm_name)[0].parser,
                                     ovrwrt_dict={"vm_action": "get",
                                                  "skip_image_processing": "yes"},
                                     ovrwrt_str=param.re_str("manage.unchanged",
                                                             args.param_str, objectless=True),
                                     ovrwrt_base_file="sets.cfg",
                                     ovrwrt_file=param.tests_ovrwrt_file)
        args.graph.r.run_test_node(TestNode(tag, parser, []))


@with_cartesian_graph
def set(args, run_params, tag=""):
    """
    Create a new state/snapshot from the current state/snapshot.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    This method could be implemented in identical way to the push/pop
    methods but we use different approach for illustration.
    """
    for vm_name in run_params.objects("vms"):
        parser = param.update_parser(args.graph.l.parse_objects(args.vm_strs, vm_name)[0].parser,
                                     ovrwrt_dict={"vm_action": "set",
                                                  "skip_image_processing": "yes"},
                                     ovrwrt_str=param.re_str("manage.unchanged",
                                                             args.param_str, objectless=True),
                                     ovrwrt_base_file="sets.cfg",
                                     ovrwrt_file=param.tests_ovrwrt_file)
        args.graph.r.run_test_node(TestNode(tag, parser, []))


@with_cartesian_graph
def unset(args, run_params, tag=""):
    """
    Remove a state/snapshot.

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run

    This method could be implemented in identical way to the push/pop
    methods but we use different approach for illustration.
    """
    # since the default unset_mode is passive (ri) we need a better
    # default value for that case but still modifiable by the user
    if "unset_mode" not in args.param_str:
        setup_str = args.param_str + param.dict_to_str({"unset_mode": "fi"})
    else:
        setup_str = args.param_str
    for vm_name in run_params.objects("vms"):
        parser = param.update_parser(args.graph.l.parse_objects(args.vm_strs, vm_name)[0].parser,
                                     ovrwrt_dict={"vm_action": "unset",
                                                  "skip_image_processing": "yes"},
                                     ovrwrt_str=param.re_str("manage.unchanged",
                                                             setup_str, objectless=True),
                                     ovrwrt_base_file="sets.cfg",
                                     ovrwrt_file=param.tests_ovrwrt_file)
        args.graph.r.run_test_node(TestNode(tag, parser, []))


def create(args, run_params, tag=""):
    """
    Create a new test object (vm, root state).

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    setup_str = args.param_str
    args.param_str += param.dict_to_str({"set_state": "root", "set_mode": "af", "set_type": "offline"})
    set(args, run_params, tag=tag)
    args.param_str = setup_str


def clean(args, run_params, tag=""):
    """
    Remove a test object (vm, root state).

    :param args: command line arguments
    :type args: :py:class:`argparse.Namespace`
    :param run_params: parameters with minimal vm configuration
    :type run_params: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    setup_str = args.param_str
    args.param_str += param.dict_to_str({"unset_state": "root", "unset_mode": "fi", "unset_type": "offline"})
    unset(args, run_params, tag=tag)
    args.param_str = setup_str
