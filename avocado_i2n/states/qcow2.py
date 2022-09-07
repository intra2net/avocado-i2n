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
import shutil
import logging as log
logging = log.getLogger('avocado.test.' + __name__)

from virttest.qemu_storage import QemuImg

from .setup import StateBackend, StateOnBackend


#: off qemu states regex (0 vm size)
QEMU_OFF_STATES_REGEX = re.compile(r"^\d+\s+([\w\.-]+)\s*(0 B)\s+\d{4}-\d\d-\d\d", flags=re.MULTILINE)
#: on qemu states regex (>0 vm size)
QEMU_ON_STATES_REGEX = re.compile(r"^\d+\s+([\w\.-]+)\s*(?!0 B)(\d+e?[\-\+]?[\.\d]* \w+)\s+\d{4}-\d\d-\d\d", flags=re.MULTILINE)


class QCOW2Backend(StateBackend):
    """Backend manipulating image states as internal QCOW2 snapshots."""

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
        qemu_img = QemuImg(params, params["images_base_dir"], params["images"])
        logging.debug("Showing %s internal states for image %s", cls.state_type(), params["images"])
        on_snapshots_dump = qemu_img.snapshot_list(force_share=True)
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
        state, image = params["get_state"], params["images"]
        params["image_chain"] = f"{image} snapshot"
        params["image_raw_device_snapshot"] = "yes"
        params["image_name_snapshot"] = state
        qemu_img = QemuImg(params, params["images_base_dir"], image)
        logging.info("Reusing %s state '%s' of %s/%s", cls.state_type(), state,
                     vm_name, image)
        qemu_img.snapshot_apply()

    @classmethod
    def set(cls, params, object=None):
        """
        Store a state saving the current changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        state, image = params["set_state"], params["images"]
        params["image_chain"] = f"{image} snapshot"
        params["image_raw_device_snapshot"] = "yes"
        params["image_name_snapshot"] = state
        qemu_img = QemuImg(params, params["images_base_dir"], image)
        logging.info("Creating %s state '%s' of %s/%s", cls.state_type(), state,
                     vm_name, image)
        qemu_img.snapshot_create()

    @classmethod
    def unset(cls, params, object=None):
        """
        Remove a state with previous changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        state, image = params["unset_state"], params["images"]
        params["image_chain"] = f"{image} snapshot"
        params["image_raw_device_snapshot"] = "yes"
        params["image_name_snapshot"] = state
        qemu_img = QemuImg(params, params["images_base_dir"], image)
        logging.info("Removing %s state '%s' of %s/%s", cls.state_type(), state,
                     vm_name, image)
        qemu_img.snapshot_del()


class QCOW2ExtBackend(QCOW2Backend):
    """Backend manipulating image states as external QCOW2 snapshots."""

    _require_running_object = False

    @classmethod
    def show(cls, params, object=None):
        """
        Return a list of available states of a specific type.

        All arguments match the base class.
        """
        image = params["images"]
        qemu_img = QemuImg(params, params["images_base_dir"], image)
        logging.debug("Showing %s external states for image %s", cls.state_type(), params["images"])
        image_dir = os.path.join(os.path.dirname(qemu_img.image_filename), image)
        if not os.path.exists(image_dir):
            return []
        snapshots = os.listdir(image_dir)
        states = []
        for snapshot in snapshots:
            if not snapshot.endswith(".qcow2"):
                continue
            size = os.stat(os.path.join(image_dir, snapshot)).st_size
            state = snapshot[:-6]
            logging.info(f"Detected {cls.state_type()} state '{state}' of size "
                         f"{round(size / 1024**3, 3)} GB ({size})")
            states.append(state)
        return states

    @classmethod
    def get(cls, params, object=None):
        """
        Retrieve a state disregarding the current changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        state, image = params["get_state"], params["images"]
        params["image_chain"] = f"snapshot {image}"
        params["image_name_snapshot"] = os.path.join(image, state)
        params["image_format_snapshot"] = "qcow2"
        qemu_img = QemuImg(params, params["images_base_dir"], image)
        logging.info("Reusing %s state '%s' of %s/%s", cls.state_type(), state,
                     vm_name, image)
        qemu_img.create(params, ignore_errors=False)

    @classmethod
    def set(cls, params, object=None):
        """
        Store a state saving the current changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        state, image = params["set_state"], params["images"]
        qemu_img = QemuImg(params, params["images_base_dir"], image)
        logging.info("Creating %s state '%s' of %s/%s", cls.state_type(), state,
                     vm_name, image)
        image_dir = os.path.join(os.path.dirname(qemu_img.image_filename), image)
        os.makedirs(image_dir, exist_ok=True)
        shutil.copy(qemu_img.image_filename, os.path.join(image_dir, state + ".qcow2"))

    @classmethod
    def unset(cls, params, object=None):
        """
        Remove a state with previous changes.

        All arguments match the base class.
        """
        vm, vm_name = object, params["vms"]
        state, image = params["unset_state"], params["images"]
        qemu_img = QemuImg(params, params["images_base_dir"], image)
        logging.info("Removing %s state '%s' of %s/%s", cls.state_type(), state,
                     vm_name, image)
        image_dir = os.path.join(os.path.dirname(qemu_img.image_filename), image)
        # TODO: should we mv to pointer image in case removed state is in backing chain?
        os.unlink(os.path.join(image_dir, state + ".qcow2"))


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
    raw_directory = params.get("raw_image_dir", ".")
    raw_image = params["raw_image"]
    # allow the user to specify a path prefix for image files
    logging.info(f"Using image prefix {raw_directory}")
    source_image = os.path.join(raw_directory, raw_image)
    params.update({"image_name_rawimg1": source_image,
                   "image_format_rawimg1": "raw",
                   "image_raw_device_rawimg1": "yes"})
    source_qemu_img = QemuImg(params, raw_directory, "rawimg1")

    if not os.path.isfile(source_image):
        raise FileNotFoundError(f"Source image {source_image} doesn't exist")

    target_qemu_img = QemuImg(params, params["images_base_dir"], params["images"])
    target_image = get_image_path(params)
    # create the target directory if needed
    target_directory = os.path.dirname(target_image)
    os.makedirs(target_directory, exist_ok=True)

    if os.path.isfile(target_image):
        logging.debug(f"{target_image} already exists, checking if it's in use")
        result = target_qemu_img.check(params, params["images_base_dir"])
        if result.exit_status == 0:
            logging.debug(f"{target_image} not in use, integrity asserted")
        else:
            if "\"write\" lock" in result.stderr_text:
                logging.error(f"{target_image} is in use, refusing to convert")
                raise
            logging.debug(f"{target_image} exists but cannot check integrity")
        logging.info(f"Overwriting existing {target_image}")

    params["convert_target"] = params["images"]
    params["convert_compressed"] = "yes"
    source_qemu_img.convert(params, params["images_base_dir"])

    logging.debug("Conversion successful")
