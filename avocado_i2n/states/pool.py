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

from .qcow2 import QCOW2Backend


class QCOW2PoolBackend(QCOW2Backend):
    """Backend manipulating off states as from a shared pool of QCOW2 images."""

    _require_running_object = False

    @classmethod
    def check_root(cls, params, object=None):
        """
        Check whether a root state or essentially the object exists.

        All arguments match the base class.
        """
        if super(QCOW2PoolBackend, cls).check_root(params, object):
            return True

        vm_name = params["vms"]
        image_name = params["image_name"]

        image_format = params.get("image_format", "qcow2")
        if image_format != "qcow2":
            raise ValueError(f"Incompatible image format {image_format} for"
                             f" {image_name} - must be qcow2")
        if not os.path.isabs(image_name):
            image_name = os.path.join(params["images_base_dir"], image_name)
        image_name += "." + image_format

        shared_pool = params.get("image_pool", "/mnt/local/images")
        image_base_name = os.path.basename(image_name)
        logging.debug(f"Checking for shared {vm_name}/{image_base_name} existence"
                      f" in the shared pool {shared_pool}")
        src_image_name = os.path.join(shared_pool, image_base_name)
        if os.path.exists(src_image_name):
            # proactive step: download available root
            os.makedirs(os.path.dirname(image_name), exist_ok=True)
            shutil.copy(src_image_name, image_name)
            logging.info("The shared %s image exists", src_image_name)
            return True
        else:
            logging.info("The shared %s image doesn't exist", src_image_name)
            return False
