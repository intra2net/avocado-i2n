# Copyright 2013-2021 Intranet AG and contributors
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
Module for the LVM state management backend.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import os
import logging

from avocado.core import exceptions
from avocado.utils import lv_utils

from .setup import StateBackend


class LVMBackend(StateBackend):
    """Backend manipulating off states as logical volumes."""

    _require_running_object = False

    @classmethod
    def _get_images_mount_loc(cls, params):
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

    @classmethod
    def show(cls, params, object=None):
        """
        Return a list of available states of a specific type.

        All arguments match the base class.
        """
        return lv_utils.lv_list(params["vg_name"])

    @classmethod
    def check(cls, params, object=None):
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

    @classmethod
    def get(cls, params, object=None):
        """
        Retrieve a state disregarding the current changes.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        mount_loc = cls._get_images_mount_loc(params)
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

    @classmethod
    def set(cls, params, object=None):
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

    @classmethod
    def unset(cls, params, object=None):
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

    @classmethod
    def check_root(cls, params, object=None):
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

    @classmethod
    def set_root(cls, params, object=None):
        """
        Set a root state to provide object existence.

        All arguments match the base class.

        Create a ramdisk, virtual group, thin pool and logical volume
        for each object (all off).
        """
        vm_name = params["vms"]
        mount_loc = cls._get_images_mount_loc(params)
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

    @classmethod
    def unset_root(cls, params, object=None):
        """
        Unset a root state to prevent object existence.

        All arguments match the base class and in addition:

        :raises: :py:class:`exceptions.TestWarn` if permanent vm was detected

        Remove the ramdisk, virtual group, thin pool and logical volume
        of each object (all off).
        """
        vm_name = params["vms"]
        mount_loc = cls._get_images_mount_loc(params)
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
