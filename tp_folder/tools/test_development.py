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
from avocado_i2n.intertest_setup import with_cartesian_graph


#: list of all available manual steps or simply semi-automation tools
__all__ = ["develop"]


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