#!/usr/bin/env python

import unittest
import unittest.mock as mock
import shutil
import re

from avocado.core import exceptions
from avocado.core.suite import TestSuite

import unittest_importer
from avocado_i2n import params_parser as param
from avocado_i2n.cartgraph import TestGraph
from avocado_i2n.loader import CartesianLoader
from avocado_i2n.runner import CartesianRunner


class DummyTestRunning(object):

    fail_switch = []
    asserted_tests = []

    def __init__(self, node_params, test_results):
        self.test_results = test_results
        if len(self.fail_switch) == 0:
            self.fail_switch = [False] * len(self.asserted_tests)
        assert len(self.fail_switch) == len(self.asserted_tests), "len(%s) != len(%s)" % (self.fail_switch, self.asserted_tests)
        # assertions about the test calls
        self.current_test_dict = node_params
        shortname = self.current_test_dict["shortname"]

        assert len(self.asserted_tests) > 0, "Unexpected test %s" % shortname
        self.expected_test_dict, self.expected_test_fail = self.asserted_tests.pop(0), self.fail_switch.pop(0)
        for checked_key in self.expected_test_dict.keys():
            assert checked_key in self.current_test_dict.keys(), "%s missing in %s" % (checked_key, shortname)
            expected, current = self.expected_test_dict[checked_key], self.current_test_dict[checked_key]
            assert re.match(expected, current) is not None, "Expected parameter %s=%s "\
                                                            "but obtained %s=%s for %s" % (checked_key, expected,
                                                                                           checked_key, current,
                                                                                           self.expected_test_dict["shortname"])

    def get_test_result(self):
        shortname = self.current_test_dict["shortname"]
        # allow tests to specify the status they expect
        if self.current_test_dict.get("test_status"):
            self.add_test_result(shortname, self.current_test_dict["test_status"])
            return True
        if self.expected_test_fail and "install" in self.expected_test_dict["shortname"]:
            self.add_test_result(shortname, "FAIL")
            raise exceptions.TestFail("God wanted this test to fail")
        elif self.expected_test_fail and self.current_test_dict.get("abort_on_error", "no") == "yes":
            self.add_test_result(shortname, "SKIP")
            raise exceptions.TestSkipError("God wanted this test to abort")
        else:
            self.add_test_result(shortname, "FAIL" if self.expected_test_fail else "PASS")
            return not self.expected_test_fail

    def add_test_result(self, shortname, status, logdir="."):
        name = mock.MagicMock()
        name.name = shortname
        self.test_results.append({
            "name": name,
            "status": status,
            "logdir": logdir,
        })


class DummyStateCheck(object):

    present_states = []

    def __init__(self, params, env):
        if params.get("check_state") in self.present_states:
            self.result = True
        else:
            self.result = False


def mock_run_test(_self, _job, factory, _queue, _set):
    return DummyTestRunning(factory[1]['vt_params'], _self.job.result.tests).get_test_result()


def mock_check_states(params, env):
    return DummyStateCheck(params, env).result


@mock.patch('avocado_i2n.cartgraph.graph.ss.check_states', mock_check_states)
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
        self.job.result = mock.MagicMock()
        self.job.result.tests = []
        self.runner = CartesianRunner()
        self.runner.job = self.job

    def tearDown(self):
        shutil.rmtree("./graph_parse", ignore_errors=True)
        shutil.rmtree("./graph_traverse", ignore_errors=True)

    def _mock_test_node(self, test_params):
        """Create a mock of a test node to call py:function:`CartesianRunner.run_test_node` directly."""
        test_node = mock.MagicMock()
        # mock node params
        params = test_params
        test_node.params = mock.MagicMock()
        test_node.params.__getitem__.side_effect = params.__getitem__
        test_node.params.__setitem__.side_effect = params.__setitem__
        test_node.params.get.side_effect = params.get
        test_node.params.keys.side_effect = params.keys
        test_node.params.get_numeric.side_effect = lambda _1, _2: int(test_params.get("retry_attempts", 1))
        # mock some needed functions
        test_node.is_objectless.side_effect = lambda: False
        test_node.get_test_factory.side_effect = lambda _: [None, { "vt_params": test_node.params }]
        return test_node

    def test_cartraph_structures(self):
        """Check various usage of all Cartesian graph components."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)

        repr = str(graph)
        self.assertIn("[cartgraph]", repr)
        self.assertIn("[object]", repr)
        self.assertIn("[node]", repr)

        test_object = graph.get_object_by(param_val="vm1")
        self.assertIn(test_object.name, graph.test_objects.keys())
        self.assertEqual(test_object.name, "vm1")
        object_num = len(graph.test_objects)
        graph.new_objects(test_object)
        self.assertEqual(len(graph.test_objects), object_num)

        test_node = graph.get_node_by(param_val="tutorial1")
        self.assertIn("1", test_node.name)
        self.assertIn(test_node.id, graph.test_nodes.keys())
        node_num = len(graph.test_objects)
        graph.new_nodes(test_node)
        self.assertEqual(len(graph.test_objects), node_num)

    def test_object_params(self):
        """Check for correctly parsed test object parameters."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        test_object = graph.get_object_by(param_val="vm1")
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
        """Check for correctly parsed test node parameters."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        test_node = graph.get_node_by(param_val="tutorial1")
        dict_generator = test_node.config.get_parser().get_dicts()
        dict1 = dict_generator.__next__()
        # Parser of test objects must contain exactly one dictionary
        self.assertRaises(StopIteration, dict_generator.__next__)
        self.assertEqual(len(dict1.keys()), len(test_node.params.keys()), "The parameters of a test node must be the same as its only parser dictionary")
        for key in dict1.keys():
            self.assertEqual(dict1[key], test_node.params[key], "The values of key %s %s=%s must be the same" % (key, dict1[key], test_node.params[key]))

    def test_object_node_overwrite(self):
        """Check for correct overwriting of preselected configuration."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        default_object_param = graph.get_node_by(param_val="tutorial1").params["images"]
        default_node_param = graph.get_node_by(param_val="tutorial1").params["kill_vm"]
        custom_object_param = default_object_param + "00"
        custom_node_param = "no" if default_node_param == "yes" else "yes"

        self.config["param_dict"]["images_vm1"] = custom_object_param
        self.config["param_dict"]["kill_vm"] = custom_node_param
        self.config["param_dict"]["new_key"] = "123"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)

        test_object = graph.get_object_by(param_val="vm1")
        test_object_params = test_object.params.object_params(test_object.name)
        self.assertNotEqual(test_object_params["images"], default_object_param,
                            "The default %s of %s wasn't overwritten" % (default_object_param, test_object.name))
        self.assertEqual(test_object_params["images"], custom_object_param,
                         "The new %s of %s must be %s" % (default_object_param, test_object.name, custom_object_param))
        self.assertEqual(test_object_params["new_key"], "123",
                         "A new parameter=%s of %s must be 123" % (test_object_params["new_key"], test_object.name))

        test_node = graph.get_node_by(param_val="tutorial1")
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
        """Check the scope of application of overwriting preselected configuration."""
        self.config["tests_str"] += "only tutorial3\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        default_object_param = graph.get_node_by(param_val="tutorial3").params["images"]
        custom_object_param1 = default_object_param + "01"
        custom_object_param2 = default_object_param + "02"

        self.config["param_dict"]["images"] = custom_object_param1
        self.config["param_dict"]["images_vm1"] = custom_object_param2
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)

        # TODO: the current suffix operators make it impossible to fully test this
        test_object1 = graph.get_object_by(param_val="vm1")
        test_object_params1 = test_object1.params.object_params(test_object1.name)
        #self.assertNotEqual(test_object_params1["images"], default_object_param,
        #                    "The default %s of %s wasn't overwritten" % (default_object_param, test_object1.name))
        self.assertNotEqual(test_object_params1["images"], custom_object_param1,
                            "The new %s of %s is of general scope" % (default_object_param, test_object1.name))
        #self.assertEqual(test_object_params1["images"], custom_object_param2,
        #                 "The new %s of %s must be %s" % (default_object_param, test_object1.name, custom_object_param2))

        test_object2 = graph.get_object_by(param_val="vm2")
        test_object_params2 = test_object2.params.object_params(test_object2.name)
        self.assertEqual(test_object_params2["images"], default_object_param,
                         "The default %s of %s must be preserved" % (default_object_param, test_object2.name))

        # TODO: the current suffix operators make it impossible to fully test this
        test_node = graph.get_node_by(param_val="tutorial3")
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
        """Check incompatibility of parsed tests and preselected available objects."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["vm_strs"] = {"vm2": "only Win10\n", "vm3": "only Ubuntu\n"}
        with self.assertRaises(param.EmptyCartesianProduct):
            graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                   self.config["tests_str"], self.config["vm_strs"],
                                                   prefix=self.prefix)

    def test_one_leaf(self):
        """Check one test running without any reusable setup."""
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
        """Check one test running with a reusable off setup."""
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
        """Check one test running without a reusable on setup."""
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
        """Check one test running with a reusable setup path."""
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
        """Check one test running with a single reusable setup test node."""
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

    def test_one_leaf_validations(self):
        """Check graph retrieval methods and component validation."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        test_object = graph.get_object_by(param_val="vm1")
        test_node = graph.get_node_by(param_val="tutorial1")
        self.assertIn(test_object, test_node.objects)
        test_node.validate()
        test_node.objects.remove(test_object)
        with self.assertRaises(ValueError):
            test_node.validate()
        test_node.objects.append(test_object)
        test_node.validate()
        test_node.params["vms"] = ""
        with self.assertRaises(ValueError):
            test_node.validate()

        self.config["param_dict"]["get_state"] = "tutorial1"
        with self.assertRaises(ValueError):
            graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                   self.config["tests_str"], self.config["vm_strs"],
                                                   prefix=self.prefix)

    def test_one_leaf_dry_run(self):
        """Check dry run of a single leaf test where no test should end up really running."""
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
        """Check a two-object test run without a reusable setup."""
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
        """Check a two-object test run with reusable setup."""
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

    def test_permanent_object_and_switch_and_cloning(self):
        """Check a test run including complex setup."""
        self.config["tests_str"] = "only leaves\n"
        self.config["tests_str"] += "only tutorial_get\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["root"]
        graph.scan_object_states(None)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.0scan.vm1", "vms": "^vm1 vm2 vm3$"},
            # automated setup of vm1
            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.permanent.linux_virtuser.vm1", "vms": "^vm1$"},
            # automated setup of vm2
            {"shortname": "^internal.stateless.0preinstall.vm2", "vms": "^vm2$"},
            {"shortname": "^original.unattended_install.cdrom.in_cdrom_ks.default_install.aio_threads.vm2", "vms": "^vm2$"},
            {"shortname": "^internal.permanent.customize.vm2", "vms": "^vm2$"},
            {"shortname": "^internal.permanent.windows_virtuser.vm2", "vms": "^vm2$"},
            # first (noop) parent GUI setup dependency through vm2
            {"shortname": "^tutorial_gui.client_noop.vm1.virtio_blk.smp2.virtio_net.CentOS.7.0.x86_64.vm2.smp2.Win10.x86_64", "vms": "^vm1 vm2$", "set_state_vm2": "guisetup.noop"},
            # on switch dependency dependency through vm1
            {"shortname": "^internal.permanent.connect.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.manage.start.vm1", "vms": "^vm1$", "get_state": "^connect$", "set_state": "^connect$", "get_type": "^off$", "set_type": "^on$"},
            # first (noop) explicit actual test
            {"shortname": "^leaves.tutorial_get.explicit_noop.vm1", "vms": "^vm1 vm2 vm3$", "get_state_vm2": "guisetup.noop"},
            # first (noop) duplicated actual test
            {"shortname": "^leaves.tutorial_get.implicit_both.vm1", "vms": "^vm1 vm2 vm3$", "get_state_vm2": "guisetup.noop"},
            # second (clicked) parent GUI setup dependency through vm2
            {"shortname": "^tutorial_gui.client_clicked.vm1", "vms": "^vm1 vm2$", "set_state_vm2": "guisetup.clicked"},
            {"shortname": "^internal.stateless.manage.start.vm1", "vms": "^vm1$", "get_state": "^connect$", "set_state": "^connect$", "get_type": "^off$", "set_type": "^on$"},
            # second (clicked) explicit actual test
            {"shortname": "^leaves.tutorial_get.explicit_clicked.vm1", "vms": "^vm1 vm2 vm3$", "get_state_vm2": "guisetup.clicked"},
            # second (clicked) duplicated actual test
            {"shortname": "^leaves.tutorial_get.implicit_both.vm1", "vms": "^vm1 vm2 vm3$", "get_state_vm2": "guisetup.clicked"},
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deep_cloning(self):
        """Check for correct deep cloning."""
        self.config["tests_str"] = "only leaves\n"
        self.config["tests_str"] += "only tutorial_finale\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["root", "install", "customize"]
        graph.scan_object_states(None)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.0scan.vm1", "vms": "^vm1 vm2 vm3$"},
            # automated setup of vm1
            {"shortname": "^internal.permanent.linux_virtuser.vm1", "vms": "^vm1$"},
            # automated setup of vm2
            {"shortname": "^internal.permanent.windows_virtuser.vm2", "vms": "^vm2$"},
            # first (noop) parent GUI setup dependency through vm2
            {"shortname": "^tutorial_gui.client_noop", "vms": "^vm1 vm2$", "set_state_vm2": "guisetup.noop"},
            # on switch dependency dependency through vm1
            {"shortname": "^internal.permanent.connect.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.manage.start.vm1", "vms": "^vm1$", "get_state": "^connect$", "set_state": "^connect$", "get_type": "^off$", "set_type": "^on$"},
            # first (noop) duplicated actual test
            {"shortname": "^tutorial_get.implicit_both.+guisetup.noop", "vms": "^vm1 vm2 vm3$", "get_state_vm2": "guisetup.noop", "set_state_vm2": "getsetup.guisetup.noop"},
            {"shortname": "^leaves.tutorial_finale.+getsetup.guisetup.noop", "vms": "^vm1 vm2 vm3$", "get_state_vm2": "getsetup.guisetup.noop"},
            # second (clicked) parent GUI setup dependency through vm2
            {"shortname": "^tutorial_gui.client_clicked", "vms": "^vm1 vm2$", "set_state_vm2": "guisetup.clicked"},
            {"shortname": "^internal.stateless.manage.start.vm1", "vms": "^vm1$", "get_state": "^connect$", "set_state": "^connect$", "get_type": "^off$", "set_type": "^on$"},
            # second (clicked) duplicated actual test
            {"shortname": "^tutorial_get.implicit_both.+guisetup.clicked", "vms": "^vm1 vm2 vm3$", "get_state_vm2": "guisetup.clicked", "set_state_vm2": "getsetup.guisetup.clicked"},
            {"shortname": "^leaves.tutorial_finale.+getsetup.guisetup.clicked", "vms": "^vm1 vm2 vm3$", "get_state_vm2": "getsetup.guisetup.clicked"},
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_complete_verbose_graph_dry_run(self):
        """Check a complete dry run traversal of a verbose (visualized) graph."""
        self.config["tests_str"] = "only all\n"
        self.config["param_dict"]["dry_run"] = "yes"
        # this type of verbosity requires graphviz dependency
        import logging
        try:
            logging.getLogger('graph').level = 0
            graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                   self.config["tests_str"], self.config["vm_strs"],
                                                   prefix=self.prefix, verbose=True)
        finally:
            logging.getLogger('graph').level = 50
        DummyStateCheck.present_states = []
        DummyTestRunning.asserted_tests = [
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])

    def test_abort_scan(self):
        """Check aborted test run due to failed object state loading or other scanning problems."""
        self.config["tests_str"] = "only leaves\n"
        self.config["tests_str"] += "only tutorial_get\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = []
        graph.scan_object_states(None)
        graph.load_setup_list.side_effect = FileNotFoundError("scan failed")
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.0scan.vm1", "vms": "^vm1 vm2 vm3$"},
        ]
        # TODO: test same on failed status by unify the fail switch and status mocking first
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, self.config["param_dict"])
        graph.load_setup_list.side_effect = None
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_abort_run(self):
        """Check for aborted traversal through explicit configuration."""
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
            {"shortname": "^internal.ephemeral.on_customize.vm1", "vms": "^vm1$", "set_state_vm1_on_error": "^$"},
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        DummyTestRunning.fail_switch[-1] = True
        with self.assertRaises(exceptions.TestSkipError):
            self.runner.run_traversal(graph, self.config["param_dict"])

    def test_abort_objectless_node(self):
        """Check for aborted traversal on objectless node detection."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        test_node = graph.get_node_by(param_val="tutorial1")
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
        """Check for proper node difference of two Cartesian graphs."""
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
        """Check for correct node difference of two Cartesian graphs."""
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

    def test_loader_runner_entries(self):
        """Check that the default loader and runner entries work as expected."""
        self.config["tests_str"] += "only tutorial1\n"
        references = "only=tutorial1 key1=val1"
        self.config["params"] = references.split()
        self.config["prefix"] = ""
        self.config["subcommand"] = "run"
        self.loader.config = self.config

        test_suite = TestSuite('suite',
                               tests=self.loader.discover(references),
                               config=self.config)

        DummyStateCheck.present_states = []
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

        self.runner.job.config = self.config
        self.runner.run_suite(self.runner.job, test_suite)

    def test_run_n_times(self):
        """Check that the test is retried `retry_attempts` times if `retry_stop` is not specified."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"]["retry_attempts"] = "4"
        graph = self.loader.parse_object_trees(
            self.config["param_dict"], self.config["tests_str"],
            self.config["vm_strs"], prefix="")
        DummyTestRunning.asserted_tests = [
            {"shortname": r"^internal.stateless.0scan.vm1", "vms": r"^vm1$"},
            {"shortname": r"^internal.stateless.0root.vm1", "vms": r"^vm1$"},
            {"shortname": r"^internal.stateless.0preinstall.vm1", "vms": r"^vm1$"},
            {"shortname": r"^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": r"^vm1$"},
            {"shortname": r"^internal.permanent.customize.vm1", "vms": r"^vm1$"},
            {"shortname": r"^internal.permanent.customize.vm1.*?\.r1", "vms": r"^vm1$"},
            {"shortname": r"^internal.permanent.customize.vm1.*?\.r2", "vms": r"^vm1$"},
            {"shortname": r"^internal.permanent.customize.vm1.*?\.r3", "vms": r"^vm1$"},
            {"shortname": r"^internal.permanent.customize.vm1.*?\.r4", "vms": r"^vm1$"},
            {"shortname": r"^internal.ephemeral.on_customize.vm1", "vms": r"^vm1$"},
            {"shortname": r"^normal.nongui.quicktest.tutorial1.vm1", "vms": r"^vm1$"},
            {"shortname": r"^normal.nongui.quicktest.tutorial1.vm1.*?\.r1", "vms": r"^vm1$"},
            {"shortname": r"^normal.nongui.quicktest.tutorial1.vm1.*?\.r2", "vms": r"^vm1$"},
            {"shortname": r"^normal.nongui.quicktest.tutorial1.vm1.*?\.r3", "vms": r"^vm1$"},
            {"shortname": r"^normal.nongui.quicktest.tutorial1.vm1.*?\.r4", "vms": r"^vm1$"},
        ]
        DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
        self.runner.run_traversal(graph, {})

    def test_last_exit_code_is_preserved(self):
        """Check that the return value of the last run is preserved."""
        params = {
            "retry_stop": "none",
            "retry_attempts": "5",
            "shortname": "some1-random_test"
        }
        test_node = self._mock_test_node(params)
        # check that all tests have been run at least this first time
        asserted_tests = [
            {"shortname": r"^some1-random_test$"},
            {"shortname": r"^some1-random_test\.r1$"},
            {"shortname": r"^some1-random_test\.r2$"},
            {"shortname": r"^some1-random_test\.r3$"},
            {"shortname": r"^some1-random_test\.r4$"},
            {"shortname": r"^some1-random_test\.r5$"}
        ]
        fail_switch = [False] * len(asserted_tests)
        DummyTestRunning.asserted_tests = list(asserted_tests)
        DummyTestRunning.fail_switch = list(fail_switch)
        status = self.runner.run_test_node(test_node, can_retry=True)
        # all runs succeed - status must be True
        self.assertTrue(status)

        # last run fails - status must be False
        test_node = self._mock_test_node(params)
        DummyTestRunning.asserted_tests = list(asserted_tests)
        DummyTestRunning.fail_switch = list(fail_switch)
        DummyTestRunning.fail_switch[-1] = True
        status = self.runner.run_test_node(test_node, can_retry=True)
        self.assertFalse(status, "runner not preserving last status")

        # fourth run fails - status must be True
        test_node = self._mock_test_node(params)
        DummyTestRunning.asserted_tests = list(asserted_tests)
        DummyTestRunning.fail_switch = list(fail_switch)
        DummyTestRunning.fail_switch[3] = True
        status = self.runner.run_test_node(test_node, can_retry=True)
        self.assertTrue(status, "runner not preserving last status")

    def test_retry_on_correct_status(self):
        """Check that certain status are ignored when retrying a test."""
        params = {
            "retry_stop": "none",
            "retry_attempts": "3",
            "shortname": "some1-random_test"
        }

        # test should not be re-run on these status
        for s in ["SKIP", "INTERRUPTED", "CANCEL"]:
            DummyTestRunning.asserted_tests = [{"shortname": r"^some1-random_test$"}]
            DummyTestRunning.fail_switch = [False]
            test_node = self._mock_test_node({ **params, "test_status": s })
            self.runner.run_test_node(test_node, can_retry=True)
            # assert that tests were not repeated
            self.assertEqual(len(self.runner.job.result.tests), 1)
            # also assert the correct results were registered
            self.assertEqual([x["status"] for x in self.runner.job.result.tests], [s])
            self.runner.job.result.tests.clear()

        # test should be re-run on these status
        for s in ["PASS", "WARN", "FAIL", "ERROR"]:
            DummyTestRunning.asserted_tests = [
                {"shortname": r"^some1-random_test$"},
                {"shortname": r"^some1-random_test\.r1$"},
                {"shortname": r"^some1-random_test\.r2$"},
                {"shortname": r"^some1-random_test\.r3$"}
            ]
            DummyTestRunning.fail_switch = [False] * len(DummyTestRunning.asserted_tests)
            test_node = self._mock_test_node({ **params, "test_status": s })
            self.runner.run_test_node(test_node, can_retry=True)
            # assert that tests were not repeated
            self.assertEqual(len(self.runner.job.result.tests), 4)
            # also assert the correct results were registered
            self.assertEqual([x["status"] for x in self.runner.job.result.tests], [s] * 4)
            self.runner.job.result.tests.clear()

    def test_stop_on_status(self):
        """Check that the `retry_stop` parameter is correctly handled by the runner."""
        params = {
            "retry_stop": "none",
            "retry_attempts": "3",
            "shortname": "some1-random_test"
        }
        # expect success and get success -> should run only once
        for s in ["PASS", "WARN"]:
            # a single test as it should not be repeated
            DummyTestRunning.asserted_tests = [{"shortname": r"^some1-random_test$"}]
            DummyTestRunning.fail_switch = [False]
            new_params = { **params, "test_status": s, "retry_stop": "success" }
            test_node = self._mock_test_node(new_params)
            self.runner.run_test_node(test_node, can_retry=True)
            # also assert the correct results were registered
            self.assertEqual([x["status"] for x in self.runner.job.result.tests], [s])
            self.runner.job.result.tests.clear()

        # expect failure and get failure -> should run only once
        for s in ["FAIL", "ERROR"]:
            # a single test as it should not be repeated
            DummyTestRunning.asserted_tests = [{"shortname": r"^some1-random_test$"}]
            DummyTestRunning.fail_switch = [False]
            new_params = { **params, "test_status": s, "retry_stop": "error" }
            test_node = self._mock_test_node(new_params)
            self.runner.run_test_node(test_node, can_retry=True)
            # also assert the correct results were registered
            self.assertEqual([x["status"] for x in self.runner.job.result.tests], [s])
            self.runner.job.result.tests.clear()

    def test_invalid_retry_stop(self):
        """Check if an exception is thrown when retry_stop has an invalid value."""
        params = {
            "retry_stop": "invalid",
            "retry_attempts": "5",
            "shortname": "some1-random_test"
        }
        test_node = self._mock_test_node(params)
        self.assertRaises(AssertionError, self.runner.run_test_node, test_node, can_retry=True)

    def test_invalid_retry_attempts(self):
        """Check if an exception is thrown when retry_attempts has an invalid value."""
        params = {
            "retry_stop": "none",
            "shortname": "some1-random_test"
        }
        # negative values
        with mock.patch.dict(params, { "retry_attempts": "-32" }):
            test_node = self._mock_test_node(params)
            self.assertRaises(AssertionError, self.runner.run_test_node, test_node, can_retry=True)

        # floats
        with mock.patch.dict(params, { "retry_attempts": "3.5" }):
            test_node = self._mock_test_node(params)
            self.assertRaises(ValueError, self.runner.run_test_node, test_node, can_retry=True)

        # non-integers
        with mock.patch.dict(params, { "retry_attempts": "hey" }):
            test_node = self._mock_test_node(params)
            self.assertRaises(ValueError, self.runner.run_test_node, test_node, can_retry=True)

if __name__ == '__main__':
    unittest.main()
