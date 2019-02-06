"""

SUMMARY
------------------------------------------------------
Run the steps necessary to do GUI test development.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import logging
import time
import os

# avocado imports
from avocado.core import exceptions

# custom imports
pass


###############################################################################
# TEST MAIN
###############################################################################

def run(test, params, env):
    """
    Main test run.

    :param test: test object
    :param params: extended dictionary of parameters
    :param env: environment object
    """
    vmnet = env.get_vmnet()
    vm, session = vmnet.get_single_vm_with_session()

    logging.info("Initializing GUI test development tools")
