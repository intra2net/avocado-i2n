"""

SUMMARY
------------------------------------------------------
Run the steps necessary to make virtual user software run on Linux.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import time
import os
import logging
# TODO: migrate from logging to log usage in messages
log = logging = logging.getLogger('avocado.test.log')

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
    :type test: :py:class:`avocado_vt.test.VirtTest`
    :param params: extended dictionary of parameters
    :type params: :py:class:`virttest.utils_params.Params`
    :param env: environment object
    :type env: :py:class:`virttest.utils_env.Env`
    """
    vmnet = env.get_vmnet()
    vm, session = vmnet.get_single_vm_with_session()

    logging.info("Making virtual user software available on the vm")
    logging.info("...")
    try:
        from guibot import GuiBot
        from guibot.config import GlobalConfig
        from guibot.controller import QemuController, VNCDoToolController
    except ImportError:
        # we would typically raise test error here to cancel all dependent tests
        # but we want the test suite to skip tests in the best case
        logging.warning("No virtual user backend found")
    logging.info("...some setup steps on linux")

    logging.info("Virtual user is ready to manipulate the vm from a screen")
    logging.info("\nFor more details check https://guibot.org")
