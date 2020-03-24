"""

SUMMARY
------------------------------------------------------
Sample test suite GET tutorial -- *Complex test dependencies*

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import time
import logging
import os

# avocado imports
from avocado.core import exceptions

# custom imports
from sample_utility import sleep


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
    vmnet.start_all_sessions()
    vms = vmnet.get_vms()
    temporary = vms.temporary
    permanent = vms.permanent

    logging.info(temporary.session.cmd_output("uptime"))
    logging.info(temporary.session.cmd_output("cat /etc/os-release"))

    logging.info(permanent.session.cmd_output("uptime"))
    logging.info(permanent.session.cmd_output("cat /etc/os-release"))

    # call to a function shared among tests
    sleep(3)

    logging.info("Test passed.")
