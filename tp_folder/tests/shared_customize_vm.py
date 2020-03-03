"""

SUMMARY
------------------------------------------------------
Deploy guest tests, utilities and data to the main virtual machine.

Copyright: Intra2net AG


CONTENTS
------------------------------------------------------
If the vm is linux-based add some conveniences like ssh key or extra rpms.
If the vm is windows-based add some GUI-tweaks like resolution and welcome messages.


INTERFACE
------------------------------------------------------

"""

import logging
import tempfile
import os
import re

# avocado imports
from avocado.core import exceptions
from avocado.core.settings import settings
from virttest import error_context

# custom imports
pass


###############################################################################
# DEFINITIONS
###############################################################################

testsuite_top_path = settings.get_value('i2n.common', 'suite_path', default="..")
guest_path = testsuite_top_path
source_avocado_path = "/usr/lib/python3.7/site-packages/avocado/utils"
destination_avocado_path = "/tmp/utils/avocado"


###############################################################################
# HELPERS
###############################################################################

def deploy_avocado(vm, params, test):
    """
    Deploy the avocado package to a vm.

    :param vm: vm to deploy to (must be compatible)
    :type vm: VM object
    :param params: deploy configuration
    :type params: {str, str}
    :param test: test object (as before)
    """
    # TODO: scp does not seem to raise exception if path does not exist
    logging.info("Deploying avocado utilities at %s", params["main_vm"])
    logging.debug("Deploying utilities from %s on host to %s on the virtual machine.",
                  source_avocado_path, destination_avocado_path)
    vm.session.cmd("mkdir -p " + destination_avocado_path)
    vm.session.cmd("touch " + os.path.join(destination_avocado_path, "__init__.py"))
    vm.copy_files_to(source_avocado_path, destination_avocado_path, timeout=180)


def deploy_data(vm, folder_name, params,
                custom_src_path="", custom_dst_name="",
                timeout=60):
    """
    Deploy data to a vm.

    :param vm: vm to deploy to (must be compatible)
    :type vm: VM object
    :param str folder_name: data folder name (default path is 'guest')
    :param params: deploy configuration
    :type params: {str, str}
    :param str custom_src_path: custom path to the src data folder
    :param str custom_dst_name: custom folder name of the dst data folder
    :param int timeout: copying timeout
    """
    wipe_data = params.get("wipe_data", "no")
    os_type = params.get("os_type", "linux")
    tmp_dir = params.get("tmp_dir", "/tmp")
    if custom_src_path == "":
        src_path = os.path.join(guest_path, folder_name)
    else:
        src_path = os.path.join(custom_src_path, folder_name)
    folder_name = custom_dst_name if custom_dst_name else folder_name
    if wipe_data == "yes" and os_type == "windows":
        w_tmp_dir = tmp_dir.replace("/", "\\")
        w_folder_name = folder_name.replace("/", "\\")
        dst_path = os.path.join(w_tmp_dir, w_folder_name).replace("/", "\\")
        try:
            vm.session.cmd("rmdir %s /s /q" % dst_path)
        except:
            pass
    elif wipe_data == "yes" and os_type == "linux":
        dst_path = os.path.join(tmp_dir, folder_name)
        vm.session.cmd("rm -fr %s" % dst_path)
    else:
        dst_path = os.path.join(tmp_dir, folder_name) if custom_dst_name else tmp_dir
    vm.copy_files_to(src_path, dst_path, timeout=timeout)


def handle_ssh_authorized_keys(vm, params):
    """
    Deploy an SSH key to a vm.

    :param vm: vm to deploy to (must be compatible)
    :type vm: VM object
    :param params: deploy configuration
    :type params: {str, str}
    """
    ssh_authorized_keys = os.environ['SSHKEY'] if 'SSHKEY' in os.environ else ""
    if ssh_authorized_keys == "":
        return
    logging.info("Enabled ssh key '{0}'".format(ssh_authorized_keys))

    tmpfile = tempfile.NamedTemporaryFile(delete=False)
    tmpfile.write((ssh_authorized_keys + '\n').encode())
    tmpfile.close()

    vm.session.cmd('mkdir -p /root/.ssh')
    vm.copy_files_to(tmpfile.name, '/root/.ssh/authorized_keys')
    os.unlink(tmpfile.name)


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
    vm, session, params = vmnet.get_single_vm_with_session_and_params()
    os_type = params.get("os_type", "linux")
    os_variant = params.get("os_variant", "ibs")
    tmp_dir = params.get("tmp_dir", "/tmp")

    # pre-deployment part
    if params.get_boolean("guest_avocado_enabled"):
        if os.path.exists(source_avocado_path):
            deploy_avocado(vm, params, test)
        else:
            logging.warning("No source avocado path found and could be deployed")

    # main deployment part
    logging.info("Deploying customized data to %s on %s", tmp_dir, params["main_vm"])
    deploy_data(vm, "data/", params)
    # WARNING: control file must add path to utils to the pythonpath
    logging.info("Deploying customized test utilities to %s on %s", tmp_dir, params["main_vm"])
    deploy_data(vm, "utils/", params)

    # additional deployment part
    additional_deployment_path = params.get("additional_deployment_dir", "/mnt/local/packages")
    destination_packages_path = params.get("deployed_packages_path", "/tmp/packages")
    if additional_deployment_path is not None and os.path.isdir(additional_deployment_path):
        logging.info("Deploying additional packages and data to %s on %s", tmp_dir, params["main_vm"])
        # careful about the splitting process - since we perform deleting need to validate here
        additional_deployment_path = additional_deployment_path.rstrip("/")
        deploy_data(vm, os.path.basename(additional_deployment_path), params,
                    os.path.dirname(additional_deployment_path), "packages", 60)
    else:
        raise exceptions.TestError("Additional deployment path %s does not exist (current dir: "
                                   "%s)" % (additional_deployment_path, os.getcwd()))
    if params.get("extra_rpms", None) is not None:
        if os_type != "linux":
            raise NotImplementedError("RPM updates are only available on some linux distros and not %s" % os_type)
        for rpm in params.objects("extra_rpms"):
            session.cmd("rpm -Uv --force %s" % os.path.join(destination_packages_path, rpm))
            logging.info("Updated package: " + rpm)

    if os_type == "linux" and params.get("redeploy_only", "no") == "no":
        handle_ssh_authorized_keys(vm, params)

    logging.info("Customized tests setup on VM finished")
    session.close()
