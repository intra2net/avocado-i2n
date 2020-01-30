# Copyright 2013-2020 Intranet AG and contributors
#
# Significant portion of this code was taken from the Avocado VT project with
# Author: Lukas Doktor <ldoktor@redhat.com>
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
Avocado plugin that extends the settings path of our config paths.
"""

import os
from pkg_resources import resource_filename
from pkg_resources import resource_listdir

from avocado.core.plugin_interfaces import Settings


class I2NSettings(Settings):

    def adjust_settings_paths(self, paths):
        base = resource_filename('avocado_i2n', 'conf.d')
        for path in [os.path.join(base, conf)
                     for conf in resource_listdir('avocado_i2n', 'conf.d')
                     if conf.endswith('.conf')]:
            paths.insert(0, path)
