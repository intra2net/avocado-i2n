#!/usr/bin/env python

import unittest
import unittest_importer

from virttest.utils_params import Params

import avocado_i2n.params_parser as param


class ParamsParserTest(unittest.TestCase):

    def setUp(self):
        self.base_dict = {}
        self.base_str = ""
        self.base_file = "sets.cfg"
        self.show_restriction = False
        self.show_dictionaries = False
        self.show_dict_fullname = False
        self.show_dict_contents = False

    def tearDown(self):
        pass

    def test_parser_params(self):
        self.base_str = "only tutorial1\n"
        parser = param.prepare_parser(base_dict=self.base_dict,
                                      base_str=self.base_str,
                                      base_file=self.base_file,
                                      show_restriction=False,
                                      show_dictionaries=False,
                                      show_dict_fullname=False,
                                      show_dict_contents=False)
        params = param.prepare_params(base_dict=self.base_dict,
                                      base_str=self.base_str,
                                      base_file=self.base_file,
                                      show_restriction=False,
                                      show_dictionaries=False,
                                      show_dict_fullname=False,
                                      show_dict_contents=False)
        d = param.peek(parser)
        for key in params.keys():
            self.assertEqual(params[key], d[key], "The %s parameter must coincide: %s != %s" % (key, params[key], d[key]))

    def testMultiplyParamsPerObject(self):
        os.environ['PREFIX'] = "ut"
        params = Params({"vm_unique_keys": "foo bar", "foo": "baz", "bar": "bazz", "other": "misc"})
        vm_params = param.multiply_params_per_object(params, ["vm1", "vm2"])
        # Object specific parameters must exist for each object
        self.assertIn("foo_vm1", vm_params)
        # Multiplication also involves the value
        self.assertTrue(vm_params["foo_vm1"].startswith("ut_vm1"), vm_params["foo_vm1"])
        # Object specific parameters must exist for each object
        self.assertIn("foo_vm2", vm_params)
        # Multiplication also involves the value
        self.assertTrue(vm_params["foo_vm2"].startswith("ut_vm2"), vm_params["foo_vm2"])
        # Default parameter is preserved after multiplication
        self.assertIn("foo", vm_params)
        # Default parameter value is preserved after multiplication
        self.assertFalse(vm_params["foo"].startswith("ut_vm1"), vm_params["foo"])
        # Default parameter value is preserved after multiplication
        self.assertFalse(vm_params["foo"].startswith("ut_vm2"), vm_params["foo"])
        # Object specific parameters must exist for each object
        self.assertIn("bar_vm1", vm_params)
        # Multiplication also involves the value
        self.assertTrue(vm_params["bar_vm1"].startswith("ut_vm1"), vm_params["bar_vm1"])
        # Object specific parameters must exist for each object
        self.assertIn("bar_vm2", vm_params)
        # Multiplication also involves the value
        self.assertTrue(vm_params["bar_vm2"].startswith("ut_vm2"), vm_params["bar_vm2"])
        # Default parameter is preserved after multiplication
        self.assertIn("bar", vm_params)
        # Default parameter value is preserved after multiplication
        self.assertFalse(vm_params["bar"].startswith("ut_vm1"), vm_params["bar"])
        # Default parameter value is preserved after multiplication
        self.assertFalse(vm_params["bar"].startswith("ut_vm2"), vm_params["bar"])
        # Object general parameters must not be multiplied
        self.assertNotIn("other_vm1", vm_params)
        # Object general parameters must not be multiplied
        self.assertNotIn("other_vm2", vm_params)
        # Object general parameters must be preserved as is
        self.assertIn("other", vm_params)
        # Object general parameter value is preserved after multiplication
        self.assertFalse(vm_params["other"].startswith("ut_vm1"), vm_params["other"])
        # Object general parameter value is preserved after multiplication
        self.assertFalse(vm_params["other"].startswith("ut_vm2"), vm_params["other"])


if __name__ == '__main__':
    unittest.main()
