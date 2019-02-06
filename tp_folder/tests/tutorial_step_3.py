"""

SUMMARY
------------------------------------------------------
Sample test suite tutorial pt. 3 -- *Multi-VM example*

Copyright: Intra2net AG


CONTENTS
------------------------------------------------------
This part of the tutorial validates deployed packages in multiple virtual
machines. It could then be extended to any client-server protocol once
the connectivity between the vm is established with a vm network ping.


INTERFACE
------------------------------------------------------

"""

import time
import logging
import os

# avocado imports
from avocado.core import exceptions
from virttest import error_context

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
    error_context.context("network configuration")
    vmnet = env.get_vmnet()
    vmnet.start_all_sessions()
    vms = vmnet.get_vms()
    server_vm = vms.server
    client_vm = vms.client
    vmnet.ping()

    error_context.context("misc commands on each vm")
    tmp_server = server_vm.session.cmd("ls " + server_vm.params["tmp_dir"])
    tmp_client = client_vm.session.cmd("dir " + client_vm.params["tmp_dir"])
    logging.info("Content of temporary server folder:\n%s", tmp_server)
    logging.info("Content of temporary client folder:\n%s", tmp_client)
    deployed_folders = ("data", "utils", "packages")
    for folder in deployed_folders:
        if folder not in tmp_server:
            raise exceptions.TestFail("No deployed %s was found on the server" % folder)
        if folder not in tmp_client:
            raise exceptions.TestFail("No deployed %s was found on the client" % folder)

    logging.info("It would appear that the test terminated in a civilized manner.")
