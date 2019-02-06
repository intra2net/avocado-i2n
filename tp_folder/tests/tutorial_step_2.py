"""

SUMMARY
------------------------------------------------------
Sample test suite tutorial pt. 2 -- *Complex test example*

Copyright: Intra2net AG


CONTENTS
------------------------------------------------------
This demo tests if certain files exist in the /etc directory of a VM
and on a second variant it extracts a tarball to the temp directory
and runs the extracted script.


INTERFACE
------------------------------------------------------

"""

import logging
import os
import subprocess

# avocado imports
from avocado.core import exceptions

# custom imports
pass


###############################################################################
# CONSTANTS
###############################################################################

TARBALL_DESTINATION = "/tmp"


###############################################################################
# HELPER FUNCTIONS
###############################################################################


def extract_tarball(params, vm):
    """
    Here we extract our tarball with the file we want to run, checking
    if the file hash matches before proceeding. Note that the extraction
    is done on the guest VM, remotely from the host.

    In this test suite, whatever is located in the data directory
    of a test (tp_folder/data/<$TEST_NAME>) will be pushed to the path
    /tmp/data/<$TEST_NAME> on the VM.
    This can be adapted using the parameter `deployed_test_data_path`.

    This function is run for each test run, i.e. for each call to
    run() below.

    :param params: extended dictionary of parameters
    :type params: {str, str}
    :params vm: guest VM object
    :type vm: virttest.qemu_vm.VM
    """
    logging.info("Enter tutorial test variant one: extract and run a file.")
    tarball_path = os.path.join(
        params["deployed_test_data_path"],
        "tutorial_step_2",
        "check_names.tar.gz"
    )

    # One way to execute commands remotely on the guest VM is to
    # use the methods from the `session` object. Here we invoke
    # a shell command and capture its output.
    hash_out = vm.session.cmd_output("md5sum %s" % tarball_path)

    # A sanity check just in case (use entire hash output to deal with CentOS locale problems)
    if params["md5sum"] not in hash_out:
        raise exceptions.TestError("MD5 checksum mismatch of file %s: "
                                   "expected %s, got:\n%s"
                                   % (tarball_path, params["md5sum"], hash_out))

    vm.session.cmd("tar -xf %s -C %s" % (tarball_path, TARBALL_DESTINATION))


def run_extracted_script(params, vm):
    """
    Verify that the script from the tarball has been successfully extracted
    and run it, checking its return code.

    :param params: extended dictionary of parameters
    :type params: {str, str}
    :params vm: guest VM object
    :type vm: virttest.qemu_vm.VM
    """
    scriptdir = params["script"]
    scriptname = scriptdir + ".sh"
    scriptabspath = os.path.join(
        TARBALL_DESTINATION,
        scriptdir,
        scriptname
    )

    vm.session.cmd("test -f " + scriptabspath)
    vm.session.cmd(scriptabspath)


def check_files(params, vm):
    """
    Asserts that some files exist on the guest VM and some others
    don't. Those files are provided by the Cartesian configuration
    and can be customized there.

    :param params: extended dictionary of parameters
    :type params: {str, str}
    :params vm: guest VM object
    :type vm: virttest.qemu_vm.VM
    """
    logging.info("Enter tutorial test variant two: check files.")

    must_exist = params["must_exist"].split(" ")
    must_not_exist = params["must_not_exist"].split(" ")
    files_prefix = params["test_prefix"]

    def aux(f):
        """Construct absolute path to file and test presence in fs verbosely."""
        fullpath = os.path.join(files_prefix, f)
        result = vm.session.cmd_status("! test -f " + fullpath)
        logging.info("  - Verifying the presence of file %s -> %s."
                     % (fullpath, result and "exists" or "nil"))
        return result

    missing = [f for f in must_exist if not aux(f)]
    unwanted = [f for f in must_not_exist if aux(f)]

    if missing and unwanted:
        logging.info(
            "Unluckily, we encountered both unwanted and missing files.")
        raise exceptions.TestFail(
            "%d mandatory files not found in path %s: \"%s\";\n"
            "%d unwanted files in path %s: \"%s\"."
            % (len(missing), files_prefix, ", ".join(missing),
               len(unwanted), files_prefix, ", ".join(unwanted)))
    elif missing:
        logging.info("Unluckily, some required files were missing.")
        raise exceptions.TestFail("%d mandatory files not found in path %s: \"%s\"."
                                  % (files_prefix, len(missing), ", ".join(missing)))
    elif unwanted:
        logging.info(
            "Unluckily, we tripped over files we really struggled to avoid.")
        raise exceptions.TestFail("%d unwanted files in path %s: \"%s\"."
                                  % (files_prefix, len(unwanted), ", ".join(unwanted)))


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

    # We use the kind parameter from the Cartesian configuration
    # to decide which test to run
    if params["kind"] == "names":
        extract_tarball(params, vm)
        run_extracted_script(params, vm)
    else:
        check_files(params, vm)
