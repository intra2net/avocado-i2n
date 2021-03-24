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
Utility to manage off and on test object states.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import os
import logging

from avocado.core import exceptions
from virttest import env_process


#: list of all available state backends and operations
__all__ = ["OFF_BACKENDS", "ON_BACKENDS", "ROOTS",
           "show_states", "check_states",
           "get_states", "set_states", "unset_states",
           "push_states", "pop_states"]


class StateBackend():
    """A general backend implementing state manipulation."""

    _require_running_object = None

    @classmethod
    def state_type(cls):
        """State type string representation depending used for logging."""
        return "on" if cls._require_running_object else "off"

    @classmethod
    def show(cls, params, object=None):
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

    @classmethod
    def check(cls, params, object=None):
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

    @classmethod
    def get(cls, params, object=None):
        """
        Retrieve a state disregarding the current changes.

        :param params: configuration parameters
        :type params: {str, str}
        :param object: object whose states are manipulated
        :type object: VM object or None
        """
        raise NotImplementedError("Cannot use abstract state backend")

    @classmethod
    def set(cls, params, object=None):
        """
        Store a state saving the current changes.

        :param params: configuration parameters
        :type params: {str, str}
        :param object: object whose states are manipulated
        :type object: VM object or None
        """
        raise NotImplementedError("Cannot use abstract state backend")

    @classmethod
    def unset(cls, params, object=None):
        """
        Remove a state with previous changes.

        :param params: configuration parameters
        :type params: {str, str}
        :param object: object whose states are manipulated
        :type object: VM object or None
        """
        raise NotImplementedError("Cannot use abstract state backend")

    @classmethod
    def check_root(cls, params, object=None):
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
        image_name = params["image_name"]
        logging.debug("Checking whether %s's %s exists (root state requested)",
                      vm_name, image_name)
        if not os.path.isabs(image_name):
            image_name = os.path.join(params["images_base_dir"], image_name)
        image_format = params.get("image_format", "qcow2")
        logging.debug("Checking for %s image %s", image_format, image_name)
        image_format = "" if image_format == "raw" else "." + image_format
        if os.path.exists(image_name + image_format):
            logging.info("The required virtual machine %s's %s exists", vm_name, image_name)
            return True
        else:
            logging.info("The required virtual machine %s's %s doesn't exist", vm_name, image_name)
            return False

    @classmethod
    def get_root(cls, params, object=None):
        """
        Get a root state or essentially due to pre-existence do nothing.

        :param params: configuration parameters
        :type params: {str, str}
        :param object: object whose states are manipulated
        :type object: VM object or None
        """
        pass

    @classmethod
    def set_root(cls, params, object=None):
        """
        Set a root state to provide object existence.

        :param params: configuration parameters
        :type params: {str, str}
        :param object: object whose states are manipulated
        :type object: VM object or None
        """
        vm_name = params["vms"]
        image_name = params["image_name"]
        if not os.path.isabs(image_name):
            image_name = os.path.join(params["images_base_dir"], image_name)
        os.makedirs(os.path.dirname(image_name), exist_ok=True)
        logging.info("Creating image %s for %s", image_name, vm_name)
        params.update({"create_image": "yes", "force_create_image": "yes"})
        env_process.preprocess_image(None, params, image_name)

    @classmethod
    def unset_root(cls, params, object=None):
        """
        Unset a root state to prevent object existence.

        :param params: configuration parameters
        :type params: {str, str}
        :param object: object whose states are manipulated
        :type object: VM object or None
        """
        vm_name = params["vms"]
        image_name = params["image_name"]
        if not os.path.isabs(image_name):
            image_name = os.path.join(params["images_base_dir"], image_name)
        logging.info("Removing image %s for %s", image_name, vm_name)
        params.update({"remove_image": "yes"})
        env_process.postprocess_image(None, params, image_name)
        try:
            os.rmdir(os.path.dirname(image_name))
        except OSError as error:
            logging.debug("Image directory not yet empty: %s", error)


class StateOnBackend(StateBackend):
    """A general backend implementing on state manipulation."""

    _require_running_object = True

    @classmethod
    def check_root(cls, params, object=None):
        """
        Check whether a root state or essentially the object is running.

        All arguments match the base class.
        """
        vm_name = params["vms"]
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
        logging.info("Booting %s to provide boot state", vm_name)
        vm = object
        if vm is None:
            raise ValueError("Need an environmental object to boot")
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


#: available off state implementations
OFF_BACKENDS = {}
#: available on state implementations
ON_BACKENDS = {}
#: keywords reserved for root states
ROOTS = ['root', '0root', 'boot', '0boot']


def _state_check_chain(do, env, vm_name, vm_params, image_name, image_params):
    """
    State chain from set/set/unset states to check states.

    :param str do: get, set, or unset
    :param env: test environment
    :type env: Env object
    :param str vm_name: name of the vm to switch on/off
    :param vm_params: vm parameters of the vm to switch on/off
    :type vm_params: {str, str}
    :param str image_name: name of the vm's image which is processed
    :param image_params: image parameters of the vm's image which is processed
    :type image_params: {str, str}
    """
    image_params["check_state"] = image_params[f"{do}_state"]
    image_params["check_type"] = image_params[f"{do}_type"]
    if do == "set":
        image_params["check_opts"] = "soft_boot=yes"
    else:
        image_params["check_opts"] = "soft_boot=no"

    # restrict inner calls
    image_params["vms"] = vm_name
    image_params["images"] = image_name
    state_exists = check_states(image_params, env)

    # if too many or no matches default to most performant type
    image_params[f"{do}_type"] = image_params["check_type"]
    vm_params[f"{do}_type"] = image_params["check_type"]

    return state_exists


def show_states(run_params, env=None):
    """
    Return a list of available states of a specific type.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :param env: test environment or nothing if not needed
    :type env: Env object or None
    :returns: list of detected states
    :rtype: [str]
    """
    states = []
    for vm_name in run_params.objects("vms"):
        vm_params = run_params.object_params(vm_name)
        for image_name in vm_params.objects("images"):
            image_params = vm_params.object_params(image_name)
            image_params["check_type"] = image_params.get("check_type", "off")
            logging.debug("Checking %s for available %s states", vm_name, image_params["check_type"])
            backend = OFF_BACKENDS[image_params["off_states"]] if image_params["check_type"] == "off" \
                else ON_BACKENDS[image_params["on_states"]]
            states += backend.show(image_params, env)
        logging.info("Detected %s states for %s: %s", image_params["check_type"], vm_name, ", ".join(states))
    return states


def check_states(run_params, env=None):
    """
    Check whether a given state exits.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :type env: Env object or None
    :returns: list of detected states
    :returns: whether the given state exists
    :rtype: bool

    If not state type is specified explicitly, we will search for all types
    in order of performance (on->off).

    .. note:: Only one vm is generally expected in the received 'vms' parameter. If
        more than one are present, the setup for all will be evaluated through
        bitwise AND, i.e. it will determine the existence of a given state configuration.
    """
    for vm_name in run_params.objects("vms"):
        vm = env.get_vm(vm_name) if env is not None else None
        vm_params = run_params.object_params(vm_name)
        for image_name in vm_params.objects("images"):
            image_params = vm_params.object_params(image_name)

            # if the snapshot is not defined skip (leaf tests that are no setup)
            if not image_params.get("check_state"):
                continue
            # NOTE: there is no concept of "check_mode" here
            image_params["check_type"] = image_params.get("check_type", "any")
            image_params["check_opts"] = image_params.get("check_opts", "soft_boot=yes")
            # TODO: document after experimental period
            # - first position is for root, second for boot
            # - each position could either be reuse check result or force existence
            image_params["check_mode"] = image_params.get("check_mode", "rf")

            state = image_params["check_state"]
            stype = image_params["check_type"]

            # minimal filters
            # TODO: partially implemented backends imply we cannot check all images
            # at once for on states as we would do with get/set/unset operations
            if image_params.get_boolean("image_readonly", False):
                logging.warning(f"Incorrect configuration: cannot use any state "
                                 f"{state} as {image_name} is readonly - skipping")
                continue

            off_backend = OFF_BACKENDS[image_params["off_states"]]
            on_backend = ON_BACKENDS[image_params["on_states"]]
            backend = off_backend if image_params["check_type"] == "off" else on_backend

            action_if_root_exists = image_params["check_mode"][0]
            action_if_boot_exists = image_params["check_mode"][1]

            # always check the corresponding root state as a prerequisite
            if state not in ROOTS or stype != "off":
                root_exists = off_backend.check_root(image_params, vm)
                if not root_exists:
                    if action_if_root_exists == "f":
                        off_backend.set_root(image_params, vm)
                    elif action_if_root_exists == "r":
                        return False
                    else:
                        raise exceptions.TestError(f"Invalid policy {action_if_root_exists}: The root "
                                                   "check action can be either of 'reuse' or 'force'.")

            # optionally check a corresponding boot state as a prerequisite
            if state not in ROOTS or stype != "on":
                boot_exists = on_backend.check_root(image_params, vm)

                # need to passively detect type in order to support provision for boot states
                if stype == "any" and state not in ROOTS:
                    state_exists = True
                    initial_type = image_params["check_type"]
                    stype = "on"
                    if not boot_exists or not on_backend.check(image_params, vm):
                        stype = "off"
                        if not off_backend.check(image_params, vm):
                            # default type to treat in case of no result
                            stype = initial_type
                            state_exists = False
                    # set this for external reporting of detected type
                    run_params["check_type"] = stype
                elif state in ROOTS:
                    state_exists = backend.check_root(image_params, vm)
                else:
                    state_exists = backend.check(image_params, vm)

                if stype in image_params.objects('skip_types'):
                    pass
                elif not boot_exists and stype == "on":
                    if action_if_boot_exists == "f" and vm is None:
                        if env is None:
                            raise exceptions.TestError(f"Creating boot states requires an "
                                                       "environment object to be provided.")
                        vm = env.create_vm(vm_params.get('vm_type'), vm_params.get('target'),
                                           vm_name, vm_params, None)
                    elif action_if_boot_exists == "f":
                        # on states require manual update of the vm parameters
                        vm.params = vm_params
                        on_backend.set_root(image_params, vm)
                    elif action_if_boot_exists == "r":
                        return False
                    else:
                        raise exceptions.TestError(f"Invalid policy {action_if_boot_exists}: The boot "
                                                   "check action can be either of 'reuse' or 'force'.")
                # bonus: switch off the vm if the requested state is an off state
                elif boot_exists and stype == "off":
                    # TODO: this could be unified with the unset on root and we could
                    # eventually implement unset off root for the off root case above
                    if action_if_boot_exists == "f" and vm is not None and vm.is_alive():
                        vm.destroy(gracefully=image_params.get_dict("check_opts").get("soft_boot", "yes")=="yes")

            else:
                state_exists = on_backend.check_root(image_params, vm)

            if not state_exists:
                return False

    return True


def get_states(run_params, env=None):
    """
    Retrieve a state disregarding the current changes.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :type env: Env object or None
    :returns: list of detected states
    :raises: :py:class:`exceptions.TestSkipError` if the retrieved state doesn't exist,
        the vm is unavailable from the env, or snapshot exists in passive mode (abort)
    :raises: :py:class:`exceptions.TestError` if invalid policy was used
    """
    for vm_name in run_params.objects("vms"):
        vm = env.get_vm(vm_name) if env is not None else None
        vm_params = run_params.object_params(vm_name)
        all_images_at_once = False
        for image_name in vm_params.objects("images"):
            image_params = vm_params.object_params(image_name)

            # if the state is not defined skip (leaf tests that are no setup)
            if not image_params.get("get_state"):
                continue
            else:
                state = image_params["get_state"]
            image_params["get_type"] = image_params.get("get_type", "any")
            image_params["get_mode"] = image_params.get("get_mode", "ra")

            # minimal filters
            if all_images_at_once:
                logging.debug(f"Skip getting {state} separately, one get is for all {vm_name}")
                continue
            if image_params.get_boolean("image_readonly", False):
                logging.warning(f"Incorrect configuration: cannot use any state "
                                 f"{state} as {image_name} is readonly - skipping")
                continue

            state_exists = _state_check_chain("get", env, vm_name, vm_params, image_name, image_params)
            skip_types = run_params.objects('skip_types')
            if image_params["get_type"] in skip_types:
                logging.debug(f"Skip getting states of types {', '.join(skip_types)}")
                continue
            if image_params["get_type"] == "on":
                all_images_at_once = True

            backend = OFF_BACKENDS[image_params["off_states"]] if image_params["get_type"] == "off" \
                else ON_BACKENDS[image_params["on_states"]]

            action_if_exists = image_params["get_mode"][0]
            action_if_doesnt_exist = image_params["get_mode"][1]
            if not state_exists and "a" == action_if_doesnt_exist:
                logging.info("Aborting because of missing snapshot for setup")
                raise exceptions.TestSkipError("Snapshot '%s' of %s doesn't exist. Aborting "
                                               "due to passive mode." % (image_params["get_state"], vm_name))
            elif not state_exists and "i" == action_if_doesnt_exist:
                logging.warning("Ignoring missing snapshot for setup")
                continue
            elif not state_exists:
                raise exceptions.TestError("Invalid policy %s: The start action on missing state can be "
                                           "either of 'abort', 'ignore'." % image_params["get_mode"])
            elif state_exists and "a" == action_if_exists:
                logging.info("Aborting because of unwanted snapshot for setup")
                raise exceptions.TestSkipError("Snapshot '%s' of %s already exists. Aborting "
                                               "due to passive mode." % (image_params["get_state"], vm_name))
            elif state_exists and "r" == action_if_exists:
                pass
            elif state_exists and "i" == action_if_exists:
                logging.warning("Ignoring present snapshot for setup")
                continue
            elif state_exists:
                raise exceptions.TestError("Invalid policy %s: The start action on present state can be "
                                           "either of 'abort', 'reuse', 'ignore'." % image_params["get_mode"])

            if image_params["get_state"] in ROOTS:
                backend.get_root(image_params, vm)
            else:
                backend.get(image_params, vm)


def set_states(run_params, env=None):
    """
    Store a state saving the current changes.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :type env: Env object or None
    :returns: list of detected states
    :raises: :py:class:`exceptions.TestSkipError` if unexpected/missing snapshot in passive mode (abort)
    :raises: :py:class:`exceptions.TestError` if invalid policy was used
    """
    for vm_name in run_params.objects("vms"):
        vm = env.get_vm(vm_name) if env is not None else None
        vm_params = run_params.object_params(vm_name)
        all_images_at_once = False
        for image_name in vm_params.objects("images"):
            image_params = vm_params.object_params(image_name)

            # if the state is not defined skip (leaf tests that are no setup)
            if not image_params.get("set_state"):
                continue
            else:
                state = image_params["set_state"]
            image_params["set_type"] = image_params.get("set_type", "any")
            image_params["set_mode"] = image_params.get("set_mode", "ff")

            # minimal filters
            if all_images_at_once:
                logging.debug(f"Skip setting {state} separately, one set is for all {vm_name}")
                continue
            if image_params.get_boolean("image_readonly", False):
                logging.warning(f"Incorrect configuration: cannot use any state "
                                 f"{state} as {image_name} is readonly - skipping")
                continue

            state_exists = _state_check_chain("set", env, vm_name, vm_params, image_name, image_params)
            skip_types = run_params.objects('skip_types')
            if image_params["set_type"] in skip_types:
                logging.debug(f"Skip setting states of types {', '.join(skip_types)}")
                continue
            if image_params["set_type"] == "on":
                all_images_at_once = True

            backend = OFF_BACKENDS[image_params["off_states"]] if image_params["set_type"] == "off" \
                else ON_BACKENDS[image_params["on_states"]]

            action_if_exists = image_params["set_mode"][0]
            action_if_doesnt_exist = image_params["set_mode"][1]
            if state_exists and "a" == action_if_exists:
                logging.info("Aborting because of unwanted snapshot for later cleanup")
                raise exceptions.TestSkipError("Snapshot '%s' of %s already exists. Aborting "
                                               "due to passive mode." % (image_params["set_state"], vm_name))
            elif state_exists and "r" == action_if_exists:
                logging.info("Keeping the already existing snapshot untouched")
                continue
            elif state_exists and "f" == action_if_exists:
                logging.info("Overwriting the already existing snapshot")
                image_params["unset_state"] = image_params["set_state"]
                if image_params["set_state"] in ROOTS:
                    backend.unset_root(image_params, vm)
                elif image_params["set_type"] == "off":
                    backend.unset(image_params, vm)
                else:
                    logging.debug("Overwriting on snapshot simply by writing it again")
            elif state_exists:
                raise exceptions.TestError("Invalid policy %s: The end action on present state can be "
                                           "either of 'abort', 'reuse', 'force'." % image_params["set_mode"])
            elif not state_exists and "a" == action_if_doesnt_exist:
                logging.info("Aborting because of missing snapshot for later cleanup")
                raise exceptions.TestSkipError("Snapshot '%s' of %s doesn't exist. Aborting "
                                               "due to passive mode." % (image_params["set_state"], vm_name))
            elif not state_exists and "f" == action_if_doesnt_exist:
                if not image_params["set_state"] in ROOTS and not backend.check_root(image_params, vm):
                    raise exceptions.TestError("Cannot force set state without a root state, use enforcing check "
                                               "policy to also force root (existing stateful object) creation.")
            elif not state_exists:
                raise exceptions.TestError("Invalid policy %s: The end action on missing state can be "
                                           "either of 'abort', 'force'." % image_params["set_mode"])

            if image_params["set_state"] in ROOTS:
                backend.set_root(image_params, vm)
            else:
                backend.set(image_params, vm)


def unset_states(run_params, env=None):
    """
    Remove a state with previous changes.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :type env: Env object or None
    :returns: list of detected states
    :raises: :py:class:`exceptions.TestSkipError` if missing snapshot in passive mode (abort)
    :raises: :py:class:`exceptions.TestError` if invalid policy was used
    """
    for vm_name in run_params.objects("vms"):
        vm = env.get_vm(vm_name) if env is not None else None
        vm_params = run_params.object_params(vm_name)
        all_images_at_once = False
        for image_name in vm_params.objects("images"):
            image_params = vm_params.object_params(image_name)

            # if the state is not defined skip (leaf tests that are no setup)
            if not image_params.get("unset_state"):
                continue
            else:
                state = image_params["unset_state"]
            image_params["unset_type"] = image_params.get("unset_type", "any")
            image_params["unset_mode"] = image_params.get("unset_mode", "fi")

            # minimal filters
            if all_images_at_once:
                logging.debug(f"Skip unsetting {state} separately, one unset is for all {vm_name}")
                continue
            if image_params.get_boolean("image_readonly", False):
                logging.warning(f"Incorrect configuration: cannot use any state "
                                 f"{state} as {image_name} is readonly - skipping")
                continue

            state_exists = _state_check_chain("unset", env, vm_name, vm_params, image_name, image_params)

            skip_types = run_params.objects('skip_types')
            if image_params["unset_type"] in skip_types:
                logging.debug(f"Skip unsetting states of types {', '.join(skip_types)}")
                continue
            if image_params["unset_type"] == "on":
                all_images_at_once = True

            backend = OFF_BACKENDS[image_params["off_states"]] if image_params["unset_type"] == "off" \
                else ON_BACKENDS[image_params["on_states"]]

            action_if_exists = image_params["unset_mode"][0]
            action_if_doesnt_exist = image_params["unset_mode"][1]
            if not state_exists and "a" == action_if_doesnt_exist:
                logging.info("Aborting because of missing snapshot for final cleanup")
                raise exceptions.TestSkipError("Snapshot '%s' of %s doesn't exist. Aborting "
                                               "due to passive mode." % (image_params["unset_state"], vm_name))
            elif not state_exists and "i" == action_if_doesnt_exist:
                logging.warning("Ignoring missing snapshot for final cleanup (will not be removed)")
                continue
            elif not state_exists:
                raise exceptions.TestError("Invalid policy %s: The unset action on missing state can be "
                                           "either of 'abort', 'ignore'." % image_params["unset_mode"])
            elif state_exists and "r" == action_if_exists:
                logging.info("Preserving state '%s' of %s for later test runs", image_params["unset_state"], vm_name)
                continue
            elif state_exists and "f" == action_if_exists:
                pass
            elif state_exists:
                raise exceptions.TestError("Invalid policy %s: The unset action on present state can be "
                                           "either of 'reuse', 'force'." % image_params["unset_mode"])

            if image_params["unset_state"] in ROOTS:
                backend.unset_root(image_params, vm)
            else:
                backend.unset(image_params, vm)


def push_states(run_params, env=None):
    """
    Identical to the set operation but used within the push/pop pair.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :type env: Env object or None
    :returns: list of detected states
    """
    for vm_name in run_params.objects("vms"):
        vm_params = run_params.object_params(vm_name)
        for image_name in vm_params.objects("images"):
            image_params = vm_params.object_params(image_name)

            if image_params["push_state"] in ROOTS:
                # cannot be done with root states
                continue

            image_params["vms"] = vm_name
            image_params["images"] = image_name

            image_params["set_state"] = image_params["push_state"]
            image_params["set_type"] = image_params.get("push_type", "any")
            image_params["set_mode"] = image_params.get("push_mode", "af")

            set_states(image_params, env)


def pop_states(run_params, env=None):
    """
    Retrieve and remove a state/snapshot.

    :param run_params: configuration parameters
    :type run_params: {str, str}
    :type env: Env object or None
    :returns: list of detected states
    """
    for vm_name in run_params.objects("vms"):
        vm_params = run_params.object_params(vm_name)
        for image_name in vm_params.objects("images"):
            image_params = vm_params.object_params(image_name)

            if image_params["pop_state"] in ROOTS:
                # cannot be done with root states
                continue

            image_params["vms"] = vm_name
            image_params["images"] = image_name

            image_params["get_state"] = image_params["pop_state"]
            image_params["get_type"] = image_params.get("pop_type", "any")
            image_params["get_mode"] = image_params.get("pop_mode", "ra")
            get_states(image_params, env)

            image_params["unset_state"] = image_params["pop_state"]
            image_params["unset_type"] = image_params.get("pop_type", "any")
            image_params["unset_mode"] = image_params.get("pop_mode", "fa")
            unset_states(image_params, env)
