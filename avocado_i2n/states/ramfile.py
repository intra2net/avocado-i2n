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
import logging
import glob

from .setup import StateOnBackend


class RamfileBackend(StateOnBackend):
    """
    Backend manipulating on states as ram dump files.

    ..note:: This "on" backend is available and still supported but not recommended.
    """

    _require_running_object = True

    @classmethod
    def _get_state_dir(cls, params):
        """
        Get the path to the ramfile dumps directory.

        :param params: configuration parameters
        :type params: {str, str}
        :returns: validated to be the same directory to dump ramfile states
        :rtype: str
        """
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
        state_dir = RamfileBackend._get_state_dir(params)
        state_path = os.path.join(state_dir, "*.state")
        return glob.glob(state_path)

    @classmethod
    def check(cls, params, object=None):
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

    @classmethod
    def get(cls, params, object=None):
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

    @classmethod
    def set(cls, params, object=None):
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

    @classmethod
    def unset(cls, params, object=None):
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
