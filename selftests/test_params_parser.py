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


if __name__ == '__main__':
    unittest.main()
