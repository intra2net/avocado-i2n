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
        check_opts = params.get_dict("check_opts")
        print_pos, print_neg = check_opts["print_pos"] == "yes", check_opts["print_neg"] == "yes"
        logging.debug("Checking whether %s exists (root state requested)", vm_name)
        condition = True
        image_name = params["image_name"]
        if not os.path.isabs(image_name):
            image_name = os.path.join(params["images_base_dir"], image_name)
        image_format = params.get("image_format", "qcow2")
        logging.debug("Checking for %s image %s", image_format, image_name)
        image_format = "" if image_format == "raw" else "." + image_format
        condition = os.path.exists(image_name + image_format)
        if condition and print_pos:
            logging.info("The required virtual machine %s exists", vm_name)
        if not condition and print_neg:
            logging.info("The required virtual machine %s doesn't exist", vm_name)
        return condition

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


#: available off state implementations
OFF_BACKENDS = {}
#: available on state implementations
ON_BACKENDS = {}
#: keywords reserved for off root states
ROOTS = ['root', '0root']
#: keywords reserved for on root states
BOOTS = ['boot', '0boot']


def enforce_check(image_params, vm=None):
    """
    Check for an on/off state of a vm object without any policy conditions.

    :param image_params: configuration parameters for a particular image
    :type image_params: {str, str}
    :param vm: object whose states are manipulated
    :type vm: VM object or None
    :returns: whether the state is exists
    :rtype: bool
    """
    backend = OFF_BACKENDS[image_params["off_states"]] if image_params["check_type"] == "off" \
        else ON_BACKENDS[image_params["on_states"]]

    image_params["check_opts"] = image_params.get("check_opts", "print_pos=no print_neg=no")
    check_opts = image_params.get_dict("check_opts")
    print_pos, print_neg = check_opts["print_pos"] == "yes", check_opts["print_neg"] == "yes"
    if image_params["check_state"] in ROOTS:
        return backend.check_root(image_params, vm)
    elif image_params["check_state"] in BOOTS:
        vm_name = image_params["vms"]
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
        return backend.check(image_params, vm)


def on_off_switch(do, skip_types, vm, vm_name, vm_params):
    """
    An on/off switch for on/off state transitions.

    :param str do: get, set, or unset
    :param skip_types: types to skip in this switch passthrough
    :type skip_types: [str]
    :param vm: vm to switch on/off if any is already available
    :type vm: VM object or None
    :param str vm_name: name of the vm to switch on/off
    :param vm_params: vm parameters of the vm to switch on/off
    :type vm_params: {str, str}
    :returns: whether the vm is ready for the state operation
    :rtype: bool

    ..todo:: study better the environment pre/postprocessing details necessary
             for flawless vm destruction and creation to improve this switch
    """
    if vm_params[f"{do}_type"] in skip_types:
        logging.debug(f"Skip {do}ting states of types {', '.join(skip_types)}")
        return False

    if vm_params[f"{do}_type"] == "off":
        if vm is not None and vm.is_alive():
            vm.destroy(gracefully=do!="get")
    else:
        if vm is None:
            vm = env.create_vm(vm_params.get('vm_type'), vm_params.get('target'),
                               vm_name, vm_params, None)
        # on states require manual update of the vm parameters
        vm.params = vm_params
        if not vm.is_alive():
            vm.create()
    return True


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
        for image_name in vm_params.objects("images"):
            image_params = vm_params.object_params(image_name)
            image_params["check_type"] = image_params.get("check_type", "off")
            logging.debug("Checking %s for available %s states", vm_name, image_params["check_type"])
            backend = OFF_BACKENDS[image_params["off_states"]] if image_params["check_type"] == "off" \
                else ON_BACKENDS[image_params["on_states"]]
            states += backend.show(image_params, env)
        logging.info("Detected %s states for %s: %s", image_params["check_type"], vm_name, ", ".join(states))
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
        vm = env.get_vm(vm_name)
        vm_params = run_params.object_params(vm_name)
        for image_name in vm_params.objects("images"):
            image_params = vm_params.object_params(image_name)

            # if the snapshot is not defined skip (leaf tests that are no setup)
            if not image_params.get("check_state"):
                continue
            # NOTE: there is no concept of "check_mode" here
            image_params["check_type"] = image_params.get("check_type", "any")
            image_params["check_opts"] = image_params.get("check_opts", "print_pos=no print_neg=no")

            image_params["vms"] = vm_name
            found_type_key = f"found_type_{image_name}_{vm_name}"
            run_params[found_type_key] = image_params["check_type"]
            if image_params["check_type"] == "any":
                image_params["check_type"] = "on"
                run_params[found_type_key] = "on"
                if not enforce_check(image_params, vm):
                    image_params["check_type"] = "off"
                    run_params[found_type_key] = "off"
                    if not enforce_check(image_params, vm):
                        # default type to treat in case of no result
                        run_params[found_type_key] = "on"
                        exists = False
                        break
            elif not enforce_check(image_params, vm):
                exists = False
                break
        if not exists:
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
        for image_name in vm_params.objects("images"):
            image_params = vm_params.object_params(image_name)

            # if the state is not defined skip (leaf tests that are no setup)
            if not image_params.get("get_state"):
                continue
            image_params["get_type"] = image_params.get("get_type", "any")
            image_params["get_mode"] = image_params.get("get_mode", "ar")

            if image_params.get_boolean("image_readonly", False):
                raise ValueError(f"Incorrect configuration: cannot use any state "
                                 f"{image_params['get_type']} as {image_name} is readonly")

            image_params["vms"] = vm_name
            image_params["images"] = image_name
            image_params["check_type"] = image_params["get_type"]
            image_params["check_state"] = image_params["get_state"]
            image_params["check_opts"] = "print_pos=no print_neg=yes"
            state_exists = check_state(image_params, env)
            # if too many or no matches default to most performant type
            image_params["get_type"] = image_params[f"found_type_{image_name}_{vm_name}"]
            vm_params["get_type"] = image_params["get_type"]
            enforce = on_off_switch(do="get", skip_types=run_params.objects('skip_types'),
                                    vm=vm, vm_name=vm_name, vm_params=vm_params)
            if not enforce:
                continue

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

            backend = OFF_BACKENDS[image_params["off_states"]] if image_params["get_type"] == "off" \
                else ON_BACKENDS[image_params["on_states"]]
            if image_params["get_state"] in ROOTS:
                backend.get_root(image_params, vm)
            elif image_params["get_state"] in BOOTS:
                # reusing both root and boot states is analogical to not doing anything
                continue
            else:
                backend.get(image_params, vm)


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
        for image_name in vm_params.objects("images"):
            image_params = vm_params.object_params(image_name)

            # if the state is not defined skip (leaf tests that are no setup)
            if not image_params.get("set_state"):
                continue
            image_params["set_type"] = image_params.get("set_type", "any")
            image_params["set_mode"] = image_params.get("set_mode", "ff")

            if image_params.get_boolean("image_readonly", False):
                raise ValueError(f"Incorrect configuration: cannot use any state "
                                 f"{image_params['set_type']} as {image_name} is readonly")

            image_params["vms"] = vm_name
            image_params["check_type"] = image_params["set_type"]
            image_params["check_state"] = image_params["set_state"]
            state_exists = check_state(image_params, env)
            # if too many or no matches default to most performant type
            image_params["set_type"] = image_params[f"found_type_{image_name}_{vm_name}"]
            vm_params["set_type"] = image_params["set_type"]
            enforce = on_off_switch(do="set", skip_types=run_params.objects('skip_types'),
                                    vm=vm, vm_name=vm_name, vm_params=vm_params)
            if not enforce:
                continue

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
                backend = OFF_BACKENDS[image_params["off_states"]] if image_params["set_type"] == "off" \
                    else ON_BACKENDS[image_params["on_states"]]
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
                pass
            elif not state_exists:
                raise exceptions.TestError("Invalid policy %s: The end action on missing state can be "
                                           "either of 'abort', 'force'." % image_params["set_mode"])

            backend = OFF_BACKENDS[image_params["off_states"]] if image_params["set_type"] == "off" \
                else ON_BACKENDS[image_params["on_states"]]
            if image_params["set_state"] in ROOTS:
                backend.set_root(image_params, vm)
            elif image_params["set_state"] in BOOTS:
                # set boot state
                if vm is None or not vm.is_alive():
                    vm.create()
            else:
                backend.set(image_params, vm)


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
        for image_name in vm_params.objects("images"):
            image_params = vm_params.object_params(image_name)

            # if the state is not defined skip (leaf tests that are no setup)
            if not image_params.get("unset_state"):
                continue
            image_params["unset_type"] = image_params.get("unset_type", "any")
            image_params["unset_mode"] = image_params.get("unset_mode", "fi")

            if image_params.get_boolean("image_readonly", False):
                raise ValueError(f"Incorrect configuration: cannot use any state "
                                 f"{image_params['unset_type']} as {image_name} is readonly")

            image_params["vms"] = vm_name
            image_params["check_type"] = image_params["unset_type"]
            image_params["check_state"] = image_params["unset_state"]
            image_params["check_opts"] = "print_pos=no print_neg=yes"
            state_exists = check_state(image_params, env)
            # if too many or no matches default to most performant type
            image_params["unset_type"] = image_params[f"found_type_{image_name}_{vm_name}"]
            vm_params["unset_type"] = image_params["unset_type"]
            enforce = on_off_switch(do="unset", skip_types=run_params.objects('skip_types'),
                                    vm=vm, vm_name=vm_name, vm_params=vm_params)
            if not enforce:
                continue

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

            backend = OFF_BACKENDS[image_params["off_states"]] if image_params["unset_type"] == "off" \
                else ON_BACKENDS[image_params["on_states"]]
            if image_params["unset_state"] in ROOTS:
                # off switch to protect from on leftover state
                if vm is not None and vm.is_alive():
                    vm.destroy(gracefully=False)
                backend.unset_root(image_params, vm)
            elif image_params["unset_state"] in BOOTS:
                if vm is not None and vm.is_alive():
                    vm.destroy(gracefully=False)
            else:
                backend.unset(image_params, vm)


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
        for image_name in vm_params.objects("images"):
            image_params = vm_params.object_params(image_name)

            if image_params["push_state"] in ROOTS + BOOTS:
                # cannot be done with root states
                continue

            image_params["vms"] = vm_name
            image_params["images"] = image_name

            image_params["set_state"] = image_params["push_state"]
            image_params["set_type"] = image_params.get("push_type", "any")
            image_params["set_mode"] = image_params.get("push_mode", "af")

            set_state(image_params, env)


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
        for image_name in vm_params.objects("images"):
            image_params = vm_params.object_params(image_name)

            if image_params["pop_state"] in ROOTS + BOOTS:
                # cannot be done with root states
                continue

            image_params["vms"] = vm_name
            image_params["images"] = image_name

            image_params["get_state"] = image_params["pop_state"]
            image_params["get_type"] = image_params.get("pop_type", "any")
            image_params["get_mode"] = image_params.get("pop_mode", "ra")
            get_state(image_params, env)

            image_params["unset_state"] = image_params["pop_state"]
            image_params["unset_type"] = image_params.get("pop_type", "any")
            image_params["unset_mode"] = image_params.get("pop_mode", "fa")
            unset_state(image_params, env)
