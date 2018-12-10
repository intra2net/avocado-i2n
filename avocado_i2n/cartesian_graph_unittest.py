#!/usr/bin/env python

import unittest
import unittest.mock as mock
import shutil
import re

from avocado.core import exceptions

from .cartesian_graph import CartesianGraph


class DummyTestRunning(object):

    fail_switch = []
    asserted_tests = []

    def __init__(self, node):
        assert len(self.fail_switch) == len(self.asserted_tests), "%s != %s" % (len(self.fail_switch), len(self.asserted_tests))
        # assertions about the test calls
        self.current_test_dict = node.params
        assert len(self.asserted_tests) > 0, "Unexpected test %s" % self.current_test_dict["shortname"]
        self.expected_test_dict = self.asserted_tests.pop(0)
        for checked_key in self.expected_test_dict.keys():
            assert checked_key in self.current_test_dict.keys(), "%s missing in %s" % (checked_key, self.current_test_dict["shortname"])
            expected, current = self.expected_test_dict[checked_key], self.current_test_dict[checked_key]
            assert re.match(expected, current) is not None, "Expected parameter %s=%s "\
                                                            "but obtained %s=%s for %s" % (checked_key, expected,
                                                                                           checked_key, current,
                                                                                           self.expected_test_dict["shortname"])

        self.expected_test_fail = self.fail_switch.pop(0)

    def result(self):
        if self.expected_test_fail and "install" in self.expected_test_dict["shortname"]:
            raise exceptions.TestFail("God wanted this test to fail")
        elif self.expected_test_fail and self.current_test_dict.get("abort_on_error", "no") == "yes":
            raise exceptions.TestSkipError("God wanted this test to abort")
        else:
            return not self.expected_test_fail


class DummyStateCheck(object):

    present_states = []

    def __init__(self, params, env, print_pos=True, print_neg=True):
        if params.get("check_state") in self.present_states:
            self.result = True
        else:
            self.result = False


def mock_run_test_node(_self, node):
    return DummyTestRunning(node).result()


def mock_check_state(params, env, print_pos=True, print_neg=True):
    return DummyStateCheck(params, env, print_pos=True, print_neg=True).result


@mock.patch('cartesian_graph.state_setup.check_state', mock_check_state)
@mock.patch.object(CartesianGraph, 'run_test_node', mock_run_test_node)
class CartesianTreesTest(unittest.TestCase):

    def setUp(self):
        DummyTestRunning.asserted_tests = []
        DummyTestRunning.fail_switch = []
        DummyStateCheck.present_states = []

        self.args = mock.MagicMock()
        self.args.param_str = ""
        self.args.tests_str = "only all\n"
        self.args.vm_strs = {"vm1": "only Business_Server\n", "vm2": "only Business_Server\n", "vm3": "only Business_Server"}

        self.prefix = ""
        self.main_vm = ""

        self.trees = CartesianGraph(self.args, {})
        self.job = None

    def tearDown(self):
        shutil.rmtree("./graph_parse", ignore_errors=True)
        shutil.rmtree("./graph_traverse", ignore_errors=True)

    def test_object_params(self):
        self.args.tests_str += "only tutorial1\n"
        self.trees.parse_object_trees(self.args.param_str, self.args.tests_str, self.args.vm_strs, self.prefix, self.main_vm)
        test_object = self.trees._testobjects[0]
        dict_generator = test_object.parser.get_dicts()
        dict1 = dict_generator.__next__()
        # Parser of test objects must contain exactly one dictionary
        self.assertRaises(StopIteration, dict_generator.__next__)
        self.assertEqual(len(dict1.keys()), len(test_object.params.keys()), "The parameters of a test node must be the same as its only parser dictionary")
        for key in dict1.keys():
            self.assertEqual(dict1[key], test_object.params[key], "The values of key %s %s=%s must be the same" % (key, dict1[key], test_object.params[key]))

    def test_node_params(self):
        self.args.tests_str += "only tutorial1\n"
        self.trees.parse_object_trees(self.args.param_str, self.args.tests_str, self.args.vm_strs, self.prefix, self.main_vm)
        test_node = self.trees._testnodes[0]
        dict_generator = test_node.parser.get_dicts()
        dict1 = dict_generator.__next__()
        # Parser of test objects must contain exactly one dictionary
        self.assertRaises(StopIteration, dict_generator.__next__)
        self.assertEqual(len(dict1.keys()), len(test_node.params.keys()), "The parameters of a test node must be the same as its only parser dictionary")
        for key in dict1.keys():
            self.assertEqual(dict1[key], test_node.params[key], "The values of key %s %s=%s must be the same" % (key, dict1[key], test_node.params[key]))

    def test_one_leaf(self):
        self.args.tests_str += "only tutorial1\n"
        self.trees.parse_object_trees(self.args.param_str, self.args.tests_str, self.args.vm_strs, self.prefix, self.main_vm)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^root.internal.stateless.manage_vms.unchanged.vm1", "vms": "^vm1$", "set_state": "^root$"},
            {"shortname": "^1a1a1a1.internal.stateless.configure_install.vm1", "vms": "^vm1$"},
            {"shortname": "^1a1a1a1.original.install.vm1", "vms": "^vm1$"},
            {"shortname": "^1a1a1.internal.permanent.customize_vm.vm1", "vms": "^vm1$"},
            {"shortname": "^1a1.internal.ephemeral.online_deploy.vm1", "vms": "^vm1$"},
            {"shortname": "^1.all.autotest.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]
        DummyTestRunning.fail_switch = [False] * 6
        self.trees.run_tests(self.args.param_str)
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_one_leaf_with_path_setup(self):
        self.args.tests_str += "only tutorial1\n"
        self.trees.parse_object_trees(self.args.param_str, self.args.tests_str, self.args.vm_strs, self.prefix, self.main_vm)
        DummyStateCheck.present_states = ["root", "install"]
        self.trees.scan_object_states(None)
        DummyTestRunning.asserted_tests = [
            # cleanup is expected only if at least one of the states is reusable (here root+install)
            {"shortname": "^1a1a1.internal.permanent.customize_vm.vm1", "vms": "^vm1$"},
            {"shortname": "^1a1.internal.ephemeral.online_deploy.vm1", "vms": "^vm1$"},
            {"shortname": "^1.all.autotest.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]
        DummyTestRunning.fail_switch = [False] * 3
        self.trees.run_tests(self.args.param_str)
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_one_leaf_with_step_setup(self):
        self.args.tests_str += "only tutorial1\n"
        self.trees.parse_object_trees(self.args.param_str, self.args.tests_str, self.args.vm_strs, self.prefix, self.main_vm)
        DummyStateCheck.present_states = ["install", "customize_vm"]
        self.trees.scan_object_states(None)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^root.internal.stateless.manage_vms.unchanged.vm1", "vms": "^vm1$", "set_state": "^root$"},
            {"shortname": "^1a1.internal.ephemeral.online_deploy.vm1", "vms": "^vm1$"},
            {"shortname": "^1.all.autotest.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]
        DummyTestRunning.fail_switch = [False] * 3
        self.trees.run_tests(self.args.param_str)
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_two_objects_without_setup(self):
        self.args.tests_str += "only tutorial3\n"
        self.trees.parse_object_trees(self.args.param_str, self.args.tests_str, self.args.vm_strs, self.prefix, self.main_vm)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^root.internal.stateless.manage_vms.unchanged.vm1", "vms": "^vm1$", "set_state": "^root$"},
            {"shortname": "^1a1a1a1a1.internal.stateless.configure_install.vm1", "vms": "^vm1$"},
            {"shortname": "^1a1a1a1a1.original.install.vm1", "vms": "^vm1$"},
            {"shortname": "^1a1a1a1.internal.permanent.customize_vm.vm1", "vms": "^vm1$"},
            {"shortname": "^1a1a1.internal.permanent.set_provider.vm1", "vms": "^vm1$"},
            {"shortname": "^1a1.internal.ephemeral.online_with_provider.vm1", "vms": "^vm1$"},

            {"shortname": "^root.internal.stateless.manage_vms.unchanged.vm2", "vms": "^vm2$", "set_state": "^root$"},
            {"shortname": "^1a1a1a1.internal.stateless.configure_install.vm2", "vms": "^vm2$"},
            {"shortname": "^1a1a1a1.original.install.vm2", "vms": "^vm2$"},
            {"shortname": "^1a1a1.internal.permanent.customize_vm.vm2", "vms": "^vm2$"},
            {"shortname": "^1a1.internal.ephemeral.online_deploy.vm2", "vms": "^vm2$"},
            {"shortname": "^1.all.tutorial3", "vms": "^vm1 vm2$"},
        ]
        DummyTestRunning.fail_switch = [False] * 12
        self.trees.run_tests(self.args.param_str)
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_two_objects_with_setup(self):
        self.args.tests_str += "only tutorial3\n"
        self.trees.parse_object_trees(self.args.param_str, self.args.tests_str, self.args.vm_strs, self.prefix, self.main_vm)
        DummyStateCheck.present_states = ["root", "install", "customize_vm"]
        self.trees.scan_object_states(None)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^1a1a1.internal.permanent.set_provider.vm1", "vms": "^vm1$"},
            {"shortname": "^1a1.internal.ephemeral.online_with_provider.vm1", "vms": "^vm1$"},
            {"shortname": "^1a1.internal.ephemeral.online_deploy.vm2", "vms": "^vm2$"},
            {"shortname": "^1.all.tutorial3", "vms": "^vm1 vm2$"},
        ]
        DummyTestRunning.fail_switch = [False] * 4
        self.trees.run_tests(self.args.param_str)
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_abort_run(self):
        self.args.tests_str += "only tutorial1\n"
        self.args.param_str += "abort_on_error=yes\n"
        self.trees.parse_object_trees(self.args.param_str, self.args.tests_str, self.args.vm_strs, self.prefix, self.main_vm)
        DummyStateCheck.present_states = ["root", "install"]
        self.trees.scan_object_states(None)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^1a1a1.internal.permanent.customize_vm.vm1", "vms": "^vm1$"},
            {"shortname": "^1a1.internal.ephemeral.online_deploy.vm1", "vms": "^vm1$"},
        ]
        DummyTestRunning.fail_switch = [False] * 2
        DummyTestRunning.fail_switch[1] = True
        with self.assertRaises(exceptions.TestSkipError):
            self.trees.run_tests(self.args.param_str)

    def test_trees_difference_zero(self):
        self.args.tests_str = "only none\n"
        self.args.tests_str += "only set_provider\n"
        self.main_vm = "vm1"
        self.trees.parse_object_trees(self.args.param_str, self.args.tests_str, self.args.vm_strs, self.prefix, self.main_vm, objectless=True)
        self.trees.flag_parent_intersection(self.trees, flag_type="run", flag=False)
        self.trees.run_tests(self.args.param_str)
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_trees_difference(self):
        self.args.tests_str = "only none\n"
        tests_str1 = self.args.tests_str
        tests_str1 += "only set_provider\n"
        tests_str2 = self.args.tests_str
        tests_str2 += "only install\n"
        self.main_vm = "vm2"
        self.trees.parse_object_trees(self.args.param_str, tests_str1, self.args.vm_strs, self.prefix, self.main_vm, objectless=True)
        reuse_graph = CartesianGraph(self.args, {})
        reuse_graph.parse_object_trees(self.args.param_str, tests_str2, self.args.vm_strs, self.prefix, self.main_vm, objectless=True)

        self.trees.flag_parent_intersection(reuse_graph, flag_type="run", flag=False)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^1a1.internal.permanent.customize_vm.vm2", "vms": "^vm2$"},
            {"shortname": "^1.internal.permanent.set_provider.vm2", "vms": "^vm2$"},
        ]
        DummyTestRunning.fail_switch = [False] * 2
        self.trees.run_tests(self.args.param_str)
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)


if __name__ == '__main__':
    unittest.main()
