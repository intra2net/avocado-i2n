#!/usr/bin/env python

import unittest
import unittest.mock as mock
import asyncio

from avocado import Test, skip
from avocado.core import exceptions
from avocado.core.suite import TestSuite, resolutions_to_runnables

import unittest_importer
from unittest_utils import DummyTestRun, DummyStateControl
from avocado_i2n import params_parser as param
from avocado_i2n.loader import CartesianLoader
from avocado_i2n.runner import CartesianRunner
from avocado_i2n.cartgraph import *


class CartesianWorkerTest(Test):

    def setUp(self):
        self.config = {}
        self.shared_pool = shared_pool = "/:/mnt/local/images/shared"
        self.config["param_dict"] = {"test_timeout": 100, "shared_pool": shared_pool}
        self.config["tests_str"] = "only normal\n"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n", "vm3": "only Ubuntu\n"}

        self.prefix = ""

        self.loader = CartesianLoader(config=self.config, extra_params={})

    def test_parse_flat_vm1(self):
        """Test for correctly parsed objects of different object variants from a restriction."""
        test_objects = TestGraph.parse_flat_objects("vm1", "vms")
        self.assertEqual(len(test_objects), 2)
        self.assertRegex(test_objects[1].params["name"], r"vms.vm1\.qemu_kvm_centos.*CentOS.*")
        self.assertEqual(test_objects[1].params["vms"], "vm1")
        self.assertEqual(test_objects[1].params["os_variant"], "el8")
        self.assertRegex(test_objects[0].params["name"], r"vms.vm1\.qemu_kvm_fedora.*Fedora.*")
        self.assertEqual(test_objects[0].params["vms"], "vm1")
        self.assertEqual(test_objects[0].params["os_variant"], "f33")

    def test_parse_flat_net1(self):
        """Test for correctly parsed objects of different object variants from a restriction."""
        test_objects = TestGraph.parse_flat_objects("net1", "nets")
        self.assertEqual(len(test_objects), 1)
        self.assertRegex(test_objects[0].params["name"], r"nets\.net1\.cluster1")
        self.assertEqual(test_objects[0].params["nets"], "net1")
        self.assertEqual(test_objects[0].params["cid"], "1")

    def test_params(self):
        """Test for correctly parsed and regenerated test worker parameters."""
        self.config["param_dict"]["slots"] = "1 2 3 4 5"
        test_workers = TestGraph.parse_workers(self.config["param_dict"])
        self.assertEqual(len(test_workers), 5)
        test_worker = test_workers[0]
        for key in test_worker.params.keys():
            self.assertEqual(test_worker.net.params[key], test_worker.params[key],
                            f"The values of key {key} {test_worker.net.params[key]}={test_worker.params[key]} must be the same")
            self.assertEqual(test_worker.params["nets_gateway"], "")
            self.assertEqual(test_worker.params["nets_host"], "c1")
            self.assertEqual(test_worker.params["nets_spawner"], "lxc")

    def test_params_slots(self):
        """Test environment setting and validation."""
        self.config["param_dict"]["slots"] = "1 remote.com/2 "
        test_workers = TestGraph.parse_workers(self.config["param_dict"])
        self.assertEqual(len(test_workers), 5)
        test_workers = [w for w in test_workers if "runtime_str" in w.params]
        self.assertEqual(len(test_workers), 3)
        self.assertEqual(test_workers[0].params["nets_gateway"], "")
        self.assertEqual(test_workers[0].params["nets_host"], "c1")
        self.assertEqual(test_workers[0].params["nets_spawner"], "lxc")
        self.assertEqual(test_workers[1].params["nets_gateway"], "remote.com")
        self.assertEqual(test_workers[1].params["nets_host"], "2")
        self.assertEqual(test_workers[1].params["nets_spawner"], "remote")
        self.assertEqual(test_workers[2].params["nets_gateway"], "")
        self.assertEqual(test_workers[2].params["nets_host"], "")
        self.assertEqual(test_workers[2].params["nets_spawner"], "process")
        self.assertEqual(TestWorker.run_slots, {"": {"": "process", "c1": "lxc"}, "remote.com": {"2": "remote"}})

    def test_sanity_in_graph(self):
        """Test generic usage and composition."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )
        self.assertEqual(len(graph.workers), 5)
        for i, worker_id in enumerate(graph.workers):
            self.assertEqual(f"net{i+1}", worker_id)
            worker = graph.workers[worker_id]
            self.assertEqual(worker_id, worker.id)
            self.assertIn("[worker]", str(worker))
            graph.new_workers(worker.net)
        self.assertEqual(len(graph.workers), 5)


class CartesianObjectTest(Test):

    def setUp(self):
        self.config = {}
        self.shared_pool = shared_pool = "/:/mnt/local/images/shared"
        self.config["param_dict"] = {"test_timeout": 100, "shared_pool": shared_pool}
        self.config["tests_str"] = "only normal\n"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n", "vm3": "only Ubuntu\n"}

        self.prefix = ""

        self.loader = CartesianLoader(config=self.config, extra_params={})

    def test_parse_composite_objects_vm1(self):
        """Test for correctly parsed vm objects from a vm string restriction."""
        test_objects = TestGraph.parse_composite_objects("vm1", "vms", "")
        self.assertEqual(len(test_objects), 2)
        self.assertRegex(test_objects[1].params["name"], r"vm1\.qemu_kvm_centos.*CentOS.*")
        self.assertEqual(test_objects[1].params["vms"], "vm1")
        self.assertEqual(test_objects[1].params["main_vm"], "vm1")
        self.assertEqual(test_objects[1].params["os_variant"], "el8")
        self.assertRegex(test_objects[0].params["name"], r"vm1\.qemu_kvm_fedora.*Fedora.*")
        self.assertEqual(test_objects[0].params["vms"], "vm1")
        self.assertEqual(test_objects[0].params["main_vm"], "vm1")
        self.assertEqual(test_objects[0].params["os_variant"], "f33")
        self.assertNotIn("only", test_objects[0].params)

    def test_parse_composite_objects_net1(self):
        """Test for a correctly parsed net object from joined vm string restrictions."""
        test_objects = TestGraph.parse_composite_objects("net1", "nets", "", self.config["vm_strs"])
        self.assertEqual(len(test_objects), 1)
        test_object = test_objects[0]
        self.assertRegex(test_object.params["name"], r"vm1\.qemu_kvm_centos.*CentOS.*vm2\.qemu_kvm_windows_10.*Win10.*.vm3.qemu_kvm_ubuntu.*Ubuntu.*")
        self.assertEqual(test_object.params["vms_vm1"], "vm1")
        self.assertEqual(test_object.params["vms_vm2"], "vm2")
        self.assertEqual(test_object.params["vms_vm3"], "vm3")
        self.assertEqual(test_object.params["main_vm"], "vm1")
        self.assertEqual(test_object.params["main_vm_vm2"], "vm2")
        self.assertEqual(test_object.params["main_vm_vm3"], "vm3")
        self.assertEqual(test_object.params["os_variant_vm1"], "el8")
        self.assertEqual(test_object.params["os_variant_vm2"], "win10")
        self.assertEqual(test_object.params["os_variant_vm3"], "ubuntutrusty")
        self.assertNotIn("only", test_object.params)
        self.assertNotIn("only_vm1", test_object.params)
        self.assertNotIn("only_vm2", test_object.params)
        self.assertNotIn("only_vm3", test_object.params)

    def test_parse_composite_objects_net1_unrestricted(self):
        """Test for a correctly parsed net object from empty joined vm string restrictions."""
        test_objects = TestGraph.parse_composite_objects("net1", "nets", "")
        # TODO: bug in the Cartesian parser, they must be 6!
        self.assertEqual(len(test_objects), 4)
        for i, test_object in enumerate(test_objects):
            self.assertEqual(test_object.dict_index, i)

    def test_parse_suffix_objects_vms(self):
        """Test for correctly parsed vm objects of all suffices."""
        self.config["vm_strs"] = {"vm1": "", "vm2": "", "vm3": ""}
        test_objects = TestGraph.parse_suffix_objects("vms", self.config["vm_strs"], self.config["param_dict"])
        vms = [o for o in test_objects if o.key == "vms"]
        self.assertEqual(len(test_objects), len(vms))
        self.assertEqual(len(vms), 6)
        vms_vm1 = [vm for vm in vms if vm.long_suffix == "vm1"]
        self.assertEqual(len(vms_vm1), 2)
        self.assertEqual(vms_vm1[0].suffix, vms_vm1[1].suffix)
        self.assertEqual(vms_vm1[0].long_suffix, vms_vm1[1].long_suffix)
        self.assertNotEqual(vms_vm1[0].id, vms_vm1[1].id)
        self.assertEqual(len([vm for vm in vms if vm.long_suffix == "vm2"]), 2)
        self.assertEqual(len([vm for vm in vms if vm.long_suffix == "vm3"]), 2)

    def test_parse_suffix_objects_nets_flat(self):
        """Test for correctly parsed net objects of all suffices."""
        self.config["net_strs"] = {"net1": "", "net2": ""}
        test_objects = TestGraph.parse_suffix_objects("nets", self.config["net_strs"], self.config["param_dict"], flat=True)
        nets = [o for o in test_objects if o.key == "nets"]
        self.assertEqual(len(test_objects), len(nets))
        self.assertEqual(len(nets), 2)
        self.assertEqual(nets[0].suffix, "net1")
        self.assertEqual(nets[0].long_suffix, "net1")
        self.assertEqual(nets[1].suffix, "net2")
        self.assertEqual(nets[1].long_suffix, "net2")

    def test_parse_object_from_vms(self):
        """Test for a correctly parsed net composite object from already parsed vm component objects."""
        vms = []
        for vm_name, vm_restriction in self.config["vm_strs"].items():
            vms += TestGraph.parse_composite_objects(vm_name, "vms", vm_restriction)
        net = TestGraph.parse_object_from_objects("net1", "nets", vms)
        self.assertEqual(net.components, vms)
        for vm in vms:
            self.assertEqual(vm.composites, [net])
            # besides object composition we should expect the joined component variants
            self.assertIn(vm.component_form, net.params["name"])
            # each joined component variant must be traceable back to the component object id
            self.assertEqual(vm.id, net.params[f"object_id_{vm.suffix}"])
            # each joined component variant must inform about supported vms via workaround restrictions
            self.assertEqual(vm.component_form, net.params[f"object_only_{vm.suffix}"])

    def test_parse_components_for_vm(self):
        """Test for correctly parsed image components with unflattened vm."""
        flat_vm = TestGraph.parse_flat_objects("vm1", "vms")[0]
        test_objects = TestGraph.parse_components_for_object(flat_vm, "vms", unflatten=True)
        vms = [o for o in test_objects if o.key == "vms"]
        images = [o for o in test_objects if o.key == "images"]
        self.assertEqual(len(test_objects), len(vms) + len(images))
        self.assertEqual(len(vms), 2)
        vms_vm1 = [vm for vm in vms if vm.long_suffix == "vm1"]
        self.assertEqual(len(vms_vm1), 2)
        self.assertEqual(vms_vm1[0].suffix, vms_vm1[1].suffix)
        self.assertEqual(vms_vm1[0].long_suffix, vms_vm1[1].long_suffix)
        self.assertNotEqual(vms_vm1[0].id, vms_vm1[1].id)
        self.assertEqual(len([image for image in images if image.long_suffix == "image1_vm1"]), 1)

    def test_parse_components_for_net(self):
        """Test for correctly parsed vm components with unflattened net."""
        flat_net = TestGraph.parse_flat_objects("net1", "nets")[0]
        test_objects = TestGraph.parse_components_for_object(flat_net, "nets", unflatten=True)
        nets = [o for o in test_objects if o.key == "nets"]
        self.assertEqual(len(nets), 8)
        # TODO: typically we should test for some of this in the net1 object variants cases above but due to limitation of the Cartesian parser and lack of
        # such functionality, the multi-variant nets are generated at this stage and therefore tested here
        def assertVariant(test_object, name, vm1_os, vm2_os, vm3_os):
            self.assertEqual(test_object.suffix, "net1")
            self.assertEqual(test_object.long_suffix, "net1")
            self.assertRegex(test_object.params["name"], name)
            self.assertEqual(test_object.params["os_variant_vm1"], vm1_os)
            self.assertEqual(test_object.params["os_variant_vm2"], vm2_os)
            self.assertEqual(test_object.params["os_variant_vm3"], vm3_os)
        assertVariant(nets[0], r"vm1\.qemu_kvm_fedora.*Fedora.*vm2\.qemu_kvm_windows_7.*Win7.*.vm3.qemu_kvm_ubuntu.*Ubuntu.*", "f33", "win7", "ubuntutrusty")
        assertVariant(nets[1], r"vm1\.qemu_kvm_fedora.*Fedora.*vm2\.qemu_kvm_windows_7.*Win7.*.vm3.qemu_kvm_kali.*Kali.*", "f33", "win7", "kl")
        assertVariant(nets[2], r"vm1\.qemu_kvm_fedora.*Fedora.*vm2\.qemu_kvm_windows_10.*Win10.*.vm3.qemu_kvm_ubuntu.*Ubuntu.*", "f33", "win10", "ubuntutrusty")
        assertVariant(nets[3], r"vm1\.qemu_kvm_fedora.*Fedora.*vm2\.qemu_kvm_windows_10.*Win10.*.vm3.qemu_kvm_kali.*Kali.*", "f33", "win10", "kl")
        assertVariant(nets[4], r"vm1\.qemu_kvm_centos.*CentOS.*vm2\.qemu_kvm_windows_7.*Win7.*.vm3.qemu_kvm_ubuntu.*Ubuntu.*", "el8", "win7", "ubuntutrusty")
        assertVariant(nets[5], r"vm1\.qemu_kvm_centos.*CentOS.*vm2\.qemu_kvm_windows_7.*Win7.*.vm3.qemu_kvm_kali.*Kali.*", "el8", "win7", "kl")
        assertVariant(nets[6], r"vm1\.qemu_kvm_centos.*CentOS.*vm2\.qemu_kvm_windows_10.*Win10.*.vm3.qemu_kvm_ubuntu.*Ubuntu.*", "el8", "win10", "ubuntutrusty")
        assertVariant(nets[7], r"vm1\.qemu_kvm_centos.*CentOS.*vm2\.qemu_kvm_windows_10.*Win10.*.vm3.qemu_kvm_kali.*Kali.*", "el8", "win10", "kl")

    def test_params(self):
        """Test for correctly parsed and regenerated test object parameters."""
        test_objects = TestGraph.parse_composite_objects("net1", "nets", "", self.config["vm_strs"], params=self.config["param_dict"])
        self.assertEqual(len(test_objects), 1)
        test_object = test_objects[0]
        regenerated_params = test_object.object_typed_params(test_object.config.get_params())
        self.assertEqual(len(regenerated_params.keys()), len(test_object.params.keys()),
                        "The parameters of a test object must be the same as its only parser dictionary")
        for key in regenerated_params.keys():
            self.assertEqual(regenerated_params[key], test_object.params[key],
                            "The values of key %s %s=%s must be the same" % (key, regenerated_params[key], test_object.params[key]))
        # the test object attributes are fully separated from its parameters
        self.assertNotIn("object_suffix", test_object.params)
        self.assertNotIn("object_type", test_object.params)
        self.assertNotIn("object_id", test_object.params)

    def test_sanity_in_graph(self):
        """Test generic usage and composition of test objects within a graph."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )

        test_objects = graph.get_objects_by(param_val="vm1", subset=graph.get_objects_by(param_val="net1"))
        for test_object in test_objects:
            self.assertIn(test_object.long_suffix, graph.suffixes.keys())
            self.assertIn(test_object.long_suffix, ["vm1", "net1"])
            object_num = len(graph.suffixes)
            graph.new_objects(test_object)
            self.assertEqual(len(graph.suffixes), object_num)

    def test_overwrite_in_graph(self):
        """Test for correct overwriting of preselected configuration."""
        self.config["param_dict"]["nets"] = "net1"
        self.config["tests_str"] += "only tutorial1\n"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )
        default_object_param = graph.get_node_by(param_val="tutorial1").params["images"]
        custom_object_param = default_object_param + "00"
        custom_node_param = "remote:/some/location"

        self.config["param_dict"]["images_vm1"] = custom_object_param
        self.config["param_dict"]["shared_pool"] = custom_node_param
        self.config["param_dict"]["new_key"] = "123"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )

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

    def test_overwrite_scope_in_graph(self):
        """Test the scope of application of overwriting preselected configuration."""
        self.config["param_dict"]["nets"] = "net1"
        self.config["tests_str"] += "only tutorial3\n"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )
        default_object_param = graph.get_node_by(param_val="tutorial3").params["images"]
        custom_object_param1 = default_object_param + "01"
        custom_object_param2 = default_object_param + "02"

        self.config["param_dict"]["images"] = custom_object_param1
        self.config["param_dict"]["images_vm1"] = custom_object_param2
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )

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


class CartesianNodeTest(Test):

    def setUp(self):
        self.config = {}
        self.shared_pool = shared_pool = "/:/mnt/local/images/shared"
        self.config["param_dict"] = {"test_timeout": 100, "shared_pool": shared_pool}
        self.config["tests_str"] = "only normal\n"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n", "vm3": "only Ubuntu\n"}

        self.prefix = ""

        self.loader = CartesianLoader(config=self.config, extra_params={})

    def test_prefix_tree_contains(self):
        """Test that a prefix tree contains the right variants."""
        tree = PrefixTree()
        node1 = TestNode("1", None)
        node2 = TestNode("2", None)
        node3 = TestNode("3", None)
        node1._params_cache = {"name": "aaa.bbb.ccc"}
        node2._params_cache = {"name": "aaa.bbb.fff"}
        node3._params_cache = {"name": "eee.bbb.fff"}
        tree.insert(node1)
        tree.insert(node2)
        tree.insert(node3)

        self.assertTrue("aaa" in tree)
        self.assertTrue("aaa.bbb" in tree)
        self.assertTrue("bbb.ccc" in tree)
        self.assertTrue("bbb" in tree)
        self.assertTrue("bbb.fff" in tree)
        self.assertTrue("eee.bbb" in tree)
        self.assertTrue("ddd" not in tree)
        self.assertTrue("ccc.ddd" not in tree)
        self.assertTrue("aaa.ddd" not in tree)
        self.assertTrue("aaa.fff" not in tree)

    def test_prefix_tree_insert(self):
        """Test the right variants are produced when inserting a test node into the prefix tree."""
        tree = PrefixTree()
        node1 = TestNode("1", None)
        node2 = TestNode("2", None)
        node3 = TestNode("3", None)
        node1._params_cache = {"name": "aaa.bbb.ccc"}
        node2._params_cache = {"name": "aaa.bbb.fff"}
        node3._params_cache = {"name": "eee.bbb.fff"}
        tree.insert(node1)
        tree.insert(node2)
        tree.insert(node3)

        self.assertEqual(tree.variant_nodes.keys(), set(["aaa", "bbb", "ccc", "eee", "fff"]))
        self.assertEqual(len(tree.variant_nodes["aaa"]), 1)
        self.assertIn("bbb", tree.variant_nodes["aaa"][0].children)
        self.assertEqual(len(tree.variant_nodes["bbb"]), 2)
        self.assertEqual(len(tree.variant_nodes["bbb"][0].children), 2)
        self.assertIn("ccc", tree.variant_nodes["bbb"][0].children)
        self.assertIn("fff", tree.variant_nodes["bbb"][0].children)
        self.assertEqual(len(tree.variant_nodes["bbb"][1].children), 1)
        self.assertIn("fff", tree.variant_nodes["bbb"][1].children)
        self.assertNotIn(tree.variant_nodes["bbb"][1].children["fff"], tree.variant_nodes["bbb"][0].children)

    def test_prefix_tree_get(self):
        """Test the right test nodes are retrieved when looking up a composite variant."""
        tree = PrefixTree()
        node1 = TestNode("1", None)
        node2 = TestNode("2", None)
        node3 = TestNode("3", None)
        node1._params_cache = {"name": "aaa.bbb.ccc"}
        node2._params_cache = {"name": "aaa.bbb.fff"}
        node3._params_cache = {"name": "eee.bbb.fff"}
        tree.insert(node1)
        tree.insert(node2)
        tree.insert(node3)

        self.assertEqual(len(tree.get("aaa")), 2)
        self.assertIn(node1, tree.get("aaa"))
        self.assertIn(node2, tree.get("aaa"))
        self.assertEqual(len(tree.get("aaa.bbb")), 2)
        self.assertIn(node1, tree.get("aaa.bbb"))
        self.assertIn(node2, tree.get("aaa.bbb"))
        self.assertEqual(len(tree.get("bbb.ccc")), 1)
        self.assertIn(node1, tree.get("bbb.ccc"))

        self.assertEqual(len(tree.get("bbb")), 3)
        self.assertEqual(len(tree.get("bbb.fff")), 2)
        self.assertIn(node2, tree.get("bbb.fff"))
        self.assertIn(node3, tree.get("bbb.fff"))
        self.assertEqual(len(tree.get("eee.bbb")), 1)
        self.assertIn(node3, tree.get("bbb.fff"))
        self.assertEqual(len(tree.get("ddd")), 0)

        self.assertEqual(len(tree.get("ccc.ddd")), 0)
        self.assertEqual(len(tree.get("aaa.ddd")), 0)
        self.assertEqual(len(tree.get("aaa.fff")), 0)

    def test_parse_node_from_object(self):
        """Test for a correctly parsed node from an already parsed net object."""
        flat_net = TestGraph.parse_net_from_object_strs("net1", self.config["vm_strs"])
        test_objects = TestGraph.parse_components_for_object(flat_net, "nets", params=self.config["param_dict"], unflatten=True)
        nets = [o for o in test_objects if o.key == "nets"]
        self.assertEqual(len(nets), 1)
        net = nets[0]
        node = TestGraph.parse_node_from_object(net, "all..tutorial_get..explicit_noop", params=self.config["param_dict"])
        self.assertEqual(node.objects[0], net)
        self.assertIn(net.params["name"], node.params["name"])
        self.assertEqual(node.params["nets"], net.params["nets"])
        self.assertEqual(node.params["vms_vm1"], net.params["vms_vm1"])
        self.assertEqual(node.params["vms_vm2"], net.params["vms_vm2"])
        self.assertEqual(node.params["vms_vm3"], net.params["vms_vm3"])
        self.assertEqual(node.params["main_vm"], net.params["main_vm"])
        self.assertEqual(node.params["main_vm_vm2"], net.params["main_vm_vm2"])
        self.assertEqual(node.params["main_vm_vm3"], net.params["main_vm_vm3"])
        self.assertEqual(node.params["os_variant_vm1"], net.params["os_variant_vm1"])
        self.assertEqual(node.params["os_variant_vm2"], net.params["os_variant_vm2"])
        self.assertEqual(node.params["os_variant_vm3"], net.params["os_variant_vm3"])

    def test_parse_node_from_object_invalid_object_type(self):
        """Test correctly parsed node is not possible from an already parsed vm object."""
        flat_net = TestGraph.parse_net_from_object_strs("net1", {"vm1": self.config["vm_strs"]["vm1"]})
        test_objects = TestGraph.parse_components_for_object(flat_net, "nets", params=self.config["param_dict"], unflatten=True)
        vms = [o for o in test_objects if o.key == "vms"]
        self.assertEqual(len(vms), 1)
        vm = vms[0]
        with self.assertRaises(ValueError):
            TestGraph.parse_node_from_object(vm, params=self.config["param_dict"])

    def test_parse_node_from_object_invalid_object_mix(self):
        """Test correctly parsed node is not possible from incompatible vm variants."""
        flat_net = TestGraph.parse_net_from_object_strs("net1", {"vm1": self.config["vm_strs"]["vm1"], "vm2": "only Win7\n"})
        test_objects = TestGraph.parse_components_for_object(flat_net, "nets", params=self.config["param_dict"], unflatten=True)
        nets = [o for o in test_objects if o.key == "nets"]
        self.assertEqual(len(nets), 1)
        net = nets[0]
        with self.assertRaises(param.EmptyCartesianProduct):
            TestGraph.parse_node_from_object(net, "all..tutorial3.remote.object.control.decorator.util", params=self.config["param_dict"])

    def test_parse_composite_nodes(self):
        """Test for correctly parsed composite nodes from graph retrievable test objects."""
        self.config["tests_str"] += "only tutorial1,tutorial2\n"

        flat_objects = TestGraph.parse_flat_objects("net1", "nets")
        self.assertEqual(len(flat_objects), 1)
        flat_object = flat_objects[0]

        flat_object.params["vms"] = "vm1"
        test_objects = TestGraph.parse_components_for_object(flat_object, "nets", unflatten=True)
        nets = [o for o in test_objects if o.key == "nets"]
        self.assertEqual(len(nets), 2)
        graph = TestGraph()
        graph.objects = test_objects

        nodes = graph.parse_composite_nodes(self.config["tests_str"], flat_object, params=self.config["param_dict"])
        self.assertEqual(len(nodes), 4)
        self.assertIn(nodes[0].objects[0], nets)
        self.assertEqual(nodes[0].params["nets"], "net1")
        self.assertEqual(len(nodes[0].objects[0].components), 1)
        self.assertEqual(len(nodes[0].objects[0].components[0].components), 1)
        self.assertIn(nodes[1].objects[0], nets)
        self.assertEqual(nodes[1].params["nets"], "net1")
        self.assertIn(nodes[2].objects[0], nets)
        self.assertEqual(nodes[2].params["nets"], "net1")
        self.assertIn(nodes[3].objects[0], nets)
        self.assertEqual(nodes[3].params["nets"], "net1")

    def test_parse_composite_nodes_compatibility_complete(self):
        """Test for correctly parsed test nodes from compatible graph retrievable test objects."""
        self.config["tests_str"] = "only all\nonly tutorial3\n"

        flat_objects = TestGraph.parse_flat_objects("net1", "nets")
        self.assertEqual(len(flat_objects), 1)
        flat_object = flat_objects[0]

        flat_object.params["vms"] = "vm1 vm2"
        test_objects = TestGraph.parse_components_for_object(flat_object, "nets", unflatten=True)
        nets = [o for o in test_objects if o.key == "nets"]
        self.assertEqual(len(nets), 4)
        graph = TestGraph()
        graph.objects = test_objects

        self.assertEqual(nets, [o for o in test_objects if o.key == "nets" if "vm1." in o.params["name"] and "vm2." in o.params["name"]])
        nets = list(reversed([o for o in test_objects if o.key == "nets"]))
        self.assertRegex(nets[0].params["name"], "qemu_kvm_centos.+qemu_kvm_windows_10")
        self.assertRegex(nets[1].params["name"], "qemu_kvm_centos.+qemu_kvm_windows_7")
        self.assertRegex(nets[2].params["name"], "qemu_kvm_fedora.+qemu_kvm_windows_10")
        self.assertRegex(nets[3].params["name"], "qemu_kvm_fedora.+qemu_kvm_windows_7")
        nodes = graph.parse_composite_nodes(self.config["tests_str"], flat_object, params=self.config["param_dict"])
        self.assertEqual(len(nodes), 20)
        for i in range(0, 4):
            self.assertIn("no_remote", nodes[i].params["name"])
            self.assertNotIn("only_vm1", nodes[i].params)
            self.assertNotIn("only_vm2", nodes[i].params)
            self.assertIn(nets[i].params["name"], nodes[i].params["name"])
        for i in range(4, 20):
            self.assertIn("remote", nodes[i].params["name"])
            self.assertEqual(nodes[i].params["only_vm1"], "qemu_kvm_centos")
            self.assertEqual(nodes[i].params["only_vm2"], "qemu_kvm_windows_10")
            self.assertIn(nets[0].params["name"], nodes[i].params["name"])

    def test_parse_composite_nodes_compatibility_separate(self):
        """Test that no restriction leaks across separately restricted variants."""
        self.config["tests_str"] = "only all\nonly tutorial3.remote.object.control.decorator.util,tutorial_gui.client_noop\n"

        flat_objects = TestGraph.parse_flat_objects("net1", "nets")
        self.assertEqual(len(flat_objects), 1)
        flat_object = flat_objects[0]

        flat_object.params["vms"] = "vm1 vm2"
        test_objects = TestGraph.parse_components_for_object(flat_object, "nets", unflatten=True)
        nets = [o for o in test_objects if o.key == "nets"]
        self.assertEqual(len(nets), 4)
        graph = TestGraph()
        graph.objects = test_objects

        self.assertEqual(nets, [o for o in test_objects if o.key == "nets" if "vm1." in o.params["name"] and "vm2." in o.params["name"]])
        nets = list(reversed([o for o in test_objects if o.key == "nets"]))
        self.assertRegex(nets[0].params["name"], "qemu_kvm_centos.+qemu_kvm_windows_10")
        self.assertRegex(nets[1].params["name"], "qemu_kvm_centos.+qemu_kvm_windows_7")
        self.assertRegex(nets[2].params["name"], "qemu_kvm_fedora.+qemu_kvm_windows_10")
        self.assertRegex(nets[3].params["name"], "qemu_kvm_fedora.+qemu_kvm_windows_7")
        nodes = graph.parse_composite_nodes(self.config["tests_str"], flat_object, params=self.config["param_dict"])
        self.assertEqual(len(nodes), 5)
        self.assertIn("remote", nodes[0].params["name"])
        self.assertEqual(nodes[0].params["only_vm1"], "qemu_kvm_centos")
        self.assertEqual(nodes[0].params["only_vm2"], "qemu_kvm_windows_10")
        self.assertIn(nets[0].params["name"], nodes[0].params["name"])
        for i in range(1, 5):
            self.assertIn("client_noop", nodes[i].params["name"])
            self.assertNotIn("only_vm1", nodes[i].params)
            self.assertNotIn("only_vm2", nodes[i].params)
            self.assertIn(nets[i-1].params["name"], nodes[i].params["name"])

    def test_is_unrolled(self):
        """Test that a flat test node is considered unrolled under the right circumstances."""
        graph = TestGraph()
        flat_objects = TestGraph.parse_flat_objects("net1", "nets")
        self.assertEqual(len(flat_objects), 1)
        flat_object = flat_objects[0]
        flat_nodes = [n for n in TestGraph.parse_flat_nodes("normal..tutorial1")]
        self.assertEqual(len(flat_nodes), 1)
        flat_node = flat_nodes[0]
        self.assertFalse(flat_node.is_unrolled(TestWorker(flat_object)))

        composite_nodes = graph.parse_composite_nodes("normal..tutorial1", flat_object)
        self.assertEqual(len(composite_nodes), 2)
        for node in composite_nodes:
            flat_node.cleanup_nodes.append(node)
        self.assertTrue(flat_node.is_unrolled(TestWorker(flat_object)))
        more_flat_objects = TestGraph.parse_flat_objects("net2", "nets")
        self.assertEqual(len(more_flat_objects), 1)
        self.assertFalse(flat_node.is_unrolled(TestWorker(more_flat_objects[0])))

        more_composite_nodes = graph.parse_composite_nodes("normal..tutorial2", flat_object)
        self.assertGreater(len(more_composite_nodes), 0)
        flat_node.cleanup_nodes = [more_composite_nodes[0]]
        self.assertFalse(flat_node.is_unrolled(TestWorker(flat_object)))

        with self.assertRaises(RuntimeError):
            composite_nodes[0].is_unrolled(TestWorker(flat_object))

    def test_params(self):
        """Test for correctly parsed test node parameters."""
        flat_nets = TestGraph.parse_flat_objects("net1", "nets", params={"only_vm1": "CentOS"})
        self.assertEqual(len(flat_nets), 1)
        flat_net = flat_nets[0]
        graph = TestGraph()
        nodes = graph.parse_composite_nodes("normal..tutorial1", flat_net)
        self.assertEqual(len(nodes), 1)
        test_node = nodes[0]

        dict_generator = test_node.recipe.get_parser().get_dicts()
        dict1 = dict_generator.__next__()
        # parser of test objects must contain exactly one dictionary
        self.assertRaises(StopIteration, dict_generator.__next__)
        self.assertEqual(len(dict1.keys()), len(test_node.params.keys()), "The parameters of a test node must be the same as its only parser dictionary")
        for key in dict1.keys():
            self.assertEqual(dict1[key], test_node.params[key], "The values of key %s %s=%s must be the same" % (key, dict1[key], test_node.params[key]))
        # all VT attributes must be initialized
        self.assertEqual(test_node.uri, test_node.params["name"])

    def test_sanity_in_graph(self):
        """Test generic usage and composition."""
        self.config["tests_str"] += "only tutorial1\n"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )

        test_node = graph.get_node_by(param_val="tutorial1", subset=graph.get_nodes_by(param_val="net1"))
        self.assertIn("1-vm1", test_node.long_prefix)

    def test_overwrite_in_graph(self):
        """Test for correct overwriting of preselected configuration."""
        self.config["param_dict"]["nets"] = "net1"
        self.config["tests_str"] += "only tutorial1\n"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )
        default_object_param = graph.get_node_by(param_val="tutorial1").params["images"]
        default_node_param = graph.get_node_by(param_val="tutorial1").params["shared_pool"]
        custom_object_param = default_object_param + "00"
        custom_node_param = "remote:/some/location"

        self.config["param_dict"]["images_vm1"] = custom_object_param
        self.config["param_dict"]["shared_pool"] = custom_node_param
        self.config["param_dict"]["new_key"] = "123"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )

        test_node = graph.get_node_by(param_val="tutorial1")
        self.assertNotEqual(test_node.params["shared_pool"], default_node_param,
                            "The default %s of %s wasn't overwritten" % (default_node_param, test_node.prefix))
        self.assertEqual(test_node.params["shared_pool"], custom_node_param,
                         "The new %s of %s must be %s" % (default_node_param, test_node.prefix, custom_node_param))
        self.assertNotEqual(test_node.params["images_vm1"], default_object_param,
                            "The default %s of %s wasn't overwritten" % (default_object_param, test_node.prefix))
        self.assertEqual(test_node.params["images_vm1"], custom_object_param,
                         "The new %s of %s must be %s" % (default_object_param, test_node.prefix, custom_object_param))
        self.assertEqual(test_node.params["new_key"], "123",
                         "A new parameter=%s of %s must be 123" % (test_node.params["new_key"], test_node.prefix))

    def test_overwrite_scope_in_graph(self):
        """Test the scope of application of overwriting preselected configuration."""
        self.config["param_dict"]["nets"] = "net1"
        self.config["tests_str"] += "only tutorial3\n"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )
        default_object_param = graph.get_node_by(param_val="tutorial3").params["images"]
        custom_object_param1 = default_object_param + "01"
        custom_object_param2 = default_object_param + "02"

        self.config["param_dict"]["images"] = custom_object_param1
        self.config["param_dict"]["images_vm1"] = custom_object_param2
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )

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

    def test_validation(self):
        """Test graph (and component) retrieval and validation methods."""
        flat_nets = TestGraph.parse_flat_objects("net1", "nets", params={"only_vm1": "CentOS"})
        self.assertEqual(len(flat_nets), 1)
        flat_net = flat_nets[0]
        graph = TestGraph()
        nodes = graph.parse_composite_nodes("normal..tutorial1", flat_net)
        self.assertEqual(len(nodes), 1)
        test_node = nodes[0]

        self.assertEqual(len([o for o in test_node.objects if o.suffix == "vm1"]), 1)
        test_object = [o for o in test_node.objects if o.suffix == "vm1"][0]
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
        nodes = graph.parse_composite_nodes("normal..tutorial1", flat_net)
        self.assertEqual(len(nodes), 1)
        test_node = nodes[0]
        test_node.setup_nodes.append(test_node)
        with self.assertRaisesRegex(ValueError, r"^Detected reflexive dependency of"):
            test_node.validate()

    @mock.patch('avocado_i2n.cartgraph.node.remote.wait_for_login', mock.MagicMock())
    @mock.patch('avocado_i2n.cartgraph.node.door', DummyStateControl)
    def test_default_run_decision(self):
        """Test expectations on the default decision policy of whether to run or skip a test node."""
        self.config["tests_str"] += "only tutorial1\n"
        params = {"slots": "1 2", "nets": "net1 net2"}
        graph = TestGraph.parse_object_trees(
            restriction=self.config["tests_str"],
            object_strs=self.config["vm_strs"],
            params=params,
        )

        worker1 = graph.workers["net1"]
        worker2 = graph.workers["net2"]

        test_node1 = graph.get_node_by(param_val="tutorial1.+net1")
        test_node2 = graph.get_node_by(param_val="tutorial1.+net2")
        # should run a leaf test node visited for the first time
        self.assertTrue(test_node1.default_run_decision(worker1))
        self.assertTrue(test_node2.default_run_decision(worker2))
        # should not run a leaf test node meant for other worker
        self.assertFalse(test_node1.default_run_decision(worker2))
        self.assertFalse(test_node2.default_run_decision(worker1))
        # should not run already visited leaf test node
        test_node1.workers.add(worker1)
        test_node1.results += [{"status": "PASS"}]
        self.assertFalse(test_node1.default_run_decision(worker1))
        # should run leaf if more reruns are needed
        test_node1.should_rerun = lambda _: True
        self.assertTrue(test_node1.default_run_decision(worker1))

        test_node1 = graph.get_node_by(param_val="install.+net1")
        test_node2 = graph.get_node_by(param_val="install.+net2")
        # should not run an internal test node meant for other worker
        self.assertFalse(test_node1.default_run_decision(worker2))
        self.assertFalse(test_node2.default_run_decision(worker1))
        # should run an internal test node without available setup
        DummyStateControl.asserted_states["check"] = {"install": {self.shared_pool: False}}
        test_node1.params["nets_host"], test_node1.params["nets_gateway"] = "1", ""
        test_node1.add_location(self.shared_pool)
        self.assertTrue(test_node1.default_run_decision(worker1))
        # should not run an internal test node with available setup
        DummyStateControl.asserted_states["check"]["install"][self.shared_pool] = True
        self.assertFalse(test_node1.default_run_decision(worker1))
        # should not run already visited internal test node by the same worker
        test_node1.workers.add(worker1)
        test_node1.results += [{"status": "PASS"}]
        self.assertFalse(test_node1.default_run_decision(worker1))
        # should not run an internal test node if needed reruns and setup from past runs
        DummyStateControl.asserted_states["check"]["install"][self.shared_pool] = True
        test_node1.should_rerun = lambda _: True
        test_node1.workers = set()
        test_node1.results = []
        self.assertFalse(test_node1.default_run_decision(worker1))
        # should run an internal test node if needed reruns and setup from current runs
        test_node1.should_rerun = lambda _: True
        test_node1.workers = set()
        test_node1.results = [{"status": "PASS"}]
        self.assertTrue(test_node1.default_run_decision(worker1))

    @skip("Needs node bridging")
    @mock.patch('avocado_i2n.cartgraph.node.remote.wait_for_login', mock.MagicMock())
    def test_default_clean_decision(self):
        """Test expectations on the default decision policy of whether to clean or not a test node."""
        self.config["tests_str"] = "only leaves\n"
        self.config["tests_str"] += "only tutorial_get\n"
        params = {"slots": "1 2", "nets": "net1 net2"}
        graph = TestGraph.parse_object_trees(
            restriction=self.config["tests_str"],
            object_strs=self.config["vm_strs"],
            params=params,
        )

        worker1 = graph.workers["net1"]
        worker2 = graph.workers["net2"]

        # should clean a test node that is not reversible
        test_node1 = graph.get_node_by(param_val="explicit_clicked.+net1")
        test_node2 = graph.get_node_by(param_val="explicit_clicked.+net2")
        self.assertTrue(test_node1.default_clean_decision(worker1))
        self.assertTrue(test_node2.default_clean_decision(worker2))
        # should not clean an internal test node meant for other worker
        self.assertFalse(test_node1.default_clean_decision(worker2))
        self.assertFalse(test_node2.default_clean_decision(worker1))

        # should not clean a reversible test node that is not globally cleanup ready
        test_node1 = graph.get_node_by(param_val="explicit_noop.+net1")
        test_node2 = graph.get_node_by(param_val="explicit_noop.+net2")
        TestWorker.run_slots = {"": {"1": "lxc", "2": "lxc"}}
        self.assertFalse(test_node1.default_clean_decision(worker1))
        self.assertFalse(test_node2.default_clean_decision(worker1))
        test_node1.workers.add(worker1)
        self.assertFalse(test_node1.default_clean_decision(worker1))
        self.assertFalse(test_node2.default_clean_decision(worker2))
        test_node1.workers.add(worker2)
        self.assertFalse(test_node1.default_clean_decision(worker1))
        self.assertFalse(test_node2.default_clean_decision(worker2))
        # should clean a reversible test node that is globally cleanup ready
        test_node2.workers.add(worker2)
        self.assertTrue(test_node1.default_clean_decision(worker1))
        self.assertTrue(test_node2.default_clean_decision(worker2))
        # should not clean an internal test node meant for other worker despite the above
        self.assertFalse(test_node1.default_clean_decision(worker2))
        self.assertFalse(test_node2.default_clean_decision(worker1))

    def test_cleanup_priority(self):
        """Test that cleanup priority prioritizes workers and then secondary criteria."""
        flat_nets = TestGraph.parse_flat_objects("net1", "nets")
        self.assertEqual(len(flat_nets), 1)
        flat_net = flat_nets[0]
        full_nets = TestGraph.parse_composite_objects("net1", "nets", "", self.config["vm_strs"])
        self.assertEqual(len(full_nets), 1)
        net = full_nets[0]

        node1 = TestGraph.parse_node_from_object(net, "normal..tutorial1", prefix="1")
        node2 = TestGraph.parse_node_from_object(net, "normal..tutorial1", prefix="2")
        worker = TestWorker(flat_net)

        # must return -1 (choose lesser node1) since node1 < node2 at prefix
        self.assertEqual(TestNode.cleanup_priority(node1, node2), -1)
        node1.workers = [worker]
        # lesser node2 has 1 worker less
        self.assertEqual(TestNode.cleanup_priority(node1, node2), 1)
        # resort to prefix again
        node2.workers = [worker]
        self.assertEqual(TestNode.cleanup_priority(node1, node2), -1)
        # lesser node 2 has fewer visited children
        child_node = TestGraph.parse_node_from_object(net, "normal..tutorial1")
        node1.visited_cleanup_nodes[child_node] = set([worker])
        self.assertEqual(TestNode.cleanup_priority(node1, node2), 1)

    def test_pick_and_visit_child(self):
        """Test that children are picked according to previous visits."""
        flat_nets = TestGraph.parse_flat_objects("net1", "nets")
        self.assertEqual(len(flat_nets), 1)
        flat_net = flat_nets[0]
        full_nets = TestGraph.parse_composite_objects("net1", "nets", "", self.config["vm_strs"])
        self.assertEqual(len(full_nets), 1)
        net = full_nets[0]

        node = TestGraph.parse_node_from_object(net, "normal..tutorial1")
        child_node1 = TestGraph.parse_node_from_object(net, "normal..tutorial1", prefix="1")
        child_node2 = TestGraph.parse_node_from_object(net, "normal..tutorial1", prefix="2")
        node.cleanup_nodes = [child_node1, child_node2]
        worker = TestWorker(flat_net)

        picked_child = node.pick_child(worker)
        self.assertEqual(picked_child, child_node1)
        node.visit_child(picked_child, worker)
        picked_child = node.pick_child(worker)
        self.assertEqual(picked_child, child_node2)
        node.visit_child(picked_child, worker)


@mock.patch('avocado_i2n.cartgraph.node.remote.wait_for_login', mock.MagicMock())
@mock.patch('avocado_i2n.cartgraph.node.door', DummyStateControl)
@mock.patch('avocado_i2n.runner.SpawnerDispatcher', mock.MagicMock())
@mock.patch.object(CartesianRunner, 'run_test_task', DummyTestRun.mock_run_test_task)
class CartesianGraphTest(Test):

    def setUp(self):
        DummyTestRun.asserted_tests = []
        self.shared_pool = shared_pool = "/:/mnt/local/images/shared"
        DummyStateControl.asserted_states = {"check": {}, "get": {}, "set": {}, "unset": {}}
        DummyStateControl.asserted_states["check"] = {"install": {shared_pool: False},
                                                      "customize": {shared_pool: False}, "on_customize": {shared_pool: False},
                                                      "connect": {shared_pool: False},
                                                      "linux_virtuser": {shared_pool: False}, "windows_virtuser": {shared_pool: False}}
        DummyStateControl.asserted_states["get"] = {"install": {shared_pool: 0},
                                                    "customize": {shared_pool: 0}, "on_customize": {shared_pool: 0},
                                                    "connect": {shared_pool: 0},
                                                    "linux_virtuser": {shared_pool: 0}, "windows_virtuser": {shared_pool: 0}}

        self.config = {}
        # TODO: migrate run slots to official workers composition as graph attributes
        self.config["param_dict"] = {"test_timeout": 100, "shared_pool": shared_pool, "slots": "1"}
        self.config["tests_str"] = "only normal\n"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n", "vm3": "only Ubuntu\n"}

        self.prefix = ""

        self.loader = CartesianLoader(config=self.config, extra_params={})
        self.job = mock.MagicMock()
        self.job.logdir = "."
        self.job.timeout = 6000
        self.job.result = mock.MagicMock()
        self.job.result.tests = []
        self.job.config = self.config
        self.runner = CartesianRunner()
        self.runner.job = self.job
        self.runner.status_server = self.job

    def _run_traversal(self, graph, params=None):
        params = params or {"test_timeout": 100}
        loop = asyncio.get_event_loop()
        slot_workers = sorted(list(graph.workers.values()), key=lambda x: x.params["name"])
        graph.runner = self.runner
        to_traverse = [graph.traverse_object_trees(s, params) for s in slot_workers if "runtime_str" in s.params]
        loop.run_until_complete(asyncio.wait_for(asyncio.gather(*to_traverse), None))
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_flag_children_all(self):
        """Test for correct node children flagging of a complete Cartesian graph."""
        self.config["param_dict"]["nets"] = "net1"
        self.config["param_dict"]["vms"] = "vm1"
        self.config["tests_str"] = "only nonleaves\n"
        self.config["tests_str"] += "only connect\n"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )

        graph.flag_children(flag_type="run", flag=lambda self, slot: False)
        DummyTestRun.asserted_tests = [
        ]
        self._run_traversal(graph, self.config["param_dict"])

        graph.flag_children(flag_type="run", flag=lambda self, slot: True)
        graph.flag_children(object_name="image1_vm1", flag_type="run", flag=lambda self, slot: False)
        DummyTestRun.asserted_tests = [
        ]
        self._run_traversal(graph, self.config["param_dict"])

    def test_flag_children(self):
        """Test for correct node children flagging for a given node."""
        self.config["param_dict"]["nets"] = "net1"
        self.config["param_dict"]["vms"] = "vm1"
        self.config["tests_str"] = "only nonleaves\n"
        self.config["tests_str"] += "only connect\n"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )

        graph.flag_children(flag_type="run", flag=lambda self, slot: False)
        graph.flag_children(node_name="customize", flag_type="run", flag=lambda self, slot: slot not in self.workers)
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^nonleaves.internal.automated.connect.vm1", "vms": "^vm1$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])

    def test_flag_intersection_all(self):
        """Test for correct node flagging of a Cartesian graph with itself."""
        self.config["param_dict"]["nets"] = "net1"
        self.config["param_dict"]["vms"] = "vm1"
        self.config["tests_str"] = "only nonleaves\n"
        self.config["tests_str"] += "only connect\n"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )
        graph.flag_intersection(graph, flag_type="run", flag=lambda self, slot: False)
        DummyTestRun.asserted_tests = [
        ]
        self._run_traversal(graph, self.config["param_dict"])

    def test_flag_intersection(self):
        """Test for correct node intersection of two Cartesian graphs."""
        self.config["param_dict"]["nets"] = "net1"
        self.config["param_dict"]["vms"] = "vm1"
        self.config["tests_str"] = "only nonleaves\n"
        tests_str1 = self.config["tests_str"] + "only connect\n"
        tests_str2 = self.config["tests_str"] + "only customize\n"
        graph = TestGraph.parse_object_trees(
            None, tests_str1,
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )
        reuse_graph = TestGraph.parse_object_trees(
            None, tests_str2,
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )

        #graph.flag_intersection(graph, flag_type="run", flag=lambda self, slot: slot not in self.workers)
        graph.flag_intersection(reuse_graph, flag_type="run", flag=lambda self, slot: False)
        DummyTestRun.asserted_tests = [
            {"shortname": "^nonleaves.internal.automated.connect.vm1", "vms": "^vm1$"},
        ]
        self._run_traversal(graph, self.config["param_dict"])

    def test_get_objects_by(self):
        """Test object retrieval with various arguments and thus calls."""
        graph = TestGraph()
        graph.objects = [n for n in TestGraph.parse_suffix_objects("vms")]
        self.assertEqual(len(graph.objects), 6)
        get_objects = graph.get_objects_by(param_val="vm\d")
        self.assertEqual(len(get_objects), len(graph.objects))
        get_objects = graph.get_objects_by(param_val="vm1")
        self.assertEqual(len(get_objects), 2)
        get_objects = graph.get_objects_by(param_val="\.CentOS", subset=get_objects)
        self.assertEqual(len(get_objects), 1)
        get_objects = graph.get_objects_by("os_type", param_val="linux", subset=get_objects)
        self.assertEqual(len(get_objects), 1)
        get_objects = graph.get_objects_by(param_key="os_variant", param_val="el8", subset=get_objects)
        self.assertEqual(len(get_objects), 1)
        get_node = graph.get_node_by(param_key="os_type", param_val="linux", subset=get_objects)
        self.assertIn(get_node, get_objects)
        get_nodes = graph.get_nodes_by(param_val="vm1", subset=[])
        self.assertEqual(len(get_nodes), 0)

    def test_get_nodes_by_name(self):
        """Test node retrieval by name using a trie as an index."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("all..tutorial3"))
        self.assertEqual(len(graph.nodes), 17)
        get_nodes = graph.get_nodes_by_name("tutorial3")
        self.assertEqual(len(get_nodes), len(graph.nodes))
        get_nodes = graph.get_nodes_by_name("tutorial3.remote")
        self.assertEqual(len(get_nodes), 16)
        get_nodes = graph.get_nodes_by_name("object")
        self.assertEqual(len(get_nodes), 8)
        get_nodes = graph.get_nodes_by_name("object.control")
        self.assertEqual(len(get_nodes), 4)
        get_nodes = graph.get_nodes_by_name("tutorial3.remote.object.control.decorator")
        self.assertEqual(len(get_nodes), 2)

    def test_get_nodes_by(self):
        """Test node retrieval with various arguments and thus calls."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("all..tutorial3"))
        self.assertEqual(len(graph.nodes), 17)
        get_nodes = graph.get_nodes_by(param_val="tutorial3")
        self.assertEqual(len(get_nodes), len(graph.nodes))
        get_nodes = graph.get_nodes_by(param_val="tutorial3.remote")
        self.assertEqual(len(get_nodes), 16)
        get_nodes = graph.get_nodes_by(param_val="\.object", subset=get_nodes)
        self.assertEqual(len(get_nodes), 8)
        get_nodes = graph.get_nodes_by("remote_control_check", param_val="yes", subset=get_nodes)
        self.assertEqual(len(get_nodes), 4)
        get_nodes = graph.get_nodes_by(param_key="remote_decorator_check", param_val="yes", subset=get_nodes)
        self.assertEqual(len(get_nodes), 2)
        get_node = graph.get_node_by(param_key="remote_util_check", param_val="yes", subset=get_nodes)
        self.assertIn(get_node, get_nodes)
        get_nodes = graph.get_nodes_by(param_val="tutorial3", subset=[])
        self.assertEqual(len(get_nodes), 0)

    def test_parse_and_get_objects_for_node_and_object_flat(self):
        """Test parsing and retrieval of objects for a flat pair of test node and object."""
        graph = TestGraph()
        flat_nodes = [n for n in TestGraph.parse_flat_nodes("normal..tutorial1")]
        self.assertEqual(len(flat_nodes), 1)
        flat_node = flat_nodes[0]
        flat_objects = TestGraph.parse_flat_objects("net1", "nets")
        self.assertEqual(len(flat_objects), 1)
        flat_object = flat_objects[0]
        self.assertNotIn("only_vm1", flat_object.params)
        flat_object.params["only_vm1"] = "CentOS"
        get_objects, parse_objects = graph.parse_and_get_objects_for_node_and_object(flat_node, flat_object)
        self.assertEqual(len(get_objects), 0)
        test_objects = parse_objects

        self.assertEqual(len(test_objects), 1)
        self.assertEqual(test_objects[0].suffix, "net1")
        #self.assertIn("CentOS", test_objects[0].params[""])
        self.assertIn("CentOS", test_objects[0].id)
        self.assertEqual(len(test_objects[0].components), 1)
        self.assertIn("CentOS", test_objects[0].components[0].id)
        self.assertEqual(len(test_objects[0].components[0].components), 1)
        self.assertEqual(test_objects[0].components[0].components[0].long_suffix, "image1_vm1")

    def test_parse_and_get_objects_for_node_and_object_full(self):
        """Test default parsing and retrieval of objects for a flat test node and full test object."""
        graph = TestGraph()
        flat_nodes = [n for n in TestGraph.parse_flat_nodes("normal..tutorial1")]
        self.assertEqual(len(flat_nodes), 1)
        flat_node = flat_nodes[0]
        full_objects = TestGraph.parse_composite_objects("net1", "nets", "", self.config["vm_strs"])
        self.assertEqual(len(full_objects), 1)
        full_object = full_objects[0]
        # TODO: limitation in the Cartesian config
        self.assertNotIn("object_only_vm1", full_object.params)
        full_object.params["object_only_vm1"] = "CentOS"
        get_objects, parse_objects = graph.parse_and_get_objects_for_node_and_object(flat_node, full_object)
        self.assertEqual(len(get_objects), 0)
        test_objects = parse_objects

        self.assertEqual(len(test_objects), 1)

        self.assertEqual(test_objects[0].suffix, "net1")
        self.assertIn("CentOS", test_objects[0].id)
        self.assertEqual(len(test_objects[0].components), 1)
        self.assertIn("CentOS", test_objects[0].components[0].id)
        self.assertEqual(len(test_objects[0].components[0].components), 1)
        self.assertEqual(test_objects[0].components[0].components[0].long_suffix, "image1_vm1")

    def test_object_node_incompatible(self):
        """Test incompatibility of parsed tests and pre-parsed available objects."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["vm_strs"] = {"vm2": "only Win10\n", "vm3": "only Ubuntu\n"}
        with self.assertRaises(param.EmptyCartesianProduct):
            TestGraph.parse_object_nodes(None, self.config["tests_str"], prefix=self.prefix,
                                         object_strs=self.config["vm_strs"],
                                         params=self.config["param_dict"])

    def test_object_node_intersection(self):
        """Test restricted vms-tests nonempty intersection of parsed tests and pre-parsed available objects."""
        self.config["tests_str"] += "only tutorial1,tutorial_get\n"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        nodes, objects = TestGraph.parse_object_nodes(None, self.config["tests_str"], prefix=self.prefix,
                                                      object_strs=self.config["vm_strs"],
                                                      params=self.config["param_dict"])
        object_suffixes = [o.suffix for o in objects]
        self.assertIn("vm1", object_suffixes)
        # due to lacking vm3 tutorial_get will not be parsed and the only already parsed vm remains vm1
        self.assertNotIn("vm2", object_suffixes)
        # vm3 is fully lacking
        self.assertNotIn("vm3", object_suffixes)
        for n in nodes:
            if "tutorial1" in n.params["name"]:
                break
        else:
            raise AssertionError("The tutorial1 variant must be present in the object-node intersection")
        for n in nodes:
            if "tutorial_get" in n.params["name"]:
                raise AssertionError("The tutorial_get variant must be skipped since vm3 is not available")

    def test_parse_and_get_nodes_for_node_and_object(self):
        """Test default parsing and retrieval of nodes for a pair of test node and object."""
        graph = TestGraph()
        nodes, objects = TestGraph.parse_object_nodes(None, "normal..tutorial1", prefix=self.prefix,
                                                      object_strs=self.config["vm_strs"],
                                                      params=self.config["param_dict"])
        self.assertEqual(len(nodes), 1)
        full_node = nodes[0]
        self.assertEqual(len(objects), 3)

        self.assertEqual(len([o for o in objects if o.key == "nets"]), 1)
        full_net = [o for o in objects if o.key == "nets"][0]
        get_nodes, parse_nodes = graph.parse_and_get_nodes_for_node_and_object(full_node, full_net)
        self.assertEqual(len(get_nodes), 0)
        self.assertEqual(len(parse_nodes), 0)

        self.assertEqual(len([o for o in objects if o.key == "vms"]), 1)
        full_vm = [o for o in objects if o.key == "vms"][0]
        get_nodes, parse_nodes = graph.parse_and_get_nodes_for_node_and_object(full_node, full_vm)
        self.assertEqual(len(get_nodes), 0)
        self.assertEqual(len(parse_nodes), 1)
        graph.new_nodes(parse_nodes)
        get_nodes, parse_nodes = graph.parse_and_get_nodes_for_node_and_object(full_node, full_vm)
        self.assertEqual(len(get_nodes), 1)
        self.assertEqual(len(parse_nodes), 0)

        self.assertEqual(len([o for o in objects if o.key == "images"]), 1)
        full_image = [o for o in objects if o.key == "images"][0]
        get_nodes, parse_nodes = graph.parse_and_get_nodes_for_node_and_object(full_node, full_image)
        self.assertEqual(len(get_nodes), 0)
        self.assertEqual(len(parse_nodes), 0)

    def test_parse_and_get_nodes_for_node_and_object_with_leaves(self):
        """Test that leaf nodes are properly reused when parsed as dependencies for node and object."""
        graph = TestGraph()
        nodes, objects = TestGraph.parse_object_nodes(None, "all..tutorial_get.explicit_clicked", prefix=self.prefix,
                                                      object_strs=self.config["vm_strs"],
                                                      params=self.config["param_dict"])
        self.assertEqual(len(nodes), 1)
        full_node = nodes[0]
        self.assertEqual(len(objects), 1+3+3)

        self.assertEqual(len([o for o in objects if o.key == "nets"]), 1)
        full_net = [o for o in objects if o.key == "nets"][0]
        get_nodes, parse_nodes = graph.parse_and_get_nodes_for_node_and_object(full_node, full_net)
        self.assertEqual(len(get_nodes), 0)
        self.assertEqual(len(parse_nodes), 0)

        self.assertEqual(len([o for o in objects if o.key == "vms"]), 3)
        for full_vm in [o for o in objects if o.key == "vms"]:
            get_nodes, parse_nodes = graph.parse_and_get_nodes_for_node_and_object(full_node, full_vm)
            self.assertEqual(len(get_nodes), 0)
            self.assertEqual(len(parse_nodes), 0)

        self.assertEqual(len([o for o in objects if o.key == "images"]), 3)

        # standard handling for vm1 as in other tests
        full_image1 = [o for o in objects if o.key == "images" and "vm1" in o.long_suffix][0]
        get_nodes, parse_nodes = graph.parse_and_get_nodes_for_node_and_object(full_node, full_image1)
        self.assertEqual(len(get_nodes), 0)
        self.assertEqual(len(parse_nodes), 1)
        graph.new_nodes(parse_nodes)
        get_nodes, parse_nodes = graph.parse_and_get_nodes_for_node_and_object(full_node, full_image1)
        self.assertEqual(len(get_nodes), 1)
        self.assertEqual(len(parse_nodes), 0)

        # most important part regarding reusability
        full_image2 = [o for o in objects if o.key == "images" and "vm2" in o.long_suffix][0]
        get_nodes, parse_nodes = graph.parse_and_get_nodes_for_node_and_object(full_node, full_image2)
        self.assertEqual(len(get_nodes), 0)
        self.assertEqual(len(parse_nodes), 1)
        # we are adding a leaf node that should be reused as the setup of this node
        leaf_nodes = graph.parse_composite_nodes("leaves..tutorial_gui.client_clicked", full_net)
        graph.new_nodes(leaf_nodes)
        get_nodes, parse_nodes = graph.parse_and_get_nodes_for_node_and_object(full_node, full_image2)
        self.assertEqual(len(get_nodes), 1)
        self.assertEqual(len(parse_nodes), 0)
        self.assertEqual(get_nodes, leaf_nodes)

        # no nodes for permanent object vm3
        full_image3 = [o for o in objects if o.key == "images" and "vm3" in o.long_suffix][0]
        get_nodes, parse_nodes = graph.parse_and_get_nodes_for_node_and_object(full_node, full_image3)
        self.assertEqual(len(get_nodes), 0)
        self.assertEqual(len(parse_nodes), 0)

    def test_parse_and_get_nodes_for_node_and_object_with_cloning(self):
        """Test parsing and retrieval of nodes for a pair of cloned test node and object."""
        graph = TestGraph()
        nodes, objects = TestGraph.parse_object_nodes(None, "leaves..tutorial_get..implicit_both", prefix=self.prefix,
                                                      object_strs=self.config["vm_strs"],
                                                      params=self.config["param_dict"])
        self.assertEqual(len(nodes), 1)
        full_node = nodes[0]
        self.assertEqual(len(objects), 7, "We need 3 images, 3 vms, and 1 net")

        self.assertEqual(len([o for o in objects if o.key == "nets"]), 1)
        full_net = [o for o in objects if o.key == "nets"][0]
        get_nodes, parse_nodes = graph.parse_and_get_nodes_for_node_and_object(full_node, full_net)
        self.assertEqual(len(get_nodes), 0)
        self.assertEqual(len(parse_nodes), 0)

        self.assertEqual(len([o for o in objects if o.key == "vms"]), 3)
        for full_vm in [o for o in objects if o.key == "vms"]:
            get_nodes, parse_nodes = graph.parse_and_get_nodes_for_node_and_object(full_node, full_vm)
            self.assertEqual(len(get_nodes), 0)
            self.assertEqual(len(parse_nodes), 0)

        self.assertEqual(len([o for o in objects if o.key == "images"]), 3)
        full_image = [o for o in objects if o.key == "images" and o.long_suffix == "image1_vm2"][0]
        get_nodes, parse_nodes = graph.parse_and_get_nodes_for_node_and_object(full_node, full_image)
        self.assertEqual(len(get_nodes), 0)
        self.assertEqual(len(parse_nodes), 2)
        graph.new_nodes(parse_nodes)
        get_nodes, parse_nodes = graph.parse_and_get_nodes_for_node_and_object(full_node, full_image)
        self.assertEqual(len(get_nodes), 2)
        self.assertEqual(len(parse_nodes), 0)

    def test_parse_branches_for_node_and_object(self):
        """Test default parsing and retrieval of branches for a pair of test node and object."""
        graph = TestGraph()
        flat_nodes = [n for n in TestGraph.parse_flat_nodes("normal..tutorial1")]
        self.assertEqual(len(flat_nodes), 1)
        flat_node = flat_nodes[0]
        flat_objects = TestGraph.parse_flat_objects("net1", "nets")
        self.assertEqual(len(flat_objects), 1)
        flat_object = flat_objects[0]

        parents, children = graph.parse_branches_for_node_and_object(flat_node, flat_object)
        self.assertEqual(len(parents), 2)
        # validate cache is exactly as expected, namely just the newly parsed nodes
        self.assertEqual(len(graph.nodes), len(parents + children))
        self.assertEqual(set(graph.nodes), set(parents + children))

        self.assertEqual(len(graph.objects), 6)
        full_nets = sorted([o for o in graph.objects if o.key == "nets"], key=lambda x: x.params["name"])
        self.assertEqual(len(full_nets), 2)
        full_vms = sorted([o for o in graph.objects if o.key == "vms"], key=lambda x: x.params["name"])
        self.assertEqual(len(full_vms), 2)
        full_images = [o for o in graph.objects if o.key == "images"]
        self.assertEqual(len(full_images), 2)

        self.assertEqual(len(children), 2)
        for i in range(len(children)):
            self.assertEqual(children[i].objects[0], full_nets[i])
            self.assertEqual(children[i].objects[0].components[0], full_vms[i])

        parents, children = graph.parse_branches_for_node_and_object(flat_node, flat_object)
        self.assertEqual(len(parents), 0)
        self.assertEqual(len(children), 0)

        # make sure the node reuse does not depend on test set restrictions
        flat_nodes = [n for n in TestGraph.parse_flat_nodes("all..tutorial1")]
        self.assertEqual(len(flat_nodes), 1)
        flat_node = flat_nodes[0]
        parents, children = graph.parse_branches_for_node_and_object(flat_node, flat_object)
        self.assertEqual(len(parents), 0)
        self.assertEqual(len(children), 0)

    def test_parse_branches_for_node_and_object_with_cloning(self):
        """Test default parsing and retrieval of branches for a pair of cloned test node and object."""
        graph = TestGraph()
        flat_nodes = [n for n in TestGraph.parse_flat_nodes("leaves..tutorial_get..implicit_both")]
        self.assertEqual(len(flat_nodes), 1)
        flat_node = flat_nodes[0]
        flat_objects = TestGraph.parse_flat_objects("net1", "nets", params={"only_vm1": "CentOS", "only_vm2": "Win10", "only_vm3": "Ubuntu"})
        self.assertEqual(len(flat_objects), 1)
        flat_object = flat_objects[0]

        parents, children = graph.parse_branches_for_node_and_object(flat_node, flat_object)
        self.assertEqual(len([p for p in parents if "tutorial_gui" in p.id]), 2)
        # validate cache is exactly as expected, namely just the newly parsed nodes
        self.assertEqual(len(graph.nodes), len(parents + children))
        self.assertEqual(set(graph.nodes), set(parents + children))

        self.assertEqual(len(graph.objects), 3+6+6)
        # nets are one triple, one double, and one single (triple for current, double and single for parents)
        full_nets = sorted([o for o in graph.objects if o.key == "nets"], key=lambda x: x.params["name"])
        self.assertEqual(len(full_nets), 3)
        # we always parse all vms independently of restrictions since they play the role of base for filtering
        full_vms = sorted([o for o in graph.objects if o.key == "vms"], key=lambda x: x.params["name"])
        self.assertEqual(len(full_vms), 6)
        full_images = [o for o in graph.objects if o.key == "images"]
        self.assertEqual(len(full_images), 6)

        self.assertEqual(len(children), 2)
        for i in range(len(children)):
            self.assertIn(children[i].objects[0], full_nets)
            self.assertTrue(set(children[i].objects[0].components) <= set(full_vms))

        parents, children = graph.parse_branches_for_node_and_object(flat_node, flat_object)
        self.assertEqual(len(parents), 0)

    def test_parse_branches_for_node_and_object_with_cloning_multivariant(self):
        """Test default parsing and retrieval of branches for a pair of cloned test node and object."""
        graph = TestGraph()
        flat_nodes = [n for n in TestGraph.parse_flat_nodes("leaves..tutorial_get..implicit_both")]
        self.assertEqual(len(flat_nodes), 1)
        flat_node = flat_nodes[0]
        flat_objects = TestGraph.parse_flat_objects("net1", "nets", params={"only_vm1": "", "only_vm2": "", "only_vm3": ""})
        self.assertEqual(len(flat_objects), 1)
        flat_object = flat_objects[0]

        # use params to overwrite the full node parameters and remove its default restriction on vm1
        parents, children = graph.parse_branches_for_node_and_object(flat_node, flat_object, params={"only_vm1": ""})
        # two variants of connect for the two variants of vm1
        self.assertEqual(len([p for p in parents if "connect" in p.id]), 2)
        # 4 variants of tutorial_gui for the 2x2 variants of vm1 and vm2 (as setup for vm2)
        self.assertEqual(len([p for p in parents if "tutorial_gui" in p.id]), 4)
        # validate cache is exactly as expected, namely just the newly parsed nodes
        self.assertEqual(len(graph.nodes), len(parents + children))
        self.assertEqual(set(graph.nodes), set(parents + children))

        self.assertEqual(len(graph.objects), 12+6+6)
        # nets are one triple, one double, and one single (triple for current, double and single for parents)
        full_nets = sorted([o for o in graph.objects if o.key == "nets"], key=lambda x: x.params["name"])
        # all triple, two double (both of CentOS with each windows variant due to one-edge reusability), and two single (vm1)
        self.assertEqual(len(full_nets), 2**3+2+2)
        # we always parse all vms independently of restrictions since they play the role of base for filtering
        full_vms = sorted([o for o in graph.objects if o.key == "vms"], key=lambda x: x.params["name"])
        self.assertEqual(len(full_vms), 6)
        full_images = [o for o in graph.objects if o.key == "images"]
        self.assertEqual(len(full_images), 6)

        self.assertEqual(len(children), 2**4)
        self.assertEqual(len([c for c in children if "implicit_both" in c.id]), 2**4)
        self.assertEqual(len([c for c in children if "implicit_both" in c.id and "guisetup.noop" in c.id]), 2**3)
        self.assertEqual(len([c for c in children if "implicit_both" in c.id and "guisetup.clicked" in c.id]), 2**3)
        for i in range(len(children)):
            self.assertIn(children[i].objects[0], full_nets)
            self.assertTrue(set(children[i].objects[0].components) <= set(full_vms))

        parents, children = graph.parse_branches_for_node_and_object(flat_node, flat_object)
        self.assertEqual(len(parents), 0)
        for flat_node in TestGraph.parse_flat_nodes("leaves..tutorial_get"):
            parents, children = graph.parse_branches_for_node_and_object(flat_node, flat_object)
            self.assertEqual(len(parents), 0)

    def test_parse_paths_to_object_roots(self):
        """Test correct expectation of parsing graph dependency paths from a leaf to all their object roots."""
        graph = TestGraph()
        flat_objects = TestGraph.parse_flat_objects("net1", "nets")
        self.assertEqual(len(flat_objects), 1)
        flat_object = flat_objects[0]
        flat_nodes = [n for n in TestGraph.parse_flat_nodes("normal..tutorial1")]
        self.assertEqual(len(flat_nodes), 1)
        flat_node = flat_nodes[0]

        generator = graph.parse_paths_to_object_roots(flat_node, flat_object)
        flat_parents, flat_children, flat_node2 = next(generator)
        self.assertEqual(flat_node, flat_node2)
        self.assertNotIn(flat_node, flat_children)
        self.assertEqual(len(flat_children), 2)
        self.assertEqual(len(flat_parents), 2)
        leaf_parents1, leaf_children1, leaf_node1 = next(generator)
        self.assertIn(leaf_node1, flat_children)
        self.assertEqual(len(leaf_children1), 0)
        self.assertEqual(len(leaf_parents1), 0)
        leaf_parents2, leaf_children2, leaf_node2 = next(generator)
        self.assertIn(leaf_node2, flat_children)
        self.assertEqual(len(leaf_children2), 0)
        self.assertEqual(len(leaf_parents2), 0)

    def test_parse_paths_to_object_roots_with_cloning_shallow(self):
        """Test parsing of complete paths to object roots with shallow cloning."""
        graph = TestGraph()
        flat_objects = TestGraph.parse_flat_objects("net1", "nets", params={"only_vm1": "CentOS", "only_vm2": "Win10", "only_vm3": "Ubuntu"})
        self.assertEqual(len(flat_objects), 1)
        flat_object = flat_objects[0]
        flat_nodes = [n for n in TestGraph.parse_flat_nodes("leaves..tutorial_get..implicit_both")]
        self.assertEqual(len(flat_nodes), 1)
        flat_node = flat_nodes[0]

        generator = graph.parse_paths_to_object_roots(flat_node, flat_object)
        flat_parents, flat_children, _ = next(generator)
        self.assertEqual(len(flat_children), 2)
        self.assertEqual(len([p for p in flat_parents if "tutorial_gui" in p.id]), 2)
        leaf_parents1, leaf_children1, leaf_node1 = next(generator)
        self.assertIn(leaf_node1, flat_children)
        self.assertEqual(len(leaf_children1), 0)
        self.assertEqual(len(leaf_parents1), 0)
        leaf_parents2, leaf_children2, leaf_node2 = next(generator)
        self.assertIn(leaf_node2, flat_children)
        self.assertEqual(len(leaf_children2), 0)
        self.assertEqual(len(leaf_parents2), 0)

        next_parents1, next_children1, parent_node1 = next(generator)
        self.assertIn(parent_node1, flat_parents)
        # no more duplication
        self.assertEqual(len(next_children1), 0)
        self.assertGreaterEqual(len(next_parents1), 0)

    def test_parse_paths_to_object_roots_with_cloning_deep(self):
        """Test parsing of complete paths to object roots with deep cloning."""
        graph = TestGraph()
        flat_objects = TestGraph.parse_flat_objects("net1", "nets", params={"only_vm1": "CentOS", "only_vm2": "Win10", "only_vm3": "Ubuntu"})
        self.assertEqual(len(flat_objects), 1)
        flat_object = flat_objects[0]
        flat_nodes = [n for n in TestGraph.parse_flat_nodes("leaves..tutorial_finale")]
        self.assertEqual(len(flat_nodes), 1)
        flat_node = flat_nodes[0]

        generator = graph.parse_paths_to_object_roots(flat_node, flat_object)
        flat_parents, flat_children, _ = next(generator)
        self.assertEqual(len(flat_children), 1)
        self.assertEqual(len([p for p in flat_parents if "tutorial_get.implicit_both" in p.id]), 1)
        leaf_parents1, leaf_children1, leaf_node1 = next(generator)
        self.assertIn(leaf_node1, flat_children)
        self.assertEqual(len(leaf_children1), 0)
        self.assertEqual(len(leaf_parents1), 0)

        next_parents1, next_children1, next_node1 = next(generator)
        self.assertIn(next_node1, flat_parents)
        # duplicated parent from double grandparent
        self.assertEqual(len(next_children1), 2)
        self.assertEqual(len([p for p in next_parents1 if "tutorial_gui" in p.id]), 2)

        next_parents2, next_children2, next_node2 = next(generator)
        # going through next children now
        self.assertIn(next_node2, next_children1)
        # implicit_both clone was cloned already
        self.assertEqual(len(next_children2), 0)
        # parents are reused so no new parsed parents
        self.assertEqual(len([p for p in next_parents2 if "tutorial_gui" in p.id]), 0)
        next_parents3, next_children3, next_node3 = next(generator)
        # going through next children now
        self.assertIn(next_node3, next_children1)
        # implicit_both clone was cloned already
        self.assertEqual(len(next_children2), 0)
        # parents are reused so no new parsed parents
        self.assertEqual(len([p for p in next_parents2 if "tutorial_gui" in p.id]), 0)

    def test_shared_root_from_object_roots(self):
        """Test correct expectation of separately adding a shared root to a graph of disconnected object trees."""
        self.config["tests_str"] += "only tutorial3\n"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
            with_shared_root=False,
        )
        graph.parse_shared_root_from_object_roots(self.config["param_dict"])
        # assert one shared root exists and it connects all object roots
        shared_root_node = None
        for node in graph.nodes:
            if node.is_shared_root():
                if shared_root_node is not None:
                    raise AssertionError("More than one shared root nodes found in graph")
                shared_root_node = node
        if not shared_root_node:
            raise AssertionError("No shared root nodes found in graph")
        for node in graph.nodes:
            if node.is_object_root():
                self.assertEqual(node.setup_nodes, [shared_root_node])

    def test_graph_sanity(self):
        """Test generic usage of the complete test graph."""
        self.config["tests_str"] += "only tutorial1\n"
        nodes, objects = TestGraph.parse_object_nodes(
            None, self.config["tests_str"],
            prefix=self.prefix,
            object_strs=self.config["vm_strs"],
            params=self.config["param_dict"],
        )
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            prefix=self.prefix,
            object_strs=self.config["vm_strs"],
            params=self.config["param_dict"],
            with_shared_root=False,
        )
        self.assertEqual({o.suffix for o in graph.objects if o.suffix not in ["net2", "net3", "net4", "net5"]},
                         {o.suffix for o in objects})
        self.assertEqual({n.prefix for n in graph.nodes if not n.produces_setup()},
                         {n.prefix for n in nodes})

        repr = str(graph)
        self.assertIn("[cartgraph]", repr)
        self.assertIn("[object]", repr)
        self.assertIn("[node]", repr)

    @skip("Needs node bridging")
    def test_traverse_one_leaf_parallel(self):
        """Test traversal path of one test without any reusable setup."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("normal..tutorial1"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": " ".join([f"{i+1}" for i in range(4)]),
                                                   "only_vm1": "CentOS"}))

        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$", "set_state_images": "^install$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_images": "^install$", "set_state_images": "^customize$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "get_state_images": "^customize$", "set_state_vms": "^on_customize$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "get_state_vms": "^on_customize$"},
        ]

        self._run_traversal(graph)

    def test_traverse_one_leaf_serial(self):
        """Test traversal path of one test without any reusable setup and with a serial unisolated run."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("normal..tutorial1"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": "", "only_vm1": "CentOS"}))

        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$", "nets_spawner": "process"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$", "nets_spawner": "process"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "nets_spawner": "process"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "nets_spawner": "process"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "nets_spawner": "process"},
        ]

        self._run_traversal(graph)

    @skip("Needs node bridging")
    def test_traverse_one_leaf_with_setup(self):
        """Test traversal path of one test with a reusable setup."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("normal..tutorial1"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": " ".join([f"{i+1}" for i in range(3)]),
                                                   "only_vm1": "CentOS"}))

        DummyStateControl.asserted_states["check"]["install"][self.shared_pool] = True
        DummyTestRun.asserted_tests = [
            # cleanup is expected only if at least one of the states is reusable (here root+install)
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "nets_spawner": "lxc", "nets_host": "^c1$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "nets_spawner": "lxc", "nets_host": "^c1$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "nets_spawner": "lxc", "nets_host": "^c1$"},
        ]

        self._run_traversal(graph)

    @skip("Needs node bridging")
    def test_traverse_one_leaf_with_step_setup(self):
        """Test traversal path of one test with a single reusable setup test node."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("normal..tutorial1"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": " ".join([f"{i+1}" for i in range(3)]),
                                                   "only_vm1": "CentOS"}))

        DummyStateControl.asserted_states["check"]["customize"][self.shared_pool] = True
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]

        self._run_traversal(graph)

    @skip("Needs node bridging")
    def test_traverse_one_leaf_with_failed_setup(self):
        """Test traversal path of one test with a failed reusable setup test node."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("normal..tutorial1"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": " ".join([f"{i+1}" for i in range(2)]),
                                                   "only_vm1": "CentOS"}))

        DummyStateControl.asserted_states["check"]["install"][self.shared_pool] = True
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "nets_host": "^c1$", "_status": "FAIL"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]

        self._run_traversal(graph)

    @skip("Needs node bridging")
    def test_traverse_one_leaf_with_retried_setup(self):
        """Test traversal path of one test with a failed but retried setup test node."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("normal..tutorial1"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": " ".join([f"{i+1}" for i in range(4)]),
                                                   "only_vm1": "CentOS"}))

        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$", "_status": "FAIL"},
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$", "_status": "PASS"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "_status": "FAIL"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "_status": "FAIL"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "_status": "PASS"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]

        self._run_traversal(graph, {"max_tries": "3", "stop_status": "pass"})

    def test_traverse_one_leaf_with_occupation_timeout(self):
        """Test multi-traversal of one test where it is occupied for too long (worker hangs)."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("normal..tutorial1", {"test_timeout": "1"}))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": "1 dead",
                                                   "only_vm1": "CentOS"}))

        test_node = graph.get_node_by(param_val="tutorial1")
        test_node.set_environment(graph.workers["net2"])
        DummyStateControl.asserted_states["check"]["install"][self.shared_pool] = True
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "nets_host": "^c1$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "nets_host": "^c1$"},
        ]

        with self.assertRaisesRegex(RuntimeError, r"^Worker .+ spent [\d\.]+ seconds waiting for occupied node"):
            self._run_traversal(graph, self.config["param_dict"])

    @skip("Needs node bridging")
    def test_traverse_two_objects_without_setup(self):
        """Test a two-object test traversal without a reusable setup."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("normal..tutorial3"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": " ".join([f"{i+1}" for i in range(4)]),
                                                   "only_vm1": "CentOS", "only_vm2": "Win10"}))

        DummyStateControl.asserted_states["check"]["install"][self.shared_pool] = False
        DummyStateControl.asserted_states["check"]["customize"][self.shared_pool] = False
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "nets_host": "^c1$"},
            {"shortname": "^internal.stateless.noop.vm2", "vms": "^vm2$", "nets_host": "^c2$"},

            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$", "nets_host": "^c1$"},
            {"shortname": "^original.unattended_install.cdrom.in_cdrom_ks.default_install.aio_threads.vm2", "vms": "^vm2$", "nets_host": "^c2$"},

            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "nets_host": "^c1$"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$", "nets_host": "^c2$"},

            {"shortname": "^internal.automated.connect.vm1", "vms": "^vm1$", "nets_host": "^c1$"},
            {"shortname": "^normal.nongui.tutorial3", "vms": "^vm1 vm2$", "nets_host": "^c1$"},
        ]

        self._run_traversal(graph)
        # recreated setup is taken from the worker that created it excluding self-sync sync (node reversal)
        self.assertEqual(DummyStateControl.asserted_states["get"]["install"][self.shared_pool], 6)
        self.assertEqual(DummyStateControl.asserted_states["get"]["customize"][self.shared_pool], 6)
        # recreated setup is taken from the worker that created it excluding self-sync sync (node reversal)
        self.assertEqual(DummyStateControl.asserted_states["get"]["connect"][self.shared_pool], 3)

    @skip("Needs node bridging")
    def test_traverse_two_objects_with_setup(self):
        """Test a two-object test traversal with reusable setup."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("normal..tutorial3"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": " ".join([f"{i+1}" for i in range(4)]),
                                                   "only_vm1": "CentOS", "only_vm2": "Win10"}))

        DummyStateControl.asserted_states["check"]["install"][self.shared_pool] = True
        DummyStateControl.asserted_states["check"]["customize"][self.shared_pool] = True
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.connect.vm1", "vms": "^vm1$", "nets_host": "^c1$"},
            {"shortname": "^normal.nongui.tutorial3", "vms": "^vm1 vm2$", "nets_host": "^c1$"},
        ]

        self._run_traversal(graph)
        # get reusable setup from shared pool once to skip and once to sync (node reversal)
        self.assertEqual(DummyStateControl.asserted_states["get"]["install"][self.shared_pool], 8)
        self.assertEqual(DummyStateControl.asserted_states["get"]["customize"][self.shared_pool], 8)
        # recreated setup is taken from the worker that created it excluding self-sync sync (node reversal)
        self.assertEqual(DummyStateControl.asserted_states["get"]["connect"][self.shared_pool], 3)

    @skip("Needs node bridging")
    def test_diverging_paths_external(self):
        """Test a multi-object test run with reusable setup of diverging workers and shared pool or previous runs."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("normal..tutorial1,normal..tutorial3"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": " ".join([f"{i+1}" for i in range(4)]),
                                                   "only_vm1": "CentOS", "only_vm2": "Win10",
                                                   "shared_pool": self.shared_pool}))

        DummyStateControl.asserted_states["check"]["install"][self.shared_pool] = True
        DummyStateControl.asserted_states["check"]["customize"][self.shared_pool] = True
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "nets_host": "^c1$",
             "get_location_image1_vm1": "/:/mnt/local/images/shared"},
            {"shortname": "^internal.automated.connect.vm1", "vms": "^vm1$", "nets_host": "^c2$",
             "get_location_image1_vm1": "/:/mnt/local/images/shared"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "nets_host": "^c1$",
             "get_location_vm1": "/:/mnt/local/images/shared /c1:/mnt/local/images/swarm"},
            {"shortname": "^normal.nongui.tutorial3", "vms": "^vm1 vm2$", "nets_host": "^c2$",
             "get_location_image1_vm1": "/:/mnt/local/images/shared /c2:/mnt/local/images/swarm"},
        ]

        self._run_traversal(graph, self.config["param_dict"])
        # expect four sync and no other cleanup calls, one for each worker
        for action in ["get"]:
            for state in ["install", "customize"]:
                # called once by worker for for each of two vms (no self-sync as setup is from previous run or shared pool)
                # NOTE: any such use cases assume the previous setup is fully synced across all workers, if this is not the case
                # it must be due to interrupted run in which case the setup is not guaranteed to be reusable on the first place
                self.assertEqual(DummyStateControl.asserted_states[action][state][self.shared_pool], 8)
            for state in ["on_customize", "connect"]:
                # called once by worker only for vm1 (excluding self-sync as setup is provided by the swarm pool)
                self.assertEqual(DummyStateControl.asserted_states[action][state][self.shared_pool], 3)
        for action in ["set", "unset"]:
            for state in DummyStateControl.asserted_states[action]:
                self.assertEqual(DummyStateControl.asserted_states[action][state][self.shared_pool], 0)

    @skip("Needs node bridging")
    def test_diverging_paths_swarm(self):
        """Test a multi-object test run where the workers will run multiple tests reusing their own local swarm setup."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("leaves..tutorial2,leaves..tutorial_gui"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": " ".join([f"{i+1}" for i in range(4)]),
                                                   "only_vm1": "CentOS", "only_vm2": "Win10",
                                                   "shared_pool": self.shared_pool}))

        workers = sorted(list(graph.workers.values()), key=lambda x: x.params["name"])
        self.assertEqual(workers[0].params["nets_spawner"], "lxc")
        self.assertEqual(workers[1].params["nets_spawner"], "lxc")
        self.assertEqual(workers[2].params["nets_spawner"], "lxc")
        self.assertEqual(workers[3].params["nets_spawner"], "lxc")

        # this is not what we test but simply a means to remove some initial nodes for simpler testing
        DummyStateControl.asserted_states["check"]["install"][self.shared_pool] = True
        DummyStateControl.asserted_states["check"]["customize"][self.shared_pool] = True
        DummyStateControl.asserted_states["check"]["guisetup.noop"] = {self.shared_pool: False}
        DummyStateControl.asserted_states["check"]["guisetup.clicked"] = {self.shared_pool: False}
        DummyStateControl.asserted_states["get"]["guisetup.noop"] = {self.shared_pool: 0}
        DummyStateControl.asserted_states["get"]["guisetup.clicked"] = {self.shared_pool: 0}
        DummyStateControl.asserted_states["unset"] = {"guisetup.noop": {self.shared_pool: 0}}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$",
             "nets_spawner": "lxc", "nets_gateway": "^$", "nets_host": "^c1$"},
            # c2 starts from second tutorial variant and waits for its single (same) setup to be provided
            {"shortname": "^internal.automated.linux_virtuser.vm1", "vms": "^vm1$",
             "nets_spawner": "lxc", "nets_gateway": "^$", "nets_host": "^c3$"},
            # c4 picks the newly available waiting setup directly from the shared node
            {"shortname": "^internal.automated.windows_virtuser.vm2", "vms": "^vm2$",
             "nets_spawner": "lxc", "nets_gateway": "^$", "nets_host": "^c4$"},
            # c1 now moves on to its planned test
            {"shortname": "^leaves.quicktest.tutorial2.files.vm1", "vms": "^vm1$",
             "nets_spawner": "lxc", "nets_gateway": "^$", "nets_host": "^c1$",
             "get_location_vm1": "[\w:/]+ /c1:/mnt/local/images/swarm"},
            # c2 no longer waits and picks its planned tests reusing setup from c1
            {"shortname": "^leaves.quicktest.tutorial2.names.vm1", "vms": "^vm1$",
             "nets_spawner": "lxc", "nets_gateway": "^$", "nets_host": "^c2$",
             "get_location_vm1": "[\w:/]+ /c1:/mnt/local/images/swarm"},
            # c3 is done with 1/2 of the setup for client_noop and waits for c4 to provide the other half
            {"shortname": "^leaves.tutorial_gui.client_noop", "vms": "^vm1 vm2$",
             "nets_spawner": "lxc", "nets_gateway": "^$", "nets_host": "^c4$",
             "get_location_image1_vm1": "[\w:/]+ /c3:/mnt/local/images/swarm", "get_location_image1_vm2": "[\w:/]+ /c4:/mnt/local/images/swarm"},
            # continuing with c1 after last considering c4 (starting from first worker again)
            {"shortname": "^leaves.tutorial_gui.client_clicked", "vms": "^vm1 vm2$",
             "nets_spawner": "lxc", "nets_gateway": "^$", "nets_host": "^c1$",
             "get_location_image1_vm1": "[\w:/]+ /c3:/mnt/local/images/swarm", "get_location_image1_vm2": "[\w:/]+ /c4:/mnt/local/images/swarm"},
        ]

        self._run_traversal(graph, self.config["param_dict"])
        # expect three sync (one for each worker without self-sync) and one cleanup call
        self.assertEqual(DummyStateControl.asserted_states["unset"]["guisetup.noop"][self.shared_pool], 1)
        self.assertEqual(DummyStateControl.asserted_states["get"]["guisetup.clicked"][self.shared_pool], 3)

    @skip("Needs node bridging")
    def test_diverging_paths_remote(self):
        """Test a multi-object test run where the workers will run multiple tests reusing also remote swarm setup."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("leaves..tutorial2,leaves..tutorial_gui"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": " ".join([f"host1/{i+1}" for i in range(2)] + [f"host2/{i+1}" for i in range(2)]),
                                                   "only_vm1": "CentOS", "only_vm2": "Win10",
                                                   "shared_pool": self.shared_pool}))

        workers = sorted(list(graph.workers.values()), key=lambda x: x.params["name"])
        self.assertEqual(workers[0].params["nets_spawner"], "remote")
        self.assertEqual(workers[1].params["nets_spawner"], "remote")
        self.assertEqual(workers[2].params["nets_spawner"], "remote")
        self.assertEqual(workers[3].params["nets_spawner"], "remote")

        # this is not what we test but simply a means to remove some initial nodes for simpler testing
        DummyStateControl.asserted_states["check"]["install"][self.shared_pool] = True
        DummyStateControl.asserted_states["check"]["customize"][self.shared_pool] = True
        DummyStateControl.asserted_states["check"]["guisetup.noop"] = {self.shared_pool: False}
        DummyStateControl.asserted_states["check"]["guisetup.clicked"] = {self.shared_pool: False}
        DummyStateControl.asserted_states["get"]["guisetup.noop"] = {self.shared_pool: 0}
        DummyStateControl.asserted_states["get"]["guisetup.clicked"] = {self.shared_pool: 0}
        DummyStateControl.asserted_states["unset"] = {"guisetup.noop": {self.shared_pool: 0}}
        DummyTestRun.asserted_tests = [
            # TODO: localhost is not acceptable when we mix hosts
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$",
             "nets_spawner": "remote", "nets_gateway": "^host1$", "nets_host": "^1$"},
            # c2 starts from second tutorial variant and waits for its single (same) setup to be provided
            {"shortname": "^internal.automated.linux_virtuser.vm1", "vms": "^vm1$",
             "nets_spawner": "remote", "nets_gateway": "^host2$", "nets_host": "^1$"},
            # c4 picks the newly available waiting setup directly from the shared node
            {"shortname": "^internal.automated.windows_virtuser.vm2", "vms": "^vm2$",
             "nets_spawner": "remote", "nets_gateway": "^host2$", "nets_host": "^2$"},
            # c1 now moves on to its planned test
            {"shortname": "^leaves.quicktest.tutorial2.files.vm1", "vms": "^vm1$",
             "nets_spawner": "remote", "nets_gateway": "^host1$", "nets_host": "^1$",
             "get_location_vm1": "[\w:/]+ host1/1:/mnt/local/images/swarm",
             "nets_shell_port_host1/1:/mnt/local/images/swarm_vm1": "22"},
            # c2 no longer waits and picks its planned tests reusing setup from c1
            {"shortname": "^leaves.quicktest.tutorial2.names.vm1", "vms": "^vm1$",
             "nets_spawner": "remote", "nets_gateway": "^host1$", "nets_host": "^2$",
             "get_location_vm1": "[\w:/]+ host1/1:/mnt/local/images/swarm",
             "nets_shell_port_host1/1:/mnt/local/images/swarm_vm1": "22"},
            # c3 is done with 1/2 of the setup for client_noop and waits for c4 to provide the other half
            {"shortname": "^leaves.tutorial_gui.client_noop", "vms": "^vm1 vm2$",
             "nets_spawner": "remote", "nets_gateway": "^host2$", "nets_host": "^2$",
             "get_location_image1_vm1": "[\w:/]+ host2/1:/mnt/local/images/swarm", "get_location_image1_vm2": "[\w:/]+ host2/2:/mnt/local/images/swarm",
             "nets_shell_port_host2/1:/mnt/local/images/swarm_image1_vm1": "221", "nets_shell_port_host2/2:/mnt/local/images/swarm_image1_vm2": "222"},
            # continuing with c1 after last considering c4 (starting from first worker again)
            {"shortname": "^leaves.tutorial_gui.client_clicked", "vms": "^vm1 vm2$",
             "nets_spawner": "remote", "nets_gateway": "^host1$", "nets_host": "^1$",
             "get_location_image1_vm1": "[\w:/]+ host2/1:/mnt/local/images/swarm", "get_location_image1_vm2": "[\w:/]+ host2/2:/mnt/local/images/swarm",
             "nets_shell_port_host2/1:/mnt/local/images/swarm_image1_vm1": "221", "nets_shell_port_host2/2:/mnt/local/images/swarm_image1_vm2": "222"},
        ]

        self._run_traversal(graph, self.config["param_dict"])
        # expect three sync (one for each worker without self-sync) and one cleanup call
        self.assertEqual(DummyStateControl.asserted_states["unset"]["guisetup.noop"][self.shared_pool], 1)
        self.assertEqual(DummyStateControl.asserted_states["get"]["guisetup.clicked"][self.shared_pool], 3)

    @skip("Needs node bridging")
    def test_diverging_paths_preparsed(self):
        """Test a multi-object parsed in advance test run where the workers will run multiple tests reusing their setup."""
        self.config["param_dict"]["nets"] = "net1 net2 net3 net4"
        self.config["param_dict"]["slots"] = " ".join([f"{i+1}" for i in range(4)])
        self.config["tests_str"] = "only leaves\n"
        self.config["tests_str"] += "only tutorial2,tutorial_gui\n"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )
        # this is not what we test but simply a means to remove some initial nodes for simpler testing
        DummyStateControl.asserted_states["check"]["install"][self.shared_pool] = True
        DummyStateControl.asserted_states["check"]["customize"][self.shared_pool] = True
        DummyStateControl.asserted_states["check"]["guisetup.noop"] = {self.shared_pool: False}
        DummyStateControl.asserted_states["check"]["guisetup.clicked"] = {self.shared_pool: False}
        DummyStateControl.asserted_states["get"]["guisetup.noop"] = {self.shared_pool: 0}
        DummyStateControl.asserted_states["get"]["guisetup.clicked"] = {self.shared_pool: 0}
        DummyStateControl.asserted_states["unset"] = {"guisetup.noop": {self.shared_pool: 0}}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "nets_host": "^c1$"},
            {"shortname": "^internal.automated.windows_virtuser.vm2", "vms": "^vm2$", "nets_host": "^c2$"},
            # this tests reentry of traversed path by an extra worker c4 reusing setup from c1
            {"shortname": "^internal.automated.linux_virtuser.vm1", "vms": "^vm1$", "nets_host": "^c3$"},
            # c4 would step back from already occupied on_customize (by c1) for the time being
            {"shortname": "^leaves.quicktest.tutorial2.files.vm1", "vms": "^vm1$", "nets_host": "^c1$",
             "get_location_vm1": "[\w:/]+ /c1:/mnt/local/images/swarm"},
            # c2 would step back from already occupied linux_virtuser (by c3) and c3 proceeds instead
            {"shortname": "^leaves.tutorial_gui.client_noop", "vms": "^vm1 vm2$", "nets_host": "^c3$",
             "get_location_image1_vm1": "[\w:/]+ /c3:/mnt/local/images/swarm", "get_location_image1_vm2": "[\w:/]+ /c2:/mnt/local/images/swarm"},
            # c4 now picks up available setup and tests from its own reentered branch
            {"shortname": "^leaves.tutorial_gui.client_clicked", "vms": "^vm1 vm2$", "nets_host": "^c4$",
             "get_location_image1_vm1": "[\w:/]+ /c3:/mnt/local/images/swarm", "get_location_image1_vm2": "[\w:/]+ /c2:/mnt/local/images/swarm"},
            # c1 would now pick its second local tutorial2.names
            {"shortname": "^leaves.quicktest.tutorial2.names.vm1", "vms": "^vm1$", "nets_host": "^c1$",
             "get_location_vm1": "[\w:/]+ /c1:/mnt/local/images/swarm"},
            # all others now step back from already occupied tutorial2.names (by c1)
        ]
        self._run_traversal(graph, self.config["param_dict"])
        # expect three sync (one for each worker without self-sync) and one cleanup call
        self.assertEqual(DummyStateControl.asserted_states["unset"]["guisetup.noop"][self.shared_pool], 1)
        self.assertEqual(DummyStateControl.asserted_states["get"]["guisetup.clicked"][self.shared_pool], 3)

        self._run_traversal(graph, self.config["param_dict"])
        # expect three sync (one for each worker without self-sync) and one cleanup call
        self.assertEqual(DummyStateControl.asserted_states["unset"]["guisetup.noop"][self.shared_pool], 1)
        self.assertEqual(DummyStateControl.asserted_states["get"]["guisetup.clicked"][self.shared_pool], 3)

    def test_cloning_simple_permanent_object(self):
        """Test a complete test run including complex setup that involves permanent vms and cloning."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("leaves..tutorial_get"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"only_vm1": "CentOS", "only_vm2": "Win10", "only_vm3": "Ubuntu",
                                                   "shared_pool": self.shared_pool}))

        DummyStateControl.asserted_states["check"]["root"] = {self.shared_pool: True}
        DummyStateControl.asserted_states["check"].update({"guisetup.noop": {self.shared_pool: False}, "guisetup.clicked": {self.shared_pool: False},
                                                           "getsetup.noop": {self.shared_pool: False}, "getsetup.clicked": {self.shared_pool: False},
                                                           "getsetup.guisetup.noop": {self.shared_pool: False},
                                                           "getsetup.guisetup.clicked": {self.shared_pool: False}})
        # test syncing also for permanent vms
        DummyStateControl.asserted_states["get"]["ready"] = {self.shared_pool: 0}
        # TODO: currently not used due to excluded self-sync but one that is not the correct implementation
        DummyStateControl.asserted_states["get"].update({"guisetup.noop": {self.shared_pool: 0}, "guisetup.clicked": {self.shared_pool: 0},
                                                         "getsetup.noop": {self.shared_pool: 0}, "getsetup.clicked": {self.shared_pool: 0},
                                                         "getsetup.guisetup.noop": {self.shared_pool: 0},
                                                         "getsetup.guisetup.clicked": {self.shared_pool: 0}})
        DummyStateControl.asserted_states["unset"] = {"guisetup.noop": {self.shared_pool: 0},
                                                      "getsetup.noop": {self.shared_pool: 0},
                                                      "ready": {self.shared_pool: 0}}
        DummyTestRun.asserted_tests = [
            # automated setup of vm1 from tutorial_gui
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
            # automated setup of vm1 from tutorial_get
            {"shortname": "^internal.automated.connect.vm1", "vms": "^vm1$"},
            # vm2 image of explicit_noop that the worker started from depends on tutorial_gui which needs another state of vm1
            {"shortname": "^internal.automated.linux_virtuser.vm1", "vms": "^vm1$"},
            # automated setup of vm2 from tutorial_gui
            {"shortname": "^internal.stateless.noop.vm2", "vms": "^vm2$"},
            {"shortname": "^original.unattended_install.cdrom.in_cdrom_ks.default_install.aio_threads.vm2", "vms": "^vm2$"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$"},
            {"shortname": "^internal.automated.windows_virtuser.vm2", "vms": "^vm2$"},
            # first (noop) parent GUI setup dependency through vm2
            {"shortname": "^tutorial_gui.client_noop.vm1.+CentOS.8.0.+vm2.+Win10", "vms": "^vm1 vm2$", "set_state_images_vm2": "guisetup.noop"},
            # first (noop) explicit actual test
            {"shortname": "^leaves.tutorial_get.explicit_noop.vm1", "vms": "^vm1 vm2 vm3$", "get_state_images_vm2": "guisetup.noop"},
            # second (clicked) parent GUI setup dependency through vm2
            {"shortname": "^tutorial_gui.client_clicked.vm1", "vms": "^vm1 vm2$", "set_state_images_vm2": "guisetup.clicked"},
            # second (clicked) explicit actual test
            {"shortname": "^leaves.tutorial_get.explicit_clicked.vm1", "vms": "^vm1 vm2 vm3$", "get_state_images_vm2": "guisetup.clicked"},
            # first (noop) duplicated actual test (child priority to reuse setup)
            {"shortname": "^leaves.tutorial_get.implicit_both.vm1", "vms": "^vm1 vm2 vm3$", "get_state_images_image1_vm2": "guisetup.noop"},
            # second (clicked) duplicated actual test
            {"shortname": "^leaves.tutorial_get.implicit_both.vm1", "vms": "^vm1 vm2 vm3$", "get_state_images_image1_vm2": "guisetup.clicked"},
        ]

        self._run_traversal(graph, self.config["param_dict"])
        # expect a single cleanup call only for the states of enforcing cleanup policy
        # expect four sync and respectively cleanup calls, one for each worker
        self.assertEqual(DummyStateControl.asserted_states["unset"]["guisetup.noop"][self.shared_pool], 1)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["getsetup.noop"][self.shared_pool], 1)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["ready"][self.shared_pool], 0)
        # root state of a permanent vm is not synced from a single worker to itself
        self.assertEqual(DummyStateControl.asserted_states["get"]["ready"][self.shared_pool], 0)

    def test_cloning_simple_cross_object(self):
        """Test a complete test run with multi-variant objects where cloning should not be affected."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("leaves..tutorial_get,leaves..tutorial_gui"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"only_vm1": "", "only_vm2": "", "only_vm3": "Ubuntu",
                                                   "shared_pool": self.shared_pool}))

        DummyStateControl.asserted_states["check"]["root"] = {self.shared_pool: True}
        DummyStateControl.asserted_states["check"].update({"guisetup.noop": {self.shared_pool: False}, "guisetup.clicked": {self.shared_pool: False},
                                                           "getsetup.noop": {self.shared_pool: False}, "getsetup.clicked": {self.shared_pool: False},
                                                           "getsetup.guisetup.noop": {self.shared_pool: False},
                                                           "getsetup.guisetup.clicked": {self.shared_pool: False}})
        DummyStateControl.asserted_states["check"]["install"][self.shared_pool] = True
        DummyStateControl.asserted_states["check"]["customize"][self.shared_pool] = True
        # test syncing also for permanent vms
        DummyStateControl.asserted_states["get"]["ready"] = {self.shared_pool: 0}
        # TODO: currently not used due to excluded self-sync but one that is not the correct implementation
        DummyStateControl.asserted_states["get"].update({"guisetup.noop": {self.shared_pool: 0}, "guisetup.clicked": {self.shared_pool: 0},
                                                         "getsetup.noop": {self.shared_pool: 0}, "getsetup.clicked": {self.shared_pool: 0},
                                                         "getsetup.guisetup.noop": {self.shared_pool: 0},
                                                         "getsetup.guisetup.clicked": {self.shared_pool: 0}})
        DummyStateControl.asserted_states["unset"] = {"guisetup.noop": {self.shared_pool: 0},
                                                      "getsetup.noop": {self.shared_pool: 0},
                                                      "ready": {self.shared_pool: 0}}
        DummyTestRun.asserted_tests = [
            # setup and first setup related leaves
            # automated setup of vm1 of CentOS variant
            {"shortname": "^internal.automated.linux_virtuser.vm1.+CentOS", "vms": "^vm1$"},
            # automated setup of vm2 of Win10 variant
            {"shortname": "^internal.automated.windows_virtuser.vm2.+Win10", "vms": "^vm2$"},
            # first (noop) parent GUI setup dependency through vm2 of Win10 variant
            {"shortname": "^leaves.tutorial_gui.client_noop.vm1.+CentOS.+vm2.+Win10", "vms": "^vm1 vm2$", "set_state_images_vm2": "guisetup.noop"},
            # automated setup of vm2 of Win7 variant
            {"shortname": "^internal.automated.windows_virtuser.vm2.+Win7", "vms": "^vm2$"},
            # first (noop) parent GUI setup dependency through vm2 of Win7 variant
            {"shortname": "^leaves.tutorial_gui.client_noop.vm1.+CentOS.+vm2.+Win7", "vms": "^vm1 vm2$", "set_state_images_vm2": "guisetup.noop"},
            # automated setup of vm1 of Fedora variant, required via extra "tutorial_gui" restriction
            {"shortname": "^internal.automated.linux_virtuser.vm1.+Fedora", "vms": "^vm1$"},
            # GUI test for vm1 of Fedora variant which is not first (noop) dependency through vm2 of Win10 variant (produced with vm1 of CentOS variant)
            {"shortname": "^leaves.tutorial_gui.client_noop.vm1.+Fedora.+vm2.+Win10", "vms": "^vm1 vm2$", "set_state_images_vm2": "guisetup.noop"},

            # pure exploration diverging from own previous paths
            # second (clicked) parent GUI setup dependency through vm2 of Win10 variant
            {"shortname": "^leaves.tutorial_gui.client_clicked.vm1.+CentOS.+vm2.+Win10", "vms": "^vm1 vm2$", "set_state_images_vm2": "guisetup.clicked"},
            # automated setup of vm1 of CentOS variant from tutorial_get
            {"shortname": "^internal.automated.connect.vm1.+CentOS", "vms": "^vm1$"},
            # first (noop) explicit actual test of CentOS+Win10
            {"shortname": "^leaves.tutorial_get.explicit_noop.vm1.+CentOS.+vm2.+Win10", "vms": "^vm1 vm2 vm3$", "get_state_images_vm2": "guisetup.noop"},
            # second (clicked) explicit actual test of CentOS+Win10
            {"shortname": "^leaves.tutorial_get.explicit_clicked.vm1.+CentOS.+vm2.+Win10", "vms": "^vm1 vm2 vm3$", "get_state_images_vm2": "guisetup.clicked"},
            # first (noop) duplicated actual test of CentOS+Win10
            {"shortname": "^leaves.tutorial_get.implicit_both.vm1.+CentOS.+vm2.+Win10", "vms": "^vm1 vm2 vm3$", "get_state_images_image1_vm2": "guisetup.noop"},

            # gradual return to previously discontinued paths
            # second (clicked) parent GUI setup dependency through vm2 of Win7 variant
            {"shortname": "^leaves.tutorial_gui.client_clicked.vm1.+CentOS.+vm2.+Win7", "vms": "^vm1 vm2$", "set_state_images_vm2": "guisetup.clicked"},
            # second (clicked) duplicated actual test of CentOS+Win7
            {"shortname": "^leaves.tutorial_get.implicit_both.vm1.+CentOS.+vm2.+Win7", "vms": "^vm1 vm2 vm3$", "get_state_images_image1_vm2": "guisetup.clicked"},
            # first (noop) duplicated actual test of CentOS+Win7
            {"shortname": "^leaves.tutorial_get.implicit_both.vm1.+CentOS.+vm2.+Win7", "vms": "^vm1 vm2 vm3$", "get_state_images_image1_vm2": "guisetup.noop"},
            # second (clicked) duplicated actual test of CentOS+Win10
            {"shortname": "^leaves.tutorial_get.implicit_both.vm1.+CentOS.+vm2.+Win10", "vms": "^vm1 vm2 vm3$", "get_state_images_image1_vm2": "guisetup.clicked"},
            # second (clicked) explicit actual test of CentOS+Win7
            {"shortname": "^leaves.tutorial_get.explicit_clicked.vm1.+CentOS.+vm2.+Win7", "vms": "^vm1 vm2 vm3$", "get_state_images_vm2": "guisetup.clicked"},
            # first (noop) explicit actual test of CentOS+Win7
            {"shortname": "^leaves.tutorial_get.explicit_noop..+CentOS.+vm2.+Win7", "vms": "^vm1 vm2 vm3$", "get_state_images_vm2": "guisetup.noop"},
            # GUI test for vm1 of Fedora variant which is not second (clicked) dependency through vm2 of Win10 variant (produced with vm1 of CentOS variant)
            {"shortname": "^leaves.tutorial_gui.client_clicked.vm1.+Fedora.+vm2.+Win10", "vms": "^vm1 vm2$", "set_state_images_vm2": "guisetup.clicked"},
            # GUI test for vm1 of Fedora variant which is not second (clicked) dependency through vm2 of Win7 variant (produced with vm1 of CentOS variant)
            {"shortname": "^leaves.tutorial_gui.client_clicked.vm1.+Fedora.+vm2.+Win7", "vms": "^vm1 vm2$", "set_state_images_vm2": "guisetup.clicked"},
            # GUI test for vm1 of Fedora variant which is not first (noop) dependency through vm2 of Win7 variant (produced with vm1 of CentOS variant)
            {"shortname": "^leaves.tutorial_gui.client_noop.vm1.+Fedora.+vm2.+Win7", "vms": "^vm1 vm2$", "set_state_images_vm2": "guisetup.noop"},
        ]

        self._run_traversal(graph, self.config["param_dict"])
        # expect four cleanups of four different variant product states
        self.assertEqual(DummyStateControl.asserted_states["unset"]["guisetup.noop"][self.shared_pool], 4)
        # expect two cleanups of two different variant product states (vm1 variant restricted)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["getsetup.noop"][self.shared_pool], 2)

    def test_cloning_deep(self):
        """Test for correct deep cloning."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("leaves..tutorial_finale"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"only_vm1": "CentOS", "only_vm2": "Win10", "only_vm3": "Ubuntu"}))

        DummyStateControl.asserted_states["check"]["install"][self.shared_pool] = True
        DummyStateControl.asserted_states["check"]["customize"][self.shared_pool] = True
        DummyStateControl.asserted_states["check"].update({"guisetup.noop": {self.shared_pool: False}, "guisetup.clicked": {self.shared_pool: False},
                                                           "getsetup.guisetup.noop": {self.shared_pool: False},
                                                           "getsetup.guisetup.clicked": {self.shared_pool: False}})
        # TODO: currently not used due to excluded self-sync but one that is not the correct implementation
        DummyStateControl.asserted_states["get"].update({"guisetup.noop": {self.shared_pool: 0}, "guisetup.clicked": {self.shared_pool: 0},
                                                         "getsetup.guisetup.noop": {self.shared_pool: 0},
                                                         "getsetup.guisetup.clicked": {self.shared_pool: 0}})
        DummyStateControl.asserted_states["unset"] = {"guisetup.noop": {self.shared_pool: 0}, "getsetup.noop": {self.shared_pool: 0}}
        DummyTestRun.asserted_tests = [
            # extra dependency dependency through vm1
            {"shortname": "^internal.automated.connect.vm1", "vms": "^vm1$"},
            # automated setup of vm1
            {"shortname": "^internal.automated.linux_virtuser.vm1", "vms": "^vm1$"},
            # automated setup of vm2
            {"shortname": "^internal.automated.windows_virtuser.vm2", "vms": "^vm2$"},
            # first (noop) parent GUI setup dependency through vm2
            {"shortname": "^tutorial_gui.client_noop", "vms": "^vm1 vm2$", "set_state_images_vm2": "guisetup.noop"},
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
        # expect a single cleanup call only for the states of enforcing cleanup policy
        self.assertEqual(DummyStateControl.asserted_states["unset"]["guisetup.noop"][self.shared_pool], 1)

    def test_dry_run(self):
        """Test a complete dry run traversal of a graph."""
        graph = TestGraph()
        # TODO: cannot parse "all" with flat nodes with largest available test set being "leaves"
        graph.new_nodes(TestGraph.parse_flat_nodes("leaves"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": " ".join([f"{i+1}" for i in range(3)])}))

        DummyStateControl.asserted_states["check"].update({"guisetup.noop": {self.shared_pool: False}, "guisetup.clicked": {self.shared_pool: False},
                                                           "getsetup.noop": {self.shared_pool: False}, "getsetup.clicked": {self.shared_pool: False},
                                                           "getsetup.guisetup.noop": {self.shared_pool: False},
                                                           "getsetup.guisetup.clicked": {self.shared_pool: False}})
        DummyTestRun.asserted_tests = [
        ]

        self._run_traversal(graph, {"dry_run": "yes"})
        for action in ["get", "set", "unset"]:
            for state in DummyStateControl.asserted_states[action]:
                self.assertEqual(DummyStateControl.asserted_states[action][state][self.shared_pool], 0)

    @skip("Needs node bridging")
    def test_abort_run(self):
        """Test that traversal is aborted through explicit configuration."""
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("tutorial1"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": " ".join([f"{i+1}" for i in range(3)]),
                                                   "only_vm1": "CentOS"}))

        DummyStateControl.asserted_states["check"]["install"][self.shared_pool] = True
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "set_state_vms_on_error": "^$", "_status": "FAIL"},
        ]

        with self.assertRaisesRegex(exceptions.TestSkipError, r"^God wanted this test to abort$"):
            self._run_traversal(graph, {"abort_on_error": "yes"})

    def test_abort_objectless_node(self):
        """Test that traversal is aborted on objectless node detection."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"]["nets"] = "net1"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )
        test_node = graph.get_node_by(param_val="tutorial1")
        # assume we are parsing invalid configuration
        test_node.params["vms"] = ""
        DummyStateControl.asserted_states["check"]["install"][self.shared_pool] = True
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$"},
        ]
        with self.assertRaisesRegex(AssertionError, r"^Cannot run test nodes not using any test objects"):
            self._run_traversal(graph, self.config["param_dict"])

    def test_parsing_on_demand(self):
        """Test that parsing on demand works as expected."""
        # make sure to parse flat nodes (with CentOS restriction) that will never be composed with any objects
        self.config["vm_strs"]["vm1"] = "only Fedora\n"

        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("leaves"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": " ".join([f"{i+1}" for i in range(3)])}))

        # wrap the on-demand parsing within a mock as a spy option
        actual_parsing = graph.parse_paths_to_object_roots
        graph.parse_paths_to_object_roots = mock.MagicMock()
        graph.parse_paths_to_object_roots.side_effect = actual_parsing

        DummyStateControl.asserted_states["check"].update({"guisetup.noop": {self.shared_pool: False}, "guisetup.clicked": {self.shared_pool: False},
                                                           "getsetup.noop": {self.shared_pool: False}, "getsetup.clicked": {self.shared_pool: False},
                                                           "getsetup.guisetup.noop": {self.shared_pool: False},
                                                           "getsetup.guisetup.clicked": {self.shared_pool: False}})
        DummyTestRun.asserted_tests = [
        ]

        self._run_traversal(graph, {"dry_run": "yes"})

        # all flat nodes must be unrolled once and must have parsed paths
        flat_nodes = [node for node in graph.nodes if node.is_flat()]
        self.assertEqual(graph.parse_paths_to_object_roots.call_count, len(flat_nodes) * 3)
        for node in flat_nodes:
            for i in range(3):
                worker = graph.workers[f"net{i+1}"]
                self.assertTrue(node.is_unrolled(worker))
                graph.parse_paths_to_object_roots.assert_any_call(node, worker.net, mock.ANY)
        # the graph has a specific connectedness with the shared root
        shared_roots = graph.get_nodes_by("shared_root", "yes")
        assert len(shared_roots) == 1, "There can be only exactly one starting node (shared root)"
        root = shared_roots[0]
        for node in graph.nodes:
            if node in root.cleanup_nodes:
                self.assertTrue(node.is_flat() or node.is_object_root())

    def test_rerun_max_times(self):
        """Test that the test is tried `max_tries` times if no status is not specified."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"]["max_tries"] = "3"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            "", self.config["vm_strs"],
            self.config["param_dict"],
        )
        DummyTestRun.asserted_tests = [
            {"shortname": r"^internal.stateless.noop.vm1", "vms": r"^vm1$"},
            {"shortname": r"^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": r"^vm1$"},
            {"shortname": r"^internal.stateless.noop.vm1", "vms": r"^vm1$"},
            {"shortname": r"^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": r"^vm1$"},
            {"shortname": r"^internal.stateless.noop.vm1", "vms": r"^vm1$"},
            {"shortname": r"^original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm1", "vms": r"^vm1$"},
            {"shortname": r"^internal.automated.customize.vm1", "vms": r"^vm1$"},
            {"shortname": r"^internal.automated.customize.vm1", "vms": r"^vm1$", "_long_prefix": r"^[a\d]+r1-vm1$"},
            {"shortname": r"^internal.automated.customize.vm1", "vms": r"^vm1$", "_long_prefix": r"^[a\d]+r2-vm1$"},
            {"shortname": r"^internal.automated.on_customize.vm1", "vms": r"^vm1$"},
            {"shortname": r"^internal.automated.on_customize.vm1", "vms": r"^vm1$", "_long_prefix": r"^[a\d]+r1-vm1$"},
            {"shortname": r"^internal.automated.on_customize.vm1", "vms": r"^vm1$", "_long_prefix": r"^[a\d]+r2-vm1$"},
            {"shortname": r"^normal.nongui.quicktest.tutorial1.vm1", "vms": r"^vm1$"},
            {"shortname": r"^normal.nongui.quicktest.tutorial1.vm1", "vms": r"^vm1$", "_long_prefix": r"^[a\d]+r1-vm1$"},
            {"shortname": r"^normal.nongui.quicktest.tutorial1.vm1", "vms": r"^vm1$", "_long_prefix": r"^[a\d]+r2-vm1$"},
        ]
        self._run_traversal(graph)

    def test_rerun_status_times(self):
        """Test that valid statuses are considered when retrying a test."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"]["nets"] = "net1"
        self.config["param_dict"]["max_tries"] = "4"
        self.config["param_dict"]["stop_status"] = ""

        # test should be re-run on these statuses
        for status in ["PASS", "WARN", "FAIL", "ERROR", "SKIP", "INTERRUPTED", "CANCEL"]:
            with self.subTest(f"Test rerun on status {status}"):
                graph = TestGraph.parse_object_trees(
                    None, self.config["tests_str"],
                    self.prefix, self.config["vm_strs"],
                    self.config["param_dict"],
                )
                DummyStateControl.asserted_states["check"] = {"root": {self.shared_pool: True}, "install": {self.shared_pool: True},
                                                              "customize": {self.shared_pool: True}, "on_customize": {self.shared_pool: True}}
                DummyTestRun.asserted_tests = [
                    {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
                    {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
                    {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
                    {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
                ]
                self._run_traversal(graph)

                # assert that tests were repeated
                self.assertEqual(len(self.runner.job.result.tests), 4)
                self.assertEqual(len(graph.get_node_by(param_val="tutorial1").results), 4)
                # also assert the correct results were registered
                self.assertEqual([x["status"] for x in self.runner.job.result.tests], [status] * 4)
                self.assertEqual(self.runner.job.result.tests, graph.get_node_by(param_val="tutorial1").results)
                # the test graph and thus the test node is recreated
                self.runner.job.result.tests.clear()

    def test_rerun_status_stop(self):
        """Test that the `stop_status` parameter lets the traversal continue as usual."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"]["nets"] = "net1"
        self.config["param_dict"]["max_tries"] = "3"

        # expect success and get success -> should run only once
        for stop_status in ["pass", "warn", "fail", "error"]:
            with self.subTest(f"Test rerun stop on status {stop_status}"):
                self.config["param_dict"]["stop_status"] = stop_status
                status = stop_status.upper()
                graph = TestGraph.parse_object_trees(
                    None, self.config["tests_str"],
                    self.prefix, self.config["vm_strs"],
                    self.config["param_dict"],
                )
                DummyStateControl.asserted_states["check"] = {"root": {self.shared_pool: True}, "install": {self.shared_pool: True},
                                                              "customize": {self.shared_pool: True}, "on_customize": {self.shared_pool: True}}
                DummyTestRun.asserted_tests = [
                    {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
                ]
                self._run_traversal(graph)

                # assert that tests were not repeated
                self.assertEqual(len(self.runner.job.result.tests), 1)
                self.assertEqual(len(graph.get_node_by(param_val="tutorial1").results), 1)
                # also assert the correct results were registered
                self.assertEqual([x["status"] for x in self.runner.job.result.tests], [status])
                self.assertEqual(self.runner.job.result.tests, graph.get_node_by(param_val="tutorial1").results)
                # the test graph and thus the test node is recreated
                self.runner.job.result.tests.clear()

    def test_rerun_status_rerun(self):
        """Test that the `rerun_status` parameter keep the traversal repeating a run."""
        self.config["tests_str"] += "only tutorial1\n"
        self.config["param_dict"]["nets"] = "net1"
        self.config["param_dict"]["max_tries"] = "3"

        # expect success and get success -> should run only once
        for stop_status in ["pass", "warn", "fail", "error"]:
            with self.subTest(f"Test rerun stop on status {stop_status}"):
                self.config["param_dict"]["rerun_status"] = stop_status
                status = stop_status.upper()
                graph = TestGraph.parse_object_trees(
                    None, self.config["tests_str"],
                    self.prefix, self.config["vm_strs"],
                    self.config["param_dict"],
                )
                DummyStateControl.asserted_states["check"] = {"root": {self.shared_pool: True}, "install": {self.shared_pool: True},
                                                              "customize": {self.shared_pool: True}, "on_customize": {self.shared_pool: True}}
                DummyTestRun.asserted_tests = [
                    {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : status},
                    {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "INTERRUPTED"},
                ]
                self._run_traversal(graph)

                # assert that tests were not repeated
                self.assertEqual(len(self.runner.job.result.tests), 2)
                self.assertEqual(len(graph.get_node_by(param_val="tutorial1").results), 2)
                # also assert the correct results were registered
                self.assertEqual([x["status"] for x in self.runner.job.result.tests], [status, "INTERRUPTED"])
                self.assertEqual(self.runner.job.result.tests, graph.get_node_by(param_val="tutorial1").results)
                # the test graph and thus the test node is recreated
                self.runner.job.result.tests.clear()

    def test_rerun_previous_job_default(self):
        """Test that rerunning a previous job gives more tries and works reasonably."""
        # need proper previous results from full nodes
        self.config["param_dict"] = {"nets": "net1"}
        self.config["tests_str"] = "only leaves..tutorial2\n"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )
        node1, node2 = graph.get_nodes_by(param_val="tutorial2")
        # results from the previous job (inclusive of setup that should now be skipped)
        self.runner.previous_results += [{"name": graph.get_node_by(param_val="on_customize").params["name"], "status": "PASS", "time": 1}]
        self.runner.previous_results += [{"name": node1.params["name"], "status": "PASS", "time": 1}]
        self.runner.previous_results += [{"name": node2.params["name"], "status": "FAIL", "time": 0.2}]

        # include flat and other types of nodes by traversing partially parsed graph
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("leaves..tutorial2"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": "1", "only_vm1": "CentOS"}))
        DummyStateControl.asserted_states["check"] = {"root": {self.shared_pool: True}, "install": {self.shared_pool: True},
                                                      "customize": {self.shared_pool: True}, "on_customize": {self.shared_pool: True}}
        DummyTestRun.asserted_tests = [
            # skip the previously passed test since it doesn't have a rerun status and rerun second test
            {"shortname": "^leaves.quicktest.tutorial2.names.vm1", "vms": "^vm1$"},
        ]
        self._run_traversal(graph, {"replay": "previous_job"})

        node1, node2 = graph.get_nodes_by(param_val="tutorial2.+vm1")
        # assert that tests were repeated only when needed
        self.assertEqual(len(self.runner.job.result.tests), 1)
        self.assertEqual(len(node1.results), 1)
        self.assertEqual(len(node2.results), 2)
        # also assert the correct results were registered
        self.assertEqual([x["status"] for x in self.runner.job.result.tests], ["PASS"])
        self.assertEqual([x["status"] for x in node1.results], ["PASS"])
        self.assertEqual([x["status"] for x in node2.results], ["FAIL", "PASS"])
        self.assertEqual(self.runner.job.result.tests, node2.results[1:])

    def test_rerun_previous_job_status(self):
        """Test that rerunning a previous job gives more tries and works reasonably."""
        # need proper previous results from full nodes
        self.config["param_dict"] = {"nets": "net1"}
        self.config["tests_str"] = "only leaves..tutorial2\n"
        graph = TestGraph.parse_object_trees(
            None, self.config["tests_str"],
            self.prefix, self.config["vm_strs"],
            self.config["param_dict"],
        )
        node1, node2 = graph.get_nodes_by(param_val="tutorial2")
        # results from the previous job (inclusive of setup that should now be skipped)
        self.runner.previous_results += [{"name": graph.get_node_by(param_val="on_customize").params["name"], "status": "PASS", "time": 1}]
        self.runner.previous_results += [{"name": node1.params["name"], "status": "PASS", "time": 1}]
        self.runner.previous_results += [{"name": node2.params["name"], "status": "FAIL", "time": 0.2}]

        # include flat and other types of nodes by traversing partially parsed graph
        graph = TestGraph()
        graph.new_nodes(TestGraph.parse_flat_nodes("leaves..tutorial2"))
        graph.parse_shared_root_from_object_roots()
        graph.new_workers(TestGraph.parse_workers({"slots": "1", "only_vm1": "CentOS"}))
        DummyStateControl.asserted_states["check"] = {"root": {self.shared_pool: True}, "install": {self.shared_pool: True},
                                                      "customize": {self.shared_pool: True}, "on_customize": {self.shared_pool: True}}
        DummyTestRun.asserted_tests = [
            # previously run setup tests with rerun status are still rerun (scan is overriden)
            {"shortname": "^internal.automated.on_customize.vm1", "vms": "^vm1$", "get_state_images": "^customize$", "set_state_vms": "^on_customize$"},
            # skip the previously passed test since it doesn't have a rerun status and rerun second test
            {"shortname": "^leaves.quicktest.tutorial2.files.vm1", "vms": "^vm1$"},
        ]
        self._run_traversal(graph, {"replay": "previous_job", "rerun_status": "pass"})

        node1, node2 = graph.get_nodes_by(param_val="tutorial2.+vm1")
        # assert that tests were repeated only when needed
        self.assertEqual(len(self.runner.job.result.tests), 2)
        self.assertEqual(len(node1.results), 2)
        self.assertEqual(len(node2.results), 1)
        # also assert the correct results were registered
        self.assertEqual([x["status"] for x in self.runner.job.result.tests], ["PASS", "PASS"])
        self.assertEqual([x["status"] for x in node1.results], ["PASS", "PASS"])
        self.assertEqual([x["status"] for x in node2.results], ["FAIL"])
        self.assertEqual(self.runner.job.result.tests[1:], node1.results[1:])

    def test_rerun_invalid(self):
        """Test if an exception is thrown with invalid retry parameter values."""
        self.config["tests_str"] += "only tutorial1\n"
        DummyStateControl.asserted_states["check"] = {"root": {self.shared_pool: True}, "install": {self.shared_pool: True},
                                                      "customize": {self.shared_pool: True}, "on_customize": {self.shared_pool: True}}

        DummyTestRun.asserted_tests = [
                    {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]
        with mock.patch.dict(self.config["param_dict"], {"max_tries": "3",
                                                         "stop_status": "invalid"}):
            graph = TestGraph.parse_object_trees(
                None, self.config["tests_str"],
                self.prefix, self.config["vm_strs"],
                self.config["param_dict"],
            )
            with self.assertRaisesRegex(ValueError, r"^Value of stop status must be a valid test status"):
                self._run_traversal(graph)

        # negative values
        DummyTestRun.asserted_tests = [
                    {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]
        with mock.patch.dict(self.config["param_dict"], {"max_tries": "-32",
                                                         "stop_status": ""}):
            graph = TestGraph.parse_object_trees(
                None, self.config["tests_str"],
                self.prefix, self.config["vm_strs"],
                self.config["param_dict"],
            )
            with self.assertRaisesRegex(ValueError, r"^Number of max_tries cannot be less than zero$"):
                self._run_traversal(graph)

        # floats
        DummyTestRun.asserted_tests = [
                    {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]
        with mock.patch.dict(self.config["param_dict"], {"max_tries": "3.5",
                                                         "stop_status": ""}):
            graph = TestGraph.parse_object_trees(
                None, self.config["tests_str"],
                self.prefix, self.config["vm_strs"],
                self.config["param_dict"],
            )
            with self.assertRaisesRegex(ValueError, r"^invalid literal for int"):
                self._run_traversal(graph)

        # non-integers
        DummyTestRun.asserted_tests = [
                    {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$"},
        ]
        with mock.patch.dict(self.config["param_dict"], {"max_tries": "hey",
                                                         "stop_status": ""}):
            graph = TestGraph.parse_object_trees(
                None, self.config["tests_str"],
                self.prefix, self.config["vm_strs"],
                self.config["param_dict"],
            )
            with self.assertRaisesRegex(ValueError, r"^invalid literal for int"):
                self._run_traversal(graph)

    def test_run_warn_duration(self):
        """Test that a good test status is converted to warning if test takes too long."""
        self.config["tests_str"] += "only tutorial1\n"

        flat_net = TestGraph.parse_net_from_object_strs("net1", self.config["vm_strs"])
        test_objects = TestGraph.parse_components_for_object(flat_net, "nets", params=self.config["param_dict"], unflatten=True)
        net = test_objects[-1]
        test_node = TestGraph.parse_node_from_object(net, "normal..tutorial1", params=self.config["param_dict"].copy())

        test_node.results = [{"status": "PASS", "time": 3}]
        DummyTestRun.asserted_tests = [
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status": "PASS", "_time": "10"},
        ]
        to_run = self.runner.run_test_node(test_node)
        status = asyncio.get_event_loop().run_until_complete(asyncio.wait_for(to_run, None))
        self.assertTrue(status)
        # the test succeed but too long so its status must be changed to WARN
        self.assertEqual(test_node.results[-1]["status"], "WARN")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_run_exit_code(self):
        """Test that the test status is properly converted to a simple exit status."""
        self.config["tests_str"] += "only tutorial1\n"

        flat_net = TestGraph.parse_net_from_object_strs("net1", self.config["vm_strs"])
        test_objects = TestGraph.parse_components_for_object(flat_net, "nets", params=self.config["param_dict"], unflatten=True)
        net = test_objects[-1]
        test_node = TestGraph.parse_node_from_object(net, "normal..tutorial1", params=self.config["param_dict"].copy())

        DummyTestRun.asserted_tests = [
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
        ]
        to_run = self.runner.run_test_node(test_node)
        status = asyncio.get_event_loop().run_until_complete(asyncio.wait_for(to_run, None))
        # all runs succeed - status must be True
        self.assertTrue(status)
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        self.runner.job.result.tests.clear()
        test_node.results.clear()

        DummyTestRun.asserted_tests = [
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "FAIL"},
        ]
        to_run = self.runner.run_test_node(test_node)
        status = asyncio.get_event_loop().run_until_complete(asyncio.wait_for(to_run, None))
        # last run fails - status must be False
        self.assertFalse(status, "Runner did not preserve last run fail status")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        self.runner.job.result.tests.clear()
        test_node.results.clear()

        DummyTestRun.asserted_tests = [
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "FAIL"},
            {"shortname": "^normal.nongui.quicktest.tutorial1.vm1", "vms": "^vm1$", "_status" : "PASS"},
        ]
        to_run = self.runner.run_test_node(test_node)
        _ = asyncio.get_event_loop().run_until_complete(asyncio.wait_for(to_run, None))
        to_run = self.runner.run_test_node(test_node)
        status = asyncio.get_event_loop().run_until_complete(asyncio.wait_for(to_run, None))
        # only previous run fails - status must be True
        self.assertTrue(status, "Runner did not preserve last run fail status")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        self.runner.job.result.tests.clear()
        test_node.results.clear()

    @mock.patch('avocado_i2n.runner.StatusRepo')
    @mock.patch('avocado_i2n.runner.StatusServer')
    @mock.patch('avocado_i2n.runner.TestGraph')
    @mock.patch('avocado_i2n.loader.TestGraph')
    def test_loader_runner_entries(self, mock_load_graph, mock_run_graph,
                                   mock_status_server, _mock_status_repo):
        """Test that the default loader and runner entries work as expected."""
        self.config["tests_str"] += "only tutorial1\n"
        reference = "only=tutorial1 key1=val1"
        self.config["params"] = reference.split()
        self.config["prefix"] = ""
        self.config["subcommand"] = "run"

        mock_load_graph.parse_flat_nodes.return_value = [mock.MagicMock(prefix="1"),
                                                         mock.MagicMock(prefix="2")]

        self.loader.config = self.config
        resolutions = [self.loader.resolve(reference)]
        mock_load_graph.parse_flat_nodes.assert_called_with(self.config["tests_str"],
                                                            self.config["param_dict"])
        runnables = resolutions_to_runnables(resolutions, self.config)
        test_suite = TestSuite('suite',
                               config=self.config,
                               tests=runnables,
                               resolutions=resolutions)
        self.assertEqual(len(test_suite), 2)

        # test status result collection needs a lot of extra mocking as a boundary
        async def create_server(): pass
        async def serve_forever(): pass
        server_instance = mock_status_server.return_value
        server_instance.create_server = create_server
        server_instance.serve_forever = serve_forever
        self.runner._update_status = mock.AsyncMock()

        run_graph_instance = mock_run_graph.return_value
        run_graph_instance.traverse_object_trees = mock.AsyncMock()
        run_graph_workers = run_graph_instance.workers.values.return_value = [mock.MagicMock()]
        run_graph_workers[0].params = {"runtime_str": "", "name": "net1"}

        self.runner.job.config = self.config
        self.runner.run_suite(self.runner.job, test_suite)
        run_graph_instance.parse_shared_root_from_object_roots.assert_called_once()
        mock_run_graph.parse_workers.assert_called_once()
        run_graph_workers[0].set_up.assert_called()
        run_graph_instance.traverse_object_trees.assert_called()


if __name__ == '__main__':
    unittest.main()
