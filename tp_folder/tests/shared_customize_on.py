"""

SUMMARY
------------------------------------------------------
Verify if a virtual machine is booted.

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
    vm, _ = vmnet.get_single_vm_with_session()

    # give the system three more seconds to settle down
    time.sleep(3)

    logging.info("Performing imaginary setup requiring the vm to be booted "
                 "at the beginning of the test and stay on at the end")
    # e.g. some program reaches a certain state which is changed upon rebooting
    # so we have to perform it here, i.e. in a special ephemeral test
    logging.info("Imaginary setup done")
