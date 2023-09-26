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
import asyncio

from avocado.core.output import LOG_UI, LOG_JOB as logging

from avocado_i2n import params_parser as param
from avocado_i2n.cartgraph import TestGraph
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

    graph = TestGraph()
    graph.new_workers(l.parse_workers(config["param_dict"]))
    graph.objects = l.parse_objects(config["param_dict"], config["vm_strs"])
    for test_object in graph.objects:
        if test_object.key != "vms":
            continue
        vm = test_object
        # parse individual net only for the current vm
        net = l.parse_object_from_objects("net1", "nets", [vm], params=config["param_dict"])
        logging.info("Performing extra setup for the permanent %s", vm.suffix)

        # consider this as a special kind of state converting test which concerns
        # permanent objects (i.e. instead of transition from customize to on
        # root, it is a transition from supposedly "permanentized" vm to the root)
        logging.info("Booting %s for the first permanent on state", vm.suffix)
        setup_dict = config["param_dict"].copy()
        setup_dict.update({"set_state_vms": "ready"})
        setup_str = param.re_str("all..internal..manage.start")
        test_node = l.parse_node_from_object(net, setup_dict, setup_str, prefix=tag)
        # TODO: traversal relies explicitly on object_suffix which only indicates
        # where a parent node was parsed from, i.e. which test object of the child node
        test_node.params["object_suffix"] = test_object.long_suffix
        graph.nodes += [test_node]

    l.parse_shared_root_from_object_trees(graph, config["param_dict"])
    r.run_workers(graph, config["param_dict"])
    LOG_UI.info("Finished permanent vm setup")
