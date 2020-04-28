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

import os
import logging
import contextlib
from collections import namedtuple

from avocado.core import job
from avocado.core import output
from avocado.core import data_dir
from avocado.core import dispatcher
from avocado.core.output import LOG_UI

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
def develop(config, tag=""):
    """
    Run manual tests specialized at development speedup.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run

    Current modes that can be supplied from the command line
    can be found in the "develop" test set.

    As with all manual tests, providing setup and making sure
    that all the vms exist is a user's responsibility.
    """
    l, r = config["graph"].l, config["graph"].r
    selected_vms = list(config["vm_strs"].keys())
    LOG_UI.info("Developing on virtual machines %s (%s)",
                ", ".join(selected_vms), os.path.basename(r.job.logdir))
    vms = " ".join(selected_vms)
    mode = config["tests_params"].get("devmode", "generator")
    setup_dict = config["param_dict"].copy()
    setup_dict.update({"vms": vms, "main_vm": selected_vms[0]})
    setup_str = param.re_str("all..manual..develop.%s" % mode)
    tests, vms = l.parse_object_nodes(setup_dict, setup_str, config["vm_strs"], prefix=tag)
    assert len(tests) == 1, "There must be exactly one develop test variant from %s" % tests
    r.run_test_node(TestNode(tag, tests[0].config, vms))
    LOG_UI.info("Development complete")
