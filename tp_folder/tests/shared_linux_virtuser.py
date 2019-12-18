"""

SUMMARY
------------------------------------------------------
Run the steps necessary to make virtual user software run on Linux.

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

    logging.info("Making virtual user software available on the vm")
    logging.info("...")
    try:
        from guibot import GuiBot
        from guibot.config import GlobalConfig
        from guibot.desktopcontrol import QemuDesktopControl, VNCDoToolDesktopControl
    except ImportError:
        # we would typically raise test error here to cancel all dependent tests
        # but we want the test suite to skip tests in the best case
        logging.warning("No virtual user backend found")
    logging.info("...some setup steps on linux")

    logging.info("Virtual user is ready to manipulate the vm from a screen")
    logging.info("\nFor more details check https://guibot.org")
