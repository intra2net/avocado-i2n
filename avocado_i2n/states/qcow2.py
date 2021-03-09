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
Module for the QCOW2 state management backends.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import os
import re
import logging

from avocado.utils import process

from .setup import StateBackend


#: qemu states regex
QEMU_STATES_REGEX = re.compile("\d+\s+([\w\.]+)\s*([\w\+\. ]+)\s+\d{4}-\d\d-\d\d")


class QCOW2Backend(StateBackend):
    """Backend manipulating off states as qcow2 snapshots."""

    _require_running_object = False

    def _get_image_path(self, params):
        """
        Get the absolute path to a QCOW2 image.

        :param params: configuration parameters
        :type params: {str, str}
        :returns: mount location for the logical volume or empty string if a
                  raw image device is used
        :rtype: str
        """
        image_name = params["image_name"]
        image_format = params.get("image_format", "qcow2")
        if not os.path.isabs(image_name):
            image_name = os.path.join(params["images_base_dir"], image_name)
        image_format = "" if image_format == "raw" else "." + image_format
        image_path = image_name + image_format
        return image_path

    @classmethod
    def show(cls, params, object=None):
        """
        Return a list of available states of a specific type.

        All arguments match the base class.
        """
        states = []
        qemu_img = params.get("qemu_img_binary", "/usr/bin/qemu-img")
        for image in params.objects("images"):
            image_params = params.object_params(image)
            image_path = self._get_image_path(image_params)
            logging.debug("Showing %s snapshots for image %s", cls.state_type(), image_path)
            on_snapshots_dump = process.system_output("%s snapshot -l %s -U" % (qemu_img, image_path)).decode()
            state_tuples = re.findall(QEMU_STATES_REGEX, on_snapshots_dump)
            for state_tuple in state_tuples:
                logging.info("Detected %s state '%s' of size %s", cls.state_type(), state_tuple[0], state_tuple[1])
                states.append(state_tuple[0])
        return states

    @classmethod
    def check(cls, params, object=None):
        """
        Check whether a given state exists.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        check_opts = params.get_dict("check_opts")
        print_pos, print_neg = check_opts["print_pos"] == "yes", check_opts["print_neg"] == "yes"
        logging.debug("Checking %s for %s state '%s'", vm_name, cls.state_type(), params["check_state"])
        if not cls.check_root(params, object):
            return False
        states = cls.show(params, object)
        for state in states:
            if state == params["check_state"]:
                if print_pos:
                    logging.info("The %s snapshot '%s' of %s exists",
                                 cls.state_type(), params["check_state"], vm_name)
                return True
        # at this point we didn't find the on state in the listed ones
        if print_neg:
            logging.info("The %s snapshot '%s' of %s doesn't exist",
                         cls.state_type(), params["check_state"], vm_name)
        return False

    @classmethod
    def get(cls, params, object=None):
        """
        Retrieve a state disregarding the current changes.

        All arguments match the base class.
        """
        vm, vm_name, state = object, params["vms"], params["get_state"]
        qemu_img = params.get("qemu_img_binary", "/usr/bin/qemu-img")
        logging.info("Reusing %s state '%s' of %s", cls.state_type(), params["get_state"], vm_name)
        for image in params.objects("images"):
            image_params = params.object_params(image)
            image_path = self._get_image_path(image_params)
            process.system("%s snapshot -a %s %s" % (qemu_img, state, image_path))

    @classmethod
    def set(cls, params, object=None):
        """
        Store a state saving the current changes.

        All arguments match the base class.
        """
        vm, vm_name, state = object, params["vms"], params["set_state"]
        qemu_img = params.get("qemu_img_binary", "/usr/bin/qemu-img")
        logging.info("Creating %s state '%s' of %s", cls.state_type(), params["set_state"], vm_name)
        for image in params.objects("images"):
            image_params = params.object_params(image)
            image_path = self._get_image_path(image_params)
            process.system("%s snapshot -c %s %s" % (qemu_img, state, image_path))

    @classmethod
    def unset(cls, params, object=None):
        """
        Remove a state with previous changes.

        All arguments match the base class.
        """
        vm, vm_name, state = object, params["vms"], params["unset_state"]
        qemu_img = params.get("qemu_img_binary", "/usr/bin/qemu-img")
        logging.info("Removing %s state '%s' of %s", cls.state_type(), params["unset_state"], vm_name)
        for image in params.objects("images"):
            image_params = params.object_params(image)
            image_path = self._get_image_path(image_params)
            process.system("%s snapshot -d %s %s" % (qemu_img, state, image_path))

    @classmethod
    def check_root(cls, params, object=None):
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


class QCOW2VTBackend(QCOW2Backend):
    """Backend manipulating on states as qcow2 snapshots using VT's VM bindings."""

    _require_running_object = True

    @classmethod
    def get(cls, params, object=None):
        """
        Retrieve a state disregarding the current changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        logging.info("Reusing on state '%s' of %s", params["get_state"], vm_name)
        vm.pause()
        vm.loadvm(params["get_state"])
        vm.resume(timeout=3)

    @classmethod
    def set(cls, params, object=None):
        """
        Store a state saving the current changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        logging.info("Setting on state '%s' of %s", params["set_state"], vm_name)
        vm.pause()
        vm.savevm(params["set_state"])
        vm.resume(timeout=3)

    @classmethod
    def unset(cls, params, object=None):
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
