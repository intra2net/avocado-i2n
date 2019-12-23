"""

SUMMARY
------------------------------------------------------
Tool to use for GUI and non-GUI test development on virtual machines.

Copyright: Intra2net AG


CONTENTS
------------------------------------------------------
This tool can be used for rapid development of tests whereby the developer
could save and revert to vm states multiple times during development, all
by using a GUI with a few buttons.


INTERFACE
------------------------------------------------------

"""

import logging
import contextlib
from collections import namedtuple

from avocado.core import job
from avocado.core import output
from avocado.core import data_dir
from avocado.core import dispatcher

from avocado_i2n import params_parser as param
from avocado_i2n.cartgraph import TestGraph, TestNode
from avocado_i2n.loader import CartesianLoader
from avocado_i2n.runner import CartesianRunner


#: list of all available manual steps or simply semi-automation tools
__all__ = ["develop"]


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
