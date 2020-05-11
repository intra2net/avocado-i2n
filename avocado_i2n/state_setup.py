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
from virttest import env_process


class StateBackend():
    """A general backend implementing state manipulation."""

    @staticmethod
    def show(params, object=None):
        """
        Return a list of available states of a specific type.

        :param params: configuration parameters
        :type params: {str, str}
        :param object: object whose states are manipulated
        :type object: VM object or None
        :returns: list of detected states
        :rtype: [str]
        """
        raise NotImplementedError("Cannot use abstract state backend")

    @staticmethod
    def check(params, object=None):
        """
        Check whether a given state exists.

        :param params: configuration parameters
        :type params: {str, str}
        :param object: object whose states are manipulated
        :type object: VM object or None
        :returns: whether the state is exists
        :rtype: bool
        """
        raise NotImplementedError("Cannot use abstract state backend")

    @staticmethod
    def get(params, object=None):
        """
        Retrieve a state disregarding the current changes.

        :param params: configuration parameters
        :type params: {str, str}
        :param object: object whose states are manipulated
        :type object: VM object or None
        """
        raise NotImplementedError("Cannot use abstract state backend")

    @staticmethod
    def set(params, object=None):
        """
        Store a state saving the current changes.

        :param params: configuration parameters
        :type params: {str, str}
        :param object: object whose states are manipulated
        :type object: VM object or None
        """
        raise NotImplementedError("Cannot use abstract state backend")

    @staticmethod
    def unset(params, object=None):
        """
        Remove a state with previous changes.

        :param params: configuration parameters
        :type params: {str, str}
        :param object: object whose states are manipulated
        :type object: VM object or None
        """
        raise NotImplementedError("Cannot use abstract state backend")

    @staticmethod
    def check_root(params, object=None):
        """
        Check whether a root state or essentially the object exists.

        :param params: configuration parameters
        :type params: {str, str}
        :param object: object whose states are manipulated
        :type object: VM object or None
        :returns: whether the object (root state) is exists
        :rtype: bool
        """
        vm_name = params["vms"]
        check_opts = params.get_dict("check_opts")
        print_pos, print_neg = check_opts["print_pos"] == "yes", check_opts["print_neg"] == "yes"
        logging.debug("Checking whether %s exists (root state requested)", vm_name)
        condition = True
        for image in params.objects("images"):
            image_params = params.object_params(image)
            image_name = image_params["image_name"]
            if not os.path.isabs(image_name):
                image_name = os.path.join(image_params["images_base_dir"], image_name)
            image_format = image_params.get("image_format", "qcow2")
            logging.debug("Checking for %s image %s", image_format, image_name)
            image_format = "" if image_format == "raw" else "." + image_format
            condition = os.path.exists(image_name + image_format)
            if condition and print_pos:
                logging.info("The required virtual machine %s exists", vm_name)
            if not condition and print_neg:
                logging.info("The required virtual machine %s doesn't exist", vm_name)
            if not condition:
                break
        return condition

    @staticmethod
    def get_root(params, object=None):
        """
        Get a root state or essentially due to pre-existence do nothing.

        :param params: configuration parameters
        :type params: {str, str}
        :param object: object whose states are manipulated
        :type object: VM object or None
        """
        pass

    @staticmethod
    def set_root(params, object=None):
        """
        Set a root state to provide object existence.

        :param params: configuration parameters
        :type params: {str, str}
        :param object: object whose states are manipulated
        :type object: VM object or None
        """
        vm_name = params["vms"]
        for image in params.objects("images"):
            image_params = params.object_params(image)
            image_name = image_params["image_name"]
            if not os.path.isabs(image_name):
                image_name = os.path.join(image_params["images_base_dir"], image_name)
            logging.info("Creating image %s for %s", image_name, vm_name)
            image_params.update({"create_image": "yes", "force_create_image": "yes"})
            env_process.preprocess_image(None, image_params, image_name)

    @staticmethod
    def unset_root(params, object=None):
        """
        Unset a root state to prevent object existence.

        :param params: configuration parameters
        :type params: {str, str}
        :param object: object whose states are manipulated
        :type object: VM object or None
        """
        vm_name = params["vms"]
        for image in params.objects("images"):
            image_params = params.object_params(image)
            image_name = image_params["image_name"]
            if not os.path.isabs(image_name):
                image_name = os.path.join(image_params["images_base_dir"], image_name)
            logging.info("Removing image %s for %s", image_name, vm_name)
            image_params.update({"remove_image": "yes"})
            env_process.postprocess_image(None, image_params, image_name)


class LVMBackend(StateBackend):
    """Backend manipulating off states as logical volumes."""

    @staticmethod
    def _get_images_mount_loc(params):
        """
        Get the path to the mount location for the logical volume.

        :param params: configuration parameters
        :type params: {str, str}
        :returns: mount location for the logical volume or empty string if a
                  raw image device is used
        :rtype: str
        """
        if params.get_boolean("image_raw_device", True):
            return ""
        mount_loc = None
        assert "images" in params.keys(), "Need 'images' definition for mounting"
        for image in params.objects("images"):
            image_params = params.object_params(image)
            image_name = image_params["image_name"]
            if mount_loc is None:
                if os.path.isabs(image_name):
                    mount_loc = os.path.dirname(image_name)
                else:
                    mount_loc = image_params["images_base_dir"]
            else:
                if os.path.isabs(image_name):
                    has_different_values = mount_loc != os.path.dirname(image_name)
                else:
                    has_different_values = mount_loc != image_params.get("images_base_dir")
                if has_different_values:
                    # it would be best to assert this but let's be more permissive
                    # to allow for stranger configuration hoping that the user knows
                    # what they are doing
                    logging.warning("Not all vm images are located in the same logical"
                                    " volume mount directory - choosing the first one"
                                    " as the actual mount location")
        if mount_loc is None:
            raise exceptions.TestError("Cannot identify LV mount location for the image"
                                       " %s with path %s" % (image, image_name))
        return mount_loc

    @staticmethod
    def show(params, object=None):
        """
        Return a list of available states of a specific type.

        All arguments match the base class.
        """
        return lv_utils.lv_list(params["vg_name"])

    @staticmethod
    def check(params, object=None):
        """
        Check whether a given state exists.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        check_opts = params.get_dict("check_opts")
        print_pos, print_neg = check_opts["print_pos"] == "yes", check_opts["print_neg"] == "yes"
        params["lv_snapshot_name"] = params["check_state"]
        logging.debug("Checking %s for off state '%s'", vm_name, params["check_state"])
        condition = lv_utils.lv_check(params["vg_name"], params["lv_snapshot_name"])
        if condition and print_pos:
            logging.info("Off snapshot '%s' of %s exists", params["check_state"], vm_name)
        if not condition and print_neg:
            logging.info("Off snapshot '%s' of %s doesn't exist", params["check_state"], vm_name)
        return condition

    @staticmethod
    def get(params, object=None):
        """
        Retrieve a state disregarding the current changes.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        mount_loc = LVMBackend._get_images_mount_loc(params)
        params["lv_snapshot_name"] = params["get_state"]
        if mount_loc:
            # mount to avoid not-mounted errors
            try:
                lv_utils.lv_mount(params["vg_name"],
                                  params["lv_pointer_name"],
                                  mount_loc)
            except lv_utils.LVException:
                pass
            lv_utils.lv_umount(params["vg_name"],
                               params["lv_pointer_name"])
        try:
            logging.info("Restoring %s to state %s", vm_name, params["get_state"])
            lv_utils.lv_remove(params["vg_name"], params["lv_pointer_name"])
            lv_utils.lv_take_snapshot(params["vg_name"],
                                      params["lv_snapshot_name"],
                                      params["lv_pointer_name"])
        finally:
            if mount_loc:
                lv_utils.lv_mount(params["vg_name"],
                                  params["lv_pointer_name"],
                                  mount_loc)

    @staticmethod
    def set(params, object=None):
        """
        Store a state saving the current changes.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        params["lv_snapshot_name"] = params["set_state"]
        logging.info("Taking a snapshot '%s' of %s", params["set_state"], vm_name)
        lv_utils.lv_take_snapshot(params["vg_name"],
                                  params["lv_pointer_name"],
                                  params["lv_snapshot_name"])

    @staticmethod
    def unset(params, object=None):
        """
        Remove a state with previous changes.

        All arguments match the base class and in addition:

        :raises: :py:class:`ValueError` if LV pointer state was used
        """
        vm_name = params["vms"]
        lv_pointer = params["lv_pointer_name"]
        if params["unset_state"] == lv_pointer:
            raise ValueError("Cannot unset built-in off state '%s'" % lv_pointer)
        params["lv_snapshot_name"] = params["unset_state"]
        logging.info("Removing snapshot %s of %s", params["lv_snapshot_name"], vm_name)
        lv_utils.lv_remove(params["vg_name"], params["lv_snapshot_name"])

    @staticmethod
    def check_root(params, object=None):
        """
        Check whether a root state or essentially the object exists.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        check_opts = params.get_dict("check_opts")
        print_pos, print_neg = check_opts["print_pos"] == "yes", check_opts["print_neg"] == "yes"
        logging.debug("Checking whether %s exists (root off state requested)", vm_name)
        condition = lv_utils.lv_check(params["vg_name"], params["lv_name"])
        if condition and print_pos:
            logging.info("The required virtual machine %s exists", vm_name)
        if not condition and print_neg:
            logging.info("The required virtual machine %s doesn't exist", vm_name)
        return condition

    @staticmethod
    def set_root(params, object=None):
        """
        Set a root state to provide object existence.

        All arguments match the base class.

        Create a ramdisk, virtual group, thin pool and logical volume
        for each object (all off).
        """
        vm_name = params["vms"]
        mount_loc = LVMBackend._get_images_mount_loc(params)
        logging.info("Creating original logical volume for %s", vm_name)
        lv_utils.vg_ramdisk(None,
                            params["vg_name"],
                            params["ramdisk_vg_size"],
                            params["ramdisk_basedir"],
                            params["ramdisk_sparse_filename"],
                            params["use_tmpfs"] == "yes")
        lv_utils.lv_create(params["vg_name"],
                           params["lv_name"],
                           params["lv_size"],
                           # NOTE: call by key to keep good argument order which wasn't
                           # accepted upstream for backward API compatibility
                           pool_name=params["pool_name"],
                           pool_size=params["pool_size"])
        lv_utils.lv_take_snapshot(params["vg_name"],
                                  params["lv_name"],
                                  params["lv_pointer_name"])
        if mount_loc:
            if not os.path.exists(mount_loc):
                os.mkdir(mount_loc)
            lv_utils.lv_mount(params["vg_name"], params["lv_pointer_name"],
                              mount_loc, create_filesystem="ext4")
            super(LVMBackend, LVMBackend).set_root(params, object)

    @staticmethod
    def unset_root(params, object=None):
        """
        Unset a root state to prevent object existence.

        All arguments match the base class and in addition:

        :raises: :py:class:`exceptions.TestWarn` if permanent vm was detected

        Remove the ramdisk, virtual group, thin pool and logical volume
        of each object (all off).
        """
        vm_name = params["vms"]
        mount_loc = LVMBackend._get_images_mount_loc(params)
        logging.info("Removing original logical volume for %s", vm_name)
        try:
            if mount_loc:
                if lv_utils.vg_check(params["vg_name"]):
                    # mount to avoid not-mounted errors
                    try:
                        lv_utils.lv_mount(params["vg_name"],
                                          params["lv_pointer_name"],
                                          mount_loc)
                    except lv_utils.LVException:
                        pass
                    lv_utils.lv_umount(params["vg_name"],
                                       params["lv_pointer_name"])
                if os.path.exists(mount_loc):
                    try:
                        os.rmdir(mount_loc)
                    except OSError as ex:
                        logging.warning("No permanent vm can be removed automatically. If "
                                        "this is not a permanent test object, see the debug.")
                        raise exceptions.TestWarn("Permanent vm %s was detected but cannot be "
                                                  "removed automatically" % vm_name)
            lv_utils.vg_ramdisk_cleanup(params["ramdisk_sparse_filename"],
                                        os.path.join(params["ramdisk_basedir"],
                                                     params["vg_name"]),
                                        params["vg_name"],
                                        None,
                                        params["use_tmpfs"] == "yes")
        except exceptions.TestError as ex:
            logging.error(ex)


class QCOW2Backend(StateBackend):
    """Backend manipulating on states as qcow2 snapshots."""

    @staticmethod
    def show(params, object=None):
        """
        Return a list of available states of a specific type.

        All arguments match the base class.
        """
        states = []
        qemu_img = params.get("qemu_img_binary", "/usr/bin/qemu-img")
        for image in params.objects("images"):
            image_params = params.object_params(image)
            image_name = image_params["image_name"]
            image_format = image_params.get("image_format", "qcow2")
            if not os.path.isabs(image_name):
                image_name = os.path.join(image_params["images_base_dir"], image_name)
            logging.debug("Showing snapshots for %s image %s", image_format, image_name)
            image_format = "" if image_format == "raw" else "." + image_format
            image_path = image_name + image_format
            on_snapshots_dump = process.system_output("%s snapshot -l %s -U" % (qemu_img, image_path)).decode()
            state_tuples = re.findall(QEMU_STATES_REGEX, on_snapshots_dump)
            for state_tuple in state_tuples:
                logging.info("Detected on state '%s' of size %s", state_tuple[0], state_tuple[1])
                states.append(state_tuple[0])
        return states

    @staticmethod
    def check(params, object=None):
        """
        Check whether a given state exists.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        check_opts = params.get_dict("check_opts")
        print_pos, print_neg = check_opts["print_pos"] == "yes", check_opts["print_neg"] == "yes"
        logging.debug("Checking %s for on state '%s'", vm_name, params["check_state"])
        if not QCOW2Backend.check_root(params, object):
            return False
        states = QCOW2Backend.show(params, object)
        for state in states:
            if state == params["check_state"]:
                if print_pos:
                    logging.info("On snapshot '%s' of %s exists",
                                 params["check_state"], vm_name)
                return True
        # at this point we didn't find the on state in the listed ones
        if print_neg:
            logging.info("On snapshot '%s' of %s doesn't exist",
                         params["check_state"], vm_name)
        return False

    @staticmethod
    def get(params, object=None):
        """
        Retrieve a state disregarding the current changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        logging.info("Reusing on state '%s' of %s", params["get_state"], vm_name)
        vm.pause()
        vm.loadvm(params["get_state"])
        vm.resume(timeout=3)

    @staticmethod
    def set(params, object=None):
        """
        Store a state saving the current changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        logging.info("Setting on state '%s' of %s", params["set_state"], vm_name)
        vm.pause()
        vm.savevm(params["set_state"])
        vm.resume(timeout=3)

    @staticmethod
    def unset(params, object=None):
        """
        Remove a state with previous changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        logging.info("Removing on state '%s' of %s", params["unset_state"], vm_name)
        vm.pause()
        # NOTE: this was supposed to be implemented in the Qemu VM object but
        # it is not unlike savevm and loadvm, perhaps due to command availability
        vm.verify_status('paused')
        logging.debug("Deleting VM %s from %s", vm_name, params["unset_state"])
        vm.monitor.send_args_cmd("delvm id=%s" % params["unset_state"])
        vm.verify_status('paused')
        vm.resume(timeout=3)

    @staticmethod
    def check_root(params, object=None):
        """
        Check whether a root state or essentially the object exists.

        All arguments match the base class and in addition:

        :raises: :py:class:`ValueError` if the used image format is either
                 unspecified or not the required QCOW2
        """
        for image in params.objects("images"):
            image_params = params.object_params(image)
            if image_params.get("image_format") is None:
                raise ValueError("Unspecified image format for %s - must be qcow2" % image)
            if image_params["image_format"] != "qcow2":
                raise ValueError("Incompatible image format %s for %s - must be qcow2"
                                 % (params["image_format"], image))
        return super(QCOW2Backend, QCOW2Backend).check_root(params, object)


class RamfileBackend(StateBackend):
    """
    Backend manipulating on states as ram dump files.

    ..note:: This "on" bakcend is available and still supported but not recommended.
    """

    @staticmethod
    def _get_state_dir(params):
        """
        Get the path to the ramfile dumps directory.

        :param params: configuration parameters
        :type params: {str, str}
        :returns: validated to be the same directory to dump ramfile states
        :rtype: str
        """
        state_dir = None
        assert "images" in params.keys(), "Need 'images' definition for state directory"
        for image in params.objects("images"):
            image_params = params.object_params(image)
            image_name = image_params["image_name"]
            if not os.path.isabs(image_name):
                image_name = os.path.join(image_params["images_base_dir"], image_name)
            if state_dir is None:
                state_dir = os.path.dirname(image_name)
            else:
                assert state_dir == os.path.dirname(image_name), "All vm images "\
                    "must be located in the same statefile dump directory"
        return state_dir

    @staticmethod
    def show(params, object=None):
        """
        Return a list of available states of a specific type.

        All arguments match the base class.
        """
        state_dir = RamfileBackend._get_state_dir(params)
        state_path = os.path.join(state_dir, "*.state")
        return glob.glob(state_path)

    @staticmethod
    def check(params, object=None):
        """
        Check whether a given state exists.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        check_opts = params.get_dict("check_opts")
        print_pos, print_neg = check_opts["print_pos"] == "yes", check_opts["print_neg"] == "yes"
        state_dir = RamfileBackend._get_state_dir(params)
        state_file = os.path.join(state_dir, params["check_state"] + ".state")
        condition = os.path.exists(state_file)
        if condition and print_pos:
            logging.info("Ramfile snapshot '%s' of %s exists", params["check_state"], vm_name)
        if not condition and print_neg:
            logging.info("Ramfile snapshot '%s' of %s doesn't exist", params["check_state"], vm_name)
        return condition

    @staticmethod
    def get(params, object=None):
        """
        Retrieve a state disregarding the current changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        logging.info("Reusing on state '%s' of %s", params["get_state"], vm_name)
        vm.pause()
        state_dir = RamfileBackend._get_state_dir(params)
        state_file = os.path.join(state_dir, params["check_state"] + ".state")
        vm.restore_from_file(state_file)
        vm.resume(timeout=3)

    @staticmethod
    def set(params, object=None):
        """
        Store a state saving the current changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        logging.info("Setting on state '%s' of %s", params["set_state"], vm_name)
        vm.pause()
        state_dir = RamfileBackend._get_state_dir(params)
        state_file = os.path.join(state_dir, params["check_state"] + ".state")
        vm.save_to_file(state_file)
        # BUG: because the built-in functionality uses system_reset
        # which leads to unclean file systems in some cases it is
        # better to restore from the saved state
        vm.restore_from_file(state_file)
        vm.resume(timeout=3)

    @staticmethod
    def unset(params, object=None):
        """
        Remove a state with previous changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        logging.info("Removing on state '%s' of %s", params["unset_state"], vm_name)
        vm.pause()
        state_dir = RamfileBackend._get_state_dir(params)
        state_file = os.path.join(state_dir, params["check_state"] + ".state")
        os.unlink(state_file)
        vm.resume(timeout=3)


#: off state implementation to use
off = LVMBackend
#: on state implementation to use
on = QCOW2Backend
#: keywords reserved for off root states
ROOTS = ['root', '0root']
#: keywords reserved for on root states
BOOTS = ['boot', '0boot']
# TODO: use "\d+\s+([\w\.]+)\s*([\w\. ]+)\s+\d{4}-\d\d-\d\d" to restore allowing
# digits in the state name once the upstream Qemu handles the reported bug:
# https://bugs.launchpad.net/qemu/+bug/1859989
#: qemu states regex
QEMU_STATES_REGEX = re.compile("\d+\s+([a-zA-Z_\.]+)\s*([\w\. ]+)\s+\d{4}-\d\d-\d\d")


def enforce_check(vm_params, vm=None):
    """
    Check for an on/off state of a vm object without any policy conditions.

    :param vm_params: configuration parameters
    :type vm_params: {str, str}
    :param vm: object whose states are manipulated
    :type vm: VM object or None
    :returns: whether the state is exists
    :rtype: bool
    """
    backend = off if vm_params["check_type"] == "off" else on
    vm_params["check_opts"] = vm_params.get("check_opts", "print_pos=no print_neg=no")
    check_opts = vm_params.get_dict("check_opts")
    print_pos, print_neg = check_opts["print_pos"] == "yes", check_opts["print_neg"] == "yes"
    if vm_params["check_state"] in ROOTS:
        return backend.check_root(vm_params, vm)
    elif vm_params["check_state"] in BOOTS:
        vm_name = vm_params["vms"]
        logging.debug("Checking whether %s is on (boot state requested)", vm_name)
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
        return backend.check(vm_params, vm)


def enforce_get(vm_params, vm=None):
    """
    Get to an on/off state of a vm object without any policy conditions.

    :param vm_params: configuration parameters
    :type vm_params: {str, str}
    :param vm: object whose states are manipulated
    :type vm: VM object or None
    """
    backend = off if vm_params["get_type"] == "off" else on
    if vm_params["get_state"] in ROOTS:
        backend.get_root(vm_params, vm)
    elif vm_params["get_state"] in BOOTS:
        # reusing both root and boot states is analogical to not doing anything
        return
    else:
        backend.get(vm_params, vm)


def enforce_set(vm_params, vm=None):
    """
    Set an on/off state of a vm object without any policy conditions.

    :param vm_params: configuration parameters
    :type vm_params: {str, str}
    :param vm: object whose states are manipulated
    :type vm: VM object or None
    """
    backend = off if vm_params["set_type"] == "off" else on
    if vm_params["set_state"] in ROOTS:
        backend.set_root(vm_params, vm)
    elif vm_params["set_state"] in BOOTS:
        # set boot state
        if vm is None or not vm.is_alive():
            vm.create()
    else:
        backend.set(vm_params, vm)


def enforce_unset(vm_params, vm=None):
    """
    Unset an on/off state of a vm object without any policy conditions.

    :param vm_params: configuration parameters
    :type vm_params: {str, str}
    :param vm: object whose states are manipulated
    :type vm: VM object or None
    """
    backend = off if vm_params["unset_type"] == "off" else on
    if vm_params["unset_state"] in ROOTS:
        # off switch to protect from on leftover state
        if vm is not None and vm.is_alive():
            vm.destroy(gracefully=False)
        backend.unset_root(vm_params, vm)
    elif vm_params["unset_state"] in BOOTS:
        if vm is not None and vm.is_alive():
            vm.destroy(gracefully=False)
    else:
        backend.unset(vm_params, vm)


def show_states(run_params, env):
    """
    Return a list of available states of a specific type.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :param env: test environment
    :type env: Env object
    :returns: list of detected states
    :rtype: [str]
    """
    states = []
    for vm_name in run_params.objects("vms"):
        vm_params = run_params.object_params(vm_name)
        vm_params["check_type"] = vm_params.get("check_type", "off")
        logging.debug("Checking %s for available %s states", vm_name, vm_params["check_type"])
        if vm_params["check_type"] == "off":
            states += off.show(vm_params, env)
        else:
            states += on.show(vm_params, env)
        logging.info("Detected %s states for %s: %s", vm_params["check_type"], vm_name, ", ".join(states))
    return states


def check_state(run_params, env):
    """
    Check whether a given state exits.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :param env: test environment
    :type env: Env object
    :returns: whether the given state exists
    :rtype: bool

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
        vm_params["check_opts"] = vm_params.get("check_opts", "print_pos=no print_neg=no")

        vm_params["vms"] = vm_name
        run_params["found_type_%s" % vm_name] = vm_params["check_type"]
        if vm_params["check_type"] == "any":
            vm_params["check_type"] = "on"
            run_params["found_type_%s" % vm_name] = "on"
            if not enforce_check(vm_params, vm):
                vm_params["check_type"] = "off"
                run_params["found_type_%s" % vm_name] = "off"
                if not enforce_check(vm_params, vm):
                    # default type to treat in case of no result
                    run_params["found_type_%s" % vm_name] = "on"
                    exists = False
                    break
        elif not enforce_check(vm_params, vm):
            exists = False
            break

    return exists


def get_state(run_params, env):
    """
    Retrieve a state disregarding the current changes.

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
        vm_params["check_opts"] = "print_pos=no print_neg=yes"
        state_exists = check_state(vm_params, env)
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
            logging.warning("Ignoring missing snapshot for setup")
        elif not state_exists:
            raise exceptions.TestError("Invalid policy %s: The start action on missing state can be "
                                       "either of 'abort', 'ignore'." % vm_params["get_mode"])
        elif state_exists and "a" == action_if_exists:
            logging.info("Aborting because of unwanted snapshot for setup")
            raise exceptions.TestSkipError("Snapshot '%s' of %s already exists. Aborting "
                                           "due to passive mode." % (vm_params["get_state"], vm_name))
        elif state_exists and "r" == action_if_exists:
            enforce_get(vm_params, vm)
        elif state_exists and "i" == action_if_exists:
            logging.warning("Ignoring present snapshot for setup")
        elif state_exists:
            raise exceptions.TestError("Invalid policy %s: The start action on present state can be "
                                       "either of 'abort', 'reuse', 'ignore'." % vm_params["get_mode"])


def set_state(run_params, env):
    """
    Store a state saving the current changes.

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
            backend = off if vm_params["set_type"] == "off" else on
            vm_params["unset_state"] = vm_params["set_state"]
            if vm_params["set_state"] in ROOTS:
                backend.unset_root(vm_params, vm)
            elif vm_params["set_type"] == "off":
                backend.unset(vm_params, vm)
            else:
                logging.debug("Overwriting on snapshot simply by writing it again")
            enforce_set(vm_params, vm)
        elif state_exists:
            raise exceptions.TestError("Invalid policy %s: The end action on present state can be "
                                       "either of 'abort', 'reuse', 'force'." % vm_params["set_mode"])
        elif not state_exists and "a" == action_if_doesnt_exist:
            logging.info("Aborting because of missing snapshot for later cleanup")
            raise exceptions.TestSkipError("Snapshot '%s' of %s doesn't exist. Aborting "
                                           "due to passive mode." % (vm_params["set_state"], vm_name))
        elif not state_exists and "f" == action_if_doesnt_exist:
            enforce_set(vm_params, vm)
        elif not state_exists:
            raise exceptions.TestError("Invalid policy %s: The end action on missing state can be "
                                       "either of 'abort', 'force'." % vm_params["set_mode"])


def unset_state(run_params, env):
    """
    Remove a state with previous changes.

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
        vm_params["check_opts"] = "print_pos=no print_neg=yes"
        state_exists = check_state(vm_params, env)
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
            logging.warning("Ignoring missing snapshot for final cleanup (will not be removed)")
        elif not state_exists:
            raise exceptions.TestError("Invalid policy %s: The unset action on missing state can be "
                                       "either of 'abort', 'ignore'." % vm_params["unset_mode"])
        elif state_exists and "r" == action_if_exists:
            logging.info("Preserving state '%s' of %s for later test runs", vm_params["unset_state"], vm_name)
        elif state_exists and "f" == action_if_exists:
            enforce_unset(vm_params, vm)
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

        if vm_params["push_state"] in ROOTS + BOOTS:
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

        if vm_params["pop_state"] in ROOTS + BOOTS:
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
