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
import shutil
import logging

from .qcow2 import QCOW2Backend, get_image_path


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
        os.unlink(dst_image_name)
