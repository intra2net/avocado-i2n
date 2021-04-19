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
import logging
import shutil
import contextlib
import fcntl
import errno

from .qcow2 import QCOW2Backend, get_image_path


#: skip waiting on locks if we only read from the pool for all processes, i.e.
#: use update_pool=no for all parallel operations
#: WARNING: use it only if you know what you are doing
SKIP_LOCKS = False


class QCOW2PoolBackend(QCOW2Backend):
    """Backend manipulating off states as from a shared pool of QCOW2 images."""

    _require_running_object = False

    @classmethod
    def check_root(cls, params, object=None):
        """
        Check whether a root state or essentially the object exists.

        All arguments match the base class.
        """
        if not params.get_boolean("use_pool", True):
            return super(QCOW2PoolBackend, cls).check_root(params, object)
        elif (params.get_boolean("update_pool", False) and
                not super(QCOW2PoolBackend, cls).check_root(params, object)):
            raise RuntimeError("Updating state pool requires local root states")
        elif (not params.get_boolean("update_pool", False) and
                super(QCOW2PoolBackend, cls).check_root(params, object)):
            return True

        vm_name = params["vms"]
        image_name = params["image_name"]
        target_image = get_image_path(params)
        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        image_base_names = os.path.join(vm_name, os.path.basename(target_image))

        logging.debug(f"Checking for shared {vm_name}/{image_name} existence"
                      f" in the shared pool {shared_pool}")
        src_image_name = os.path.join(shared_pool, image_base_names)
        if os.path.exists(src_image_name):
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
        if (super(QCOW2PoolBackend, cls).check_root(params, object) or
                not params.get_boolean("use_pool", True)):
            super(QCOW2PoolBackend, cls).get_root(params, object)
            return

        vm_name = params["vms"]
        image_name = params["image_name"]
        target_image = get_image_path(params)
        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        image_base_names = os.path.join(vm_name, os.path.basename(target_image))

        logging.info(f"Downloading shared {vm_name}/{image_name} "
                     f"from the shared pool {shared_pool}")
        src_image_name = os.path.join(shared_pool, image_base_names)
        update_timeout = params.get_numeric("update_pool_timeout", 300)
        with image_lock(src_image_name, update_timeout) as lock:
            os.makedirs(os.path.dirname(target_image), exist_ok=True)
            shutil.copy(src_image_name, target_image)

    @classmethod
    def set_root(cls, params, object=None):
        """
        Set a root state to provide object existence.

        All arguments match the base class.
        """
        # local and pool root setting are mutually exclusive as we usually want
        # to set the pool root from an existing local root with some states on it
        if not params.get_boolean("update_pool", False):
            super(QCOW2PoolBackend, cls).set_root(params, object)
            return

        vm_name = params["vms"]
        image_name = params["image_name"]
        target_image = get_image_path(params)
        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        image_base_names = os.path.join(vm_name, os.path.basename(target_image))

        logging.info(f"Uploading shared {vm_name}/{image_name} "
                     f"to the shared pool {shared_pool}")
        dst_image_name = os.path.join(shared_pool, image_base_names)
        update_timeout = params.get_numeric("update_pool_timeout", 300)
        with image_lock(dst_image_name, update_timeout) as lock:
            os.makedirs(shared_pool, exist_ok=True)
            shutil.copy(target_image, dst_image_name)

    @classmethod
    def unset_root(cls, params, object=None):
        """
        Unset a root state to prevent object existence.

        All arguments match the base class and in addition:
        """
        # local and pool root setting are mutually exclusive as we usually want
        # to set the pool root from an existing local root with some states on it
        if not params.get_boolean("update_pool", False):
            super(QCOW2PoolBackend, cls).unset_root(params, object)
            return

        vm_name = params["vms"]
        image_name = params["image_name"]
        target_image = get_image_path(params)
        shared_pool = params.get("image_pool", "/mnt/local/images/pool")
        image_base_names = os.path.join(vm_name, os.path.basename(target_image))

        logging.info(f"Removing shared {vm_name}/{image_name} "
                     f"from the shared pool {shared_pool}")
        dst_image_name = os.path.join(shared_pool, image_base_names)
        update_timeout = params.get_numeric("update_pool_timeout", 300)
        with image_lock(dst_image_name, update_timeout) as lock:
            os.unlink(dst_image_name)


@contextlib.contextmanager
def image_lock(image_path, timeout=300):
    """
    Wait for a lock to free image for state pool operations.

    :param str image_path: path to the potentially locked image
    :param int timeout: timeout to wait before erroring out (default 5 mins)
    """
    if READONLY_MODE:
        yield None
        return
    lockfile = image_path + ".lock"
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
