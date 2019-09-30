import os
import sys

from setuptools import setup

VERSION = open('VERSION', 'r').read().strip()

VIRTUAL_ENV = hasattr(sys, 'real_prefix')


def get_dir(system_path=None, virtual_path=None):
    """
    Retrieve VIRTUAL_ENV friendly path
    :param system_path: Relative system path
    :param virtual_path: Overrides system_path for virtual_env only
    :return: VIRTUAL_ENV friendly path
    """
    if virtual_path is None:
        virtual_path = system_path
    if VIRTUAL_ENV:
        if virtual_path is None:
            virtual_path = []
        return os.path.join(*virtual_path)
    else:
        if system_path is None:
            system_path = []
        return os.path.join(*(['/'] + system_path))


setup(name='avocado-framework-plugins-i2n',
      version=VERSION,
      description='Avocado Intra2net Plugins',
      author='Intra2net AG',
      author_email='support@intra2net.com',
      url='http://github.com/intra2net/avocado-i2n',
      packages=['avocado_i2n', 'avocado_i2n.plugins', 'avocado_i2n.cartgraph', 'avocado_i2n.vmnet'],
      package_data={'avocado_i2n.vmnet': ['templates/*.template']},
      install_requires=['avocado-framework-plugins-vt', 'aexpect'],
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
