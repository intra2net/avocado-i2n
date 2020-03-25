#!/usr/bin/env python

import unittest
import unittest.mock as mock
import contextlib
import re

from avocado.core import exceptions
from virttest import utils_params

import unittest_importer
from avocado_i2n import intertest_setup
from avocado_i2n.runner import CartesianRunner


class DummyTestRunning(object):

    fail_switch = False
    asserted_tests = []

    def __init__(self, node):
        # assertions about the test calls
        current_test_dict = node.params
        assert len(self.asserted_tests) > 0, "Unexpected test %s" % current_test_dict["shortname"]
        expected_test_dict = self.asserted_tests.pop(0)
        for checked_key in expected_test_dict.keys():
            assert checked_key in current_test_dict.keys(), "%s missing in %s" % (checked_key, current_test_dict["shortname"])
            expected, current = expected_test_dict[checked_key], current_test_dict[checked_key]
            assert re.match(expected, current) is not None, "Expected parameter %s=%s "\
                                                            "but obtained %s=%s for %s" % (checked_key, expected,
                                                                                           checked_key, current,
                                                                                           expected_test_dict["shortname"])

        if self.fail_switch:
            raise exceptions.TestFail("God wanted this test to fail")


@contextlib.contextmanager
def new_job(config):
    # jobless run delegation - simply pass to another mock function
    job = mock.MagicMock()
    job.logdir = "/some/path"
    yield job


def mock_run_test_node(_self, node):
    return DummyTestRunning(node)


@mock.patch('avocado_i2n.intertest_setup.new_job', new_job)
@mock.patch.object(CartesianRunner, 'run_test_node', mock_run_test_node)
class IntertestSetupTest(unittest.TestCase):

    def setUp(self):
        DummyTestRunning.asserted_tests = []
        DummyTestRunning.fail_switch = False

        self.config = {}
        self.config["selected_vms"] = []
        self.config["param_str"] = ""
        self.config["vm_strs"] = {}
        self.config["tests_params"] = utils_params.Params()
        self.config["vms_params"] = utils_params.Params()

    def test_full_default(self):
        self.config["selected_vms"] = ["vm1", "vm2"]
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.0root.vm1", "vms": "^vm1$", "set_state": "^root$"},
            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-7.*\.iso$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.0root.vm2", "vms": "^vm2$", "set_state": "^root$"},
            {"shortname": "^internal.stateless.0preinstall.vm2", "vms": "^vm2$"},
            {"shortname": "^original.unattended_install", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$"},
            {"shortname": "^internal.permanent.customize.vm2", "vms": "^vm2$"},
        ]
        intertest_setup.full(self.config, tag="1r")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_full_custom(self):
        self.config["selected_vms"] = ["vm1", "vm2"]
        self.config["vms_params"]["state_vm1"] = "customize"
        self.config["vms_params"]["state_vm2"] = "connect"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.0root.vm1", "vms": "^vm1$", "set_state": "^root$"},
            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-7.*\.iso$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.0root.vm2", "vms": "^vm2$", "set_state": "^root$"},
            {"shortname": "^internal.stateless.0preinstall.vm2", "vms": "^vm2$"},
            {"shortname": "^original.unattended_install.*vm2", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$"},
            {"shortname": "^internal.permanent.customize.vm2", "vms": "^vm2$"},
            {"shortname": "^internal.permanent.connect.vm2", "vms": "^vm2$"},
        ]
        intertest_setup.full(self.config, tag="1r")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_full_root(self):
        self.config["selected_vms"] = ["vm1", "vm2"]
        self.config["vms_params"]["state_vm1"] = "customize"
        self.config["vms_params"]["state_vm2"] = "root"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.0root.vm1", "vms": "^vm1$", "set_state": "^root$"},
            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-7.*\.iso$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.0root.vm2", "vms": "^vm2$", "set_state": "^root$"},
        ]
        intertest_setup.full(self.config, tag="1r")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_full_install(self):
        self.config["selected_vms"] = ["vm1", "vm2"]
        self.config["vms_params"]["state_vm1"] = "customize"
        self.config["vms_params"]["state_vm2"] = "install"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.0root.vm1", "vms": "^vm1$", "set_state": "^root$"},
            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-7.*\.iso$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.0root.vm2", "vms": "^vm2$", "set_state": "^root$"},
            {"shortname": "^internal.stateless.0preinstall.vm2", "vms": "^vm2$"},
            {"shortname": "^original.unattended_install.*vm2", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$"},
        ]
        intertest_setup.full(self.config, tag="1r")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_update_default(self):
        self.config["selected_vms"] = ["vm1", "vm2"]
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state": "^on_customize$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state": "^linux_virtuser$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state": "^on_connect$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state": "^connect$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "unset_state": "^windows_virtuser$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "unset_state": "^on_customize$"},
            {"shortname": "^internal.permanent.customize.vm2", "vms": "^vm2$"},
        ]
        intertest_setup.update(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_update_custom(self):
        self.config["selected_vms"] = ["vm1", "vm2"]
        self.config["vms_params"]["from_state"] = "install"
        self.config["vms_params"]["to_state"] = "on_customize"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$", "get_state": "^install$"},
            {"shortname": "^internal.ephemeral.on_customize.vm1", "vms": "^vm1$", "get_state": "^customize$"},
            {"shortname": "^internal.permanent.customize.vm2", "vms": "^vm2$", "get_state": "^install$"},
            {"shortname": "^internal.ephemeral.on_customize.vm2", "vms": "^vm2$", "get_state": "^customize$"},
        ]
        intertest_setup.update(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_install(self):
        self.config["selected_vms"] = ["vm1", "vm2"]
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-7.*\.iso$"},
            {"shortname": "^internal.stateless.0preinstall.vm2", "vms": "^vm2$"},
            {"shortname": "^original.unattended_install.*vm2", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$"},
        ]
        intertest_setup.install(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deploy_stateless(self):
        self.config["selected_vms"] = ["vm1", "vm2"]
        self.config["vm_strs"] = {"vm1": "only CentOS\nstateless=yes\n", "vm2": "only Win10\nstateless=yes\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$", "get_state": "^$", "set_state": "^$"},
            {"shortname": "^internal.permanent.customize.vm2", "vms": "^vm2$", "get_state": "^$", "set_state": "^$"},
        ]
        intertest_setup.deploy(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deploy_stateful(self):
        self.config["selected_vms"] = ["vm1", "vm2"]
        self.config["vm_strs"] = {"vm1": "only CentOS\nstateless=no\n", "vm2": "only Win10\nstateless=no\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$", "get_state": "^install$", "set_state": "^customize$"},
            {"shortname": "^internal.permanent.customize.vm2", "vms": "^vm2$", "get_state": "^install$", "set_state": "^customize$"},
        ]
        intertest_setup.deploy(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deploy_states(self):
        self.config["selected_vms"] = ["vm1"]
        self.config["vm_strs"] = {"vm1": "only CentOS\nstates=state1 state2\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$", "get_state": "^state1$", "set_state": "^state1$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$", "get_state": "^state2$", "set_state": "^state2$"},
        ]
        intertest_setup.deploy(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deploy_states_multivm(self):
        self.config["selected_vms"] = ["vm1", "vm2"]
        self.config["vm_strs"] = {"vm1": "only CentOS\nstates=state1 state2 state3\n", "vm2": "only Win10\nstates=state1 state3\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$", "get_state": "^state1$", "set_state": "^state1$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$", "get_state": "^state2$", "set_state": "^state2$"},
            {"shortname": "^internal.permanent.customize.vm1", "vms": "^vm1$", "get_state": "^state3$", "set_state": "^state3$"},
            {"shortname": "^internal.permanent.customize.vm2", "vms": "^vm2$", "get_state": "^state1$", "set_state": "^state1$"},
            {"shortname": "^internal.permanent.customize.vm2", "vms": "^vm2$", "get_state": "^state3$", "set_state": "^state3$"},
        ]
        intertest_setup.deploy(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_internal_stateless(self):
        self.config["selected_vms"] = ["vm2"]
        self.config["vm_strs"] = {"vm2": "only Win10\nnode=connect\nstateless=yes\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.permanent.connect.vm2", "vms": "^vm2$", "get_state": "^$", "set_state": "^$"},
        ]
        intertest_setup.internal(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_internal_stateful(self):
        self.config["selected_vms"] = ["vm2"]
        self.config["vm_strs"] = {"vm2": "only Win10\nnode=connect\nstateless=no\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "internal.permanent.connect.vm2", "vms": "^vm2$", "get_state": "^customize$", "set_state": "^connect$"},
        ]
        intertest_setup.internal(self.config, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_boot(self):
        self.config["selected_vms"] = ["vm1", "vm2"]
        self.config["param_str"] += "vms=vm1 vm2\n"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.start", "start_vm": "^yes$", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.boot(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_download(self):
        self.config["selected_vms"] = ["vm1", "vm2"]
        self.config["param_str"] += "vms=vm1 vm2\n"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.download", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.download(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_upload(self):
        self.config["selected_vms"] = ["vm1", "vm2"]
        self.config["param_str"] += "vms=vm1 vm2\n"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.upload", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.upload(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_shutdown(self):
        self.config["selected_vms"] = ["vm1", "vm2"]
        self.config["param_str"] += "vms=vm1 vm2\n"
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.stop", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.shutdown(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_manual_state_manipulation(self):
        self.config["selected_vms"] = ["vm2"]
        self.config["vm_strs"] = {"vm2": "only Win10\n"}
        for state_action in ["check", "pop", "push", "get", "set", "unset"]:
            DummyTestRunning.asserted_tests = [
                {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$",
                 "skip_image_processing": "^yes$", "vm_action": "^%s$" % state_action},
            ]
            setup_func = getattr(intertest_setup, state_action)
            setup_func(self.config)

        for state_action in ["create", "clean"]:
            DummyTestRunning.asserted_tests = [
                {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$",
                 "skip_image_processing": "^yes$", "vm_action": "^set$" if state_action == "create" else "^unset$",
                 "set_state": "^root$", "unset_state": "^root$"},
            ]
            if state_action == "create":
                del DummyTestRunning.asserted_tests[0]["unset_state"]
            else:
                del DummyTestRunning.asserted_tests[0]["set_state"]
            setup_func = getattr(intertest_setup, state_action)
            setup_func(self.config, "5m")

    def test_develop(self):
        self.config["selected_vms"] = ["vm1", "vm2"]
        self.config["vm_strs"] = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}

        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.manual.develop.generator.vm1", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.load_addons_tools()
        intertest_setup.develop(self.config, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)


if __name__ == '__main__':
    unittest.main()
