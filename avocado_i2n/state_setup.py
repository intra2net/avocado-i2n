# Copyright 2013-2020 Intranet AG and contributors
#
# avocado-i2n is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# avocado-i2n is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with avocado-i2n.  If not, see <http://www.gnu.org/licenses/>.

"""

SUMMARY
------------------------------------------------------
Utility to manage off and on virtual machine states.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import os
import re
import logging
import glob

from avocado.core import exceptions
from avocado.utils import process
from avocado.utils import lv_utils


#: keywords reserved for off root states
OFF_ROOTS = ['root', '0root']
#: keywords reserved for on root states
ON_ROOTS = ['boot', '0boot']
# TODO: use "\d+\s+([\w\.]+)\s*([\w\. ]+)\s+\d{4}-\d\d-\d\d" to restore allowing
# digits in the state name once the upstream Qemu handles the reported bug:
# https://bugs.launchpad.net/qemu/+bug/1859989
#: qemu states regex
QEMU_STATES_REGEX = re.compile("\d+\s+([a-zA-Z_\.]+)\s*([\w\. ]+)\s+\d{4}-\d\d-\d\d")


def set_root(run_params):
    """
    Create a ramdisk, virtual group, thin pool and logical volume
    for each vm (all off).

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :raises: :py:class:`exceptions.TestError` if the root state already exists
    """
    vms = run_params.objects("vms")
    for vm_name in vms:
        vm_params = run_params.object_params(vm_name)

        if lv_utils.vg_check(vm_params["vg_name"]):
            if vm_params.get("force_create", "no") == "yes":
                logging.info("Removing the previously created %s", vm_name)
                if vm_params.get("image_raw_device", "yes") == "no":
                    mount_loc = os.path.dirname(vm_params["image_name"])
                    # mount to avoid not-mounted errors
                    try:
                        lv_utils.lv_mount(vm_params["vg_name"],
                                          vm_params["lv_pointer_name"],
                                          mount_loc)
                    except lv_utils.LVException:
                        pass
                    lv_utils.lv_umount(vm_params["vg_name"],
                                       vm_params["lv_pointer_name"])
                logging.debug("Removing previous volume group of %s", vm_name)
                lv_utils.vg_ramdisk_cleanup(vm_params["ramdisk_sparse_filename"],
                                            os.path.join(vm_params["ramdisk_basedir"],
                                                         vm_params["vg_name"]),
                                            vm_params["vg_name"],
                                            None,
                                            vm_params["use_tmpfs"] == "yes")
            else:
                raise exceptions.TestError("The root state of %s already exists" % vm_name)

        logging.info("Preparing original logical volume for %s", vm_name)
        lv_utils.vg_ramdisk(None,
                            vm_params["vg_name"],
                            vm_params["ramdisk_vg_size"],
                            vm_params["ramdisk_basedir"],
                            vm_params["ramdisk_sparse_filename"],
                            vm_params["use_tmpfs"] == "yes")
        lv_utils.lv_create(vm_params["vg_name"],
                           vm_params["lv_name"],
                           vm_params["lv_size"],
                           # NOTE: call by key to keep good argument order which wasn't
                           # accepted upstream for backward API compatibility
                           pool_name=vm_params["pool_name"],
                           pool_size=vm_params["pool_size"])
        lv_utils.lv_take_snapshot(vm_params["vg_name"],
                                  vm_params["lv_name"],
                                  vm_params["lv_pointer_name"])
        if vm_params.get("image_raw_device", "yes") == "no":
            mount_loc = os.path.dirname(vm_params["image_name"])
            if not os.path.exists(mount_loc):
                os.mkdir(mount_loc)
            lv_utils.lv_mount(vm_params["vg_name"], vm_params["lv_pointer_name"],
                              mount_loc, create_filesystem="ext4")


def unset_root(run_params):
    """
    Remove the ramdisk, virtual group, thin pool and logical volume
    of each vm (all off).

    :param run_params: configuration parameters
    :type run_params: {str, str}
    """
    vms = run_params.objects("vms")
    logging.info("Removing vms %s with their images", run_params["vms"])
    for vm_name in vms:
        vm_params = run_params.object_params(vm_name)
        try:
            if vm_params.get("image_raw_device", "yes") == "no":
                mount_loc = os.path.dirname(vm_params["image_name"])
                if lv_utils.vg_check(vm_params["vg_name"]):
                    # mount to avoid not-mounted errors
                    try:
                        lv_utils.lv_mount(vm_params["vg_name"],
                                          vm_params["lv_pointer_name"],
                                          mount_loc)
                    except lv_utils.LVException:
                        pass
                    lv_utils.lv_umount(vm_params["vg_name"],
                                       vm_params["lv_pointer_name"])
                if os.path.exists(mount_loc):
                    try:
                        os.rmdir(mount_loc)
                    except OSError as ex:
                        logging.warning("No permanent vm can be removed automatically. If "
                                        "this is not a permanent test object, see the debug.")
                        raise exceptions.TestWarn("Permanent vm %s was detected but cannot be "
                                                  "removed automatically" % vm_name)
            lv_utils.vg_ramdisk_cleanup(vm_params["ramdisk_sparse_filename"],
                                        os.path.join(vm_params["ramdisk_basedir"],
                                                     vm_params["vg_name"]),
                                        vm_params["vg_name"],
                                        None,
                                        vm_params["use_tmpfs"] == "yes")
        except exceptions.TestError as ex:
            logging.error(ex)


def show_states(run_params, env):
    """
    Return a list of available states of a specific type.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :param env: test environment
    :type env: Env object
    """
    states = []
    for vm_name in run_params.objects("vms"):
        vm_params = run_params.object_params(vm_name)

        if vm_params.get("check_type", "off") == "off":
            logging.debug("Checking %s for available off states", vm_name)
            states = lv_utils.lv_list(vm_params["vg_name"])
            logging.info("Detected off states for %s: %s", vm_name, ", ".join(states))
        else:
            if vm_params["check_type"] == "ramfile":
                state_dir = vm_params.get("image_name", "")
                state_dir = os.path.dirname(state_dir)
                state_path = os.path.join(state_dir, "*.state")
                states = glob.glob(state_path)
                logging.info("Detected ramfile snapshots for %s: %s", vm_name, ", ".join(states))
            else:
                vm_image = "%s.%s" % (vm_params["image_name"],
                                      vm_params.get("image_format", "qcow2"))
                qemu_img = vm_params.get("qemu_img_binary", "/usr/bin/qemu-img")
                on_snapshots_dump = process.system_output("%s snapshot -l %s -U" % (qemu_img, vm_image)).decode()
                state_tuples = re.findall(QEMU_STATES_REGEX, on_snapshots_dump)
                for state_tuple in state_tuples:
                    logging.info("Detected on state '%s' of size %s",
                                 state_tuple[0], state_tuple[1])
                    states.append(state_tuple[0])
    return states


def check_state(run_params, env,
                print_pos=False, print_neg=False):
    """
    Check whether a given state/snapshot exits and return True if it does,
    False otherwise.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :param env: test environment
    :type env: Env object
    :param bool print_pos: whether to print that the state was found
    :param bool print_neg: whether to print that the state wasn't found

    If not state type is specified explicitly, we will search for all types
    in order of performance (on->off).

    .. note:: Only one vm is generally expected in the received 'vms' parameter. If
        more than one are present, the setup for all will be evaluated through
        bitwise AND, i.e. it will determine the existence of a given state configuration.
    """
    exists = True
    for vm_name in run_params.objects("vms"):
        vm_params = run_params.object_params(vm_name)
        vm = env.get_vm(vm_name)
        # if the snapshot is not defined skip (leaf tests that are no setup)
        if not vm_params.get("check_state"):
            continue
        # NOTE: there is no concept of "check_mode" here
        vm_params["check_type"] = vm_params.get("check_type", "any")

        vm_params["vms"] = vm_name
        run_params["found_type_%s" % vm_name] = vm_params["check_type"]
        if vm_params["check_type"] == "any":
            vm_params["check_type"] = "on"
            run_params["found_type_%s" % vm_name] = "on"
            if not _check_state(vm, vm_params, print_pos=print_pos, print_neg=print_neg):
                vm_params["check_type"] = "ramfile"
                run_params["found_type_%s" % vm_name] = "ramfile"
                # BUG: currently "ramfile" is very error-prone so let's not mention it
                if not _check_state(vm, vm_params, print_pos=True, print_neg=False):
                    vm_params["check_type"] = "off"
                    run_params["found_type_%s" % vm_name] = "off"
                    if not _check_state(vm, vm_params, print_pos=print_pos, print_neg=print_neg):
                        # default type to treat in case of no result
                        run_params["found_type_%s" % vm_name] = "on"
                        exists = False
                        break
        elif not _check_state(vm, vm_params, print_pos=print_pos, print_neg=print_neg):
            exists = False
            break

    return exists


def get_state(run_params, env):
    """
    Retrieve a state/snapshot disregarding the current changes.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :param env: test environment
    :type env: Env object
    :raises: :py:class:`exceptions.TestSkipError` if the retrieved state doesn't exist,
        the vm is unavailable from the env, or snapshot exists in passive mode (abort)
    :raises: :py:class:`exceptions.TestError` if invalid policy was used
    """
    for vm_name in run_params.objects("vms"):
        vm = env.get_vm(vm_name)
        vm_params = run_params.object_params(vm_name)
        # if the snapshot is not defined skip (leaf tests that are no setup)
        if not vm_params.get("get_state"):
            continue
        vm_params["get_type"] = vm_params.get("get_type", "any")
        vm_params["get_mode"] = vm_params.get("get_mode", "ar")

        vm_params["vms"] = vm_name
        vm_params["check_type"] = vm_params["get_type"]
        vm_params["check_state"] = vm_params["get_state"]
        state_exists = check_state(vm_params, env, print_neg=True)
        # if too many or no matches default to most performant type
        vm_params["get_type"] = vm_params["found_type_%s" % vm_name]
        if state_exists:
            # on/off switch
            if vm_params["get_type"] in run_params.get("skip_types", []):
                logging.debug("Skip getting states of types %s" % ", ".join(run_params.objects("skip_types")))
                continue
            if vm is None:
                vm = env.create_vm(vm_params.get('vm_type'), vm_params.get('target'),
                                   vm_name, vm_params, None)
            # TODO: study better the environment pre/postprocessing details necessary for flawless
            # vm destruction and creation to improve the on/off switch
            if vm_params["get_type"] == "off":
                if vm.is_alive():
                    vm.destroy(gracefully=False)
            else:
                # on states require manual update of the vm parameters
                vm.params = vm_params
                if not vm.is_alive():
                    vm.create()

        action_if_exists = vm_params["get_mode"][0]
        action_if_doesnt_exist = vm_params["get_mode"][1]
        if not state_exists and "a" == action_if_doesnt_exist:
            logging.info("Aborting because of missing snapshot for setup")
            raise exceptions.TestSkipError("Snapshot '%s' of %s doesn't exist. Aborting "
                                           "due to passive mode." % (vm_params["get_state"], vm_name))
        elif not state_exists and "i" == action_if_doesnt_exist:
            logging.warn("Ignoring missing snapshot for setup")
        elif not state_exists:
            raise exceptions.TestError("Invalid policy %s: The start action on missing state can be "
                                       "either of 'abort', 'ignore'." % vm_params["get_mode"])
        elif state_exists and "a" == action_if_exists:
            logging.info("Aborting because of unwanted snapshot for setup")
            raise exceptions.TestSkipError("Snapshot '%s' of %s already exists. Aborting "
                                           "due to passive mode." % (vm_params["get_state"], vm_name))
        elif state_exists and "r" == action_if_exists:
            _get_state(vm, vm_params)
        elif state_exists and "i" == action_if_exists:
            logging.warn("Ignoring present snapshot for setup")
        elif state_exists:
            raise exceptions.TestError("Invalid policy %s: The start action on present state can be "
                                       "either of 'abort', 'reuse', 'ignore'." % vm_params["get_mode"])


def set_state(run_params, env):
    """
    Save cleanup states for vms with `set_state` parameter.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :param env: test environment
    :type env: Env object
    :raises: :py:class:`exceptions.TestSkipError` if unexpected/missing snapshot in passive mode (abort)
    :raises: :py:class:`exceptions.TestError` if invalid policy was used
    """
    for vm_name in run_params.objects("vms"):
        vm = env.get_vm(vm_name)
        vm_params = run_params.object_params(vm_name)
        # if the snapshot is not defined skip (leaf tests that are no setup)
        if not vm_params.get("set_state"):
            continue
        vm_params["set_type"] = vm_params.get("set_type", "any")
        vm_params["set_mode"] = vm_params.get("set_mode", "ff")

        vm_params["vms"] = vm_name
        vm_params["check_type"] = vm_params["set_type"]
        vm_params["check_state"] = vm_params["set_state"]
        state_exists = check_state(vm_params, env)
        # if too many or no matches default to most performant type
        vm_params["set_type"] = vm_params["found_type_%s" % vm_name]
        # on/off filter
        if vm_params["set_type"] in run_params.get("skip_types", []):
            logging.debug("Skip setting states of types %s" % ", ".join(run_params.objects("skip_types")))
            continue
        if vm_params["set_type"] == "off":
            vm.destroy(gracefully=True)
        # NOTE: setting an on state assumes that the vm is on just like
        # setting an off state assumes that the vm already exists

        action_if_exists = vm_params["set_mode"][0]
        action_if_doesnt_exist = vm_params["set_mode"][1]
        if state_exists and "a" == action_if_exists:
            logging.info("Aborting because of unwanted snapshot for later cleanup")
            raise exceptions.TestSkipError("Snapshot '%s' of %s already exists. Aborting "
                                           "due to passive mode." % (vm_params["set_state"], vm_name))
        elif state_exists and "r" == action_if_exists:
            logging.info("Keeping the already existing snapshot untouched")
        elif state_exists and "f" == action_if_exists:
            logging.info("Overwriting the already existing snapshot")
            if vm_params["set_state"] in OFF_ROOTS and vm_params["set_type"] == "off":
                unset_root(vm_params)
            elif vm_params["set_type"] == "off":
                vm_params["lv_snapshot_name"] = vm_params["set_state"]
                lv_utils.lv_remove(vm_params["vg_name"], vm_params["lv_snapshot_name"])
            else:
                logging.debug("Overwriting on snapshot simply by writing it again")
            _set_state(vm, vm_params)
        elif state_exists:
            raise exceptions.TestError("Invalid policy %s: The end action on present state can be "
                                       "either of 'abort', 'reuse', 'force'." % vm_params["set_mode"])
        elif not state_exists and "a" == action_if_doesnt_exist:
            logging.info("Aborting because of missing snapshot for later cleanup")
            raise exceptions.TestSkipError("Snapshot '%s' of %s doesn't exist. Aborting "
                                           "due to passive mode." % (vm_params["set_state"], vm_name))
        elif not state_exists and "f" == action_if_doesnt_exist:
            _set_state(vm, vm_params)
        elif not state_exists:
            raise exceptions.TestError("Invalid policy %s: The end action on missing state can be "
                                       "either of 'abort', 'force'." % vm_params["set_mode"])


def unset_state(run_params, env):
    """
    Remove cleanup states for vms with `unset_state` parameter.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :param env: test environment
    :type env: Env object
    :raises: :py:class:`exceptions.TestSkipError` if missing snapshot in passive mode (abort)
    :raises: :py:class:`exceptions.TestError` if invalid policy was used
    """
    for vm_name in run_params.objects("vms"):
        vm = env.get_vm(vm_name)
        vm_params = run_params.object_params(vm_name)
        if not vm_params.get("unset_state"):
            # if the snapshot is not defined skip (leaf tests that are no setup)
            continue
        vm_params["unset_type"] = vm_params.get("unset_type", "any")
        vm_params["unset_mode"] = vm_params.get("unset_mode", "fi")

        vm_params["vms"] = vm_name
        vm_params["check_type"] = vm_params["unset_type"]
        vm_params["check_state"] = vm_params["unset_state"]
        state_exists = check_state(vm_params, env, print_neg=True)
        # if too many or no matches default to most performant type
        vm_params["unset_type"] = vm_params["found_type_%s" % vm_name]
        # NOTE: no custom handling needed here

        action_if_exists = vm_params["unset_mode"][0]
        action_if_doesnt_exist = vm_params["unset_mode"][1]
        if not state_exists and "a" == action_if_doesnt_exist:
            logging.info("Aborting because of missing snapshot for final cleanup")
            raise exceptions.TestSkipError("Snapshot '%s' of %s doesn't exist. Aborting "
                                           "due to passive mode." % (vm_params["unset_state"], vm_name))
        elif not state_exists and "i" == action_if_doesnt_exist:
            logging.warn("Ignoring missing snapshot for final cleanup (will not be removed)")
        elif not state_exists:
            raise exceptions.TestError("Invalid policy %s: The unset action on missing state can be "
                                       "either of 'abort', 'ignore'." % vm_params["unset_mode"])
        elif state_exists and "r" == action_if_exists:
            logging.info("Preserving state '%s' of %s for later test runs", vm_params["unset_state"], vm_name)
        elif state_exists and "f" == action_if_exists:
            _unset_state(vm, vm_params)
        elif state_exists:
            raise exceptions.TestError("Invalid policy %s: The unset action on present state can be "
                                       "either of 'reuse', 'force'." % vm_params["unset_mode"])


def push_state(run_params, env):
    """
    Identical to the set operation but used within the push/pop pair.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :param env: test environment
    :type env: Env object
    """
    for vm_name in run_params.objects("vms"):
        vm_params = run_params.object_params(vm_name)
        vm_params["vms"] = vm_name

        if vm_params["push_state"] in OFF_ROOTS + ON_ROOTS:
            # cannot be done with root states
            continue

        vm_params["set_state"] = vm_params["push_state"]
        vm_params["set_type"] = vm_params.get("push_type", "any")
        vm_params["set_mode"] = vm_params.get("push_mode", "af")

        set_state(vm_params, env)


def pop_state(run_params, env):
    """
    Retrieve and remove a state/snapshot.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :param env: test environment
    :type env: Env object
    """
    for vm_name in run_params.objects("vms"):
        vm_params = run_params.object_params(vm_name)
        vm_params["vms"] = vm_name

        if vm_params["pop_state"] in OFF_ROOTS + ON_ROOTS:
            # cannot be done with root states
            continue

        vm_params["get_state"] = vm_params["pop_state"]
        vm_params["get_type"] = vm_params.get("pop_type", "any")
        vm_params["get_mode"] = vm_params.get("pop_mode", "ra")
        get_state(vm_params, env)
        vm_params["unset_state"] = vm_params["pop_state"]
        vm_params["unset_type"] = vm_params.get("pop_type", "any")
        vm_params["unset_mode"] = vm_params.get("pop_mode", "fa")
        unset_state(vm_params, env)


def _check_state(vm, vm_params, print_pos=False, print_neg=False):
    """
    Check for an on/off state of a vm object.

    We use LVM for off snapshots and QCOW2 for on snapshots.
    """
    vm_name = vm_params["vms"]
    if vm_params["check_type"] == "off":
        vm_params["lv_snapshot_name"] = vm_params["check_state"]
        if vm_params.get("check_state", "root") in OFF_ROOTS:
            logging.debug("Checking whether %s exists (root off state requested)", vm_name)
            if vm_params.get("image_format", "qcow2") != "raw":
                logging.debug("Checking using %s image", vm_params.get("image_format", "qcow2"))
                condition = os.path.exists("%s.%s" % (vm_params["image_name"],
                                                      vm_params.get("image_format", "qcow2")))
            else:
                logging.debug("Checking using raw image")
                condition = os.path.exists(vm_params["image_name"])
            if not condition and vm_params.get("vg_name") is not None:
                condition = lv_utils.lv_check(vm_params["vg_name"], vm_params["lv_name"])
            if not condition:
                if print_neg:
                    logging.info("The required virtual machine %s doesn't exist", vm_name)
                return False
            else:
                if print_pos:
                    logging.info("The required virtual machine %s exists", vm_name)
                return True
        else:
            logging.debug("Checking %s for off state '%s'", vm_name, vm_params["check_state"])
            if not lv_utils.lv_check(vm_params["vg_name"], vm_params["lv_snapshot_name"]):
                if print_neg:
                    logging.info("Off snapshot '%s' of %s doesn't exist",
                                 vm_params["check_state"], vm_name)
                return False
            else:
                if print_pos:
                    logging.info("Off snapshot '%s' of %s exists",
                                 vm_params["check_state"], vm_name)
                return True
    else:
        if vm_params.get("check_state", "boot") in ON_ROOTS:
            logging.debug("Checking whether %s is on (root on state requested)", vm_name)
            try:
                state_exists = vm.is_alive()
            except ValueError:
                state_exists = False
            if state_exists and print_pos:
                logging.info("The required virtual machine %s is on", vm_name)
            elif not state_exists and print_neg:
                logging.info("The required virtual machine %s is off", vm_name)
            return state_exists
        else:
            if vm_params["check_type"] == "ramfile":
                state_dir = vm_params.get("image_name", "")
                state_dir = os.path.dirname(state_dir)
                state_file = os.path.join(state_dir, vm_params["check_state"])
                state_file = "%s.state" % state_file
                if not os.path.exists(state_file):
                    if print_neg:
                        logging.info("Ramfile snapshot '%s' of %s doesn't exist",
                                     vm_params["check_state"], vm_name)
                    return False
                else:
                    if print_pos:
                        logging.info("Ramfile snapshot '%s' of %s exists",
                                     vm_params["check_state"], vm_name)
                    return True
            else:
                logging.debug("Checking %s for on state '%s'",
                              vm_name, vm_params["check_state"])

                vm_image = "%s.%s" % (vm_params["image_name"],
                                      vm_params.get("image_format", "qcow2"))
                if not os.path.exists(vm_image):
                    return False
                qemu_img = vm_params.get("qemu_img_binary", "/usr/bin/qemu-img")
                on_snapshots_dump = process.system_output("%s snapshot -l %s -U" % (qemu_img, vm_image)).decode()
                logging.debug("Listed on states:\n%s", on_snapshots_dump)
                state_tuples = re.findall(QEMU_STATES_REGEX, on_snapshots_dump)
                for state_tuple in state_tuples:
                    logging.debug("Detected on state '%s' of size %s",
                                  state_tuple[0], state_tuple[1])
                    if state_tuple[0] == vm_params["check_state"]:
                        if print_pos:
                            logging.info("On snapshot '%s' of %s exists",
                                         vm_params["check_state"], vm_name)
                        return True
                # at this point we didn't find the on state in the listed ones
                if print_neg:
                    logging.info("On snapshot '%s' of %s doesn't exist",
                                 vm_params["check_state"], vm_name)
                return False


def _get_state(vm, vm_params):
    """
    Get to an on/off state of a vm object.

    We use LVM for off snapshots and QCOW2 for on snapshots.
    """
    vm_name = vm_params["vms"]
    if vm_params["get_state"] in OFF_ROOTS + ON_ROOTS:
        # reusing root states (off root and on boot) is analogical to not doing anything
        return

    if vm_params["get_type"] == "off":
        vm_params["lv_snapshot_name"] = vm_params["get_state"]
        if vm_params.get("image_raw_device", "yes") == "no":
            mount_loc = os.path.dirname(vm_params["image_name"])
            # mount to avoid not-mounted errors
            try:
                lv_utils.lv_mount(vm_params["vg_name"],
                                  vm_params["lv_pointer_name"],
                                  mount_loc)
            except lv_utils.LVException:
                pass
            lv_utils.lv_umount(vm_params["vg_name"],
                               vm_params["lv_pointer_name"])
        try:
            logging.info("Restoring %s to state %s", vm_name, vm_params["get_state"])
            lv_utils.lv_remove(vm_params["vg_name"], vm_params["lv_pointer_name"])
            lv_utils.lv_take_snapshot(vm_params["vg_name"],
                                      vm_params["lv_snapshot_name"],
                                      vm_params["lv_pointer_name"])
        finally:
            if vm_params.get("image_raw_device", "yes") == "no":
                mount_loc = os.path.dirname(vm_params["image_name"])
                lv_utils.lv_mount(vm_params["vg_name"],
                                  vm_params["lv_pointer_name"],
                                  mount_loc)
    else:
        logging.info("Reusing on state '%s' of %s", vm_params["get_state"], vm_name)
        vm.pause()
        # NOTE: second on type is available and still supported but not recommended
        if vm_params["get_type"] != "ramfile":
            vm.loadvm(vm_params["get_state"])
        else:
            state_dir = vm_params.get("image_name", "")
            state_dir = os.path.dirname(state_dir)
            state_file = os.path.join(state_dir, vm_params["get_state"])
            state_file = "%s.state" % state_file
            vm.restore_from_file(state_file)
        vm.resume(timeout=3)


def _set_state(vm, vm_params):
    """
    Set an on/off state of a vm object.

    We use LVM for off snapshots and QCOW2 for on snapshots.
    """
    vm_name = vm_params["vms"]
    if vm_params["set_state"] in OFF_ROOTS:
        # vm_params["vms"] = vm_name
        vm_params["main_vm"] = vm_name
        set_root(vm_params)
    elif vm_params["set_type"] == "off":
        vm_params["lv_snapshot_name"] = vm_params["set_state"]
        logging.info("Taking a snapshot '%s' of %s", vm_params["set_state"], vm_name)
        lv_utils.lv_take_snapshot(vm_params["vg_name"],
                                  vm_params["lv_pointer_name"],
                                  vm_params["lv_snapshot_name"])
    elif vm_params["set_state"] in ON_ROOTS:
        # set boot state
        if vm is None or not vm.is_alive():
            vm.create()
    else:
        logging.info("Setting on state '%s' of %s", vm_params["set_state"], vm_name)
        vm.pause()
        # NOTE: second on type is available and still supported but not recommended
        if vm_params["set_type"] != "ramfile":
            vm.savevm(vm_params["set_state"])
        else:
            state_dir = vm_params.get("image_name", "")
            state_dir = os.path.dirname(state_dir)
            state_file = os.path.join(state_dir, vm_params["set_state"])
            state_file = "%s.state" % state_file
            vm.save_to_file(state_file)
            # BUG: because the built-in functionality uses system_reset
            # which leads to unclean file systems in some cases it is
            # better to restore from the saved state
            vm.restore_from_file(state_file)
        vm.resume(timeout=3)


def _unset_state(vm, vm_params):
    """
    Unset an on/off state of a vm object.

    We use LVM for off snapshots and QCOW2 for on snapshots.
    """
    vm_name = vm_params["vms"]
    if vm_params["unset_state"] in OFF_ROOTS:
        # off switch to protect from on leftover state
        if vm is not None and vm.is_alive():
            vm.destroy(gracefully=False)
        # vm_params["vms"] = vm_name
        vm_params["main_vm"] = vm_name
        unset_root(vm_params)
    elif vm_params["unset_type"] == "off":
        lv_pointer = vm_params["lv_pointer_name"]
        if vm_params["unset_state"] == lv_pointer:
            raise ValueError("Cannot unset built-in off state '%s'" % lv_pointer)
        vm_params["lv_snapshot_name"] = vm_params["unset_state"]
        logging.info("Removing snapshot %s of %s", vm_params["lv_snapshot_name"], vm_name)
        lv_utils.lv_remove(vm_params["vg_name"], vm_params["lv_snapshot_name"])
    elif vm_params["unset_state"] in ON_ROOTS:
        if vm is not None and vm.is_alive():
            vm.destroy(gracefully=False)
    else:
        logging.info("Removing on state '%s' of %s", vm_params["unset_state"], vm_name)
        vm.pause()
        # NOTE: second on type is available and still supported but not recommended
        if vm_params["unset_type"] != "ramfile":
            # NOTE: this was supposed to be implemented in the Qemu VM object but
            # it is not unlike savevm and loadvm, perhaps due to command availability
            vm.verify_status('paused')
            logging.debug("Deleting VM %s from %s", vm_name, vm_params["unset_state"])
            vm.monitor.send_args_cmd("delvm id=%s" % vm_params["unset_state"])
            vm.verify_status('paused')
        else:
            state_dir = vm_params.get("image_name", "")
            state_dir = os.path.dirname(state_dir)
            state_file = os.path.join(state_dir, vm_params["set_state"])
            state_file = "%s.state" % state_file
            os.unlink(state_file)
        vm.resume(timeout=3)
