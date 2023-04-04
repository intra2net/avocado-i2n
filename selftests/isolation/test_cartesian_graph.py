#!/usr/bin/env python

import unittest
import unittest.mock as mock
import shutil
import asyncio
import re

from aexpect.exceptions import ShellCmdError
from avocado import Test, skip
from avocado.core import exceptions
from avocado.core.suite import TestSuite, resolutions_to_runnables

import unittest_importer
from avocado_i2n import params_parser as param
from avocado_i2n.loader import CartesianLoader
from avocado_i2n.runner import CartesianRunner


class DummyTestRun(object):

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

    @staticmethod
    async def mock_run_test(_self, _job, node):
        # define ID-s and other useful parameter filtering
        node.get_runnable()
        node.params["_uid"] = node.id_test.uid
        # small enough not to slow down our tests too much for a test timeout of 300 but
        # large enough to surpass the minimal occupation waiting timeout for more realism
        await asyncio.sleep(0.5)
        return DummyTestRun(node.params, _self.job.result.tests).get_test_result()


class DummyStateControl(object):

    asserted_states = {"check": {}, "get": {}, "set": {}, "unset": {}}
    states_params = {}
    action = "check"

    def __init__(self):
        params = self.states_params
        do = self.action
        self.result = True

        for vm in params.objects("vms"):
            vm_params = params.object_params(vm)
            for image in params.objects("images"):
                image_params = vm_params.object_params(image)
                do_source = image_params.get(f"{do}_location_images", "")
                do_state = image_params.get(f"{do}_state_images")
                if not do_state:
                    do_state = image_params.get(f"{do}_state_vms")
                    do_source = image_params.get(f"{do}_location_vms", "")
                    if not do_state:
                        continue

                assert do_state in self.asserted_states[do], f"Unexpected state {do_state} to {do}"
                if image_params.get_boolean("use_pool"):
                    assert do_source != "", f"Empty {do} state location for {do_state}"
                if do == "check":
                    if not self.asserted_states[do][do_state] and params.get("set_location") is None:
                        self.result = False
                else:
                    self.asserted_states[do][do_state] += 1

    @staticmethod
    def run_subcontrol(session, mod_control_path):
        if not DummyStateControl().result:
            raise ShellCmdError(1, "command", "AssertionError")

    @staticmethod
    def set_subcontrol_parameter(_, __, do):
        DummyStateControl.action = do

    @staticmethod
    def set_subcontrol_parameter_dict(_, __, node_params):
        DummyStateControl.states_params = node_params


@mock.patch('avocado_i2n.cartgraph.node.remote.wait_for_login', mock.MagicMock())
@mock.patch('avocado_i2n.cartgraph.node.door', DummyStateControl)
@mock.patch('avocado_i2n.cartgraph.node.SpawnerDispatcher', mock.MagicMock())
@mock.patch.object(CartesianRunner, 'run_test', DummyTestRun.mock_run_test)
class CartesianGraphTest(Test):

    def setUp(self):
        DummyTestRun.asserted_tests = []
        DummyStateControl.asserted_states = {"check": {}, "get": {}, "set": {}, "unset": {}}
        DummyStateControl.asserted_states["check"] = {"install": False,
                                                      "customize": False, "on_customize": False,
                                                      "connect": False,
                                                      "linux_virtuser": False, "windows_virtuser": False}
        DummyStateControl.asserted_states["get"] = {"install": 0,
                                                    "customize": 0, "on_customize": 0,
                                                    "connect": 0,
                                                    "linux_virtuser": 0, "windows_virtuser": 0}

        self.config = {}
        self.config["param_dict"] = {"test_timeout": 100}
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
        self.runner.slots = ["1"]
        self.runner.status_server = self.job

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
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$", "set_state_images": "^install$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_images": "^install$", "set_state_images": "^customize$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "get_state_images": "^customize$", "set_state_vms": "^on_customize$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "get_state_vms": "^on_customize$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_one_leaf(self):
        """Test traversal path of one test without any reusable setup."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$", "set_state_images": "^install$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_images": "^install$", "set_state_images": "^customize$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "get_state_images": "^customize$", "set_state_vms": "^on_customize$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "get_state_vms": "^on_customize$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_one_leaf_serial(self):
        """Test traversal path of one test without any reusable setup and with a serial unisolated run."""
        self.runner.slots = [""]
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$", "nets_spawner": "process"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$", "nets_spawner": "process"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "nets_spawner": "process"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "nets_spawner": "process"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "nets_spawner": "process"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_one_leaf_with_setup(self):
        """Test traversal path of one test with a reusable setup."""
        self.runner.slots = [f"{i+1}" for i in range(4)]
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateControl.asserted_states["check"]["install"] = True
        DummyTestRun.asserted_tests = [
            # cleanup is expected only if at least one of the states is reusable (here root+install)
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "nets_spawner": "lxc", "nets_host": "^c1$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "nets_spawner": "lxc", "nets_host": "^c1$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "nets_spawner": "lxc", "nets_host": "^c1$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_one_leaf_with_step_setup(self):
        """Test traversal path of one test with a single reusable setup test node."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateControl.asserted_states["check"]["customize"] = True
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_one_leaf_with_failed_setup(self):
        """Test traversal path of one test with a failed reusable setup test node."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateControl.asserted_states["check"]["install"] = True
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "nets_host": "^c1$", "_status": "FAIL"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

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
        with self.assertRaisesRegex(ValueError, r"^Additional parametric objects .+ not in .+$"):
            test_node.validate()
        test_node.objects.append(test_object)
        test_node.validate()
        test_node.params["vms"] = ""
        with self.assertRaisesRegex(ValueError, r"^Missing parametric objects .+ from .+$"):
            test_node.validate()

        # detect reflexive dependencies in the graph
        self.config["param_dict"]["get"] = "tutorial1"
        with self.assertRaisesRegex(ValueError, r"^Detected reflexive dependency of"):
            self.loader.parse_object_trees(self.config["param_dict"],
                                           self.config["tests_str"], self.config["vm_strs"],
                                           prefix=self.prefix)

    def test_one_leaf_with_occupation_timeout(self):
        """Test multi-traversal of one test where it is occupied for too long (worker hangs)."""
        self.config["param_dict"]["test_timeout"] = 1
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        test_node = graph.get_node_by(param_val="tutorial1")
        test_node.set_environment(self.job, "dead")
        DummyStateControl.asserted_states["check"]["install"] = True
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "nets_host": "^c1$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "nets_host": "^c1$"},
        ]
        with self.assertRaisesRegex(RuntimeError, r"^Worker .+ spent [\d\.]+ seconds waiting for occupied node"):
            self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_one_leaf_dry_run(self):
        """Test dry run of a single leaf test where no test should end up really running."""
        self.config["param_dict"]["dry_run"] = "yes"
        self.config["tests_str"] += "only tutorial1\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyTestRun.asserted_tests = [
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_two_objects_without_setup(self):
        """Test a two-object test run without a reusable setup."""
        self.config["tests_str"] += "only tutorial3\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyTestRun.asserted_tests = [
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
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_two_objects_with_setup(self):
        """Test a two-object test run with reusable setup."""
        self.runner.slots = [f"{i+1}" for i in range(4)]
        self.config["tests_str"] += "only tutorial3\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateControl.asserted_states["check"]["install"] = True
        DummyStateControl.asserted_states["check"]["customize"] = True
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.connect.vm1", "vms": "^vm1$", "nets_host": "^c1$"},
            {"shortname": "^normal.nongui.tutorial3", "vms": "^vm1 vm2$", "nets_host": "^c1$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_diverging_paths_with_setup(self):
        """Test a multi-object test run with reusable setup of diverging workers."""
        self.runner.slots = [f"{i+1}" for i in range(4)]
        self.config["tests_str"] += "only tutorial1,tutorial3\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateControl.asserted_states["check"]["install"] = True
        DummyStateControl.asserted_states["check"]["customize"] = True
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "nets_host": "^c1$"},
            {"shortname": "^internal.automated.connect.vm1", "vms": "^vm1$", "nets_host": "^c2$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "nets_host": "^c1$", "get_location_vm1": "c1:"},
            {"shortname": "^normal.nongui.tutorial3", "vms": "^vm1 vm2$", "nets_host": "^c2$", "get_location_image1_vm1": "c2:"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        # expect four sync and no other cleanup calls, one for each worker
        for action in ["get"]:
            for state in ["install", "customize"]:
                # called once by worker for for each of two vms (excluding self-sync)
                self.assertEqual(DummyStateControl.asserted_states[action][state], 6)
            for state in ["on_customize", "connect"]:
                # called once by worker only for vm1
                self.assertEqual(DummyStateControl.asserted_states[action][state], 3)
        for action in ["set", "unset"]:
            for state in DummyStateControl.asserted_states[action]:
                self.assertEqual(DummyStateControl.asserted_states[action][state], 0)

    def test_diverging_paths_with_swarm_setup(self):
        """Test a multi-object test run where the workers will run multiple tests reusing their own local swarm setup."""
        self.runner.slots = [f"{i+1}" for i in range(4)]
        self.config["tests_str"] = "only leaves\n"
        self.config["tests_str"] += "only tutorial2,tutorial_gui\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        # this is not what we test but simply a means to remove some initial nodes for simpler testing
        DummyStateControl.asserted_states["check"]["install"] = True
        DummyStateControl.asserted_states["check"]["customize"] = True
        DummyStateControl.asserted_states["check"]["guisetup.noop"] = False
        DummyStateControl.asserted_states["check"]["guisetup.clicked"] = False
        DummyStateControl.asserted_states["get"]["guisetup.noop"] = 0
        DummyStateControl.asserted_states["get"]["guisetup.clicked"] = 0
        DummyStateControl.asserted_states["unset"] = {"guisetup.noop": 0}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "nets_host": "^c1$"},
            {"shortname": "^internal.automated.windows_virtuser.vm2", "vms": "^vm2$", "nets_host": "^c2$"},
            # this tests reentry of traversed path by an extra worker c4 reusing setup from c1
            {"shortname": "^internal.automated.linux_virtuser.vm1", "vms": "^vm1$", "nets_host": "^c3$"},
            # c4 would step back from already occupied on_customize (by c1) for the time being
            {"shortname": "^leaves.quicktest.tutorial2.files.vm1", "vms": "^vm1$", "nets_host": "^c1$",
             "get_location_vm1": "c1:/mnt/local/images/swarm"},
            # c2 would step back from already occupied linux_virtuser (by c3) and c3 proceeds instead
            {"shortname": "^leaves.tutorial_gui.client_noop", "vms": "^vm1 vm2$", "nets_host": "^c3$",
             "get_location_image1_vm1": "c3:/mnt/local/images/swarm", "get_location_image1_vm2": "c2:/mnt/local/images/swarm"},
            # c4 now picks up available setup and tests from its own reentered branch
            {"shortname": "^leaves.tutorial_gui.client_clicked", "vms": "^vm1 vm2$", "nets_host": "^c4$",
             "get_location_image1_vm1": "c3:/mnt/local/images/swarm", "get_location_image1_vm2": "c2:/mnt/local/images/swarm"},
            # c1 would now pick its second local tutorial2.names
            {"shortname": "^leaves.quicktest.tutorial2.names.vm1", "vms": "^vm1$", "nets_host": "^c1$", "get_location_vm1": "c1:/mnt/local/images/swarm"},
            # all others now step back from already occupied tutorial2.names (by c1)
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        # expect three sync and four cleanup calls, one for each worker without self-sync
        self.assertEqual(DummyStateControl.asserted_states["unset"]["guisetup.noop"], 4)
        self.assertEqual(DummyStateControl.asserted_states["get"]["guisetup.clicked"], 3)

    def test_diverging_paths_with_remote_setup(self):
        """Test a multi-object test run where the workers will run multiple tests reusing also remote swarm setup."""
        self.runner.slots = [f"{i+1}" for i in range(2)] + [f"host1/{i+1}" for i in range(2)] + [f"host2/22"]
        self.config["tests_str"] = "only leaves\n"
        self.config["tests_str"] += "only tutorial2,tutorial_gui\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        # this is not what we test but simply a means to remove some initial nodes for simpler testing
        DummyStateControl.asserted_states["check"]["install"] = True
        DummyStateControl.asserted_states["check"]["customize"] = True
        DummyStateControl.asserted_states["check"]["guisetup.noop"] = False
        DummyStateControl.asserted_states["check"]["guisetup.clicked"] = False
        DummyStateControl.asserted_states["get"]["guisetup.noop"] = 0
        DummyStateControl.asserted_states["get"]["guisetup.clicked"] = 0
        DummyStateControl.asserted_states["unset"] = {"guisetup.noop": 0}
        DummyTestRun.asserted_tests = [
            # TODO: localhost is not acceptable when we mix hosts
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "nets_spawner": "lxc", "nets_gateway": "^$", "nets_host": "^c1$"},
            {"shortname": "^internal.automated.windows_virtuser.vm2", "vms": "^vm2$", "nets_spawner": "lxc", "nets_gateway": "^$", "nets_host": "^c2$"},
            # this tests remote container reuse of previous setup
            {"shortname": "^internal.automated.linux_virtuser.vm1", "vms": "^vm1$", "nets_spawner": "remote", "nets_gateway": "^host1$", "nets_host": "^1$"},
            # c1 reuses its own setup moving further down
            {"shortname": "^leaves.quicktest.tutorial2.files.vm1", "vms": "^vm1$", "nets_spawner": "lxc", "nets_host": "^c1$",
             "get_location_vm1": "c1:/mnt/local/images/swarm"},
            # remote container reused setup from itself and from local c2
            {"shortname": "^leaves.tutorial_gui.client_noop", "vms": "^vm1 vm2$", "nets_spawner": "remote", "nets_host": "^1$",
             "get_location_image1_vm1": "host1/1:/mnt/local/images/swarm", "get_location_image1_vm2": "c2:/mnt/local/images/swarm"},
            # ultimate speed up comes from the second remote container from the first remote location
            {"shortname": "^leaves.tutorial_gui.client_clicked", "vms": "^vm1 vm2$", "nets_spawner": "remote", "nets_host": "^2$",
             "get_location_image1_vm1": "host1/1:/mnt/local/images/swarm", "get_location_image1_vm2": "c2:/mnt/local/images/swarm"},
            # all of local c1's setup will be reused by a second remote location containers that would pick up tutorial2.names
            {"shortname": "^leaves.quicktest.tutorial2.names.vm1", "vms": "^vm1$", "nets_spawner": "remote", "nets_host": "^22$",
             "get_location_vm1": "c1:/mnt/local/images/swarm"},
            # all others now step back from already occupied nodes
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        # expect three sync and four cleanup calls, one for each worker without self-sync
        self.assertEqual(DummyStateControl.asserted_states["unset"]["guisetup.noop"], 5)
        self.assertEqual(DummyStateControl.asserted_states["get"]["guisetup.clicked"], 4)

    def test_permanent_object_and_simple_cloning(self):
        """Test a complete test run including complex setup."""
        self.config["tests_str"] = "only leaves\n"
        self.config["tests_str"] += "only tutorial_get\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateControl.asserted_states["check"]["root"] = True
        DummyStateControl.asserted_states["check"].update({"guisetup.noop": False, "guisetup.clicked": False,
                                                           "getsetup.noop": False, "getsetup.clicked": False,
                                                           "getsetup.guisetup.noop": False,
                                                           "getsetup.guisetup.clicked": False})
        # test syncing also for permanent vms
        DummyStateControl.asserted_states["get"]["ready"] = 0
        DummyStateControl.asserted_states["get"].update({"guisetup.noop": 0, "guisetup.clicked": 0,
                                                         "getsetup.noop": 0, "getsetup.clicked": 0,
                                                         "getsetup.guisetup.noop": 0,
                                                         "getsetup.guisetup.clicked": 0})
        DummyStateControl.asserted_states["unset"] = {"guisetup.noop": 0, "getsetup.noop": 0, "ready": 0}
        DummyTestRun.asserted_tests = [
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
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        # expect a single cleanup call only for the states of enforcing cleanup policy
        # expect four sync and respectively cleanup calls, one for each worker
        self.assertEqual(DummyStateControl.asserted_states["unset"]["guisetup.noop"], 1)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["getsetup.noop"], 1)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["ready"], 0)
        # root state of a permanent vm is not synced from a single worker to itself
        self.assertEqual(DummyStateControl.asserted_states["get"]["ready"], 0)

    def test_deep_cloning(self):
        """Test for correct deep cloning."""
        self.config["tests_str"] = "only leaves\n"
        self.config["tests_str"] += "only tutorial_finale\n"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateControl.asserted_states["check"]["install"] = True
        DummyStateControl.asserted_states["check"]["customize"] = True
        DummyStateControl.asserted_states["check"].update({"guisetup.noop": False, "guisetup.clicked": False,
                                                           "getsetup.guisetup.noop": False,
                                                           "getsetup.guisetup.clicked": False})
        DummyStateControl.asserted_states["get"].update({"guisetup.noop": 0, "guisetup.clicked": 0,
                                                         "getsetup.guisetup.noop": 0,
                                                         "getsetup.guisetup.clicked": 0})
        DummyStateControl.asserted_states["unset"] = {"guisetup.noop": 0, "getsetup.noop": 0}
        DummyTestRun.asserted_tests = [
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
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        # expect a single cleanup call only for the states of enforcing cleanup policy
        self.assertEqual(DummyStateControl.asserted_states["unset"]["guisetup.noop"], 1)

    def test_complete_graph_dry_run(self):
        """Test a complete dry run traversal of a graph."""
        self.config["tests_str"] = "only all\n"
        self.config["param_dict"]["dry_run"] = "yes"

        DummyStateControl.asserted_states["check"].update({"guisetup.noop": False, "guisetup.clicked": False,
                                                           "getsetup.noop": False, "getsetup.clicked": False,
                                                           "getsetup.guisetup.noop": False,
                                                           "getsetup.guisetup.clicked": False})
        DummyTestRun.asserted_tests = [
        ]

        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                self.config["tests_str"], self.config["vm_strs"],
                                                prefix=self.prefix, verbose=True)
        self._run_traversal(graph, self.config["param_dict"])
        for action in ["get", "set", "unset"]:
            for state in DummyStateControl.asserted_states[action]:
                self.assertEqual(DummyStateControl.asserted_states[action][state], 0)

    def test_abort_run(self):
        """Test that traversal is aborted through explicit configuration."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"].update({"abort_on_error": "yes"})
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        DummyStateControl.asserted_states["check"]["install"] = True
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "set_state_vms_on_error": "^$", "_status": "FAIL"},
        ]
        with self.assertRaisesRegex(exceptions.TestSkipError, r"^God wanted this test to abort$"):
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
        DummyStateControl.asserted_states["check"]["install"] = True
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$"},
        ]
        with self.assertRaisesRegex(AssertionError, r"^Cannot run test nodes not using any test objects"):
            self._run_traversal(graph, self.config["param_dict"])

    @skip("The run, scan, and other flags are no longer compatible with manual setting")
    def test_trees_difference_zero(self):
        """Test for proper node difference of two Cartesian graphs."""
        self.config["tests_str"] = "only nonleaves\n"
        self.config["tests_str"] += "only connect\n"
        self.config["param_dict"]["vms"] = "vm1"
        graph = self.loader.parse_object_trees(self.config["param_dict"],
                                               self.config["tests_str"], self.config["vm_strs"],
                                               prefix=self.prefix)
        graph.flag_parent_intersection(graph, flag_type="run", flag=False)
        graph.flag_parent_intersection(graph, flag_type="scan", flag=False)
        DummyTestRun.asserted_tests = [
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    @skip("The run, scan, and other flags are no longer compatible with manual setting")
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
        DummyTestRun.asserted_tests = [
            {"shortname": "^nonleaves.internal.automated.connect.vm2", "vms": "^vm2$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    @mock.patch('avocado_i2n.runner.StatusRepo')
    @mock.patch('avocado_i2n.runner.StatusServer')
    @mock.patch('avocado_i2n.runner.TestNode.start_environment')
    @mock.patch('avocado_i2n.cartgraph.graph.TestGraph.visualize')
    def test_loader_runner_entries(self, _mock_visualize, _mock_start_environment,
                                   mock_status_server, _mock_status_repo):
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

        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$", "set_state_images": "^install$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_images": "^install$", "set_state_images": "^customize$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "get_state_images": "^customize$", "set_state_vms": "^on_customize$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "get_state_vms": "^on_customize$"},
        ]

        async def create_server(): pass
        async def serve_forever(): pass
        server_instance = mock_status_server.return_value
        server_instance.create_server = create_server
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
        DummyTestRun.asserted_tests = [
            {"shortname": r"^internal.stateless.noop.vm1", "vms": r"^vm1$"},
            {"shortname": r"^internal.stateless.noop.vm1", "vms": r"^vm1$"},
            {"shortname": r"^internal.stateless.noop.vm1", "vms": r"^vm1$"},
            {"shortname": r"^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": r"^vm1$"},
            {"shortname": r"^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": r"^vm1$"},
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
        self.config["param_dict"]["retry_stop"] = ""

        # test should not be re-run on these statuses
        for status in ["SKIP", "INTERRUPTED", "CANCEL"]:
            graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                   self.config["tests_str"], self.config["vm_strs"],
                                                   prefix=self.prefix)
            DummyStateControl.asserted_states["check"] = {"root": True, "install": True,
                                                          "customize": True, "on_customize": True}
            DummyTestRun.asserted_tests = [
                {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
            ]
            self._run_traversal(graph, self.config["param_dict"])
            self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

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
            DummyStateControl.asserted_states["check"] = {"root": True, "install": True,
                                                          "customize": True, "on_customize": True}
            DummyTestRun.asserted_tests = [
                {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
                {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
                {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
                {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
            ]
            self._run_traversal(graph, self.config["param_dict"])
            self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

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
        for stop_status in ["pass", "warn", "fail", "error"]:
            self.config["param_dict"]["retry_stop"] = stop_status
            status = stop_status.upper()
            graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                self.config["tests_str"], self.config["vm_strs"],
                                                prefix=self.prefix)
            DummyStateControl.asserted_states["check"] = {"root": True, "install": True,
                                                          "customize": True, "on_customize": True}
            DummyTestRun.asserted_tests = [
                {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
            ]
            self._run_traversal(graph, self.config["param_dict"])
            self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

            # assert that tests were not repeated
            self.assertEqual(len(self.runner.job.result.tests), 1)
            # also assert the correct results were registered
            self.assertEqual([x["status"] for x in self.runner.job.result.tests], [status])
            self.runner.job.result.tests.clear()

    def test_run_retry_invalid(self):
        """Test if an exception is thrown with invalid retry parameter values."""
        self.config["tests_str"] += "only tutorial1\n"
        DummyStateControl.asserted_states["check"] = {"root": True, "install": True,
                                                        "customize": True, "on_customize": True}
        DummyTestRun.asserted_tests = [
        ]

        with mock.patch.dict(self.config["param_dict"], {"retry_attempts": "3",
                                                         "retry_stop": "invalid"}):
            graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                   self.config["tests_str"], self.config["vm_strs"],
                                                   prefix=self.prefix)
            with self.assertRaisesRegex(ValueError, r"^Value of retry_stop must be a valid test status"):
                self._run_traversal(graph, self.config["param_dict"])

        # negative values
        with mock.patch.dict(self.config["param_dict"], {"retry_attempts": "-32",
                                                         "retry_stop": "none"}):
            graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                   self.config["tests_str"], self.config["vm_strs"],
                                                   prefix=self.prefix)
            with self.assertRaisesRegex(ValueError, r"^Value of retry_attempts cannot be less than zero$"):
                self._run_traversal(graph, self.config["param_dict"])

        # floats
        with mock.patch.dict(self.config["param_dict"], {"retry_attempts": "3.5",
                                                         "retry_stop": "none"}):
            graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                   self.config["tests_str"], self.config["vm_strs"],
                                                   prefix=self.prefix)
            with self.assertRaisesRegex(ValueError, r"^invalid literal for int"):
                self._run_traversal(graph, self.config["param_dict"])

        # non-integers
        with mock.patch.dict(self.config["param_dict"], {"retry_attempts": "hey",
                                                         "retry_stop": "none"}):
            graph = self.loader.parse_object_trees(self.config["param_dict"],
                                                   self.config["tests_str"], self.config["vm_strs"],
                                                   prefix=self.prefix)
            with self.assertRaisesRegex(ValueError, r"^invalid literal for int"):
                self._run_traversal(graph, self.config["param_dict"])

    def test_run_exit_code(self):
        """Test that the return value of the last run is preserved."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"]["retry_attempts"] = "2"
        self.config["param_dict"]["retry_stop"] = ""

        test_objects = self.loader.parse_objects(self.config["param_dict"], self.config["vm_strs"])
        net = test_objects[-1]
        test_node = self.loader.parse_node_from_object(net, self.config["param_dict"].copy(),
                                                       param.re_str("normal..tutorial1"))

        DummyTestRun.asserted_tests = [
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
        ]
        to_run = self.runner.run_test_node(test_node)
        status = asyncio.get_event_loop().run_until_complete(asyncio.wait_for(to_run, None))
        # all runs succeed - status must be True
        self.assertTrue(status)
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        self.runner.job.result.tests.clear()

        DummyTestRun.asserted_tests = [
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "FAIL"},
        ]
        to_run = self.runner.run_test_node(test_node)
        status = asyncio.get_event_loop().run_until_complete(asyncio.wait_for(to_run, None))
        # last run fails - status must be False
        self.assertFalse(status, "Runner did not preserve last run fail status")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        self.runner.job.result.tests.clear()

        DummyTestRun.asserted_tests = [
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "FAIL"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
        ]
        to_run = self.runner.run_test_node(test_node)
        status = asyncio.get_event_loop().run_until_complete(asyncio.wait_for(to_run, None))
        # fourth run fails - status must be True
        self.assertTrue(status, "Runner did not preserve last pass status after previous fail")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        self.runner.job.result.tests.clear()


if __name__ == '__main__':
    unittest.main()
