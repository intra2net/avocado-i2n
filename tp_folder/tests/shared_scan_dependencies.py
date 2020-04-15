"""

SUMMARY
------------------------------------------------------
This test must be viewed as the primary test that is needed by all the
remaining tests.

Copyright: Intra2net AG


CONTENTS
------------------------------------------------------
All operations on vm objects like monitor commands, login, etc. can only
be done inside a test. This is the main reason we are wrapping this part
of the Cartesian graph setup in a test instead of performing it separately.

This large limitation of avocado-vt is purely historical - the entire vm
management grew out of a single client test (virt.py) and therefore all
vm vital operations that we need can only be accessed within this test.
All our manual (intertest_setup) or automated (cartesian_graph) setup code
can therefore be considered "intertest" space and quite often we might
need test bubbles like this to perform operations on vms.


INTERFACE
------------------------------------------------------

"""

import logging
import os

# avocado imports
from avocado.core import exceptions
from virttest import error_context

# custom imports
from avocado_i2n import state_setup
from avocado_i2n.cartgraph import TestGraph


###############################################################################
# TEST MAIN
###############################################################################

@error_context.context_aware
def run(test, params, env):
    """
    Main test run.

    :param test: test object
    :param params: extended dictionary of parameters
    :param env: environment object
    """
    error_context.context("Dependency check")
    logging.info("Scanning for already available setup that we can reuse")

    trees = TestGraph.REFERENCE
    try:
        trees.scan_object_states(env)
    finally:
        trees.save_setup_list(test.job.logdir)

    logging.info("Scan completed successfully")
