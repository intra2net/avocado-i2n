#!/usr/bin/env python

import unittest
import unittest_importer

import avocado_i2n.cmd_parser as cmd


class CmdParserTest(unittest.TestCase):

    def setUp(self):
        self.config = {}
        self.config["params"] = ["aaa=bbb"]

    def tearDown(self):
        pass

    def test_param_dict(self):
        self.config["params"] += ["ccc"]
        cmd.params_from_cmd(self.config)
        self.assertEqual(self.config["param_str"], "aaa = bbb\n")

    def test_selected_vms(self):
        cmd.params_from_cmd(self.config)
        self.assertEqual(self.config["selected_vms"], self.config["available_vms"])

        self.config["params"] += ["vms=vm1"]
        cmd.params_from_cmd(self.config)
        self.assertEqual(self.config["selected_vms"], ["vm1"])

    def test_selected_vms_invalid(self):
        self.config["params"] += ["vms=vmX"]
        with self.assertRaises(ValueError):
            cmd.params_from_cmd(self.config)

    def test_selected_restr(self):
        cmd.params_from_cmd(self.config)
        self.assertIn("only normal\n", self.config["tests_str"])

        self.config["params"] += ["only=minimal"]
        cmd.params_from_cmd(self.config)
        self.assertIn("only minimal\n", self.config["tests_str"])

    def test_selected_restr_invalid(self):
        self.config["params"] += ["default_only=nonminimal"]
        with self.assertRaises(ValueError):
            cmd.params_from_cmd(self.config)

if __name__ == '__main__':
    unittest.main()
