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
        self.assertEqual(len(self.config["param_dict"].keys()), 1)
        self.assertIn("aaa", self.config["param_dict"].keys())
        self.assertEqual(self.config["param_dict"]["aaa"], "bbb")

    def test_selected_vms(self):
        # test default (from config)
        cmd.params_from_cmd(self.config)
        self.assertEqual(list(self.config["vm_strs"].keys()), self.config["available_vms"])
        self.assertIn("only CentOS", self.config["vm_strs"]["vm1"])
        self.assertIn("only Win10", self.config["vm_strs"]["vm2"])
        self.assertIn("only Ubuntu", self.config["vm_strs"]["vm3"])

        # test override (from command line)

        # TODO: current sample test suite does not support multiple guest variants per object
        self.config["params"] += ["only_vm1=CentOS"]
        cmd.params_from_cmd(self.config)
        self.assertEqual(list(self.config["vm_strs"].keys()), self.config["available_vms"])
        self.assertIn("only CentOS", self.config["vm_strs"]["vm1"])

        self.config["params"] += ["vms=vm1"]
        cmd.params_from_cmd(self.config)
        self.assertEqual(list(self.config["vm_strs"].keys()), ["vm1"])
        self.assertIn("only CentOS", self.config["vm_strs"]["vm1"])

    def test_selected_vms_invalid(self):
        base_params = self.config["params"]

        self.config["params"] = base_params + ["vms=vmX"]
        with self.assertRaises(ValueError):
            cmd.params_from_cmd(self.config)

        self.config["params"] = base_params + ["default_only_vm1="]
        with self.assertRaises(ValueError):
            cmd.params_from_cmd(self.config)

    def test_selected_tests(self):
        # test default (from config)
        cmd.params_from_cmd(self.config)
        self.assertIn("only normal\n", self.config["tests_str"])

        # test override (from command line)
        self.config["params"] += ["only=minimal"]
        cmd.params_from_cmd(self.config)
        self.assertIn("only minimal\n", self.config["tests_str"])

    def test_selected_tests_invalid(self):
        self.config["params"] += ["default_only=nonminimal"]
        with self.assertRaises(ValueError):
            cmd.params_from_cmd(self.config)

    def test_selected_tests_nontrivial(self):
        # test default (from config)
        cmd.params_from_cmd(self.config)
        self.assertIn("only normal\n", self.config["tests_str"])
        self.assertNotIn("only tutorial1\n", self.config["tests_str"])

        # test override (from command line)

        self.config["params"] += ["only=tutorial1"]
        cmd.params_from_cmd(self.config)
        self.assertIn("only normal\n", self.config["tests_str"])
        self.assertIn("only tutorial1\n", self.config["tests_str"])

        self.config["params"] += ["only=minimal"]
        cmd.params_from_cmd(self.config)
        self.assertIn("only minimal\n", self.config["tests_str"])
        self.assertIn("only tutorial1\n", self.config["tests_str"])

if __name__ == '__main__':
    unittest.main()
