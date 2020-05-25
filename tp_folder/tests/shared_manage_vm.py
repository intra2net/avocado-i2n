"""

SUMMARY
------------------------------------------------------
Perform vm management functions like booting, running a code on the guest,
rebooting or shutting down a vm.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import logging
import time
import os

# avocado imports
from avocado.core import exceptions
from virttest import error_context
from avocado_i2n import state_setup

# custom imports
pass


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
    vmnet = env.get_vmnet()

    if params.get("vm_action", "run") == "boot":
        vmnet.start_all_sessions()
    elif params.get("vm_action", "run") == "run":
        vms = vmnet.get_ordered_vms()
        for vm in vms:
            raise NotImplementedError("Run control files or other code snippet on an %s vm", params["os_type"])
    elif params.get("vm_action", "run") == "download":
        if params.get("os_type", "linux") in ["android"]:
            raise NotImplementedError("No data exchange is currently possible for Android")
        for vm in vmnet.get_ordered_vms():
            to_dir = os.path.join(test.logdir)
            for f in vm.params.objects("files"):
                logging.info("Downloading %s to %s (%s)", f, to_dir, vm.name)
                vm.copy_files_from(f, to_dir, timeout=30)
    elif params.get("vm_action", "run") == "upload":
        if params.get("os_type", "linux") in ["android"]:
            raise NotImplementedError("No data exchange is currently possible for Android")
        for vm in vmnet.get_ordered_vms():
            to_dir = vm.params["tmp_dir"]
            for f in vm.params.objects("files"):
                logging.info("Uploading %s to %s (%s)", f, to_dir, vm.name)
                vm.copy_files_to(f, to_dir, timeout=30)
    elif params.get("vm_action", "run") == "shutdown":
        for vm in vmnet.get_ordered_vms():
            if vm.name == params.get("main_vm"):
                # NOTE: the rest of the vms will be destroyed automatically during post-processing
                vm.destroy(gracefully=True)
                break

    # state manipulation
    elif params.get("vm_action", "run") == "check":
        logging.info("Checking for %s's state '%s'", params["main_vm"], params["check_state"])
        params["check_opts"] = params.get("check_opts", "print_pos=yes print_neg=yes")
        state_setup.check_state(params, env)
    elif params.get("vm_action", "run") == "push":
        logging.info("Pushing %s's state '%s'", params["main_vm"], params["push_state"])
        state_setup.push_state(params, env)
    elif params.get("vm_action", "run") == "pop":
        logging.info("Popping %s's state '%s'", params["main_vm"], params["pop_state"])
        state_setup.pop_state(params, env)
    elif params.get("vm_action", "run") in ["get", "set"]:
        # this operations are performed automatically by the environment process
        state_param = params["get_state"] if params["vm_action"] == "get" else params["set_state"]
        logging.info("%sting %s's state '%s'", params["vm_action"].title(), params["main_vm"], state_param)
    elif params.get("vm_action", "run") == "unset":
        logging.info("Unsetting %s's state '%s'", params["main_vm"], params["unset_state"])
        state_setup.unset_state(params, env)
