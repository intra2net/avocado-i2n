#!/usr/bin/env python

import unittest
import unittest_importer

from avocado import Test
import avocado_i2n.cmd_parser as cmd
import avocado_i2n.params_parser as param


class CmdParserTest(Test):

    def setUp(self):
        self.config = {}
        self.config["params"] = ["aaa=bbb"]

    def tearDown(self):
        pass

    def test_param_dict(self):
        cmd.params_from_cmd(self.config)
        self.assertEqual(len(self.config["param_dict"].keys()), 1)
        self.assertIn("aaa", self.config["param_dict"].keys())
        self.assertEqual(self.config["param_dict"]["aaa"], "bbb")
        self.config["params"] += ["ccc"]
        with self.assertRaises(SystemExit):
            cmd.params_from_cmd(self.config)

    def test_selected_vms(self):
        # test default (from config)
        cmd.params_from_cmd(self.config)
        self.assertEqual(self.config["vm_strs"], self.config["available_vms"])
        self.assertIn("only CentOS", self.config["vm_strs"]["vm1"])
        self.assertIn("only Win10", self.config["vm_strs"]["vm2"])
        self.assertIn("only Ubuntu", self.config["vm_strs"]["vm3"])

        # test override (from command line)

        self.config["params"] += ["only_vm1=Fedora", "only_vm2=Win10"]
        cmd.params_from_cmd(self.config)
        self.assertEqual(self.config["vm_strs"], self.config["available_vms"])
        self.assertIn("only Fedora", self.config["vm_strs"]["vm1"])
        self.assertIn("only Win10", self.config["vm_strs"]["vm2"])
        self.assertIn("only Ubuntu", self.config["vm_strs"]["vm3"])

        self.config["params"] += ["vms=vm2", "only_vm2=Win7"]
        cmd.params_from_cmd(self.config)
        self.assertEqual(sorted(self.config["available_vms"].keys()), ["vm1", "vm2", "vm3"])
        self.assertEqual(sorted(self.config["vm_strs"].keys()), ["vm2"])
        self.assertIn("only Win7", self.config["vm_strs"]["vm2"])

    def test_selected_vms_invalid(self):
        base_params = self.config["params"]

        self.config["params"] = base_params + ["vms=vmX"]
        with self.assertRaises(ValueError):
            cmd.params_from_cmd(self.config)

    def test_selected_tests(self):
        # test default (from config)
        cmd.params_from_cmd(self.config)
        self.assertIn("normal", self.config["available_restrictions"])
        self.assertIn("only normal\n", self.config["tests_str"])

        # test override (from command line)
        self.config["params"] += ["only=minimal"]
        cmd.params_from_cmd(self.config)
        self.assertIn("minimal", self.config["available_restrictions"])
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

    def test_abort_early_empty_product(self):
        self.config["params"] += ["only=install"]
        with self.assertRaises(param.EmptyCartesianProduct):
            cmd.params_from_cmd(self.config)

        self.config["params"] = ["only=nonexistent_variant"]
        with self.assertRaises(param.EmptyCartesianProduct):
            cmd.params_from_cmd(self.config)

        self.config["params"] = ["only=tutoria1", "only=tutorial2"]
        with self.assertRaises(param.EmptyCartesianProduct):
            cmd.params_from_cmd(self.config)

if __name__ == '__main__':
    unittest.main()
