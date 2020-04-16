#!/usr/bin/env python

import unittest
import unittest_importer

import avocado_i2n.cmd_parser as cmd


class CmdParserTest(unittest.TestCase):

    def setUp(self):
        self.config = {}
        self.config["params"] = []

    def tearDown(self):
        pass

    def test_parse_cmd(self):
        cmd.params_from_cmd(self.config)


if __name__ == '__main__':
    unittest.main()
