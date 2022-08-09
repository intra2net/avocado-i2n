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

from aexpect import remote

from .setup import StateBackend
from .qcow2 import QCOW2Backend, QCOW2ExtBackend, get_image_path
from .ramfile import RamfileBackend


#: skip waiting on locks if we only read from the pool for all processes, i.e.
#: use update_pool=no for all parallel operations
#: WARNING: use it only if you know what you are doing
SKIP_LOCKS = False


class QCOW2RootPoolBackend(StateBackend):
    """Backend manipulating root states from a shared pool of QCOW2 images."""

    # TODO: currently only qcow2 is supported
    local_state_backend = QCOW2Backend

    @classmethod
    def check_root(cls, params, object=None):
        """
        Check whether a root state or essentially the object exists.

        All arguments match the base class.
        """
        if not params.get_boolean("use_pool", True):
            return cls.local_state_backend.check_root(params, object)
        elif (params.get_boolean("update_pool", False) and
                not cls.local_state_backend.check_root(params, object)):
            raise RuntimeError("Updating state pool requires local root states")
        elif (not params.get_boolean("update_pool", False) and
                cls.local_state_backend.check_root(params, object)):
            return True

        vm_name = params["vms"]
        image_name = params["image_name"]
        target_image = get_image_path(params)
        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        image_base_names = os.path.join(vm_name, os.path.basename(target_image))

        logging.debug(f"Checking for shared {vm_name}/{image_name} existence"
                      f" in the shared pool {shared_pool}")
        src_image_name = os.path.join(shared_pool, image_base_names)
        # it is possible that the the root state is partially provided
        if os.path.exists(target_image) and not params.get_boolean("update_pool", False):
            logging.info("The local %s image exists but from partial root state",
                         src_image_name)
            return False
        elif os.path.exists(src_image_name):
            cls.get_root(params, object)
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
        if (cls.local_state_backend.check_root(params, object) or
                not params.get_boolean("use_pool", True)):
            cls.local_state_backend.get_root(params, object)
            return

        vm_name = params["vms"]
        image_name = params["image_name"]
        target_image = get_image_path(params)
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
        # local and pool root setting are mutually exclusive as we usually want
        # to set the pool root from an existing local root with some states on it
        if not params.get_boolean("update_pool", False):
            cls.local_state_backend.set_root(params, object)
            return

        vm_name = params["vms"]
        image_name = params["image_name"]
        target_image = get_image_path(params)
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
        # local and pool root setting are mutually exclusive as we usually want
        # to set the pool root from an existing local root with some states on it
        if not params.get_boolean("update_pool", False):
            cls.local_state_backend.unset_root(params, object)
            return

        vm_name = params["vms"]
        image_name = params["image_name"]
        target_image = get_image_path(params)
        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        image_base_names = os.path.join(vm_name, os.path.basename(target_image))

        logging.info(f"Removing shared {vm_name}/{image_name} "
                     f"from the shared pool {shared_pool}")
        dst_image_name = os.path.join(shared_pool, image_base_names)
        delete_in_pool(dst_image_name, params)


class QCOW2PoolBackend(StateBackend):
    """Backend manipulating image states from a shared pool of QCOW2 images."""

    # TODO: currently only qcow2ext is supported
    local_image_state_backend = QCOW2ExtBackend
    # TODO: currently only ramfile is supported
    local_vm_state_backend = RamfileBackend

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
    def show(cls, params, object=None):
        """
        Return a list of available states of a specific type.

        All arguments match the base class.
        """
        local_state_backend = cls._type_decorator(params["object_type"])
        if not params.get_boolean("use_pool", True):
            return local_state_backend.show(params, object)
        elif (params.get_boolean("update_pool", False) and
                not local_state_backend.check(params, object)):
            raise RuntimeError("Updating state pool requires local states")

        cache_states = local_state_backend.show(params, object)

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

        return list(set(cache_states).union(set(pool_states)))

    @classmethod
    def check(cls, params, object=None):
        """
        Check whether a given state exists.

        All arguments match the base class.
        """
        local_state_backend = cls._type_decorator(params["object_type"])
        locally_present = local_state_backend.check(params, object)
        if params.get_boolean("update_pool", False) and not locally_present:
            raise RuntimeError("Updating state pool requires local states")
        elif params.get_boolean("update_pool", False):
            return False
        else:
            vm_name = params["vms"]
            state_tag = f"{vm_name}"
            if params["object_type"] in ["images", "nets/vms/images"]:
                image_name = params["images"]
                state_tag += f"/{image_name}"
            logging.debug(f"Checking for {state_tag} state '{params['check_state']}'")
            states = cls.show(params, object)
            for state in states:
                if state == params["check_state"]:
                    if not locally_present:
                        params["get_state"] = state
                        params["pool_only"] = "yes"
                        cls.get(params, object)
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
        local_state_backend = cls._type_decorator(params["object_type"])
        if (local_state_backend.check(params, object) or
                not params.get_boolean("use_pool", True)):
            local_state_backend.get(params, object)
            return

        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        cache_dir = params["vms_base_dir"]

        vm_name = params["vms"]
        state_tag = f"{vm_name}"
        if params["object_type"] in ["images", "nets/vms/images"]:
            image_name = params["images"]
            state_tag += f"/{image_name}"
        state = params["get_state"]
        logging.info(f"Downloading shared {state_tag} state {state} "
                     f"from the shared pool {shared_pool}")

        for image_name in params.objects("images"):
            image_params = params.object_params(image_name)
            cache_path = os.path.join(cache_dir, vm_name, image_name, state + ".qcow2")
            pool_path = os.path.join(shared_pool, vm_name, image_name, state + ".qcow2")
            download_from_pool(cache_path, pool_path, image_params)
        if params["object_type"] in ["vms", "nets/vms"]:
            cache_path = os.path.join(cache_dir, vm_name, state + ".state")
            pool_path = os.path.join(shared_pool, vm_name, state + ".state")
            download_from_pool(cache_path, pool_path, params)

        if not params.get_boolean("pool_only"):
            local_state_backend.get(params, object)

    @classmethod
    def set(cls, params, object=None):
        """
        Set a root state to provide object existence.

        All arguments match the base class.
        """
        local_state_backend = cls._type_decorator(params["object_type"])
        # local and pool root setting are mutually exclusive as we usually want
        # to set the pool root from an existing local root with some states on it
        if not params.get_boolean("update_pool", False):
            local_state_backend.set(params, object)
            return

        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        cache_dir = params["vms_base_dir"]

        vm_name = params["vms"]
        state_tag = f"{vm_name}"
        if params["object_type"] in ["images", "nets/vms/images"]:
            image_name = params["images"]
            state_tag += f"/{image_name}"
        state = params["set_state"]
        logging.info(f"Uploading shared {state_tag} state {state} "
                     f"to the shared pool {shared_pool}")

        for image_name in params.objects("images"):
            image_params = params.object_params(image_name)
            cache_path = os.path.join(cache_dir, vm_name, image_name, state + ".qcow2")
            pool_path = os.path.join(shared_pool, vm_name, image_name, state + ".qcow2")
            upload_to_pool(cache_path, pool_path, image_params)
        if params["object_type"] in ["vms", "nets/vms"]:
            cache_path = os.path.join(cache_dir, vm_name, state + ".state")
            pool_path = os.path.join(shared_pool, vm_name, state + ".state")
            upload_to_pool(cache_path, pool_path, params)

    @classmethod
    def unset(cls, params, object=None):
        """
        Unset a root state to prevent object existence.

        All arguments match the base class and in addition:
        """
        local_state_backend = cls._type_decorator(params["object_type"])
        # local and pool root setting are mutually exclusive as we usually want
        # to set the pool root from an existing local root with some states on it
        if not params.get_boolean("update_pool", False):
            local_state_backend.unset(params, object)
            return

        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        cache_dir = params["vms_base_dir"]

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

    @classmethod
    def check_root(cls, params, object=None):
        """
        Check whether a root state or essentially the object exists.

        All arguments match the base class.
        """
        local_state_backend = cls._type_decorator(params["object_type"])
        return local_state_backend.check_root(params, object)

    @classmethod
    def get_root(cls, params, object=None):
        """
        Get a root state or essentially due to pre-existence do nothing.

        All arguments match the base class.
        """
        local_state_backend = cls._type_decorator(params["object_type"])
        local_state_backend.get_root(params, object)

    @classmethod
    def set_root(cls, params, object=None):
        """
        Set a root state to provide object existence.

        All arguments match the base class.
        """
        local_state_backend = cls._type_decorator(params["object_type"])
        local_state_backend.set_root(params, object)

    @classmethod
    def unset_root(cls, params, object=None):
        """
        Unset a root state to prevent object existence.

        All arguments match the base class and in addition:
        """
        local_state_backend = cls._type_decorator(params["object_type"])
        local_state_backend.unset_root(params, object)


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
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    update_timeout = params.get_numeric("update_pool_timeout", 300)
    if ":" in pool_path:
        # TODO: no support for remote lock files yet
        host, path = pool_path.split(":")
        remote.copy_files_from(host,
                               params["nets_file_transfer_client"],
                               params["nets_username"], params["nets_password"],
                               params["nets_file_transfer_port"],
                               path, cache_path,
                               timeout=update_timeout)
        return
    with image_lock(pool_path, update_timeout) as lock:
        shutil.copy(pool_path, cache_path)


def upload_to_pool(cache_path, pool_path, params):
    """
    Upload a path to the pool depending on the pool location.

    :param str cache_path: cache path to upload from
    :param str pool_path: pool path to upload to
    :param params: configuration parameters
    :type params: {str, str}
    """
    update_timeout = params.get_numeric("update_pool_timeout", 300)
    if ":" in pool_path:
        # TODO: need to create remote directory if not available
        # TODO: no support for remote lock files yet
        host, path = pool_path.split(":")
        remote.copy_files_to(host,
                             params["nets_file_transfer_client"],
                             params["nets_username"], params["nets_password"],
                             params["nets_file_transfer_port"],
                             cache_path, path,
                             timeout=update_timeout)
        return
    with image_lock(pool_path, update_timeout) as lock:
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
