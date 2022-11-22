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
Module for the QCOW2 pool state management backend.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import os
import time
import logging as log
logging = log.getLogger('avocado.test.' + __name__)
import shutil
import contextlib
import fcntl
import errno

from aexpect import remote, ops
from avocado.utils import crypto

from .setup import StateBackend


#: skip waiting on locks if we only read from the pool for all processes, i.e.
#: use update_pool=no for all parallel operations or else
#: WARNING: use it only if you know what you are doing
SKIP_LOCKS = False


class StateBundleTransfer():
    """Backend manipulating root states from a shared pool of QCOW2 images."""

    @staticmethod
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

    @classmethod
    def check_root(cls, params, object=None):
        """
        Check whether a root state or essentially the object exists.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        image_name = params["image_name"]
        target_image = StateBundleTransfer.get_image_path(params)
        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        image_base_name = os.path.join(vm_name, os.path.basename(target_image))

        logging.debug(f"Checking for shared {vm_name}/{image_name} existence"
                      f" in the shared pool {shared_pool}")
        src_image_name = os.path.join(shared_pool, image_base_name)
        # it is possible that the the root state is partially provided
        if os.path.exists(src_image_name):
            logging.info("The shared %s image exists", src_image_name)
            return True
        else:
            logging.info("The shared %s image doesn't exist", src_image_name)
            return False

    @classmethod
    def get_root(cls, params, object=None):
        """
        Get a root state or essentially due to pre-existence do nothing.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        image_name = params["image_name"]
        target_image = StateBundleTransfer.get_image_path(params)
        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        image_base_names = os.path.join(vm_name, os.path.basename(target_image))

        logging.info(f"Downloading shared {vm_name}/{image_name} "
                     f"from the shared pool {shared_pool}")
        src_image_name = os.path.join(shared_pool, image_base_names)
        download_from_pool(target_image, src_image_name, params)

    @classmethod
    def set_root(cls, params, object=None):
        """
        Set a root state to provide object existence.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        image_name = params["image_name"]
        target_image = StateBundleTransfer.get_image_path(params)
        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        image_base_names = os.path.join(vm_name, os.path.basename(target_image))

        logging.info(f"Uploading shared {vm_name}/{image_name} "
                     f"to the shared pool {shared_pool}")
        dst_image_name = os.path.join(shared_pool, image_base_names)
        upload_to_pool(target_image, dst_image_name, params)

    @classmethod
    def unset_root(cls, params, object=None):
        """
        Unset a root state to prevent object existence.

        All arguments match the base class and in addition:
        """
        vm_name = params["vms"]
        image_name = params["image_name"]
        target_image = StateBundleTransfer.get_image_path(params)
        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        image_base_names = os.path.join(vm_name, os.path.basename(target_image))

        logging.info(f"Removing shared {vm_name}/{image_name} "
                     f"from the shared pool {shared_pool}")
        dst_image_name = os.path.join(shared_pool, image_base_names)
        delete_in_pool(dst_image_name, params)


class StateChainTransfer():
    """Backend manipulating image states from a shared pool of QCOW2 images."""

    @classmethod
    def _type_decorator(cls, state_type):
        """
        Determine the local state backend to use from the required state type.

        :param str state_type: "vms" or "images" (supported)
        """
        # TODO: there is some inconsistency in the object type specification
        if state_type in ["images", "nets/vms/images"]:
            return cls.local_image_state_backend
        elif state_type in ["vms", "nets/vms"]:
            return cls.local_vm_state_backend
        else:
            raise ValueError(f"Unsupported state type for pooling {state_type}")

    @classmethod
    def _transfer_chain(cls, state, backend, params, down=True):
        """
        Repeat pool operation an all dependencies states backing a given state.

        :param str state: state name
        :param params: configuration parameters
        :param backend: local state backend to show states with
        :type backend: :py:class:`avocado_i2n.states.setup.StateBackend`
        :type params: {str, str}
        :param bool down: whether the chain is downloaded or uploaded
        """
        transfer_operation = download_from_pool if down else upload_to_pool

        shared_pool = params["image_pool"]
        cache_dir = params["vms_base_dir"]
        vm_name = params["vms"]

        next_state = state
        while next_state != "":
            for image_name in params.objects("images"):
                image_params = params.object_params(image_name)
                cache_path = os.path.join(cache_dir, vm_name, image_name, next_state + ".qcow2")
                pool_path = os.path.join(shared_pool, vm_name, image_name, next_state + ".qcow2")
                # if only vm state is not available this would indicate image corruption
                transfer_operation(cache_path, pool_path, image_params)
            if next_state == state and params["object_type"] in ["vms", "nets/vms"]:
                cache_path = os.path.join(cache_dir, vm_name, next_state + ".state")
                pool_path = os.path.join(shared_pool, vm_name, next_state + ".state")
                transfer_operation(cache_path, pool_path, params)
            # download of state chain is not yet complete if the state has backing dependencies
            next_state = backend.get_dependency(next_state, params)

    @classmethod
    def show(cls, params, object=None):
        """
        Return a list of available states of a specific type.

        All arguments match the base class.
        """
        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        cache_dir = params["vms_base_dir"]

        vm_name = params["vms"]
        state_tag = f"{vm_name}"
        if params["object_type"] in ["images", "nets/vms/images"]:
            image_name = params["images"]
            state_tag += f"/{image_name}"
        logging.debug(f"Checking for shared {state_tag} states "
                      f"in the shared pool {shared_pool}")

        # TODO: list in vm dir or image dir
        pool_states = list_pool(cache_dir, shared_pool,
                                params, object, local_state_backend)
        return pool_states

    @classmethod
    def check(cls, params, object=None):
        """
        Check whether a given state exists.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        state_tag = f"{vm_name}"
        if params["object_type"] in ["images", "nets/vms/images"]:
            image_name = params["images"]
            state_tag += f"/{image_name}"
        logging.debug(f"Checking for {state_tag} state '{params['check_state']}'")
        states = cls.show(params, object)
        for state in states:
            if state == params["check_state"]:
                logging.info(f"The {state_tag} state '{params['check_state']}' exists")
                return True
        # at this point we didn't find the state in the listed ones
        logging.info(f"The {state_tag} state '{params['check_state']}' doesn't exist")
        return False

    @classmethod
    def get(cls, params, object=None):
        """
        Get a root state or essentially due to pre-existence do nothing.

        All arguments match the base class.
        """
        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        cache_dir = params["vms_base_dir"]

        vm_name = params["vms"]
        state_tag = f"{vm_name}"
        format = "state"
        if params["object_type"] in ["images", "nets/vms/images"]:
            image_name = params["images"]
            state_tag += f"/{image_name}"
            format = "qcow2"
        state = params["get_state"]
        logging.info(f"Downloading shared {state_tag} state {state} "
                     f"from the shared pool {shared_pool} to {cache_dir}")

        try:
            cls._transfer_chain(state, local_state_backend, params, down=True)
        except Exception as error:
            remove_path = os.path.join(cache_dir, state_tag, state + "." + format)
            os.unlink(remove_path)
            raise error

    @classmethod
    def set(cls, params, object=None):
        """
        Set a root state to provide object existence.

        All arguments match the base class.
        """
        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        cache_dir = params["vms_base_dir"]

        vm_name = params["vms"]
        state_tag = f"{vm_name}"
        if params["object_type"] in ["images", "nets/vms/images"]:
            image_name = params["images"]
            state_tag += f"/{image_name}"
        state = params["set_state"]
        logging.info(f"Uploading shared {state_tag} state {state} "
                     f"to the shared pool {shared_pool} from {cache_dir}")

        try:
            cls._transfer_chain(state, local_state_backend, params, down=False)
        except Exception as error:
            remove_path = os.path.join(shared_pool, state_tag, state + "." + format)
            delete_in_pool(remove_path, params)
            raise error

    @classmethod
    def unset(cls, params, object=None):
        """
        Unset a root state to prevent object existence.

        All arguments match the base class and in addition:
        """
        shared_pool = params.get("image_pool", "/mnt/local/images/pool")

        vm_name = params["vms"]
        state_tag = f"{vm_name}"
        if params["object_type"] in ["images", "nets/vms/images"]:
            image_name = params["images"]
            state_tag += f"/{image_name}"
        state = params["unset_state"]
        logging.info(f"Removing shared {state_tag} state {state} "
                     f"from the shared pool {shared_pool}")

        for image_name in params.objects("images"):
            image_params = params.object_params(image_name)
            pool_path = os.path.join(shared_pool, vm_name, image_name, state + ".qcow2")
            delete_in_pool(pool_path, image_params)
        if params["object_type"] in ["vms", "nets/vms"]:
            pool_path = os.path.join(shared_pool, vm_name, state + ".state")
            delete_in_pool(pool_path, params)


class RootSourcedStateBackend(StateBackend):
    """Backend manipulating root states from a possibly shared source."""

    transport = StateBundleTransfer

    @classmethod
    def check_root(cls, params, object=None):
        """
        Check whether a root state or essentially the object exists.

        All arguments match the base class.
        """
        local_root_exists = cls._check_root(params, object)
        if not params.get_boolean("use_pool", True):
            return local_root_exists
        elif params.get_boolean("update_pool", False) and not local_root_exists:
            raise RuntimeError("Updating state pool requires local root states")
        elif (not params.get_boolean("update_pool", False) and local_root_exists):
            return True

        shared_root_exists = cls.transport.check_root(params, object)
        # TODO: extra complexity as it is possible that the root state is partially provided
        # so get rid of this instead of adding it to test contract
        target_image = cls.transport.get_image_path(params)
        if os.path.exists(target_image) and not params.get_boolean("update_pool", False):
            return False
        elif not local_root_exists and shared_root_exists:
            cls.transport.get_root(params, object)
            return True

    @classmethod
    def get_root(cls, params, object=None):
        """
        Get a root state or essentially due to pre-existence do nothing.

        All arguments match the base class.
        """
        if (cls._check_root(params, object) or
                not params.get_boolean("use_pool", True)):
            cls._get_root(params, object)
            return
        cls.transport.get_root(params, object)

    @classmethod
    def set_root(cls, params, object=None):
        """
        Set a root state to provide object existence.

        All arguments match the base class.
        """
        # local and pool root setting are mutually exclusive as we usually want
        # to set the pool root from an existing local root with some states on it
        if not params.get_boolean("update_pool", False):
            cls._set_root(params, object)
        else:
            cls.transport.set_root(params, object)

    @classmethod
    def unset_root(cls, params, object=None):
        """
        Unset a root state to prevent object existence.

        All arguments match the base class and in addition:
        """
        # local and pool root setting are mutually exclusive as we usually want
        # to set the pool root from an existing local root with some states on it
        if not params.get_boolean("update_pool", False):
            cls._unset_root(params, object)
        else:
            cls.transport.unset_root(params, object)


class SourcedStateBackend(StateBackend):
    """Backend manipulating states from a possibly shared source."""

    transport = StateChainTransfer

    @classmethod
    def show(cls, params, object=None):
        """
        Return a list of available states of a specific type.

        All arguments match the base class.
        """
        cache_states = cls._show(params, object)
        if not params.get_boolean("use_pool", True):
            return cache_states

        pool_states = cls.transport.show(params, object)
        return list(set(cache_states).union(set(pool_states)))

    @classmethod
    def check(cls, params, object=None):
        """
        Check whether a given state exists.

        All arguments match the base class.
        """
        local_state_exists = cls._check(params, object)
        if params.get_boolean("update_pool", False) and not local_state_exists:
            raise RuntimeError("Updating state pool requires local states")
        # TODO: excessive complexity, get rid of this instead of adding it to test contract
        elif params.get_boolean("update_pool", False):
            return False
        elif not params.get_boolean("use_pool", True):
            return local_state_exists
        elif local_state_exists:
            return True

        pool_state_exists = cls.transport.check(params, object)
        if pool_state_exists and not local_state_exists:
            params["get_state"] = params["check_state"]
            cls.transport.get(params, object)
            return True
        return local_state_exists

    @classmethod
    def get(cls, params, object=None):
        """
        Get a root state or essentially due to pre-existence do nothing.

        All arguments match the base class.
        """
        if (cls._check(params, object) or
                not params.get_boolean("use_pool", True)):
            cls._get(params, object)
            return
        cls.transport.get(params, object)
        cls._get(params, object)

    @classmethod
    def set(cls, params, object=None):
        """
        Set a root state to provide object existence.

        All arguments match the base class.
        """
        # local and pool root setting are mutually exclusive as we usually want
        # to set the pool root from an existing local root with some states on it
        if not params.get_boolean("update_pool", False):
            cls._set(params, object)
        else:
            cls.transport.set(params, object)

    @classmethod
    def unset(cls, params, object=None):
        """
        Unset a root state to prevent object existence.

        All arguments match the base class and in addition:
        """
        # local and pool root setting are mutually exclusive as we usually want
        # to set the pool root from an existing local root with some states on it
        if not params.get_boolean("update_pool", False):
            cls._unset(params, object)
        else:
            cls.transport.unset(params, object)


def list_pool(cache_path, pool_path, params, object, backend):
    """
    List all states in a path from the pool.

    :param str cache_path: cache path to list local states from
    :param str pool_path: pool path to list pool states from
    :param params: configuration parameters
    :type params: {str, str}
    :param object: object whose states are manipulated
    :type object: :py:class:`virttest.qemu_vm.VM` or None
    :param backend: local state backend to show states with
    :type backend: :py:class:`avocado_i2n.states.setup.StateBackend`
    """
    if ":" in pool_path:
        host, path = pool_path.split(":")
        session = remote.remote_login(params["nets_shell_client"],
                                      host,
                                      params["nets_shell_port"],
                                      params["nets_username"], params["nets_password"],
                                      params["nets_shell_prompt"])
        # TODO: not local backend agnostic so use a remote control file
        if params["object_type"] in ["images", "nets/vms/images"]:
            state_tag = f"{params['vms']}/{params['images']}"
            format = ".qcow2"
        else:
            state_tag = f"{params['vms']}"
            format = ".state"
        path = os.path.join(path, state_tag)
        states = session.cmd_output(f"ls {path}").split()
        states = [p.replace(format, "") for p in states]
    else:
        params["vms_base_dir"] = pool_path
        states = backend.show(params, object)
        params["vms_base_dir"] = cache_path
    return states


def download_from_pool(cache_path, pool_path, params):
    """
    Download a path from the pool depending on the pool location.

    :param str cache_path: cache path to download to
    :param str pool_path: pool path to download from
    :param params: configuration parameters
    :type params: {str, str}
    """
    if os.path.exists(cache_path):
        local_hash = crypto.hash_file(cache_path, 1048576, "md5")
    else:
        local_hash = ""

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)

    update_timeout = params.get_numeric("update_pool_timeout", 300)
    if ":" in pool_path:
        # TODO: no support for remote lock files yet
        host, path = pool_path.split(":")

        session = remote.remote_login(params["nets_shell_client"],
                                      host,
                                      params["nets_shell_port"],
                                      params["nets_username"], params["nets_password"],
                                      params["nets_shell_prompt"])
        remote_hash = ops.hash_file(session, path, "1M", "md5")

        if local_hash == remote_hash:
            logging.info(f"Skip download of an already available {cache_path} ({remote_hash})")
            return
        if local_hash is not None:
            logging.info(f"Force download of an already available {cache_path} ({remote_hash})")

        remote.copy_files_from(host,
                               params["nets_file_transfer_client"],
                               params["nets_username"], params["nets_password"],
                               params["nets_file_transfer_port"],
                               path, cache_path,
                               timeout=update_timeout)
        return

    with image_lock(pool_path, update_timeout) as lock:
        remote_hash = crypto.hash_file(pool_path, 1048576, "md5")
        if local_hash == remote_hash:
            logging.info(f"Skip download of an already available {cache_path}")
            return
        shutil.copy(pool_path, cache_path)


def upload_to_pool(cache_path, pool_path, params):
    """
    Upload a path to the pool depending on the pool location.

    :param str cache_path: cache path to upload from
    :param str pool_path: pool path to upload to
    :param params: configuration parameters
    :type params: {str, str}
    """
    if os.path.exists(cache_path):
        local_hash = crypto.hash_file(cache_path, 1048576, "md5")
    else:
        local_hash = ""

    update_timeout = params.get_numeric("update_pool_timeout", 300)
    if ":" in pool_path:
        # TODO: need to create remote directory if not available
        # TODO: no support for remote lock files yet
        host, path = pool_path.split(":")

        session = remote.remote_login(params["nets_shell_client"],
                                      host,
                                      params["nets_shell_port"],
                                      params["nets_username"], params["nets_password"],
                                      params["nets_shell_prompt"])
        remote_hash = ops.hash_file(session, path, "1M", "md5")

        if local_hash == remote_hash:
            logging.info(f"Skip upload of an already available {cache_path} ({remote_hash})")
            return
        if local_hash is not None:
            logging.info(f"Force upload of an already available {cache_path} ({remote_hash})")

        remote.copy_files_to(host,
                             params["nets_file_transfer_client"],
                             params["nets_username"], params["nets_password"],
                             params["nets_file_transfer_port"],
                             cache_path, path,
                             timeout=update_timeout)
        return

    with image_lock(pool_path, update_timeout) as lock:
        remote_hash = crypto.hash_file(pool_path, 1048576, "md5")
        if local_hash == remote_hash:
            logging.info(f"Skip upload of an already available {cache_path}")
            return
        os.makedirs(os.path.dirname(pool_path), exist_ok=True)
        shutil.copy(cache_path, pool_path)


def delete_in_pool(pool_path, params):
    """
    Delete a path in the pool depending on the pool location.

    :param str pool_path: path in the pool to delete
    :param params: configuration parameters
    :type params: {str, str}
    """
    update_timeout = params.get_numeric("update_pool_timeout", 300)
    if ":" in pool_path:
        host, path = pool_path.split(":")
        session = remote.remote_login(params["nets_shell_client"],
                                      host,
                                      params["nets_shell_port"],
                                      params["nets_username"], params["nets_password"],
                                      params["nets_shell_prompt"])
        # TODO: not local backend agnostic so use a remote control file
        session.cmd(f"rm {path}")
    with image_lock(pool_path, update_timeout) as lock:
        os.unlink(pool_path)


@contextlib.contextmanager
def image_lock(resource_path, timeout=300):
    """
    Wait for a lock to free image for state pool operations.

    :param str resource_path: path to the potentially locked resource
    :param int timeout: timeout to wait before erroring out (default 5 mins)
    """
    if SKIP_LOCKS:
        yield None
        return
    lockfile = resource_path + ".lock"
    os.makedirs(os.path.dirname(lockfile), exist_ok=True)
    with open(lockfile, "wb") as fd:
        for _ in range(timeout):
            try:
                fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except IOError as error:
                # block here but still support a finite timeout
                if error.errno != errno.EACCES and error.errno != errno.EAGAIN:
                    raise
            else:
                break
            logging.debug("Waiting for image to become available")
            time.sleep(1)
        else:
            raise RuntimeError(f"Waiting to acquire {lockfile} took more than "
                               f"the allowed {timeout} seconds")
        try:
            yield fd
        finally:
            fcntl.lockf(fd, fcntl.LOCK_UN)
