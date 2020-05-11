# Copyright 2013-2020 Intranet AG and contributors
#
# Significant portion of this code was taken from the Avocado VT project with
# Author: Lucas Meneghel Rodrigues <lmr@redhat.com>
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

import os
import sys
import glob

from setuptools import setup

VERSION = open('VERSION', 'r').read().strip()


def __is_virtual_env():
    return (hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and
                                            sys.base_prefix != sys.prefix))


def get_dir(system_path=None, virtual_path=None):
    """
    Retrieve VIRTUAL_ENV friendly path
    :param system_path: Relative system path
    :param virtual_path: Overrides system_path for virtual_env only
    :return: VIRTUAL_ENV friendly path
    """
    if virtual_path is None:
        virtual_path = system_path
    if __is_virtual_env():
        if virtual_path is None:
            virtual_path = []
        return os.path.join(*virtual_path)
    else:
        if system_path is None:
            system_path = []
        return os.path.join(*(['/'] + system_path))


def get_data_files():
    def add_files(level=[]):
        installed_location = ['usr', 'share', 'avocado-plugins-i2n']
        installed_location += level
        level_str = '/'.join(level)
        if level_str:
            level_str += '/'
        file_glob = '%s*' % level_str
        files_found = [path for path in glob.glob(file_glob) if
                       os.path.isfile(path)]
        return [((get_dir(installed_location, level)), files_found)]

    data_files = []
    data_files_dirs = ['tp_folder']

    for data_file_dir in data_files_dirs:
        for root, dirs, files in os.walk(data_file_dir):
            for subdir in dirs:
                rt = root.split('/')
                rt.append(subdir)
                data_files += add_files(rt)

    return data_files


setup(name='avocado-framework-plugin-i2n',
      version=VERSION,
      description='Avocado Intra2net Plugins',
      author='Intra2net AG',
      author_email='support@intra2net.com',
      url='http://github.com/intra2net/avocado-i2n',
      packages=['avocado_i2n', 'avocado_i2n.plugins', 'avocado_i2n.cartgraph', 'avocado_i2n.vmnet'],
      package_data={'avocado_i2n.vmnet': ['templates/*.template']},
      install_requires=['avocado-framework-plugin-vt==%s' % VERSION, 'aexpect'],
      data_files=get_data_files(),
      include_package_data=True,
      entry_points={
          'avocado.plugins.settings': [
              'i2n-settings = avocado_i2n.plugins.i2n_settings:I2NSettings',
              ],
          'avocado.plugins.cli': [
              'auto = avocado_i2n.plugins.auto:Auto',
              ],
          'avocado.plugins.cli.cmd': [
              'manu = avocado_i2n.plugins.manu:Manu',
              ],
          'avocado.plugins.runner': [
              # TODO: wait for the upstream to make the default loader a plugin as well
              'traverser = avocado_i2n.runner:CartesianRunner',
              ],
          },
      )
