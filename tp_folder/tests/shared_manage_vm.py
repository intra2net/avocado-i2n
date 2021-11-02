"""

SUMMARY
------------------------------------------------------
Perform vm management functions like booting, running a code on the guest,
rebooting or shutting down a vm.

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
from virttest import error_context
from avocado_i2n.states import setup as ss

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
    :type test: :py:class:`avocado_vt.test.VirtTest`
    :param params: extended dictionary of parameters
    :type params: :py:class:`virttest.utils_params.Params`
    :param env: environment object
    :type env: :py:class:`virttest.utils_env.Env`
    """
    vmnet = env.get_vmnet()

    if params.get("vm_action", "run") == "boot":
        vmnet.start_all_sessions()
    elif params.get("vm_action", "run") == "run":
        for vm in vmnet.get_ordered_vms():
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
            vm.destroy(gracefully=True)

    # state manipulation
    elif params.get("vm_action", "run") == "check":
        logging.info("Checking %s's (and its images') states", params["main_vm"])
        ss.check_states(params, env)
    elif params.get("vm_action", "run") == "push":
        logging.info("Pushing %s's (and its images') states", params["main_vm"])
        ss.push_states(params, env)
    elif params.get("vm_action", "run") == "pop":
        logging.info("Popping %s's (and its images') states", params["main_vm"])
        ss.pop_states(params, env)
    elif params.get("vm_action", "run") in ["get", "set"]:
        # these operations are performed automatically by the environment process
        logging.info("%sting %s's (and its images') states", params["vm_action"].title(), params["main_vm"])
    elif params.get("vm_action", "run") == "unset":
        logging.info("Unsetting %s's (and its images') states", params["main_vm"])
        ss.unset_states(params, env)
