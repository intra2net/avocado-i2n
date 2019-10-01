#!/usr/bin/env python

import unittest
import unittest.mock as mock
import shutil
import re

from avocado.core import exceptions

import unittest_importer
from avocado_i2n.vmnet import VMNetwork


class VMNetworkTest(unittest.TestCase):

    def setUp(self):
        self.vmnet = mock.MagicMock()

    def tearDown(self):
        pass

    def test_object_params(self):
        pass


if __name__ == '__main__':
    unittest.main()
