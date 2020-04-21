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
    selected_vms = sorted(config["vm_strs"].keys())
    LOG_UI.info("Starting permanent vm setup for %s (%s)",
                ", ".join(selected_vms), os.path.basename(r.job.logdir))

    for vm in l.parse_objects(config["param_dict"], config["vm_strs"]):
        logging.info("Performing extra setup for the permanent %s", vm.name)

        # consider this as a special kind of ephemeral test which concerns
        # permanent objects (i.e. instead of transition from customize to on
        # root, it is a transition from supposedly "permanentized" vm to the root)
        logging.info("Booting %s for the first permanent on state", vm.name)
        setup_dict = config["param_dict"].copy()
        setup_dict.update({"set_state": "ready"})
        setup_str = param.re_str("all..internal..manage.start")
        test_node = l.parse_node_from_object(vm, setup_dict, setup_str, prefix=tag)
        r.run_test_node(test_node)

    LOG_UI.info("Finished permanent vm setup")
