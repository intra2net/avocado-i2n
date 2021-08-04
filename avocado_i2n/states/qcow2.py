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
import logging as log
logging = log.getLogger('avocado.test.' + __name__)

from avocado.utils import process

from .setup import StateBackend, StateOnBackend


#: off qemu states regex (0 vm size)
QEMU_OFF_STATES_REGEX = re.compile(r"^\d+\s+([\w\.]+)\s*(0 B)\s+\d{4}-\d\d-\d\d", flags=re.MULTILINE)
#: on qemu states regex (>0 vm size)
QEMU_ON_STATES_REGEX = re.compile(r"^\d+\s+([\w\.]+)\s*(?!0 B)(\d+e?[\-\+]?[\.\d]* \w+)\s+\d{4}-\d\d-\d\d", flags=re.MULTILINE)


class QCOW2Backend(StateBackend):
    """
    Backend manipulating image states as QCOW2 snapshots.

    ..todo:: There are utilities providing access to the Qemu image binary
             provided by Avocado VT similarly to the LV utilities used for the
             LVM backend instead of independently implemented here.
    """

    _require_running_object = False

    @classmethod
    def state_type(cls):
        """State type string representation depending used for logging."""
        return "on/vm" if cls._require_running_object else "off/image"

    @classmethod
    def show(cls, params, object=None):
        """
        Return a list of available states of a specific type.

        All arguments match the base class.
        """
        qemu_img = params.get("qemu_img_binary", "/usr/bin/qemu-img")
        image_path = get_image_path(params)
        logging.debug("Showing %s snapshots for image %s", cls.state_type(), image_path)
        on_snapshots_dump = process.system_output("%s snapshot -l %s -U" % (qemu_img, image_path)).decode()
        pattern = QEMU_ON_STATES_REGEX if cls._require_running_object else QEMU_OFF_STATES_REGEX
        state_tuples = re.findall(pattern, on_snapshots_dump)
        states = []
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
        object_name = params["vms"] if cls._require_running_object else params["vms"] + "/" + params["images"]
        logging.debug("Checking %s for %s state '%s'", object_name,
                      cls.state_type(), params["check_state"])
        states = cls.show(params, object)
        for state in states:
            if state == params["check_state"]:
                logging.info("The %s snapshot '%s' of %s exists",
                             cls.state_type(), params["check_state"],
                             object_name)
                return True
        # at this point we didn't find the on state in the listed ones
        logging.info("The %s snapshot '%s' of %s doesn't exist",
                     cls.state_type(), params["check_state"],
                     object_name)
        return False

    @classmethod
    def get(cls, params, object=None):
        """
        Retrieve a state disregarding the current changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        state, image_name = params["get_state"], params["images"]
        qemu_img = params.get("qemu_img_binary", "/usr/bin/qemu-img")
        logging.info("Reusing %s state '%s' of %s/%s", cls.state_type(), state,
                     vm_name, image_name)
        image_path = get_image_path(params)
        process.system("%s snapshot -a %s %s" % (qemu_img, state, image_path))

    @classmethod
    def set(cls, params, object=None):
        """
        Store a state saving the current changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        state, image_name = params["set_state"], params["images"]
        qemu_img = params.get("qemu_img_binary", "/usr/bin/qemu-img")
        logging.info("Creating %s state '%s' of %s/%s", cls.state_type(), state,
                     vm_name, image_name)
        image_path = get_image_path(params)
        process.system("%s snapshot -c %s %s" % (qemu_img, state, image_path))

    @classmethod
    def unset(cls, params, object=None):
        """
        Remove a state with previous changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        state, image_name = params["unset_state"], params["images"]
        qemu_img = params.get("qemu_img_binary", "/usr/bin/qemu-img")
        logging.info("Removing %s state '%s' of %s/%s", cls.state_type(), state,
                     vm_name, image_name)
        image_path = get_image_path(params)
        process.system("%s snapshot -d %s %s" % (qemu_img, state, image_path))


class QCOW2VTBackend(StateOnBackend, QCOW2Backend):
    """Backend manipulating vm states as QCOW2 snapshots using VT's VM bindings."""

    _require_running_object = True

    @classmethod
    def get(cls, params, object=None):
        """
        Retrieve a state disregarding the current changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        logging.info("Reusing vm state '%s' of %s", params["get_state"], vm_name)
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
        logging.info("Setting vm state '%s' of %s", params["set_state"], vm_name)
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
        logging.info("Removing vm state '%s' of %s", params["unset_state"], vm_name)
        vm.pause()
        # NOTE: this was supposed to be implemented in the Qemu VM object but
        # it is not unlike savevm and loadvm, perhaps due to command availability
        vm.verify_status('paused')
        logging.debug("Deleting VM %s from %s", vm_name, params["unset_state"])
        vm.monitor.send_args_cmd("delvm id=%s" % params["unset_state"])
        vm.verify_status('paused')
        vm.resume(timeout=3)


def get_image_path(params):
    """
    Get the absolute path to a QCOW2 image.

    :param params: configuration parameters
    :type params: {str, str}
    :returns: absolute path to the QCOW2 image
    :rtype: str
    """
    image_name = params["image_name"]
    image_format = params.get("image_format")
    if image_format is None:
        raise ValueError(f"Unspecified image format for {image_name} - "
                         "must be qcow2 or raw")
    if image_format not in ["raw", "qcow2"]:
        raise ValueError(f"Incompatible image format {image_format} for"
                         f" {image_name} - must be qcow2 or raw")
    if not os.path.isabs(image_name):
        image_name = os.path.join(params["images_base_dir"], image_name)
    image_format = "" if image_format == "raw" else "." + image_format
    image_path = image_name + image_format
    return image_path


def convert_image(params):
    """
    Convert a raw img to a QCOW2 or other image usable for virtual machines.

    :param params: configuration parameters
    :type params: {str, str}
    :raises: py:class:`FileNotFoundError` if the source image doesn't exist
    :raises: py:class:`AssertionError` when the source image is in use

    .. note:: This function could be used with qemu-img for more general images
        and not just the QCOW2 format.
    """
    qemu_img = params.get("qemu_img_binary", "/usr/bin/qemu-img")
    raw_directory = params.get("raw_image_dir", ".")
    # allow the user to specify a path prefix for image files
    logging.info(f"Using image prefix {raw_directory}")

    source_image = os.path.join(raw_directory, params[f"raw_image"])
    target_image = get_image_path(params)
    target_format = params["image_format"]

    if not os.path.isfile(source_image):
        raise FileNotFoundError(f"Source image {source_image} doesn't exist")

    # create the target directory if needed
    target_directory = os.path.dirname(target_image)
    os.makedirs(target_directory, exist_ok=True)

    if os.path.isfile(target_image):
        logging.debug(f"{target_image} already exists, checking if it's in use")
        try:
            process.run(f"{qemu_img} check {target_image}")
            logging.debug(f"{target_image} not in use, integrity asserted")
        except process.CmdError as ex:
            # file is in use
            if "\"write\" lock" in ex.result.stderr_text:
                logging.error(f"{target_image} is in use, refusing to convert")
                raise
            logging.debug(f"{target_image} exists but cannot check integrity")
        logging.info(f"Overwriting existing {target_image}")

    logging.debug(f"Converting image {source_image} to {target_image} formatted to {target_format}")
    process.run(f"{qemu_img} convert -c -p -O {target_format} \"{source_image}\" \"{target_image}\"",
                timeout=params.get_numeric("conversion_timeout", 12000))
    logging.debug("Conversion successful")
