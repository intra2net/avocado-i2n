#!/usr/bin/env python

import unittest
import unittest.mock as mock
import shutil
import asyncio
import re

from avocado import Test
from avocado.core import exceptions
from avocado.core.suite import TestSuite, resolutions_to_runnables

import unittest_importer
from avocado_i2n import params_parser as param
from avocado_i2n.loader import CartesianLoader
from avocado_i2n.runner import CartesianRunner


class DummyTestRunning(object):

    asserted_tests = []

    def __init__(self, node_params, test_results):
        self.test_results = test_results
        # assertions about the test calls
        self.current_test_dict = node_params
        shortname = self.current_test_dict["shortname"]

        assert len(self.asserted_tests) > 0, "Unexpected test %s" % shortname
        self.expected_test_dict = self.asserted_tests.pop(0)
        for checked_key in self.expected_test_dict.keys():
            if checked_key.startswith("_"):
                continue
            assert checked_key in self.current_test_dict.keys(), "%s missing in %s (params: %s)" % (checked_key, shortname, self.current_test_dict)
            expected, current = self.expected_test_dict[checked_key], self.current_test_dict[checked_key]
            assert re.match(expected, current) is not None, "Expected parameter %s=%s "\
                                                            "but obtained %s=%s for %s (params: %s)" % (checked_key, expected,
                                                                                                        checked_key, current,
                                                                                                        self.expected_test_dict["shortname"],
                                                                                                        self.current_test_dict)

    def get_test_result(self):
        uid = self.current_test_dict["_uid"]
        name = self.current_test_dict["name"]
        # allow tests to specify the status they expect
        status = self.expected_test_dict.get("_status", "PASS")
        self.add_test_result(uid, name, status)
        if status in ["ERROR", "FAIL"] and self.current_test_dict.get("abort_on_error", "no") == "yes":
            raise exceptions.TestSkipError("God wanted this test to abort")
        return status not in ["ERROR", "FAIL"]

    def add_test_result(self, uid, name, status, logdir="."):
        mocktestid = mock.MagicMock(uid=uid, name=name)
        # have to set actual name attribute
        mocktestid.name = name
        self.test_results.append({
            "name": mocktestid,
            "status": status,
            "logdir": logdir,
        })


class DummyStateCheck(object):

    present_states = []

    def __init__(self, params, env):
        check_state = None
        for vm in params.objects("vms"):
            vm_params = params.object_params(vm)
            for image in params.objects("images"):
                image_params = vm_params.object_params(image)
                check_state = image_params.get("check_state_images")
                if check_state:
                    break
                check_state = image_params.get("check_state_vms")
                if check_state:
                    break
        if check_state in self.present_states:
            self.result = True
        else:
            self.result = False


async def mock_run_test(_self, _job, node):
    # define ID-s and other useful parameter filtering
    node.get_runnable()
    node.params["_uid"] = node.long_prefix
    await asyncio.sleep(0.1)
    return DummyTestRunning(node.params, _self.job.result.tests).get_test_result()


def mock_check_states(params, env):
    return DummyStateCheck(params, env).result


@mock.patch('avocado_i2n.cartgraph.node.ss.check_states', mock_check_states)
@mock.patch('avocado_i2n.cartgraph.node.SpawnerDispatcher', mock.MagicMock())
@mock.patch.object(CartesianRunner, 'run_test', mock_run_test)
class CartesianGraphTest(Test):

    def setUp(self):
        DummyTestRunning.asserted_tests = []
        DummyStateCheck.present_states = []

        self.config = {}
        self.config["param_dict"] = {}
        self.config["tests_str"] = "only normal\n"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n", "vm3": "only Ubuntu\n"}

        self.prefix = ""

        self.loader = CartesianLoader(config=self.config, extra_params={})
        self.job = mock.MagicMock()
        self.job.logdir = "."
        self.job.timeout = 6000
        self.job.result = mock.MagicMock()
        self.job.result.tests = []
        self.runner = CartesianRunner()
        self.runner.job = self.job
        self.runner.slots = ["c1"]
        self.runner.status_server = self.job

    def tearDown(self):
        shutil.rmtree("./graph_parse", ignore_errors=True)
        shutil.rmtree("./graph_traverse", ignore_errors=True)

    def _run_traversal(self, graph, params):
        loop = asyncio.get_event_loop()
        to_traverse = [self.runner.run_traversal(graph, params, s) for s in self.runner.slots]
        loop.run_until_complete(asyncio.wait_for(asyncio.gather(*to_traverse), None))

    def test_cartraph_structures(self):
        """Test sanity of various usage of all Cartesian graph components."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)

        repr = str(graph)
        self.assertIn("[cartgraph]", repr)
        self.assertIn("[object]", repr)
        self.assertIn("[node]", repr)

        test_objects = graph.get_objects_by(param_val="vm1")
        for test_object in test_objects:
            self.assertIn(test_object.long_suffix, graph.suffixes.keys())
            self.assertIn(test_object.long_suffix, ["vm1", "net1"])
            object_num = len(graph.suffixes)
            graph.new_objects(test_object)
            self.assertEqual(len(graph.suffixes), object_num)

        test_node = graph.get_node_by(param_val="tutorial1")
        self.assertIn("1-vm1", test_node.long_prefix)
        self.assertIn(test_node.long_prefix, graph.prefixes.keys())
        node_num = len(graph.prefixes)
        graph.new_nodes(test_node)
        self.assertEqual(len(graph.prefixes), node_num)

    def test_object_params(self):
        """Test for correctly parsed test object parameters."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        test_object = graph.get_object_by(param_key="object_suffix", param_val="^vm1$")
        regenerated_params = test_object.object_typed_params(test_object.config.get_params())
        self.assertEqual(len(regenerated_params.keys()), len(test_object.params.keys()),
                         "The parameters of a test object must be the same as its only parser dictionary")
        for key in regenerated_params.keys():
            self.assertEqual(regenerated_params[key], test_object.params[key],
                             "The values of key %s %s=%s must be the same" % (key, regenerated_params[key], test_object.params[key]))

    def test_node_params(self):
        """Test for correctly parsed test node parameters."""
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
        """Test for correct overwriting of preselected configuration."""
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

        test_objects = graph.get_objects_by(param_val="vm1")
        vm_objects = [o for o in test_objects if o.key == "vms"]
        self.assertEqual(len(vm_objects), 1, "There must be exactly one vm object for tutorial1")
        test_object = vm_objects[0]
        test_object_params = test_object.params.object_params(test_object.suffix)
        self.assertNotEqual(test_object_params["images"], default_object_param,
                            "The default %s of %s wasn't overwritten" % (default_object_param, test_object.suffix))
        self.assertEqual(test_object_params["images"], custom_object_param,
                         "The new %s of %s must be %s" % (default_object_param, test_object.suffix, custom_object_param))
        self.assertEqual(test_object_params["new_key"], "123",
                         "A new parameter=%s of %s must be 123" % (test_object_params["new_key"], test_object.suffix))

        test_node = graph.get_node_by(param_val="tutorial1")
        self.assertNotEqual(test_node.params["kill_vm"], default_node_param,
                            "The default %s of %s wasn't overwritten" % (default_node_param, test_node.prefix))
        self.assertEqual(test_node.params["kill_vm"], custom_node_param,
                         "The new %s of %s must be %s" % (default_node_param, test_node.prefix, custom_node_param))
        self.assertNotEqual(test_node.params["images_vm1"], default_object_param,
                            "The default %s of %s wasn't overwritten" % (default_object_param, test_node.prefix))
        self.assertEqual(test_node.params["images_vm1"], custom_object_param,
                         "The new %s of %s must be %s" % (default_object_param, test_node.prefix, custom_object_param))
        self.assertEqual(test_node.params["new_key"], "123",
                         "A new parameter=%s of %s must be 123" % (test_node.params["new_key"], test_node.prefix))

    def test_object_node_overwrite_scope(self):
        """Test the scope of application of overwriting preselected configuration."""
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
        test_objects = graph.get_objects_by(param_val="vm1")
        vm_objects = [o for o in test_objects if o.key == "vms"]
        self.assertEqual(len(vm_objects), 1, "There must be exactly one vm object for tutorial1")
        test_object1 = vm_objects[0]
        test_object_params1 = test_object1.params.object_params(test_object1.suffix)
        #self.assertNotEqual(test_object_params1["images"], default_object_param,
        #                    "The default %s of %s wasn't overwritten" % (default_object_param, test_object1.suffix))
        self.assertNotEqual(test_object_params1["images"], custom_object_param1,
                            "The new %s of %s is of general scope" % (default_object_param, test_object1.suffix))
        #self.assertEqual(test_object_params1["images"], custom_object_param2,
        #                 "The new %s of %s must be %s" % (default_object_param, test_object1.suffix, custom_object_param2))

        test_objects = graph.get_objects_by(param_val="vm2")
        vm_objects = [o for o in test_objects if o.key == "vms"]
        self.assertEqual(len(vm_objects), 1, "There must be exactly one vm object for tutorial1")
        test_object2 = vm_objects[0]
        test_object_params2 = test_object2.params.object_params(test_object2.suffix)
        self.assertEqual(test_object_params2["images"], default_object_param,
                         "The default %s of %s must be preserved" % (default_object_param, test_object2.suffix))

        # TODO: the current suffix operators make it impossible to fully test this
        test_node = graph.get_node_by(param_val="tutorial3")
        self.assertNotEqual(test_node.params["images"], default_object_param,
                         "The object-general default %s of %s must be overwritten" % (default_object_param, test_node.prefix))
        self.assertEqual(test_node.params["images"], custom_object_param1,
                         "The object-general new %s of %s must be %s" % (default_object_param, test_node.prefix, custom_object_param1))
        #self.assertNotEqual(test_node.params["images_vm1"], default_object_param,
        #                    "The default %s of %s wasn't overwritten" % (default_object_param, test_node.prefix))
        #self.assertEqual(test_node.params["images_vm1"], custom_object_param2,
        #                 "The new %s of %s must be %s" % (default_object_param, test_node.prefix, custom_object_param2))
        self.assertEqual(test_node.params["images_vm2"], default_object_param,
                         "The second %s of %s should be preserved" % (default_object_param, test_node.prefix))

    def test_object_node_incompatible(self):
        """Test incompatibility of parsed tests and preselected available objects."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["vm_strs"] = {"vm2": "only Win10\n", "vm3": "only Ubuntu\n"}
        with self.assertRaises(param.EmptyCartesianProduct):
            self.loader.parse_object_trees(self.config["param_dict"],
                                           self.config["tests_str"], self.config["vm_strs"],
                                           prefix=self.prefix)

        # restrict to vms-tests intersection if the same is nonempty
        self.config["tests_str"] += "only tutorial1,tutorial_get\n"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$", "set_state_images": "^install$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_images": "^install$", "set_state_images": "^customize$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "get_state_images": "^customize$", "set_state_vms": "^on_customize$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "get_state_vms": "^on_customize$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_one_leaf(self):
        """Test traversal path of one test without any reusable setup."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$", "set_state_images": "^install$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_images": "^install$", "set_state_images": "^customize$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "get_state_images": "^customize$", "set_state_vms": "^on_customize$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "get_state_vms": "^on_customize$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_one_leaf_with_setup(self):
        """Test traversal path of one test with a reusable setup."""
        self.runner.slots = [f"c{i+1}" for i in range(4)]
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["root", "install"]
        DummyTestRunning.asserted_tests = [
            # cleanup is expected only if at least one of the states is reusable (here root+install)
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "hostname": "^c1$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "hostname": "^c1$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "hostname": "^c1$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_one_leaf_with_step_setup(self):
        """Test traversal path of one test with a single reusable setup test node."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["customize"]
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_one_leaf_validation(self):
        """Test graph (and component) retrieval and validation methods."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        test_object = graph.get_object_by(param_key="object_suffix", param_val="^vm1$")
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

        # detect reflexive dependencies in the graph
        self.config["param_dict"]["get"] = "tutorial1"
        with self.assertRaises(ValueError):
            self.loader.parse_object_trees(self.config["param_dict"],
                                           self.config["tests_str"], self.config["vm_strs"],
                                           prefix=self.prefix)

    def test_one_leaf_dry_run(self):
        """Test dry run of a single leaf test where no test should end up really running."""
        self.config["param_dict"]["dry_run"] = "yes"
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyTestRunning.asserted_tests = [
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_two_objects_without_setup(self):
        """Test a two-object test run without a reusable setup."""
        self.config["tests_str"] += "only tutorial3\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = []
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.automated.connect.vm1", "vms": "^vm1$"},

            {"shortname": "^internal.stateless.noop.vm2", "vms": "^vm2$"},
            {"shortname": "^original.unattended_install.cdrom.in_cdrom_ks.default_install.aio_threads.vm2", "vms": "^vm2$"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$"},
            {"shortname": "^normal.nongui.tutorial3", "vms": "^vm1 vm2$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_two_objects_with_setup(self):
        """Test a two-object test run with reusable setup."""
        self.runner.slots = [f"c{i+1}" for i in range(4)]
        self.config["tests_str"] += "only tutorial3\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["root", "install", "customize"]
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.automated.connect.vm1", "vms": "^vm1$", "hostname": "^c1$"},
            {"shortname": "^normal.nongui.tutorial3", "vms": "^vm1 vm2$", "hostname": "^c1$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_diverging_paths_with_setup(self):
        """Test a multi-object test run with reusable setup of diverging workers."""
        self.runner.slots = [f"c{i+1}" for i in range(4)]
        self.config["tests_str"] += "only tutorial1,tutorial3\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["root", "install", "customize"]
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "hostname": "^c1$"},
            {"shortname": "^internal.automated.connect.vm1", "vms": "^vm1$", "hostname": "^c2$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "hostname": "^c1$"},
            {"shortname": "^normal.nongui.tutorial3", "vms": "^vm1 vm2$", "hostname": "^c2$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_diverging_paths_with_locally_reused_setup(self):
        """Test a multi-object test run where the workers will run multiple tests reusing their own local setup."""
        # TODO: node setup is currently not reusable across workers so need <=2 to make this work
        self.runner.slots = [f"c{i+1}" for i in range(2)]
        self.config["tests_str"] = "only leaves\n"
        self.config["tests_str"] += "only tutorial2,tutorial_gui\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["root", "install", "customize", "customize"]
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "hostname": "^c1$"},
            {"shortname": "^internal.automated.windows_virtuser.vm2", "vms": "^vm2$", "hostname": "^c2$"},
            {"shortname": "^leaves.quicktest.tutorial2.files.vm1", "vms": "^vm1$", "hostname": "^c1$"},
            {"shortname": "^internal.automated.linux_virtuser.vm1", "vms": "^vm1$", "hostname": "^c2$"},
            {"shortname": "^leaves.quicktest.tutorial2.names.vm1", "vms": "^vm1$", "hostname": "^c1$"},
            {"shortname": "^leaves.tutorial_gui.client_noop", "vms": "^vm1 vm2$", "hostname": "^c2$"},
            # TODO: this tests reentry of traversed path well but node setup is currently not reusable across workers
            {"shortname": "^leaves.tutorial_gui.client_clicked", "vms": "^vm1 vm2$", "hostname": "^c1$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_permanent_object_and_simple_cloning(self):
        """Test a complete test run including complex setup."""
        self.config["tests_str"] = "only leaves\n"
        self.config["tests_str"] += "only tutorial_get\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["root"]
        DummyTestRunning.asserted_tests = [
            # automated setup of vm1
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.automated.linux_virtuser.vm1", "vms": "^vm1$"},
            # automated setup of vm2
            {"shortname": "^internal.stateless.noop.vm2", "vms": "^vm2$"},
            {"shortname": "^original.unattended_install.cdrom.in_cdrom_ks.default_install.aio_threads.vm2", "vms": "^vm2$"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$"},
            {"shortname": "^internal.automated.windows_virtuser.vm2", "vms": "^vm2$"},
            # first (noop) parent GUI setup dependency through vm2
            {"shortname": "^tutorial_gui.client_noop.vm1.virtio_blk.smp2.virtio_net.CentOS.8.0.x86_64.vm2.smp2.Win10.x86_64", "vms": "^vm1 vm2$", "set_state_images_vm2": "guisetup.noop"},
            # extra dependency dependency through vm1
            {"shortname": "^internal.automated.connect.vm1", "vms": "^vm1$"},
            # first (noop) explicit actual test
            {"shortname": "^leaves.tutorial_get.explicit_noop.vm1", "vms": "^vm1 vm2 vm3$", "get_state_images_vm2": "guisetup.noop"},
            # first (noop) duplicated actual test
            {"shortname": "^leaves.tutorial_get.implicit_both.vm1", "vms": "^vm1 vm2 vm3$", "get_state_images_image1_vm2": "guisetup.noop"},
            # second (clicked) parent GUI setup dependency through vm2
            {"shortname": "^tutorial_gui.client_clicked.vm1", "vms": "^vm1 vm2$", "set_state_images_vm2": "guisetup.clicked"},
            # second (clicked) explicit actual test
            {"shortname": "^leaves.tutorial_get.explicit_clicked.vm1", "vms": "^vm1 vm2 vm3$", "get_state_images_vm2": "guisetup.clicked"},
            # second (clicked) duplicated actual test
            {"shortname": "^leaves.tutorial_get.implicit_both.vm1", "vms": "^vm1 vm2 vm3$", "get_state_images_image1_vm2": "guisetup.clicked"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deep_cloning(self):
        """Test for correct deep cloning."""
        self.config["tests_str"] = "only leaves\n"
        self.config["tests_str"] += "only tutorial_finale\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["root", "install", "customize"]
        DummyTestRunning.asserted_tests = [
            # automated setup of vm1
            {"shortname": "^internal.automated.linux_virtuser.vm1", "vms": "^vm1$"},
            # automated setup of vm2
            {"shortname": "^internal.automated.windows_virtuser.vm2", "vms": "^vm2$"},
            # first (noop) parent GUI setup dependency through vm2
            {"shortname": "^tutorial_gui.client_noop", "vms": "^vm1 vm2$", "set_state_images_vm2": "guisetup.noop"},
            # extra dependency dependency through vm1
            {"shortname": "^internal.automated.connect.vm1", "vms": "^vm1$"},
            # first (noop) duplicated actual test
            {"shortname": "^tutorial_get.implicit_both.+guisetup.noop", "vms": "^vm1 vm2 vm3$", "get_state_images_image1_vm2": "guisetup.noop", "set_state_images_image1_vm2": "getsetup.guisetup.noop"},
            {"shortname": "^leaves.tutorial_finale.+getsetup.guisetup.noop", "vms": "^vm1 vm2 vm3$", "get_state_images_image1_vm2": "getsetup.guisetup.noop"},
            # second (clicked) parent GUI setup dependency through vm2
            {"shortname": "^tutorial_gui.client_clicked", "vms": "^vm1 vm2$", "set_state_images_vm2": "guisetup.clicked"},
            # second (clicked) duplicated actual test
            {"shortname": "^tutorial_get.implicit_both.+guisetup.clicked", "vms": "^vm1 vm2 vm3$", "get_state_images_image1_vm2": "guisetup.clicked", "set_state_images_image1_vm2": "getsetup.guisetup.clicked"},
            {"shortname": "^leaves.tutorial_finale.+getsetup.guisetup.clicked", "vms": "^vm1 vm2 vm3$", "get_state_images_image1_vm2": "getsetup.guisetup.clicked"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_complete_verbose_graph_dry_run(self):
        """Test a complete dry run traversal of a verbose (visualized) graph."""
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
        self._run_traversal(graph, self.config["param_dict"])

    def test_abort_run(self):
        """Test that traversal is aborted through explicit configuration."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"].update({"abort_on_error": "yes"})
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["root", "install"]
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "set_state_vms_on_error": "^$", "_status": "FAIL"},
        ]
        with self.assertRaises(exceptions.TestSkipError):
            self._run_traversal(graph, self.config["param_dict"])

    def test_abort_objectless_node(self):
        """Test that traversal is aborted on objectless node detection."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        test_node = graph.get_node_by(param_val="tutorial1")
        # assume we are parsing invalid configuration
        test_node.params["vms"] = ""
        DummyStateCheck.present_states = ["root", "install"]
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$"},
        ]
        with self.assertRaises(AssertionError):
            self._run_traversal(graph, self.config["param_dict"])

    def test_trees_difference_zero(self):
        """Test for proper node difference of two Cartesian graphs."""
        self.config["tests_str"] = "only nonleaves\n"
        self.config["tests_str"] += "only connect\n"
        self.config["param_dict"]["vms"] = "vm1"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        graph.flag_parent_intersection(graph, flag_type="run", flag=False)
        DummyTestRunning.asserted_tests = [
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_trees_difference(self):
        """Test for correct node difference of two Cartesian graphs."""
        self.config["tests_str"] = "only nonleaves\n"
        tests_str1 = self.config["tests_str"]
        tests_str1 += "only connect\n"
        tests_str2 = self.config["tests_str"]
        tests_str2 += "only customize\n"
        self.config["param_dict"]["vms"] = "vm2"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               tests_str1, self.config["vm_strs"],
                                               prefix=self.prefix)
        reuse_graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                     tests_str2, self.config["vm_strs"],
                                                     prefix=self.prefix)

        graph.flag_parent_intersection(reuse_graph, flag_type="run", flag=False)
        DummyTestRunning.asserted_tests = [
            {"shortname": "^nonleaves.internal.automated.connect.vm2", "vms": "^vm2$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    @mock.patch('avocado_i2n.runner.StatusRepo')
    @mock.patch('avocado_i2n.runner.StatusServer')
    def test_loader_runner_entries(self, mock_status_server, mock_status_repo):
        """Test that the default loader and runner entries work as expected."""
        self.config["tests_str"] += "only tutorial1\n"
        reference = "only=tutorial1 key1=val1"
        self.config["params"] = reference.split()
        self.config["prefix"] = ""
        self.config["subcommand"] = "run"
        self.loader.config = self.config

        resolutions = [self.loader.resolve(reference)]
        runnables = resolutions_to_runnables(resolutions, self.config)
        test_suite = TestSuite('suite',
                               config=self.config,
                               tests=runnables,
                               resolutions=resolutions)

        DummyStateCheck.present_states = []
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$", "set_state_images": "^install$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_images": "^install$", "set_state_images": "^customize$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "get_state_images": "^customize$", "set_state_vms": "^on_customize$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "get_state_vms": "^on_customize$"},
        ]

        async def serve_forever(): pass
        server_instance = mock_status_server.return_value
        server_instance.serve_forever = serve_forever

        self.runner.job.config = self.config
        self.runner.run_suite(self.runner.job, test_suite)

    def test_run_retry_times(self):
        """Test that the test is retried `retry_attempts` times if `retry_stop` is not specified."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"]["retry_attempts"] = "2"
        graph = self.loader.parse_object_trees(
            self.config["param_dict"], self.config["tests_str"],
            self.config["vm_strs"], prefix="")
        DummyTestRunning.asserted_tests = [
            {"shortname": r"^internal.stateless.noop.vm1", "vms": r"^vm1$"},
            {"shortname": r"^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": r"^vm1$"},
            {"shortname": r"^internal.automated.customize.vm1", "vms": r"^vm1$"},
            {"shortname": r"^internal.automated.customize.vm1", "vms": r"^vm1$", "short_id": r"^[a\d]+r1-vm1$"},
            {"shortname": r"^internal.automated.customize.vm1", "vms": r"^vm1$", "short_id": r"^[a\d]+r2-vm1$"},
            {"shortname": r"^internal.automated.on_customize.vm1", "vms": r"^vm1$"},
            {"shortname": r"^internal.automated.on_customize.vm1", "vms": r"^vm1$", "short_id": r"^[a\d]+r1-vm1$"},
            {"shortname": r"^internal.automated.on_customize.vm1", "vms": r"^vm1$", "short_id": r"^[a\d]+r2-vm1$"},
            {"shortname": r"^normal.nongui.quicktest.tutorial1.vm1", "vms": r"^vm1$"},
            {"shortname": r"^normal.nongui.quicktest.tutorial1.vm1", "vms": r"^vm1$", "short_id": r"^[a\d]+r1-vm1$"},
            {"shortname": r"^normal.nongui.quicktest.tutorial1.vm1", "vms": r"^vm1$", "short_id": r"^[a\d]+r2-vm1$"},
        ]
        self._run_traversal(graph, {})

    def test_run_retry_status(self):
        """Test that certain statuses are ignored when retrying a test."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"]["retry_attempts"] = "3"
        self.config["param_dict"]["retry_stop"] = "none"

        # test should not be re-run on these statuses
        for status in ["SKIP", "INTERRUPTED", "CANCEL"]:
            graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                   self.config["tests_str"], self.config["vm_strs"],
                                                   prefix=self.prefix)
            DummyStateCheck.present_states = ["root", "install", "customize", "on_customize"]
            DummyTestRunning.asserted_tests = [
                {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
            ]
            self._run_traversal(graph, self.config["param_dict"])
            self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

            # assert that tests were not repeated
            self.assertEqual(len(self.runner.job.result.tests), 1)
            # also assert the correct results were registered
            self.assertEqual([x["status"] for x in self.runner.job.result.tests], [status])
            self.runner.job.result.tests.clear()

        # test should be re-run on these statuses
        for status in ["PASS", "WARN", "FAIL", "ERROR"]:
            graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                   self.config["tests_str"], self.config["vm_strs"],
                                                   prefix=self.prefix)
            DummyStateCheck.present_states = ["root", "install", "customize", "on_customize"]
            DummyTestRunning.asserted_tests = [
                {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
                {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
                {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
                {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
            ]
            self._run_traversal(graph, self.config["param_dict"])
            self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

            # assert that tests were repeated
            self.assertEqual(len(self.runner.job.result.tests), 4)
            # also assert the correct results were registered
            self.assertEqual([x["status"] for x in self.runner.job.result.tests], [status] * 4)
            self.runner.job.result.tests.clear()

    def test_run_retry_status_stop(self):
        """Test that the `retry_stop` parameter is respected by the runner."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"]["retry_attempts"] = "3"

        # expect success and get success -> should run only once
        self.config["param_dict"]["retry_stop"] = "success"
        for status in ["PASS", "WARN"]:
            graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                   self.config["tests_str"], self.config["vm_strs"],
                                                   prefix=self.prefix)
            DummyStateCheck.present_states = ["root", "install", "customize", "on_customize"]
            DummyTestRunning.asserted_tests = [
                {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
            ]
            self._run_traversal(graph, self.config["param_dict"])
            self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

            # assert that tests were not repeated
            self.assertEqual(len(self.runner.job.result.tests), 1)
            # also assert the correct results were registered
            self.assertEqual([x["status"] for x in self.runner.job.result.tests], [status])
            self.runner.job.result.tests.clear()

        # expect failure and get failure -> should run only once
        self.config["param_dict"]["retry_stop"] = "error"
        for status in ["FAIL", "ERROR"]:
            graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                   self.config["tests_str"], self.config["vm_strs"],
                                                   prefix=self.prefix)
            DummyStateCheck.present_states = ["root", "install", "customize", "on_customize"]
            DummyTestRunning.asserted_tests = [
                {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
            ]
            self._run_traversal(graph, self.config["param_dict"])
            self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

            # assert that tests were not repeated
            self.assertEqual(len(self.runner.job.result.tests), 1)
            # also assert the correct results were registered
            self.assertEqual([x["status"] for x in self.runner.job.result.tests], [status])
            self.runner.job.result.tests.clear()

    def test_run_retry_invalid(self):
        """Test if an exception is thrown with invalid retry parameter values."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateCheck.present_states = ["root", "install", "customize", "on_customize"]
        DummyTestRunning.asserted_tests = [
        ]

        self.config["param_dict"]["retry_attempts"] = "3"
        self.config["param_dict"]["retry_stop"] = "invalid"
        with self.assertRaises(AssertionError):
            self._run_traversal(graph, self.config["param_dict"])

        self.config["param_dict"]["retry_stop"] = "none"
        # negative values
        with mock.patch.dict(self.config["param_dict"], {"retry_attempts": "-32"}):
            with self.assertRaises(AssertionError):
                self._run_traversal(graph, self.config["param_dict"])
        # floats
        with mock.patch.dict(self.config["param_dict"], {"retry_attempts": "3.5"}):
            with self.assertRaises(AssertionError):
                self._run_traversal(graph, self.config["param_dict"])
        # non-integers
        with mock.patch.dict(self.config["param_dict"], {"retry_attempts": "hey"}):
            with self.assertRaises(AssertionError):
                self._run_traversal(graph, self.config["param_dict"])

    def test_run_exit_code(self):
        """Test that the return value of the last run is preserved."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"]["retry_attempts"] = "2"
        self.config["param_dict"]["retry_stop"] = "none"

        test_objects = self.loader.parse_objects(self.config["param_dict"], self.config["vm_strs"])
        net = test_objects[-1]
        test_node = self.loader.parse_node_from_object(net, self.config["param_dict"].copy(),
                                                       param.re_str("normal..tutorial1"))

        DummyTestRunning.asserted_tests = [
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
        ]
        to_run = self.runner.run_test_node(test_node, self.config["param_dict"])
        status = asyncio.get_event_loop().run_until_complete(asyncio.wait_for(to_run, None))
        # all runs succeed - status must be True
        self.assertTrue(status)
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)
        self.runner.job.result.tests.clear()

        DummyTestRunning.asserted_tests = [
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "FAIL"},
        ]
        to_run = self.runner.run_test_node(test_node, self.config["param_dict"])
        status = asyncio.get_event_loop().run_until_complete(asyncio.wait_for(to_run, None))
        # last run fails - status must be False
        self.assertFalse(status, "Runner did not preserve last run fail status")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)
        self.runner.job.result.tests.clear()

        DummyTestRunning.asserted_tests = [
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "FAIL"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
        ]
        to_run = self.runner.run_test_node(test_node, self.config["param_dict"])
        status = asyncio.get_event_loop().run_until_complete(asyncio.wait_for(to_run, None))
        # fourth run fails - status must be True
        self.assertTrue(status, "Runner did not preserve last pass status after previous fail")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)
        self.runner.job.result.tests.clear()


if __name__ == '__main__':
    unittest.main()
