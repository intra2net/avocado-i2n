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
Module for the ramfile state management backend.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import os
import logging as log
logging = log.getLogger('avocado.test.' + __name__)

from virttest import env_process

from .setup import StateBackend


class RamfileBackend(StateBackend):
    """Backend manipulating vm states as ram dump files."""

    image_state_backend = None

    @classmethod
    def _get_state_dir(cls, params):
        """
        Get the path to the ramfile dumps directory.

        :param params: configuration parameters
        :type params: {str, str}
        :returns: validated to be the same directory to dump ramfile states
        :rtype: str
        """
        if len(params.objects("images")) > 1:
            raise NotImplementedError("Currently only one image per vm is supported")
        image_name = params["image_name"]
        if not os.path.isabs(image_name):
            image_name = os.path.join(params["images_base_dir"], image_name)
        return os.path.dirname(image_name)

    @classmethod
    def show(cls, params, object=None):
        """
        Return a list of available states of a specific type.

        All arguments match the base class.
        """
        logging.debug(f"Showing states for vm {params['vms']}")
        state_dir = RamfileBackend._get_state_dir(params)
        snapshots = os.listdir(state_dir)
        image_snapshots = cls.image_state_backend.show(params, object)
        states = []
        for snapshot in snapshots:
            if not snapshot.endswith(".state"):
                continue
            size = os.stat(os.path.join(state_dir, snapshot)).st_size
            state = snapshot[:-6]
            logging.info(f"Detected memory state '{snapshot}' of size "
                         f"{round(size / 1024**3, 3)} GB ({size})")
            if state in image_snapshots:
                logging.info(f"Memory state '{snapshot}' is a complete vm state")
                states.append(state)
        return states

    @classmethod
    def check(cls, params, object=None):
        """
        Check whether a given state exists.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        logging.debug("Checking %s for vm state '%s'", vm_name, params["check_state"])
        states = cls.show(params, vm)
        for state in states:
            if state == params["check_state"]:
                logging.info("The vm snapshot '%s' of %s exists",
                             params["check_state"], vm_name)
                return True
        # at this point we didn't find the state in the listed ones
        logging.info("The vm snapshot '%s' of %s doesn't exist",
                     params["check_state"], vm_name)
        return False

    @classmethod
    def get(cls, params, object=None):
        """
        Retrieve a state disregarding the current changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        logging.info("Reusing vm state '%s' of %s", params["get_state"], vm_name)
        vm.destroy(gracefully=False)
        cls.image_state_backend.get(params, vm)
        state_dir = RamfileBackend._get_state_dir(params)
        state_file = os.path.join(state_dir, params["check_state"] + ".state")
        vm.restore_from_file(state_file)
        vm.resume(timeout=3)

    @classmethod
    def set(cls, params, object=None):
        """
        Store a state saving the current changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        logging.info("Setting vm state '%s' of %s", params["set_state"], vm_name)
        vm.pause()
        state_dir = RamfileBackend._get_state_dir(params)
        state_file = os.path.join(state_dir, params["check_state"] + ".state")
        vm.save_to_file(state_file)
        vm.destroy(gracefully=False)
        cls.image_state_backend.set(params, vm)
        # BUG: because the built-in functionality uses system_reset
        # which leads to unclean file systems in some cases it is
        # better to restore from the saved state
        vm.restore_from_file(state_file)
        vm.resume(timeout=3)

    @classmethod
    def unset(cls, params, object=None):
        """
        Remove a state with previous changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        logging.info("Removing vm state '%s' of %s", params["unset_state"], vm_name)
        vm.pause()
        cls.image_state_backend.unset(params, vm)
        state_dir = RamfileBackend._get_state_dir(params)
        state_file = os.path.join(state_dir, params["check_state"] + ".state")
        os.unlink(state_file)
        vm.resume(timeout=3)

    @classmethod
    def check_root(cls, params, object=None):
        """
        Check whether a root state or essentially the object is running.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        logging.debug("Checking whether %s's root state is fully available", vm_name)

        state_dir = os.path.join(params["vms_base_dir"], params["vms"])
        if not os.path.exists(state_dir):
            logging.info("The base directory for the virtual machine %s is missing", vm_name)
            return False

        for image in params.objects("images"):
            image_params = params.object_params(image)
            image_name = image_params["image_name"]
            if not os.path.isabs(image_name):
                image_name = os.path.join(image_params["images_base_dir"], image_name)
            image_format = image_params.get("image_format", "qcow2")
            image_format = "" if image_format in ["raw", ""] else "." + image_format
            if not os.path.exists(image_name + image_format):
                logging.info("The required virtual machine %s has a missing image %s",
                             vm_name, image_name + image_format)
                return False

        if not params.get_boolean("use_env", True):
            return True
        logging.debug("Checking whether %s is on (boot state requested)", vm_name)
        vm = object
        if vm is not None and vm.is_alive():
            logging.info("The required virtual machine %s is on", vm_name)
            return True
        else:
            logging.info("The required virtual machine %s is off", vm_name)
            return False

    @classmethod
    def set_root(cls, params, object=None):
        """
        Set a root state to provide running object.

        All arguments match the base class.

        ..todo:: study better the environment pre/postprocessing details necessary
                 for flawless vm destruction and creation to improve these
        """
        vm_name = params["vms"]
        for image in params.objects("images"):
            image_params = params.object_params(image)
            image_name = image_params["image_name"]
            if not os.path.isabs(image_name):
                image_name = os.path.join(image_params["images_base_dir"], image_name)
            image_format = image_params.get("image_format")
            image_format = "" if image_format in ["raw", ""] else "." + image_format
            if not os.path.exists(image_name + image_format):
                logging.info("Creating image %s in order to boot %s",
                             image_name + image_format, vm_name)
                os.makedirs(os.path.dirname(image_name), exist_ok=True)
                image_params.update({"create_image": "yes", "force_create_image": "yes"})
                env_process.preprocess_image(None, image_params, image_name)
        if not params.get_boolean("use_env", True):
            return
        logging.info("Booting %s to provide boot state", vm_name)
        vm = object
        if vm is None:
            raise ValueError("Need an environmental object to boot")
            #vm = env.create_vm(params.get('vm_type'), params.get('target'),
            #                   vm_name, params, None)
        if not vm.is_alive():
            vm.create()

    @classmethod
    def unset_root(cls, params, object=None):
        """
        Unset a root state to prevent object from running.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        logging.info("Shutting down %s to prevent boot state", vm_name)
        vm = object
        if vm is not None and vm.is_alive():
            vm.destroy(gracefully=False)
