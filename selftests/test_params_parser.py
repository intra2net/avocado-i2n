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

    def testIsObjectSpecific(self):
        self.assertTrue(param.is_object_specific("genie_vm1", ["vm1", "vm2"]))
        self.assertFalse(param.is_object_specific("genie_vm1", ["nic1", "nic2"]))
        self.assertTrue(param.is_object_specific("god_vm2", ["vm1", "vm2"]))
        self.assertFalse(param.is_object_specific("god_vm2", ["nic1", "nic2"]))
        self.assertFalse(param.is_object_specific("genie", ["vm1", "vm2"]))
        self.assertFalse(param.is_object_specific("god", ["vm1", "vm2"]))
        self.assertFalse(param.is_object_specific("wizard", ["vm1", "vm2"]))
        self.assertFalse(param.is_object_specific("wizard", ["wizard"]))

    def testObjectParams(self):
        vm_params = Params({"name_vm1": "josh", "name_vm2": "jean", "name": "jarjar", "surname": "jura"})
        params = param.object_params(vm_params, "vm1", ["vm1", "vm2"])
        for key in params.keys():
            self.assertFalse(param.is_object_specific(key, ["vm1", "vm2"]))

    def testObjectifyParams(self):
        params = Params({"name_vm1": "josh", "name_vm2": "jean", "name": "jarjar", "surname": "jura"})
        vm_params = param.objectify_params(params, "vm1", ["vm1", "vm2"])
        # Parameters already specific to the object must be preserved
        self.assertIn("name_vm1" in vm_params)
        # Parameters already specific to the object must be preserved
        self.assertEqual(vm_params["name_vm1"], params["name_vm1"])
        # Parameters specific to a different object must be pruned
        self.assertNotIn("name_vm2", vm_params)
        # Parameters not specific to any object must be pruned if there is specific alternative
        self.assertNotIn("name", vm_params)
        # Parameters not specific to any object must become specific to the object
        self.assertIn("surname_vm1", vm_params)
        # Parameters not specific to any object must become specific to the object
        self.assertNotIn("surname", vm_params)

    def testMergeObjectParams(self):
        params1 = Params({"name_vm1": "josh", "name": "jarjar", "surname": "jura"})
        params2 = Params({"name_vm2": "jean", "name": "jaja", "surname": "jura"})
        vm_params = param.merge_object_params(["vm1", "vm2"], [params1, params2], "vms", "vm1")
        # Main object specific parameters must be default
        self.assertIn("name", vm_params)
        # Main object specific parameters must be default
        self.assertEqual(vm_params["name"], params1["name_vm1"])
        # Secondary object specific parameters must be preserved
        self.assertIn("name_vm2", vm_params)
        # Secondary object specific parameters must be preserved
        self.assertEqual(vm_params["name_vm2"], params2["name_vm2"])
        # The parameters identical for all objects are reduced to default parameters
        self.assertIn("surname", vm_params)
        # The parameters identical for all objects are reduced to default parameters
        self.assertEqual(vm_params["surname"], "jura")

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
