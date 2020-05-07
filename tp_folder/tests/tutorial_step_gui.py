"""

SUMMARY
------------------------------------------------------
Sample test suite GUI tutorial -- *Using the GUI test extension*

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import os
import logging
import random

# avocado imports
from avocado.core import exceptions

# custom imports
try:
    from guibot.guibot import GuiBot
    from guibot.config import GlobalConfig
    from guibot.desktopcontrol import QemuDesktopControl, VNCDoToolDesktopControl
    BOT_AVAILABLE = True
except ImportError:
    logging.warning("No virtual user backend found")
    BOT_AVAILABLE = False


###############################################################################
# HELPERS
###############################################################################

def get_image_root():
    """
    Get the image root from the avocado config.

    :raises: :py:class:`IOError` if path cannot be found

    Try with a host path first, then if not with a guest path,
    and ultimately fail if none of these is available.
    """
    try:
        from avocado.core.settings import settings
        testsuite_top_path = settings.get_value('i2n.common', 'suite_path', default="..")
        image_root = os.path.join(testsuite_top_path, "data", "visual")
    except ImportError:
        image_root = os.path.join("/tmp", "data", "visual")
    if not os.path.exists(image_root):
        raise IOError("No image root path was found")
    return image_root


def set_logging(lvl, logdir):
    """
    Set the logging level for the GuiBot library.

    :param int lvl: logging level
    :param str logdir: directory to place the imglogs into
    """
    if isinstance(lvl, str):
        lvl = int(lvl)
    logging.getLogger("guibot").setLevel(lvl)
    GlobalConfig.image_logging_level = lvl
    GlobalConfig.image_logging_destination = os.path.join(logdir, "imglogs")


def set_shared_configuration(mouse_drag=False):
    """
    Set some shared configuration for all visual objects.

    :param bool mouse_drag: mouse dragging switch
    """
    # we have tons of tests that can benefit from less visualization and clear-cut timeouts
    GlobalConfig.smooth_mouse_drag = mouse_drag

    # legacy setting - since we use mostly tempfeat default to it
    GlobalConfig.hybrid_match_backend = "tempfeat"


def initiate_vm_screen(vm, screen_type):
    """
    Helper for screen instantiation.

    :param vm: vm whose screen the virtual user is initialized on
    :type vm: VM object
    :param str screen_type: 'qemu' or 'vncdotool'
    :returns: a desktop backend and its name (screen tuple)
    :rtype: DesktopControl object
    """
    if screen_type == 'qemu':
        dc = QemuDesktopControl(synchronize=False)
        dc.params["qemu"]["qemu_monitor"] = vm.monitors[0]
        dc.synchronize_backend()
        logging.debug("Initiating qemu monitor screen for vm %s", vm.name)
    elif screen_type == 'vncdotool':
        dc = VNCDoToolDesktopControl(synchronize=False)
        # starting from 5900, i.e. :0 == 5900
        dc.params["vncdotool"]["vnc_port"] = vm.vnc_port - 5900
        dc.params["vncdotool"]["vnc_delay"] = 0.02
        dc.synchronize_backend()
        logging.debug("Initiating vnc server screen for vm %s on port %s (%s)",
                      vm.name, dc.params["vncdotool"]["vnc_port"], vm.vnc_port)
    return dc


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
    logging.info("Running GUI tutorial test.")

    # Get the VM Network object for this test
    vmnet = env.get_vmnet()
    vmnet.start_all_sessions()
    vms = vmnet.get_vms()
    server_vm = vms.server
    client_vm = vms.client
    vmnet.ping_all()

    logging.info("Starting a minimal GUI test on two vms (screens)")
    if not BOT_AVAILABLE:
        raise exceptions.TestSkipError("No virtual user backend found")
    image_root = get_image_root()
    set_logging(params.get("vu_logging_level", 20), test.logdir)
    set_shared_configuration(params.get("smooth_mouse_motion", "no") == "yes")
    server_screen = initiate_vm_screen(server_vm, 'vncdotool')
    client_screen = initiate_vm_screen(client_vm, 'vncdotool')

    # click on a button on the server if available
    bot = GuiBot(dc=server_screen)
    bot.add_path(image_root)
    if bot.exists('centos-kickstart-finish'):
        bot.click('centos-kickstart-finish')
    else:
        bot.type_text('Anyone there?')

    # click on a button on the client if available
    if params["set_state_vm2"] == "guisetup.clicked":
        bot.dc_backend = client_screen
        if bot.exists('win10-start-button'):
            bot.click('win10-start-button')
        else:
            bot.type_text('Anyone here?')
    elif params["set_state_vm2"] == "guisetup.noop":
        logging.info("The virtual user will do nothing on the client screen")
    else:
        raise exceptions.TestError("Invalid option for Windows client GUI setup "
                                   "operation %s" % params["set_state_vm2"])

    logging.info("Running done.")
    logging.info("\nFor more details check https://guibot.org")
