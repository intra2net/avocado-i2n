#!/usr/bin/env python

import unittest
import unittest_importer

from avocado import Test
from virttest.utils_params import Params

import avocado_i2n.params_parser as param


class ParamsParserTest(Test):

    def setUp(self):
        self.base_dict = {}
        self.base_str = "only normal\n"
        self.base_file = "sets.cfg"
        self.show_restriction = False
        self.show_dictionaries = False
        self.show_dict_fullname = False
        self.show_dict_contents = False

    def tearDown(self):
        pass

    def test_join_str(self):
        """Test a resulting join string satifies certain syntactic form."""
        output = param.join_str({"obj1": "only a", "obj2": "param1 = A\n"}, base_str="")
        self.assertEqual(output, "obj1:\n"
                                 "    only a\n"
                                 "obj2:\n"
                                 "    param1 = A\n"
                                 "join obj1 obj2\n")

    def test_parser_params(self):
        """Test that parameters obtain from parser or directly are the same."""
        self.base_str += "only tutorial1\n"
        config = param.Reparsable()
        config.parse_next_batch(base_file=self.base_file,
                                base_str=self.base_str,
                                base_dict=self.base_dict)
        parser = config.get_parser(show_restriction=False,
                                   show_dictionaries=False,
                                   show_dict_fullname=False,
                                   show_dict_contents=False)
        params = config.get_params(show_restriction=False,
                                   show_dictionaries=False,
                                   show_dict_fullname=False,
                                   show_dict_contents=False)
        d = parser.get_dicts().__next__()
        for key in params.keys():
            self.assertEqual(params[key], d[key], "The %s parameter must coincide: %s != %s" % (key, params[key], d[key]))


if __name__ == '__main__':
    unittest.main()
