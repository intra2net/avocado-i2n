#!/usr/bin/env python

import unittest
import unittest.mock as mock
import contextlib
import re

from avocado import Test
from virttest import utils_params

import unittest_importer
from unittest_utils import DummyTestRun, DummyStateControl
from avocado_i2n import intertest_setup
from avocado_i2n.runner import CartesianRunner


@contextlib.contextmanager
def new_job(config):
    # jobless run delegation - simply pass to another mock function
    job = mock.MagicMock()
    job.logdir = "."
    job.timeout = 60
    job.config = config
    job.result.tests = []

    loader, runner = config["graph"].l, config["graph"].r
    loader.logdir = job.logdir
    runner.job = job
    runner.slots = config["param_dict"].get("slots", "localhost").split(" ")

    yield job


@mock.patch('avocado_i2n.intertest_setup.new_job', new_job)
@mock.patch('avocado_i2n.cartgraph.node.remote.wait_for_login', mock.MagicMock())
@mock.patch('avocado_i2n.cartgraph.node.door', DummyStateControl)
@mock.patch('avocado_i2n.cartgraph.node.SpawnerDispatcher', mock.MagicMock())
@mock.patch.object(CartesianRunner, 'run_test', DummyTestRun.mock_run_test)
class IntertestSetupTest(Test):

    def setUp(self):
        DummyTestRun.asserted_tests = []
        self.shared_pool = "/:/mnt/local/images/shared"

        self.config = {}
        self.config["available_vms"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n", "vm3": "only Ubuntu\n"}
        self.config["available_restrictions"] = ["leaves", "normal", "minimal"]
        self.config["param_dict"] = {"slots": "1"}
        self.config["vm_strs"] = self.config["available_vms"].copy()
        self.config["tests_str"] = {}
        self.config["tests_params"] = utils_params.Params()
        self.config["vms_params"] = utils_params.Params()

    def test_update_default(self):
        """Test the general usage of the manual update-cache tool."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyStateControl.asserted_states["unset"] = {"install": {self.shared_pool: 0},
                                                      "customize": {self.shared_pool: 0}, "on_customize": {self.shared_pool: 0},
                                                      "connect": {self.shared_pool: 0},
                                                      "linux_virtuser": {self.shared_pool: 0}, "windows_virtuser": {self.shared_pool: 0},
                                                      "guisetup.noop": {self.shared_pool: 0}, "guisetup.clicked": {self.shared_pool: 0},
                                                      "getsetup.noop": {self.shared_pool: 0}, "getsetup.guisetup.noop": {self.shared_pool: 0},
                                                      "getsetup.clicked": {self.shared_pool: 0}, "getsetup.guisetup.clicked": {self.shared_pool: 0}}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-8.*\.iso$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.noop.vm2", "vms": "^vm2$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$"},
        ]
        intertest_setup.update(self.config, tag="1r")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        # states along the updated path are not be removed
        self.assertEqual(DummyStateControl.asserted_states["unset"]["install"][self.shared_pool], 0)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["customize"][self.shared_pool], 0)
        # states after the updated path will be removed (default remove set is the entire graph)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["on_customize"][self.shared_pool], 2)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["connect"][self.shared_pool], 1)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["guisetup.clicked"][self.shared_pool], 1)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["getsetup.clicked"][self.shared_pool], 1)

    def test_update_custom(self):
        """Test the state customized usage of the manual update-cache tool."""
        self.config["vms_params"]["from_state_vm1"] = "customize"
        self.config["vms_params"]["from_state_vm2"] = "install"
        self.config["vms_params"]["to_state_vm1"] = "connect"
        self.config["vms_params"]["to_state_vm2"] = "customize"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyStateControl.asserted_states["unset"] = {"install": {self.shared_pool: 0},
                                                      "customize": {self.shared_pool: 0}, "on_customize": {self.shared_pool: 0},
                                                      "connect": {self.shared_pool: 0},
                                                      "linux_virtuser": {self.shared_pool: 0}, "windows_virtuser": {self.shared_pool: 0},
                                                      "guisetup.noop": {self.shared_pool: 0}, "guisetup.clicked": {self.shared_pool: 0},
                                                      "getsetup.noop": {self.shared_pool: 0}, "getsetup.guisetup.noop": {self.shared_pool: 0},
                                                      "getsetup.clicked": {self.shared_pool: 0}, "getsetup.guisetup.clicked": {self.shared_pool: 0}}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_images": "^install$"},
            {"shortname": "^internal.automated.connect.vm1", "vms": "^vm1$", "get_state_images": "^customize$"},
            {"shortname": "^internal.stateless.noop.vm2", "vms": "^vm2$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm2", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$", "get_state_images": "^install$"},
        ]
        intertest_setup.update(self.config, tag="1r")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        # states before the updated path are not be removed
        self.assertEqual(DummyStateControl.asserted_states["unset"]["install"][self.shared_pool], 0)
        # states along the updated path are not be removed
        self.assertEqual(DummyStateControl.asserted_states["unset"]["customize"][self.shared_pool], 0)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["connect"][self.shared_pool], 0)
        # states after the updated path will be removed (default remove set is the entire graph)
        # TODO: states derived from all nodes along the path must be removed and not just from the end of the path (need 2 on_customize)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["on_customize"][self.shared_pool], 1)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["guisetup.clicked"][self.shared_pool], 1)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["getsetup.clicked"][self.shared_pool], 1)

    def test_update_custom_parallel(self):
        """Test the state customized usage of the manual update-cache tool."""
        self.config["param_dict"]["slots"] = "1 2"
        self.config["vms_params"]["from_state_vm1"] = "customize"
        self.config["vms_params"]["from_state_vm2"] = "install"
        self.config["vms_params"]["to_state_vm1"] = "connect"
        self.config["vms_params"]["to_state_vm2"] = "customize"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyStateControl.asserted_states["unset"] = {"install": {self.shared_pool: 0},
                                                      "customize": {self.shared_pool: 0}, "on_customize": {self.shared_pool: 0},
                                                      "connect": {self.shared_pool: 0},
                                                      "linux_virtuser": {self.shared_pool: 0}, "windows_virtuser": {self.shared_pool: 0},
                                                      "guisetup.noop": {self.shared_pool: 0}, "guisetup.clicked": {self.shared_pool: 0},
                                                      "getsetup.noop": {self.shared_pool: 0}, "getsetup.guisetup.noop": {self.shared_pool: 0},
                                                      "getsetup.clicked": {self.shared_pool: 0}, "getsetup.guisetup.clicked": {self.shared_pool: 0}}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_images": "^install$", "nets_host": "^c1$"},
            {"shortname": "^internal.stateless.noop.vm2", "vms": "^vm2$", "type": "^shared_configure_install$", "nets_host": "^c2$"},
            {"shortname": "^internal.automated.connect.vm1", "vms": "^vm1$", "get_state_images": "^customize$", "nets_host": "^c1$"},
            {"shortname": "^original.unattended_install.*vm2", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$", "nets_host": "^c2$"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$", "get_state_images": "^install$", "nets_host": "^c2$"},
        ]
        intertest_setup.update(self.config, tag="1r")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        # states before the updated path are not be removed
        self.assertEqual(DummyStateControl.asserted_states["unset"]["install"][self.shared_pool], 0)
        # states along the updated path are not be removed
        self.assertEqual(DummyStateControl.asserted_states["unset"]["customize"][self.shared_pool], 0)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["connect"][self.shared_pool], 0)
        # states after the updated path will be removed (default remove set is the entire graph)
        # TODO: states derived from all nodes along the path must be removed and not just from the end of the path (need 4 on_customize)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["on_customize"][self.shared_pool], 2)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["guisetup.clicked"][self.shared_pool], 2)
        self.assertEqual(DummyStateControl.asserted_states["unset"]["getsetup.clicked"][self.shared_pool], 2)

    def test_update_install(self):
        """Test the install-only state customized usage of the manual update-cache tool."""
        self.config["vms_params"]["from_state"] = "install"
        self.config["vms_params"]["to_state"] = "install"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyStateControl.asserted_states["unset"] = {"install": {self.shared_pool: 0},
                                                      "customize": {self.shared_pool: 0}, "on_customize": {self.shared_pool: 0},
                                                      "connect": {self.shared_pool: 0},
                                                      "linux_virtuser": {self.shared_pool: 0}, "windows_virtuser": {self.shared_pool: 0},
                                                      "guisetup.noop": {self.shared_pool: 0}, "guisetup.clicked": {self.shared_pool: 0},
                                                      "getsetup.noop": {self.shared_pool: 0}, "getsetup.guisetup.noop": {self.shared_pool: 0},
                                                      "getsetup.clicked": {self.shared_pool: 0}, "getsetup.guisetup.clicked": {self.shared_pool: 0}}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-8.*\.iso$"},
            {"shortname": "^internal.stateless.noop.vm2", "vms": "^vm2$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm2", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$"},
        ]
        intertest_setup.update(self.config, tag="1r")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        for unset_state in DummyStateControl.asserted_states["unset"]:
            if unset_state == "install":
                self.assertEqual(DummyStateControl.asserted_states["unset"][unset_state][self.shared_pool], 0)
            else:
                self.assertGreater(DummyStateControl.asserted_states["unset"][unset_state][self.shared_pool], 0)

    def test_update_remove_set(self):
        """Test the remove set usage of the manual update-cache tool."""
        self.config["vms_params"]["remove_set"] = "minimal"
        self.config["vm_strs"] = {"vm1": "only CentOS\n"}
        DummyStateControl.asserted_states["unset"] = {"on_customize": {self.shared_pool: 0}, "connect": {self.shared_pool: 0}}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-8.*\.iso$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
        ]
        intertest_setup.update(self.config, tag="0")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        # states within the remove set would be removed if they are descendants of updated test node
        self.assertEqual(DummyStateControl.asserted_states["unset"]["on_customize"][self.shared_pool], 1)
        # states outside of the remove set would not be touched
        self.assertEqual(DummyStateControl.asserted_states["unset"]["connect"][self.shared_pool], 0)

        self.config["vms_params"]["remove_set"] = "tutorial1"
        DummyStateControl.asserted_states["unset"] = {"on_customize": {self.shared_pool: 0}, "connect": {self.shared_pool: 0}}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-8.*\.iso$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
        ]
        intertest_setup.update(self.config, tag="0")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        # states within the remove set would be removed if they are descendants of updated test node
        self.assertEqual(DummyStateControl.asserted_states["unset"]["on_customize"][self.shared_pool], 1)
        # states outside of the remove set would not be touched
        self.assertEqual(DummyStateControl.asserted_states["unset"]["connect"][self.shared_pool], 0)

        self.config["vms_params"]["remove_set"] = "minimal..tutorial1"
        DummyStateControl.asserted_states["unset"] = {"on_customize": {self.shared_pool: 0}, "connect": {self.shared_pool: 0}}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-8.*\.iso$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
        ]
        intertest_setup.update(self.config, tag="0")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)
        # states within the remove set would be removed if they are descendants of updated test node
        self.assertEqual(DummyStateControl.asserted_states["unset"]["on_customize"][self.shared_pool], 1)
        # states outside of the remove set would not be touched
        self.assertEqual(DummyStateControl.asserted_states["unset"]["connect"][self.shared_pool], 0)

        self.config["vms_params"]["remove_set"] = "minimal"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-8.*\.iso$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
        ]
        # vm2 does not participate in any test from the minimal test set but vm1 will be updated before this assertion fails
        with self.assertRaises(AssertionError):
            # TODO: do not use assertion errors on the graph side as these could be confused with the assertion errors here
            intertest_setup.update(self.config, tag="0")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_deploy_stateless(self):
        """Test the usage of the manual data deployment tool without any states."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_vms": "^root$", "set_state_vms": "^$",
             "get_state_images": "^root$", "set_state_images": "^$", "redeploy_only": "yes"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$", "get_state_vms": "^root$", "set_state_vms": "^$",
             "get_state_images": "^root$", "set_state_images": "^$", "redeploy_only": "yes"},
        ]
        intertest_setup.deploy(self.config, tag="ut")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

        self.config["param_dict"]["to_state_vms_vm1"] = ""
        self.config["param_dict"]["to_state_images_vm2"] = ""
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_vms": "^root$", "set_state_vms": "^$",
             "get_state_images": "^root$", "set_state_images": "^$"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$", "get_state_vms": "^root$", "set_state_vms": "^$",
             "get_state_images": "^root$", "set_state_images": "^$"},
        ]
        intertest_setup.deploy(self.config, tag="ut")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_deploy_states(self):
        """Test the error of the manual data deployment tool on too generic states."""
        self.config["param_dict"]["to_state"] = "state1"
        self.config["vm_strs"] = {"vm1": "only CentOS\n"}
        DummyTestRun.asserted_tests = []
        with self.assertRaises(ValueError):
            intertest_setup.deploy(self.config, tag="ut")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_deploy_state_multivm(self):
        """Test the usage of the manual data deployment tool on specific states of multiple types."""
        self.config["param_dict"]["to_state_vms_vm1"] = "state1"
        self.config["param_dict"]["to_state_vms_vm2"] = "state2"
        self.config["param_dict"]["to_state_images_vm1"] = "state3"
        self.config["param_dict"]["to_state_images_vm2"] = "state4"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_vms": "^state1$", "set_state_vms": "^state1$",
             "get_state_images": "^state3$", "set_state_images": "^state3$"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$", "get_state_vms": "^state2$", "set_state_vms": "^state2$",
             "get_state_images": "^state4$", "set_state_images": "^state4$"},
        ]
        intertest_setup.deploy(self.config, tag="ut")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

        self.config["vm_strs"] = {"vm1": "only CentOS\n"}
        DummyTestRun.asserted_tests = []
        with self.assertRaises(AssertionError):
            intertest_setup.deploy(self.config, tag="ut")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_internal_stateless(self):
        """Test the usage of the internal node access tool without any states."""
        self.config["param_dict"]["node"] = "connect"
        self.config["vm_strs"] = {"vm2": "only Win10\n"}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.automated.connect.vm2", "vms": "^vm2$", "get_state_vms": "^root$", "set_state_vms": "^$",
             "get_state_images": "^root$", "set_state_images": "^$"},
        ]
        intertest_setup.internal(self.config, tag="ut")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_internal_stateful(self):
        """Test the usage of the internal node access tool with custom states."""
        self.config["param_dict"]["node"] = "connect"
        self.config["param_dict"]["to_state_images"] = "stateX"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRun.asserted_tests = [
            {"shortname": "internal.automated.connect.vm1", "vms": "^vm1$", "get_state_images": "^stateX", "set_state_images": "^stateX"},
            {"shortname": "internal.automated.connect.vm2", "vms": "^vm2$", "get_state_images": "^stateX", "set_state_images": "^stateX"},
        ]
        intertest_setup.internal(self.config, tag="ut")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_boot(self):
        """Test the general usage of the manual boot tool."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.manage.start", "start_vm": "^yes$", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.boot(self.config, tag="0")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_download(self):
        """Test the general usage of the manual download tool."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.manage.download", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.download(self.config, tag="0")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_upload(self):
        """Test the general usage of the manual upload tool."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.manage.upload", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.upload(self.config, tag="0")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_shutdown(self):
        """Test the general usage of the manual shutdown tool."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.manage.stop", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.shutdown(self.config, tag="0")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_manual_state_manipulation(self):
        """Test the general usage of all state manipulation tools."""
        self.config["vm_strs"] = {"vm2": "only Win10\n", "vm3": "only Ubuntu\n"}
        for state_action in ["check", "pop", "push", "get", "set", "unset"]:
            DummyTestRun.asserted_tests = [
                {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$",
                 "skip_image_processing": "^yes$", "vm_action": "^%s$" % state_action},
                {"shortname": "^internal.stateless.manage.unchanged.vm3", "vms": "^vm3$",
                 "skip_image_processing": "^yes$", "vm_action": "^%s$" % state_action},
            ]
            setup_func = getattr(intertest_setup, state_action)
            setup_func(self.config)

        for state_action in ["collect", "create", "clean"]:
            operation = "set" if state_action == "create" else "unset"
            operation = "get" if state_action == "collect" else operation
            DummyTestRun.asserted_tests = [
                {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$",
                 "skip_image_processing": "^yes$", "vm_action": "^%s$" % operation},
                {"shortname": "^internal.stateless.manage.unchanged.vm3", "vms": "^vm3$",
                 "skip_image_processing": "^yes$", "vm_action": "^%s$" % operation},
            ]
            for test_dict in DummyTestRun.asserted_tests:
                test_dict[operation+"_state_images"] = "^root$"
                test_dict[operation+"_mode_images"] = "^af$" if operation == "set" else "^fa$"
                test_dict[operation+"_mode_images"] = "^ii$" if operation == "get" else test_dict[operation+"_mode_images"]
            setup_func = getattr(intertest_setup, state_action)
            setup_func(self.config, "5m")

    def test_develop_tool(self):
        """Test the general usage of the sample custom development tool."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}

        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.manual.develop.generator.vm1", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.load_addons_tools()
        intertest_setup.develop(self.config, tag="0")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)

    def test_permanent_vm_tool(self):
        """Test the general usage of the sample custom permanent vm creation tool."""
        self.config["vm_strs"] = {"vm3": "only Ubuntu\n"}

        DummyTestRun.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm3", "vms": "^vm3$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm3", "vms": "^vm3$", "cdrom_cd1": ".*ubuntu-14.04.*\.iso$", "set_state_images": "^install$"},
            {"shortname": "^internal.automated.customize.vm3", "vms": "^vm3$", "set_state_images": "^customize$"},
            {"shortname": "^internal.stateless.manage.start.vm3", "vms": "^vm3$", "set_state_vms": "^ready$"},
        ]
        intertest_setup.load_addons_tools()
        intertest_setup.update(self.config, tag="0")
        intertest_setup.permubuntu(self.config, tag="0")
        self.assertEqual(len(DummyTestRun.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRun.asserted_tests)


if __name__ == '__main__':
    unittest.main()
