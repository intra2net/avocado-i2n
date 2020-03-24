"""

SUMMARY
------------------------------------------------------
Tool to semi-automate the creation of a selection of permanent vms.

Copyright: Intra2net AG


CONTENTS
------------------------------------------------------
This tool contains manual steps to use to create permanent vms.

Currently supported vms are based on: Ubuntu.


INTERFACE
------------------------------------------------------

"""

import os
import logging

from avocado.core.output import LOG_UI
from avocado_i2n import params_parser as param
from avocado_i2n.cartgraph import TestNode
from avocado_i2n.intertest_setup import with_cartesian_graph


#: list of all available manual steps or simply semi-automation tools
__all__ = ["permubuntu"]


############################################################
# Custom manual user steps
############################################################


@with_cartesian_graph
def permubuntu(config, tag=""):
    """
    Perform all extra setup needed for the ubuntu permanent vms.

    :param config: command line arguments and run configuration
    :type config: {str, str}
    :param str tag: extra name identifier for the test to be run
    """
    l, r = config["graph"].l, config["graph"].r
    LOG_UI.info("Starting permanent vm setup for %s (%s)",
                ", ".join(config["selected_vms"]), os.path.basename(r.job.logdir))

    vms = l.parse_objects(config["vm_strs"], " ".join(config["selected_vms"]))
    for vm in vms:
        logging.info("Performing extra setup for the permanent %s", vm.name)

        # consider this as a special kind of ephemeral test which concerns
        # permanent objects (i.e. instead of transition from customize to on
        # root, it is a transition from supposedly "permanentized" vm to the root)
        logging.info("Booting %s for the first permanent on state", vm.name)
        reparsable = vm.config.get_copy()
        reparsable.parse_next_batch(base_file="sets.cfg",
                                    ovrwrt_file=param.tests_ovrwrt_file(),
                                    ovrwrt_str=param.re_str("nonleaves..manage.start", config["param_str"]),
                                    ovrwrt_dict={"set_state": "ready"})
        r.run_test_node(TestNode(tag, reparsable, []))

    LOG_UI.info("Finished permanent vm setup")
