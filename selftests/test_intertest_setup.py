#!/usr/bin/env python

import unittest
import unittest.mock as mock
import contextlib
import re

from avocado import Test
from avocado.core import exceptions
from virttest import utils_params

import unittest_importer
from avocado_i2n import intertest_setup
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


@contextlib.contextmanager
def new_job(config):
    # jobless run delegation - simply pass to another mock function
    job = mock.MagicMock()
    job.logdir = "."
    job.timeout = 60

    loader, runner = config["graph"].l, config["graph"].r
    loader.logdir = job.logdir
    runner.job = job

    yield job


async def mock_run_test(_self, _job, node):
    if not hasattr(_self, "result"):
        _self.job.result = mock.MagicMock()
        _self.job.result.tests = []
    # define ID-s and other useful parameter filtering
    node.get_runnable()
    node.params["_uid"] = node.long_prefix
    DummyTestRunning(node.params, _self.job.result.tests).get_test_result()


def mock_check_states(params, env):
    return DummyStateCheck(params, env).result


@mock.patch('avocado_i2n.intertest_setup.new_job', new_job)
@mock.patch('avocado_i2n.cartgraph.node.ss.check_states', mock_check_states)
@mock.patch('avocado_i2n.cartgraph.node.SpawnerDispatcher', mock.MagicMock())
@mock.patch.object(CartesianRunner, 'run_test', mock_run_test)
class IntertestSetupTest(Test):

    def setUp(self):
        DummyTestRunning.asserted_tests = []

        self.config = {}
        self.config["available_vms"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n", "vm3": "only Ubuntu\n"}
        self.config["available_restrictions"] = ["leaves", "normal", "minimal"]
        self.config["param_dict"] = {}
        self.config["vm_strs"] = self.config["available_vms"].copy()
        self.config["tests_str"] = {}
        self.config["tests_params"] = utils_params.Params()
        self.config["vms_params"] = utils_params.Params()

    def test_full_default(self):
        """Test the general usage of the manual full-setup tool."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-8.*\.iso$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.noop.vm2", "vms": "^vm2$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$"},
        ]
        intertest_setup.full(self.config, tag="1r")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_full_custom(self):
        """Test the state customized usage of the manual full-setup tool."""
        self.config["vms_params"]["to_state_vm1"] = "customize"
        self.config["vms_params"]["to_state_vm2"] = "connect"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-8.*\.iso$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.noop.vm2", "vms": "^vm2$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm2", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$"},
            {"shortname": "^internal.automated.connect.vm2", "vms": "^vm2$"},
        ]
        intertest_setup.full(self.config, tag="1r")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_full_install(self):
        """Test the install state customized usage of the manual full-setup tool."""
        self.config["vms_params"]["to_state_vm1"] = "customize"
        self.config["vms_params"]["to_state_vm2"] = "install"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-8.*\.iso$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.noop.vm2", "vms": "^vm2$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm2", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$"},
        ]
        intertest_setup.full(self.config, tag="1r")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_update_default(self):
        """Test the general usage of the manual update-setup tool."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state_vms_vm1": "^on_customize$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state_images_image1_vm1": "^connect"},
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state_images_image1_vm1": "^linux_virtuser$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_mode": "ra", "set_mode": "fa", "unset_mode": "ra"},
            {"shortname": "^internal.stateless.manage.unchanged", "vms": "^vm1 vm2 vm3$", "unset_state_images_image1_vm2": "^getsetup.noop"},
            {"shortname": "^internal.stateless.manage.unchanged", "vms": "^vm1 vm2 vm3$", "unset_state_images_image1_vm2": "^getsetup.clicked"},
            {"shortname": "^internal.stateless.manage.unchanged", "vms": "^vm1 vm2 vm3$", "unset_state_images_image1_vm2": "^getsetup.guisetup.noop"},
            {"shortname": "^internal.stateless.manage.unchanged", "vms": "^vm1 vm2 vm3$", "unset_state_images_image1_vm2": "^getsetup.guisetup.clicked"},
            {"shortname": "^internal.stateless.manage.unchanged", "vms": "^vm1 vm2$", "unset_state_images_image1_vm2": "^guisetup.noop"},
            {"shortname": "^internal.stateless.manage.unchanged", "vms": "^vm1 vm2$", "unset_state_images_image1_vm2": "^guisetup.clicked"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "unset_state_images_image1_vm2": "^windows_virtuser$"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$", "get_mode": "ra", "set_mode": "fa", "unset_mode": "ra"},
        ]
        intertest_setup.update(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_update_custom_cleanup(self):
        """Test the custom cleanup usage of the manual update-setup tool."""
        self.config["vms_params"]["remove_set"] = "minimal"
        self.config["vm_strs"] = {"vm1": "only CentOS\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state_vms_vm1": "^on_customize$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
        ]
        intertest_setup.update(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

        self.config["vms_params"]["remove_set"] = "tutorial1"
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state_vms_vm1": "^on_customize$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
        ]
        intertest_setup.update(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

        self.config["vms_params"]["remove_set"] = "minimal..tutorial1"
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state_vms_vm1": "^on_customize$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
        ]
        intertest_setup.update(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

        self.config["vms_params"]["remove_set"] = "minimal"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state_vms_vm1": "^on_customize$"},
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$"},
        ]
        # vm2 does not participate in any test from the minimal test set but vm1 will be updated before this assertion fails
        with self.assertRaises(AssertionError):
            # TODO: do not use assertion errors on the graph side as these could be confused with the assertion errors here
            intertest_setup.update(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_update_custom(self):
        """Test the custom state usage of the manual update-setup tool."""
        self.config["vms_params"]["from_state"] = "install"
        self.config["vms_params"]["to_state"] = "connect"
        self.config["vm_strs"] = {"vm1": "only CentOS\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_images": "^install$"},
            {"shortname": "^internal.automated.connect.vm1", "vms": "^vm1$", "get_state_images": "^customize$"},
        ]
        intertest_setup.update(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_update_install(self):
        """Test the usage of the manual update-setup tool does now allow states before install."""
        self.config["vms_params"]["to_state"] = "install"
        self.config["vm_strs"] = {"vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
        ]
        intertest_setup.update(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_install(self):
        """Test the general usage of the manual install tool."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-8.*\.iso$"},
            {"shortname": "^internal.stateless.noop.vm2", "vms": "^vm2$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm2", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$"},
        ]
        intertest_setup.install(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_install_abort(self):
        """Test that a failure in different installation test stages aborts properly."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm1", "vms": "^vm1$", "type": "^shared_configure_install$", "_status": "FAIL"},
            # skipped install test node
            {"shortname": "^internal.stateless.noop.vm2", "vms": "^vm2$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm2", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$", "_status": "FAIL"},
        ]
        intertest_setup.install(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deploy_stateless(self):
        """Test the usage of the manual data deployment tool without any states."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_vms": "^root$", "set_state_vms": "^$",
             "get_state_images": "^root$", "set_state_images": "^$", "redeploy_only": "yes"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$", "get_state_vms": "^root$", "set_state_vms": "^$",
             "get_state_images": "^root$", "set_state_images": "^$", "redeploy_only": "yes"},
        ]
        intertest_setup.deploy(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

        self.config["param_dict"]["to_state_vms_vm1"] = ""
        self.config["param_dict"]["to_state_images_vm2"] = ""
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_vms": "^root$", "set_state_vms": "^$",
             "get_state_images": "^root$", "set_state_images": "^$"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$", "get_state_vms": "^root$", "set_state_vms": "^$",
             "get_state_images": "^root$", "set_state_images": "^$"},
        ]
        intertest_setup.deploy(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deploy_states(self):
        """Test the error of the manual data deployment tool on too generic states."""
        self.config["param_dict"]["to_state"] = "state1"
        self.config["vm_strs"] = {"vm1": "only CentOS\n"}
        DummyTestRunning.asserted_tests = []
        with self.assertRaises(ValueError):
            intertest_setup.deploy(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deploy_state_multivm(self):
        """Test the usage of the manual data deployment tool on specific states of multiple types."""
        self.config["param_dict"]["to_state_vms_vm1"] = "state1"
        self.config["param_dict"]["to_state_vms_vm2"] = "state2"
        self.config["param_dict"]["to_state_images_vm1"] = "state3"
        self.config["param_dict"]["to_state_images_vm2"] = "state4"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.automated.customize.vm1", "vms": "^vm1$", "get_state_vms": "^state1$", "set_state_vms": "^state1$",
             "get_state_images": "^state3$", "set_state_images": "^state3$"},
            {"shortname": "^internal.automated.customize.vm2", "vms": "^vm2$", "get_state_vms": "^state2$", "set_state_vms": "^state2$",
             "get_state_images": "^state4$", "set_state_images": "^state4$"},
        ]
        intertest_setup.deploy(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

        self.config["vm_strs"] = {"vm1": "only CentOS\n"}
        DummyTestRunning.asserted_tests = []
        with self.assertRaises(AssertionError):
            intertest_setup.deploy(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_internal_stateless(self):
        """Test the usage of the internal node access tool without any states."""
        self.config["param_dict"]["node"] = "connect"
        self.config["vm_strs"] = {"vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.automated.connect.vm2", "vms": "^vm2$", "get_state_vms": "^root$", "set_state_vms": "^$",
             "get_state_images": "^root$", "set_state_images": "^$"},
        ]
        intertest_setup.internal(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_internal_stateful(self):
        """Test the usage of the internal node access tool with custom states."""
        self.config["param_dict"]["node"] = "connect"
        self.config["param_dict"]["to_state_images"] = "stateX"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "internal.automated.connect.vm1", "vms": "^vm1$", "get_state_images": "^stateX", "set_state_images": "^stateX"},
            {"shortname": "internal.automated.connect.vm2", "vms": "^vm2$", "get_state_images": "^stateX", "set_state_images": "^stateX"},
        ]
        intertest_setup.internal(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_boot(self):
        """Test the general usage of the manual boot tool."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.start", "start_vm": "^yes$", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.boot(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_download(self):
        """Test the general usage of the manual download tool."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.download", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.download(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_upload(self):
        """Test the general usage of the manual upload tool."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.upload", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.upload(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_shutdown(self):
        """Test the general usage of the manual shutdown tool."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.stop", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.shutdown(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_manual_state_manipulation(self):
        """Test the general usage of all state manipulation tools."""
        self.config["vm_strs"] = {"vm2": "only Win10\n", "vm3": "only Ubuntu\n"}
        for state_action in ["check", "pop", "push", "get", "set", "unset"]:
            DummyTestRunning.asserted_tests = [
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
            DummyTestRunning.asserted_tests = [
                {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$",
                 "skip_image_processing": "^yes$", "vm_action": "^%s$" % operation},
                {"shortname": "^internal.stateless.manage.unchanged.vm3", "vms": "^vm3$",
                 "skip_image_processing": "^yes$", "vm_action": "^%s$" % operation},
            ]
            for test_dict in DummyTestRunning.asserted_tests:
                test_dict[operation+"_state_images"] = "^root$"
                test_dict[operation+"_mode_images"] = "^af$" if operation == "set" else "^fa$"
                test_dict[operation+"_mode_images"] = "^ii$" if operation == "get" else test_dict[operation+"_mode_images"]
            setup_func = getattr(intertest_setup, state_action)
            setup_func(self.config, "5m")

    def test_develop_tool(self):
        """Test the general usage of the sample custom development tool."""
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}

        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.manual.develop.generator.vm1", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.load_addons_tools()
        intertest_setup.develop(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_permanent_vm_tool(self):
        """Test the general usage of the sample custom permanent vm creation tool."""
        self.config["vm_strs"] = {"vm3": "only Ubuntu\n"}

        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.noop.vm3", "vms": "^vm3$", "type": "^shared_configure_install$"},
            {"shortname": "^original.unattended_install.*vm3", "vms": "^vm3$", "cdrom_cd1": ".*ubuntu-14.04.*\.iso$", "set_state_images": "^install$"},
            {"shortname": "^internal.automated.customize.vm3", "vms": "^vm3$", "set_state_images": "^customize$"},
            {"shortname": "^internal.stateless.manage.start.vm3", "vms": "^vm3$", "set_state_vms": "^ready$"},
        ]
        intertest_setup.load_addons_tools()
        intertest_setup.full(self.config, tag="0")
        intertest_setup.permubuntu(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)


if __name__ == '__main__':
    unittest.main()
