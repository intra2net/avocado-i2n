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
import json

from aexpect import remote, ops_linux as ops
from avocado.utils import crypto

from virttest.qemu_storage import QemuImg

from .setup import StateBackend


#: skip waiting on locks if we only read from the pool for all processes, i.e.
#: use update_pool=no for all parallel operations or else
#: WARNING: use it only if you know what you are doing
SKIP_LOCKS = False


class TransferOps():
    """A small namespace for pool transfer operations of multiple types."""

    _session_cache = {}

    @classmethod
    def get_session(cls, host, params):
        """
        Get a possibly reused session to the remote location.

        :param str host: remote host name for the remote location
        :param params: configuration parameters
        :type params: {str, str}
        :returns: a new session or previously cached session
        :rtype: :py:class:`aexpect.ShellSession`
        """
        session = cls._session_cache.get(host)
        if not session:
            session = remote.remote_login(params["nets_shell_client"],
                                          params['nets_shell_host'], params["nets_shell_port"],
                                          params["nets_username"], params["nets_password"],
                                          params["nets_shell_prompt"])
            cls._session_cache[host] = session
        return session

    @staticmethod
    def list(pool_path, params):
        """
        List all states in a path from the pool.

        :param str pool_path: pool path to list pool states from
        :param params: configuration parameters
        :type params: {str, str}
        """
        if ":" in pool_path:
            return TransferOps.list_remote(pool_path, params)
        elif ";" in pool_path:
            return TransferOps.list_link(pool_path.replace(";", ""), params)
        else:
            return TransferOps.list_local(pool_path, params)

    @staticmethod
    def compare(cache_path, pool_path, params):
        """
        Compare cache and pool external state version.

        :param str cache_path: cache path to compare with
        :param str pool_path: pool path to compare with
        :param params: configuration parameters
        :type params: {str, str}
        """
        if ":" in pool_path:
            return TransferOps.compare_remote(cache_path, pool_path, params)
        elif ";" in pool_path:
            return TransferOps.compare_link(cache_path, pool_path.replace(";", ""), params)
        else:
            return TransferOps.compare_local(cache_path, pool_path, params)

    @staticmethod
    def download(cache_path, pool_path, params):
        """
        Download a path from the pool depending on the pool location.

        :param str cache_path: cache path to download to
        :param str pool_path: pool path to download from
        :param params: configuration parameters
        :type params: {str, str}
        """
        if ":" in pool_path:
            TransferOps.download_remote(cache_path, pool_path, params)
        elif ";" in pool_path:
            TransferOps.download_link(cache_path, pool_path.replace(";", ""), params)
        else:
            TransferOps.download_local(cache_path, pool_path, params)

    @staticmethod
    def upload(cache_path, pool_path, params):
        """
        Upload a path to the pool depending on the pool location.

        :param str cache_path: cache path to upload from
        :param str pool_path: pool path to upload to
        :param params: configuration parameters
        :type params: {str, str}
        """
        if ":" in pool_path:
            TransferOps.upload_remote(cache_path, pool_path, params)
        elif ";" in pool_path:
            TransferOps.upload_link(cache_path, pool_path.replace(";", ""), params)
        else:
            TransferOps.upload_local(cache_path, pool_path, params)

    @staticmethod
    def delete(pool_path, params):
        """
        Delete a path in the pool depending on the pool location.

        :param str pool_path: path in the pool to delete
        :param params: configuration parameters
        :type params: {str, str}
        """
        if ":" in pool_path:
            TransferOps.delete_remote(pool_path, params)
        elif ";" in pool_path:
            TransferOps.delete_link(pool_path.replace(";", ""), params)
        else:
            TransferOps.delete_local(pool_path, params)

    @staticmethod
    def list_local(pool_path, params):
        """
        List all states in a path from the pool.

        All arguments are identical to the main entry method.
        """
        if not os.path.exists(pool_path):
            return []
        return os.listdir(pool_path)

    @staticmethod
    def compare_local(cache_path, pool_path, params):
        """
        Compare cache and pool external state version.

        All arguments are identical to the main entry method.
        """
        if os.path.exists(cache_path):
            local_hash = crypto.hash_file(cache_path, 1048576, "md5")
        else:
            local_hash = ""
        if os.path.exists(pool_path):
            remote_hash = crypto.hash_file(pool_path, 1048576, "md5")
        else:
            remote_hash = ""

        return local_hash == remote_hash

    @staticmethod
    def download_local(cache_path, pool_path, params):
        """
        Download a path from the pool depending on the pool location.

        All arguments are identical to the main entry method.
        """
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)

        update_timeout = params.get_numeric("update_pool_timeout", 300)
        with image_lock(pool_path, update_timeout) as lock:
            if TransferOps.compare_local(cache_path, pool_path, params):
                logging.info(f"Skip download of an already available {cache_path}")
                return
            shutil.copy(pool_path, cache_path)

    @staticmethod
    def upload_local(cache_path, pool_path, params):
        """
        Upload a path to the pool depending on the pool location.

        All arguments are identical to the main entry method.
        """
        update_timeout = params.get_numeric("update_pool_timeout", 300)
        with image_lock(pool_path, update_timeout) as lock:
            if TransferOps.compare_local(cache_path, pool_path, params):
                logging.info(f"Skip upload of an already available {cache_path}")
                return
            os.makedirs(os.path.dirname(pool_path), exist_ok=True)
            shutil.copy(cache_path, pool_path)

    @staticmethod
    def delete_local(pool_path, params):
        """
        Delete a path in the pool depending on the pool location.

        All arguments are identical to the main entry method.
        """
        update_timeout = params.get_numeric("update_pool_timeout", 300)
        with image_lock(pool_path, update_timeout) as lock:
            os.unlink(pool_path)

    @staticmethod
    def list_remote(pool_path, params):
        """
        List all states in a path from the pool.

        All arguments are identical to the main entry method.
        """
        host, path = pool_path.split(":")
        session = TransferOps.get_session(host, params)
        status, output = session.cmd_status_output(f"ls {path}")
        if status != 0:
            logging.debug(f"Path {path} not found: {output}")
            return []
        return output.split()

    @staticmethod
    def compare_remote(cache_path, pool_path, params):
        """
        Compare cache and pool external state version.

        All arguments are identical to the main entry method.
        """
        if os.path.exists(cache_path):
            local_hash = crypto.hash_file(cache_path, 1048576, "md5")
        else:
            local_hash = ""
        host, path = pool_path.split(":")

        session = TransferOps.get_session(host, params)
        remote_hash = ops.hash_file(session, path, "1M", "md5")

        return local_hash == remote_hash

    @staticmethod
    def download_remote(cache_path, pool_path, params):
        """
        Download a path from the pool depending on the pool location.

        All arguments are identical to the main entry method.
        """
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        # TODO: no support for remote lock files yet
        host, path = pool_path.split(":")

        if TransferOps.compare_remote(cache_path, pool_path, params):
            logging.info(f"Skip download of an already available and valid {cache_path}")
            return
        if os.path.exists(cache_path):
            logging.info(f"Force download of an already available {cache_path}")

        remote.copy_files_from(params["nets_shell_host"],
                               params["nets_file_transfer_client"],
                               params["nets_username"], params["nets_password"],
                               params["nets_file_transfer_port"],
                               path, cache_path,
                               timeout=params.get_numeric("update_pool_timeout", 300))

    @staticmethod
    def upload_remote(cache_path, pool_path, params):
        """
        Upload a path to the pool depending on the pool location.

        All arguments are identical to the main entry method.
        """
        # TODO: need to create remote directory if not available
        # TODO: no support for remote lock files yet
        host, path = pool_path.split(":")

        if TransferOps.compare_remote(cache_path, pool_path, params):
            logging.info(f"Skip upload of an already available {pool_path}")
            return
        logging.info(f"Will possibly force upload to {pool_path}")

        remote.copy_files_to(params["nets_shell_host"],
                             params["nets_file_transfer_client"],
                             params["nets_username"], params["nets_password"],
                             params["nets_file_transfer_port"],
                             cache_path, path,
                             timeout=params.get_numeric("update_pool_timeout", 300))

    @staticmethod
    def delete_remote(pool_path, params):
        """
        Delete a path in the pool depending on the pool location.

        All arguments are identical to the main entry method.
        """
        host, path = pool_path.split(":")
        session = remote.remote_login(params["nets_shell_client"],
                                      params["nets_shell_host"],
                                      params["nets_shell_port"],
                                      params["nets_username"], params["nets_password"],
                                      params["nets_shell_prompt"])
        session.cmd(f"rm {path}")

    @staticmethod
    def compare_link(cache_path, pool_path, params):
        """
        Compare cache and pool external state version.

        All arguments are identical to the main entry method.
        """
        if os.path.islink(cache_path):
            return os.path.realpath(cache_path) == pool_path
        else:
            return TransferOps.compare_local(cache_path, pool_path, params)

    @staticmethod
    def list_link(pool_path, params):
        """
        List all states in a path from the pool.

        All arguments are identical to the main entry method.
        """
        return TransferOps.list_local(pool_path, params)

    @staticmethod
    def download_link(cache_path, pool_path, params):
        """
        Download a path from the pool depending on the pool location.

        All arguments are identical to the main entry method.
        """
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)

        update_timeout = params.get_numeric("update_pool_timeout", 300)
        with image_lock(pool_path, update_timeout) as lock:
            if TransferOps.compare_link(cache_path, pool_path, params):
                logging.info(f"Skip link of an already available {cache_path}")
                return
            # actual data must be kept safe
            if not os.path.islink(cache_path) and os.path.exists(cache_path):
                raise RuntimeError(f"Cannot link to {pool_path}, {cache_path} data exists")
            # clean up dead links
            if os.path.islink(cache_path) and not os.path.exists(cache_path):
                logging.warning(f"Dead link {cache_path} image detected")
            # possibly reset the symlink pointer
            if os.path.islink(cache_path):
                os.unlink(cache_path)
            os.symlink(pool_path, cache_path)

    @staticmethod
    def upload_link(cache_path, pool_path, params):
        """
        Upload a path to the pool depending on the pool location.

        All arguments are identical to the main entry method.
        """
        if os.path.islink(cache_path):
            raise ValueError("Cannot upload a symlink to its destination")
        else:
            TransferOps.upload_local(cache_path, pool_path, params)

    @staticmethod
    def delete_link(pool_path, params):
        """
        Delete a path in the pool depending on the pool location.

        All arguments are identical to the main entry method.
        """
        TransferOps.delete_local(pool_path, params)


class QCOW2ImageTransfer(StateBackend):
    """Backend manipulating root or external states from a shared pool of QCOW2 images."""

    ops = TransferOps

    @staticmethod
    def get_image_path(params):
        """
        Get the absolute path to a QCOW2 image.

        :param params: configuration parameters
        :type params: {str, str}
        :returns: absolute path to the QCOW2 image
        :rtype: str
        """
        vm_name, image_name = params["vms"], params["images"]
        vm_dir = os.path.join(params["vms_base_dir"], vm_name)

        image_path, image_format = params["image_name"], params.get("image_format")
        if image_format is None:
            raise ValueError(f"Unspecified image format for {image_name} - "
                            "must be qcow2 or raw")
        if image_format not in ["raw", "qcow2"]:
            raise ValueError(f"Incompatible image format {image_format} for"
                            f" {image_name} - must be qcow2 or raw")
        if not os.path.isabs(image_path):
            image_path = os.path.join(vm_dir, image_path)
        image_format = "" if image_format == "raw" else "." + image_format
        image_path = image_path + image_format
        return image_path

    @classmethod
    def check_root(cls, params, object=None):
        """
        Check whether a root state or essentially the object exists.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        image_name = params["image_name"]
        target_image = cls.get_image_path(params)
        shared_pool = params["image_pool"]
        image_base_name = os.path.join(vm_name, os.path.basename(target_image))

        logging.debug(f"Checking for shared {vm_name}/{image_name} existence"
                      f" in the shared pool {shared_pool}")
        src_image_name = os.path.join(shared_pool, image_base_name)
        # it is possible that the the root state is partially provided
        pool_images = cls.ops.list(os.path.join(shared_pool, vm_name), params)
        if image_name + ".qcow2" in pool_images:
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
        target_image = cls.get_image_path(params)
        shared_pool = params["image_pool"]
        image_base_names = os.path.join(vm_name, os.path.basename(target_image))

        logging.info(f"Downloading shared {vm_name}/{image_name} "
                     f"from the shared pool {shared_pool}")
        src_image_name = os.path.join(shared_pool, image_base_names)
        cls.ops.download(target_image, src_image_name, params)

    @classmethod
    def set_root(cls, params, object=None):
        """
        Set a root state to provide object existence.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        image_name = params["image_name"]
        target_image = cls.get_image_path(params)
        shared_pool = params["image_pool"]
        image_base_names = os.path.join(vm_name, os.path.basename(target_image))

        logging.info(f"Uploading shared {vm_name}/{image_name} "
                     f"to the shared pool {shared_pool}")
        dst_image_name = os.path.join(shared_pool, image_base_names)
        cls.ops.upload(target_image, dst_image_name, params)

    @classmethod
    def unset_root(cls, params, object=None):
        """
        Unset a root state to prevent object existence.

        All arguments match the base class and in addition:
        """
        vm_name = params["vms"]
        image_name = params["image_name"]
        target_image = cls.get_image_path(params)
        shared_pool = params["image_pool"]
        image_base_names = os.path.join(vm_name, os.path.basename(target_image))

        logging.info(f"Removing shared {vm_name}/{image_name} "
                     f"from the shared pool {shared_pool}")
        dst_image_name = os.path.join(shared_pool, image_base_names)
        cls.ops.delete(dst_image_name, params)

    @classmethod
    def get_state_dir(cls, params):
        """
        Get the directory used for storing states according to internal criteria.

        All of the arguments match the signature of the other methods here.
        """
        return params["swarm_pool"] if params.get("swarm_pool") else params["vms_base_dir"]

    @classmethod
    def get_dependency(cls, state, params):
        """
        Return a backing state that the current state depends on.

        :param str state: state name to retrieve the backing dependency of

        The rest of the arguments match the signature of the other methods here.
        """
        vm_name, image_name = params["vms"], params["images"]
        vm_dir = os.path.join(cls.get_state_dir(params), vm_name)
        params["image_chain"] = f"snapshot {image_name}"
        params["image_name_snapshot"] = os.path.join(image_name, state)
        params["image_format_snapshot"] = "qcow2"
        # TODO: we might want to return the complete backing chain but in some
        # cases parts of it are stored in a remote location
        #params["backing_chain"] = "yes"
        qemu_img = QemuImg(params.object_params("snapshot"), vm_dir, "snapshot")
        image_info = qemu_img.info(force_share=True, output="json")
        image_file = json.loads(image_info).get("backing-filename", "")
        return os.path.basename(image_file.replace(".qcow2", ""))

    @classmethod
    def compare_chain(cls, state, params):
        """
        Compare checksums for all dependencies states backing a given state.

        :param str state: state name
        :param params: configuration parameters
        :type params: {str, str}
        """
        cache_dir = cls.get_state_dir(params)
        pool_dir = params.get("get_location", params.get("image_pool", ""))
        vm_name = params["vms"]

        logging.info("Compare chain!")
        next_state = state
        while next_state != "":
            for image_name in params.objects("images"):
                image_params = params.object_params(image_name)
                if next_state == image_params["image_name"]:
                    cache_path = os.path.join(cache_dir, vm_name, next_state + ".qcow2")
                    pool_path = os.path.join(pool_dir, vm_name, next_state + ".qcow2")
                else:
                    cache_path = os.path.join(cache_dir, vm_name, image_name, next_state + ".qcow2")
                    pool_path = os.path.join(pool_dir, vm_name, image_name, next_state + ".qcow2")
                if not cls.ops.compare(cache_path, pool_path, image_params):
                    logging.info("Different 1!")
                    return False
            if next_state == state and params["object_type"] in ["vms", "nets/vms"]:
                cache_path = os.path.join(cache_dir, vm_name, next_state + ".state")
                pool_path = os.path.join(pool_dir, vm_name, next_state + ".state")
                if not cls.ops.compare(cache_path, pool_path, params):
                    logging.info("Different 2!")
                    return False
            # comparison of state chain is not yet complete if the state has backing dependencies
            next_state = cls.get_dependency(next_state, params) if next_state != image_params["image_name"] else ""

        logging.info("Same!")
        return True

    @classmethod
    def transfer_chain(cls, state, cache_dir, pool_dir, params, down=True):
        """
        Repeat pool operation an all dependencies states backing a given state.

        :param str state: state name
        :param str cache_dir: root cache directory to transfer from/to
        :param str pool_dir: root pool directory to transfer from/to
        :param params: configuration parameters
        :type params: {str, str}
        :param bool down: whether the chain is downloaded or uploaded
        """
        transfer_operation = cls.ops.download if down else cls.ops.upload
        vm_name = params["vms"]

        next_state = state
        while next_state != "":
            for image_name in params.objects("images"):
                image_params = params.object_params(image_name)
                cache_path = os.path.join(cache_dir, vm_name, image_name, next_state + ".qcow2")
                pool_path = os.path.join(pool_dir, vm_name, image_name, next_state + ".qcow2")
                # if only vm state is not available this would indicate image corruption
                transfer_operation(cache_path, pool_path, image_params)
            if next_state == state and params["object_type"] in ["vms", "nets/vms"]:
                cache_path = os.path.join(cache_dir, vm_name, next_state + ".state")
                pool_path = os.path.join(pool_dir, vm_name, next_state + ".state")
                transfer_operation(cache_path, pool_path, params)
            # transfer of state chain is not yet complete if the state has backing dependencies
            next_state = cls.get_dependency(next_state, params)

    @classmethod
    def show(cls, params, object=None):
        """
        Return a list of available states of a specific type.

        All arguments match the base class.
        """
        vm_name = params["vms"]
        state_tag = f"{vm_name}"
        format = ".state"
        if params["object_type"] in ["images", "nets/vms/images"]:
            image_name = params["images"]
            state_tag += f"/{image_name}"
            format = ".qcow2"

        pool_dir = params.get("check_location", params.get("image_pool", ""))
        path = os.path.join(pool_dir, state_tag)
        logging.debug(f"Checking for shared {state_tag} states "
                      f"in the shared pool {pool_dir}")

        states = cls.ops.list(path, params)
        states = [p.replace(format, "") for p in states]
        return states

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
        Get a state transferring its entire chain of dependencies.

        All arguments match the base class.
        """
        cache_dir = cls.get_state_dir(params)
        pool_dir = params.get("get_location", params.get("image_pool", ""))

        vm_name = params["vms"]
        state_tag = f"{vm_name}"
        format = "state"
        if params["object_type"] in ["images", "nets/vms/images"]:
            image_name = params["images"]
            state_tag += f"/{image_name}"
            format = "qcow2"
        state = params["get_state"]
        logging.info(f"Downloading shared {state_tag} state {state} "
                     f"from the shared pool {pool_dir} to {cache_dir}")

        try:
            cls.transfer_chain(state, cache_dir, pool_dir, params, down=True)
        except Exception as error:
            #remove_path = os.path.join(cache_dir, state_tag, state + "." + format)
            # TODO: error in self-syncing could result in self-deletion!
            #os.unlink(remove_path)
            raise error

    @classmethod
    def set(cls, params, object=None):
        """
        Set a state transferring its entire chain of dependencies.

        All arguments match the base class.
        """
        cache_dir = cls.get_state_dir(params)
        pool_dir = params.get("set_location", params.get("image_pool", ""))

        vm_name = params["vms"]
        state_tag = f"{vm_name}"
        if params["object_type"] in ["images", "nets/vms/images"]:
            image_name = params["images"]
            state_tag += f"/{image_name}"
        state = params["set_state"]
        logging.info(f"Uploading shared {state_tag} state {state} "
                     f"to the shared pool {pool_dir} from {cache_dir}")

        try:
            cls.transfer_chain(state, cache_dir, pool_dir, params, down=False)
        except Exception as error:
            #remove_path = os.path.join(pool_dir, state_tag, state + "." + format)
            #cls.ops.delete(remove_path, params)
            raise error

    @classmethod
    def unset(cls, params, object=None):
        """
        Unset a state preserving its entire chain of dependencies.

        All arguments match the base class and in addition:
        """
        pool_dir = params.get("unset_location", params.get("image_pool", ""))

        vm_name = params["vms"]
        state_tag = f"{vm_name}"
        if params["object_type"] in ["images", "nets/vms/images"]:
            image_name = params["images"]
            state_tag += f"/{image_name}"
        state = params["unset_state"]
        logging.info(f"Removing shared {state_tag} state {state} "
                     f"from the shared pool {pool_dir}")

        for image_name in params.objects("images"):
            image_params = params.object_params(image_name)
            pool_path = os.path.join(pool_dir, vm_name, image_name, state + ".qcow2")
            cls.ops.delete(pool_path, image_params)
        if params["object_type"] in ["vms", "nets/vms"]:
            pool_path = os.path.join(pool_dir, vm_name, state + ".state")
            cls.ops.delete(pool_path, params)


class RootSourcedStateBackend(StateBackend):
    """Backend manipulating root states from a possibly shared source."""

    transport = QCOW2ImageTransfer

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
        pool_root_exists = cls.transport.check_root(params, object)
        return local_root_exists or pool_root_exists

    @classmethod
    def get_root(cls, params, object=None):
        """
        Get a root state or essentially due to pre-existence do nothing.

        All arguments match the base class.
        """
        if params.get_boolean("update_pool", False):
            cls.transport.get_root(params, object)
            return
        if not params.get_boolean("use_pool", True):
            cls._get_root(params, object)
            return

        local_root_exists = cls._check_root(params, object)
        pool_root_exists = cls.transport.check_root(params, object)

        if pool_root_exists:
            if local_root_exists:
                cache_valid = cls.transport.compare_chain(params["image_name"], params)
            else:
                cache_valid = False
            if not cache_valid:
                cls.transport.get_root(params, object)
        cls._get_root(params, object)

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

    transport = QCOW2ImageTransfer

    @classmethod
    def get_state_dir(cls, params):
        """
        Get the directory used for storing states according to internal criteria.

        :param params: parameters for the current state manipulation
        :type params: {str, str}
        """
        return params["swarm_pool"] if params.get("swarm_pool") else params["vms_base_dir"]

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
        elif not params.get_boolean("use_pool", True):
            return local_state_exists
        pool_state_exists = cls.transport.check(params, object)
        return local_state_exists or pool_state_exists

    @classmethod
    def get(cls, params, object=None):
        """
        Get a root state or essentially due to pre-existence do nothing.

        All arguments match the base class.
        """
        if params.get_boolean("update_pool", False):
            cls.transport.get(params, object)
            return
        if not params.get_boolean("use_pool", True):
            cls._get(params, object)
            return

        local_state_exists = cls._check(params, object)
        pool_state_exists = cls.transport.check(params, object)

        if pool_state_exists:
            if local_state_exists:
                cache_valid = cls.transport.compare_chain(params["get_state"], params)
            else:
                cache_valid = False
            if not cache_valid:
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
