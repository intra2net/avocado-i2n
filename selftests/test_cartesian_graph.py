#!/usr/bin/env python

import unittest
import unittest.mock as mock
import shutil
import re

from avocado.core import exceptions

import unittest_importer
from avocado_i2n import params_parser as param
from avocado_i2n.cartgraph import TestGraph
from avocado_i2n.loader import CartesianLoader
from avocado_i2n.runner import CartesianRunner


class DummyTestRunning(object):

    fail_switch = []
    asserted_tests = []

    def __init__(self, node_params):
        assert len(self.fail_switch) == len(self.asserted_tests), "len(%s) != len(%s)" % (self.fail_switch, self.asserted_tests)
        # assertions about the test calls
        self.current_test_dict = node_params
        assert len(self.asserted_tests) > 0, "Unexpected test %s" % self.current_test_dict["shortname"]
        self.expected_test_dict, self.expected_test_fail = self.asserted_tests.pop(0), self.fail_switch.pop(0)
        for checked_key in self.expected_test_dict.keys():
            assert checked_key in self.current_test_dict.keys(), "%s missing in %s" % (checked_key, self.current_test_dict["shortname"])
            expected, current = self.expected_test_dict[checked_key], self.current_test_dict[checked_key]
            assert re.match(expected, current) is not None, "Expected parameter %s=%s "\
                                                            "but obtained %s=%s for %s" % (checked_key, expected,
                                                                                           checked_key, current,
                                                                                           self.expected_test_dict["shortname"])

    def result(self):
        if self.expected_test_fail and "install" in self.expected_test_dict["shortname"]:
            raise exceptions.TestFail("God wanted this test to fail")
        elif self.expected_test_fail and self.current_test_dict.get("abort_on_error", "no") == "yes":
            raise exceptions.TestSkipError("God wanted this test to abort")
        else:
            return not self.expected_test_fail


class DummyStateCheck(object):

    present_states = []

    def __init__(self, params, env):
        if params.get("check_state") in self.present_states:
            self.result = True
        else:
            self.result = False


def mock_run_test(_self, _job, _result, factory, _queue, _set):
    return DummyTestRunning(factory[1]['vt_params']).result()


def mock_check_state(params, env):
    return DummyStateCheck(params, env).result


@mock.patch('avocado_i2n.cartgraph.graph.state_setup.check_state', mock_check_state)
@mock.patch.object(CartesianRunner, 'run_test', mock_run_test)
@mock.patch.object(TestGraph, 'load_setup_list', mock.MagicMock())
class CartesianGraphTest(unittest.TestCase):

    def setUp(self):
        DummyTestRunning.asserted_tests = []
        DummyTestRunning.fail_switch = []
        DummyStateCheck.present_states = []

        self.config = {}
        self.config["param_dict"] = {}
        self.config["tests_str"] = "only normal\n"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n", "vm3": "only Ubuntu\n"}

        self.prefix = ""
        self.main_vm = ""

        self.loader = CartesianLoader(config=self.config, extra_params={})
        self.job = mock.MagicMock()
        self.job.logdir = "."
        self.result = mock.MagicMock()
        self.runner = CartesianRunner()
        self.runner.job = self.job
        self.runner.result = self.result

    def tearDown(self):
        shutil.rmtree("./graph_parse", ignore_errors=True)
        shutil.rmtree("./graph_traverse", ignore_errors=True)

    def test_object_params(self):
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        test_object = graph.get_objects_by(param_val="vm1")[0]
        dict_generator = test_object.config.get_parser().get_dicts()
        dict1 = dict_generator.__next__()
        # Parser of test objects must contain exactly one dictionary
        self.assertRaises(StopIteration, dict_generator.__next__)
        self.assertEqual(len(dict1.keys()), len(test_object.params.keys()),
                         "The parameters of a test node must be the same as its only parser dictionary")
        for key in dict1.keys():
            self.assertEqual(dict1[key], test_object.params[key],
                             "The values of key %s %s=%s must be the same" % (key, dict1[key], test_object.params[key]))

    def test_node_params(self):
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        test_node = graph.get_nodes_by(param_val="tutorial1")[0]
        dict_generator = test_node.config.get_parser().get_dicts()
        dict1 = dict_generator.__next__()
        # Parser of test objects must contain exactly one dictionary
        self.assertRaises(StopIteration, dict_generator.__next__)
        self.assertEqual(len(dict1.keys()), len(test_node.params.keys()), "The parameters of a test node must be the same as its only parser dictionary")
        for key in dict1.keys():
            self.assertEqual(dict1[key], test_node.params[key], "The values of key %s %s=%s must be the same" % (key, dict1[key], test_node.params[key]))

    def test_object_node_overwrite(self):
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        default_object_param = graph.get_nodes_by(param_val="tutorial1")[0].params["images"]
        default_node_param = graph.get_nodes_by(param_val="tutorial1")[0].params["kill_vm"]
        custom_object_param = default_object_param + "00"
        custom_node_param = "no" if default_node_param == "yes" else "yes"

        self.config["param_dict"]["images_vm1"] = custom_object_param
        self.config["param_dict"]["kill_vm"] = custom_node_param
        self.config["param_dict"]["new_key"] = "123"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)

        test_object = graph.get_objects_by(param_val="vm1")[0]
        test_object_params = test_object.params.object_params(test_object.name)
        self.assertNotEqual(test_object_params["images"], default_object_param,
                            "The default %s of %s wasn't overwritten" % (default_object_param, test_object.name))
        self.assertEqual(test_object_params["images"], custom_object_param,
                         "The new %s of %s must be %s" % (default_object_param, test_object.name, custom_object_param))
        self.assertEqual(test_object_params["new_key"], "123",
                         "A new parameter=%s of %s must be 123" % (test_object_params["new_key"], test_object.name))

        test_node = graph.get_nodes_by(param_val="tutorial1")[0]
        self.assertNotEqual(test_node.params["kill_vm"], default_node_param,
                            "The default %s of %s wasn't overwritten" % (default_node_param, test_node.name))
        self.assertEqual(test_node.params["kill_vm"], custom_node_param,
                         "The new %s of %s must be %s" % (default_node_param, test_node.name, custom_node_param))
        self.assertNotEqual(test_node.params["images_vm1"], default_object_param,
                            "The default %s of %s wasn't overwritten" % (default_object_param, test_node.name))
        self.assertEqual(test_node.params["images_vm1"], custom_object_param,
                         "The new %s of %s must be %s" % (default_object_param, test_node.name, custom_object_param))
        self.assertEqual(test_node.params["new_key"], "123",
                         "A new parameter=%s of %s must be 123" % (test_node.params["new_key"], test_object.name))

    def test_object_node_overwrite_scope(self):
        self.config["tests_str"] += "only tutorial3\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        default_object_param = graph.get_nodes_by(param_val="tutorial3")[0].params["images"]
        custom_object_param1 = default_object_param + "01"
        custom_object_param2 = default_object_param + "02"

        self.config["param_dict"]["images"] = custom_object_param1
        self.config["param_dict"]["images_vm1"] = custom_object_param2
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)

        # TODO: the current suffix operators make it impossible to fully test this
        test_object1 = graph.get_objects_by(param_val="vm1")[0]
        test_object_params1 = test_object1.params.object_params(test_object1.name)
        #self.assertNotEqual(test_object_params1["images"], default_object_param,
        #                    "The default %s of %s wasn't overwritten" % (default_object_param, test_object1.name))
        self.assertNotEqual(test_object_params1["images"], custom_object_param1,
                            "The new %s of %s is of general scope" % (default_object_param, test_object1.name))
        #self.assertEqual(test_object_params1["images"], custom_object_param2,
        #                 "The new %s of %s must be %s" % (default_object_param, test_object1.name, custom_object_param2))

        test_object2 = graph.get_objects_by(param_val="vm2")[0]
        test_object_params2 = test_object2.params.object_params(test_object2.name)
        self.assertEqual(test_object_params2["images"], default_object_param,
                         "The default %s of %s must be preserved" % (default_object_param, test_object2.name))

        # TODO: the current suffix operators make it impossible to fully test this
        test_node = graph.get_nodes_by(param_val="tutorial3")[0]
        self.assertNotEqual(test_node.params["images"], default_object_param,
                         "The object-general default %s of %s must be overwritten" % (default_object_param, test_node.name))
        self.assertEqual(test_node.params["images"], custom_object_param1,
                         "The object-general new %s of %s must be %s" % (default_object_param, test_node.name, custom_object_param1))
        #self.assertNotEqual(test_node.params["images_vm1"], default_object_param,
        #                    "The default %s of %s wasn't overwritten" % (default_object_param, test_node.name))
        #self.assertEqual(test_node.params["images_vm1"], custom_object_param2,
        #                 "The new %s of %s must be %s" % (default_object_param, test_node.name, custom_object_param2))
        self.assertEqual(test_node.params["images_vm2"], default_object_param,
                         "The second %s of %s should be preserved" % (default_object_param, test_node.name))

    def test_object_node_incompatible(self):
        self.config["tests_str"] += "only tutorial1\n"
        self.config["vm_strs"] = {"vm2": "only Win10\n", "vm3": "only Ubuntu\n"}
        with self.assertRaises(param.EmptyCartesianProduct):
            graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                   self.config["tests_str"], self.config["vm_strs"],
                                                   prefix=self.prefix, verbose=True)

    def test_one_leaf(self):
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.0scan.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.0root.vm1", "vms": "^vm1$", "set_state": "^root$", "set_type": "^off$"},
            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$", "set_state": "^install$", "set_type": "^off$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$", "get_state": "^install$", "set_state": "^customize$", "get_type": "^off$", "set_type": "^off$"},
            {"shortname": "^internal.ephemeral.on_customize.vm1", "vms": "^vm1$", "get_state": "^customize$", "set_state": "^on_customize$", "get_type": "^off$", "set_type": "^on$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "get_state": "^on_customize$"},
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_one_leaf_with_off_setup(self):
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"].update({"get_type": "off", "set_type": "off"})
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.0scan.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.0root.vm1", "vms": "^vm1$", "set_state": "^root$", "set_type": "^off$"},
            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$", "set_state": "^install$", "set_type": "^off$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$", "get_state": "^install$", "set_state": "^customize$", "get_type": "^off$", "set_type": "^off$"},
            {"shortname": "^internal.ephemeral.on_customize.vm1", "vms": "^vm1$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_one_leaf_with_on_setup(self):
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"].update({"get_type": "on", "set_type": "on"})
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.0scan.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.0root.vm1", "vms": "^vm1$", "set_state": "^root$", "set_type": "^on$"},
            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.manage.start.vm1", "vms": "^vm1$", "set_state": "^install$", "set_type": "^on$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$", "get_state": "^install$", "set_state": "^customize$", "get_type": "^on$", "set_type": "^on$"},
            {"shortname": "^internal.ephemeral.on_customize.vm1", "vms": "^vm1$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_one_leaf_with_path_setup(self):
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["root", "install"]
        graph.scan_object_states(None)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.0scan.vm1", "vms": "^vm1$"},
            # cleanup is expected only if at least one of the states is reusable (here root+install)
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.ephemeral.on_customize.vm1", "vms": "^vm1$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_one_leaf_with_step_setup(self):
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["install", "customize"]
        graph.scan_object_states(None)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.0scan.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.0root.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.ephemeral.on_customize.vm1", "vms": "^vm1$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_one_leaf_dry_run(self):
        self.config["param_dict"]["dry_run"] = "yes"
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        graph.scan_object_states(None)
        DummyTestRunning.asserted_tests = [
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_two_objects_without_setup(self):
        self.config["tests_str"] += "only tutorial3\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = []
        graph.scan_object_states(None)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.0scan.vm1", "vms": "^vm1 vm2$"},

            {"shortname": "^internal.stateless.0root.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.permanent.connect.vm1", "vms": "^vm1$"},

            {"shortname": "^internal.stateless.0root.vm2", "vms": "^vm2$"},
            {"shortname": "^internal.stateless.0preinstall.vm2", "vms": "^vm2$"},
            {"shortname": "^original.unattended_install.cdrom.in_cdrom_ks.default_install.aio_threads.vm2", "vms": "^vm2$"},
            {"shortname": "^internal.permanent.customize.vm2", "vms": "^vm2$"},
            {"shortname": "^normal.nongui.tutorial3", "vms": "^vm1 vm2$"},
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_two_objects_with_setup(self):
        self.config["tests_str"] += "only tutorial3\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["root", "install", "customize"]
        graph.scan_object_states(None)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.0scan.vm1", "vms": "^vm1 vm2$"},
            {"shortname": "^internal.permanent.connect.vm1", "vms": "^vm1$"},
            {"shortname": "^normal.nongui.tutorial3", "vms": "^vm1 vm2$"},
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_with_permanent_object_and_switch(self):
        self.config["tests_str"] = "only leaves\n"
        self.config["tests_str"] += "only tutorial_get\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["root"]
        graph.scan_object_states(None)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.0scan.vm1", "vms": "^vm1 vm3$"},

            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.permanent.connect.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.manage.start.vm1", "vms": "^vm1$", "get_state": "^connect", "set_state": "^connect$", "get_type": "^off$", "set_type": "^on$"},

            {"shortname": "^leaves.tutorial_get", "vms": "^vm1 vm3$"},
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_without_permanent_object(self):
        self.config["tests_str"] = "only leaves\n"
        self.config["tests_str"] += "only tutorial_get\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = []
        with self.assertRaises(AssertionError):
            graph.scan_object_states(None)
        graph.load_setup_list.side_effect = FileNotFoundError("scan failed")
        DummyTestRunning.asserted_tests = [
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_abort_run(self):
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"].update({"abort_on_error": "yes"})
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["root", "install"]
        graph.scan_object_states(None)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.0scan.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.ephemeral.on_customize.vm1", "vms": "^vm1$"},
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        DummyTestRunning.fail_switch[-1] = True
        with self.assertRaises(exceptions.TestSkipError):
            self.runner.run_traversal(graph, self.config["param_dict"])

    def test_abort_objectless_node(self):
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        test_node = graph.get_nodes_by(param_val="tutorial1")[0]
        # assume we are parsing invalid configuration
        test_node.params["vms"] = ""
        DummyStateCheck.present_states = ["root", "install"]
        graph.scan_object_states(None)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.0scan.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.ephemeral.on_customize.vm1", "vms": "^vm1$"},
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        with self.assertRaises(AssertionError):
            self.runner.run_traversal(graph, self.config["param_dict"])

    def test_trees_difference_zero(self):
        self.config["tests_str"] = "only nonleaves\n"
        self.config["tests_str"] += "only connect\n"
        self.main_vm = "vm1"
        self.config["param_dict"]["main_vm"] = "vm1"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        graph.flag_parent_intersection(graph, flag_type="run", flag=False)
        DummyTestRunning.asserted_tests = [
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_trees_difference(self):
        self.config["tests_str"] = "only nonleaves\n"
        tests_str1 = self.config["tests_str"]
        tests_str1 += "only connect\n"
        tests_str2 = self.config["tests_str"]
        tests_str2 += "only 0preinstall\n"
        self.main_vm = "vm2"
        self.config["param_dict"]["main_vm"] = "vm2"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               tests_str1, self.config["vm_strs"],
                                               prefix=self.prefix)
        reuse_graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                     tests_str2, self.config["vm_strs"],
                                                     prefix=self.prefix)

        graph.flag_parent_intersection(reuse_graph, flag_type="run", flag=False)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.permanent.customize.vm2", "vms": "^vm2$"},
            {"shortname": "^nonleaves.internal.permanent.connect.vm2", "vms": "^vm2$"},
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)


if __name__ == '__main__':
    unittest.main()
