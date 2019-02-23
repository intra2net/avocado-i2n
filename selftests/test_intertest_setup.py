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
def new_job(args):
    # jobless run delegation - simply pass to another mock function
    yield mock.MagicMock()


def mock_run_test_node(_self, node):
    return DummyTestRunning(node)


@mock.patch('avocado_i2n.intertest_setup.new_job', new_job)
@mock.patch.object(CartesianRunner, 'run_test_node', mock_run_test_node)
class IntertestSetupTest(unittest.TestCase):

    def setUp(self):
        DummyTestRunning.asserted_tests = []
        DummyTestRunning.fail_switch = False

        self.args = mock.MagicMock()
        self.args.param_str = ""
        self.args.vm_strs = {}
        self.run_params = utils_params.Params()

    def test_full(self):
        self.run_params["vms"] = "vm1 vm2"
        self.args.vm_strs = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "set_state": "^root$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "set_state": "^root$"},
            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-7.*\.iso$"},
            {"shortname": "^internal.stateless.0preinstall.vm2", "vms": "^vm2$"},
            {"shortname": "^original.unattended_install.*vm2", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$"},
            {"shortname": "^internal.permanent.customize_vm.vm1", "vms": "^vm1$", "redeploy_only": "^no$"},
            {"shortname": "^internal.permanent.customize_vm.vm2", "vms": "^vm2$", "redeploy_only": "^no$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "set_state": "^customize_vm$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "set_state": "^customize_vm$"},
        ]
        intertest_setup.full(self.args, self.run_params, tag="5")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    # TODO: avoid direct calls to the avocado process module and use calls to the state setup instead
    @mock.patch('avocado_i2n.intertest_setup.process')
    def test_update(self, _mock_process):
        self.run_params["vms"] = "vm1 vm2"
        self.run_params["dry_run"] = "yes"
        self.args.vm_strs = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "get_state": "^install$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "get_state": "^install$"},
            {"shortname": "^internal.permanent.customize_vm.vm1", "vms": "vm1", "redeploy_only": "^no$"},
            {"shortname": "^internal.permanent.customize_vm.vm2", "vms": "vm2", "redeploy_only": "^no$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "set_state": "^customize_vm$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "set_state": "^customize_vm$"},
        ]
        intertest_setup.update(self.args, self.run_params, tag="2")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_graphfull_default(self):
        self.run_params["vms"] = "vm1 vm2"
        self.args.vm_strs = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "set_state": "^root$"},
            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-7.*\.iso$"},
            {"shortname": "^internal.permanent.customize_vm.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "set_state": "^root$"},
            {"shortname": "^internal.stateless.0preinstall.vm2", "vms": "^vm2$"},
            {"shortname": "^original.unattended_install", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$"},
            {"shortname": "^internal.permanent.customize_vm.vm2", "vms": "^vm2$"},
        ]
        intertest_setup.graphfull(self.args, self.run_params, tag="1r")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_graphfull_custom(self):
        self.run_params["vms"] = "vm1 vm2"
        self.run_params["state_vm1"] = "customize_vm"
        self.run_params["state_vm2"] = "set_provider"
        self.args.vm_strs = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "set_state": "^root$"},
            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-7.*\.iso$"},
            {"shortname": "^internal.permanent.customize_vm.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "set_state": "^root$"},
            {"shortname": "^internal.stateless.0preinstall.vm2", "vms": "^vm2$"},
            {"shortname": "^original.unattended_install.*vm2", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$"},
            {"shortname": "^internal.permanent.customize_vm.vm2", "vms": "^vm2$"},
            {"shortname": "^internal.permanent.set_provider.vm2", "vms": "^vm2$"},
        ]
        intertest_setup.graphfull(self.args, self.run_params, tag="1r")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_graphfull_root(self):
        self.run_params["vms"] = "vm1 vm2"
        self.run_params["state_vm1"] = "customize_vm"
        self.run_params["state_vm2"] = "root"
        self.args.vm_strs = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "unset_state": "^root$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "set_state": "^root$"},
            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-7.*\.iso$"},
            {"shortname": "^internal.permanent.customize_vm.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "set_state": "^root$"},
        ]
        intertest_setup.graphfull(self.args, self.run_params, tag="1r")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_graphupdate_default(self):
        self.run_params["vms"] = "vm1 vm2"
        self.args.vm_strs = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state": "^online_deploy$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state": "^online_with_provider$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm1", "vms": "^vm1$", "unset_state": "^set_provider$"},
            {"shortname": "^internal.permanent.customize_vm.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$", "unset_state": "^online_deploy$"},
            {"shortname": "^internal.permanent.customize_vm.vm2", "vms": "^vm2$"},
        ]
        intertest_setup.graphupdate(self.args, self.run_params, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_graphupdate_custom(self):
        self.run_params["vms"] = "vm1 vm2"
        self.run_params["from_state"] = "install"
        self.run_params["to_state"] = "online_deploy"
        self.args.vm_strs = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.permanent.customize_vm.vm1", "vms": "^vm1$", "get_state": "^install$"},
            {"shortname": "^internal.ephemeral.online_deploy.vm1", "vms": "^vm1$", "get_state": "^customize_vm$"},
            {"shortname": "^internal.permanent.customize_vm.vm2", "vms": "^vm2$", "get_state": "^install$"},
            {"shortname": "^internal.ephemeral.online_deploy.vm2", "vms": "^vm2$", "get_state": "^customize_vm$"},
        ]
        intertest_setup.graphupdate(self.args, self.run_params, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    @unittest.skip("Manual step not supported in sample test suite and will be partially deprecated")
    def test_windows(self):
        self.run_params["with_outlook"] = "no"
        self.run_params["vms"] = "vm2"
        self.args.vm_strs = {"vm2": "only Win10\n"}

        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.start.vm2.smp2.Win10.x86_64$", "vms": "^vm2$", "set_state": "^windows_online$"},
            {"shortname": "^internal.permanent.windows_virtuser.vm2.smp2.Win10.x86_64$", "vms": "^vm2$", "get_state": "^customize_vm$", "set_state": "^windows_virtuser$"},
        ]
        intertest_setup.windows(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

        self.run_params["with_outlook"] = "2013"

        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.start.vm2.smp2.Win10.x86_64$", "vms": "^vm2$", "set_state": "^windows_online$"},
            {"shortname": "^internal.permanent.windows_virtuser.vm2.smp2.Win10.x86_64$", "vms": "^vm2$", "get_state": "^customize_vm$", "set_state": "^windows_virtuser$"},
            {"shortname": "^internal.manual.outlook_prep.ol2013.vm2.smp2.Win10.x86_64$", "vms": "^vm2$", "get_state": "^windows_online$", "set_state": "^outlook_prep$"},
        ]
        intertest_setup.windows(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_develop(self):
        self.run_params["vms"] = "vm1 vm2"
        self.args.vm_strs = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}

        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.manual.develop.generator.vm1", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.develop(self.args, self.run_params, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_install(self):
        self.run_params["vms"] = "vm1 vm2"
        self.args.vm_strs = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.0preinstall.vm1", "vms": "^vm1$"},
            {"shortname": "^original.unattended_install.*vm1", "vms": "^vm1$", "cdrom_cd1": ".*CentOS-7.*\.iso$"},
            {"shortname": "^internal.stateless.0preinstall.vm2", "vms": "^vm2$"},
            {"shortname": "^original.unattended_install.*vm2", "vms": "^vm2$", "cdrom_cd1": ".*win.*\.iso$"},
        ]
        intertest_setup.install(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deploy_stateless(self):
        self.run_params["vms"] = "vm1 vm2"
        self.args.vm_strs = {"vm1": "only CentOS\nstateless=yes\n", "vm2": "only Win10\nstateless=yes\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.permanent.customize_vm.vm1", "vms": "^vm1$", "get_state": "^$", "set_state": "^$"},
            {"shortname": "^internal.permanent.customize_vm.vm2", "vms": "^vm2$", "get_state": "^$", "set_state": "^$"},
        ]
        intertest_setup.deploy(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deploy_stateful(self):
        self.run_params["vms"] = "vm1 vm2"
        self.args.vm_strs = {"vm1": "only CentOS\nstateless=no\n", "vm2": "only Win10\nstateless=no\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.permanent.customize_vm.vm1", "vms": "^vm1$", "get_state": "^install$", "set_state": "^customize_vm$"},
            {"shortname": "^internal.permanent.customize_vm.vm2", "vms": "^vm2$", "get_state": "^install$", "set_state": "^customize_vm$"},
        ]
        intertest_setup.deploy(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deploy_states(self):
        self.run_params["vms"] = "vm1"
        self.args.vm_strs = {"vm1": "only CentOS\nstates=state1 state2\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.permanent.customize_vm.vm1", "vms": "^vm1$", "get_state": "^state1$", "set_state": "^state1$"},
            {"shortname": "^internal.permanent.customize_vm.vm1", "vms": "^vm1$", "get_state": "^state2$", "set_state": "^state2$"},
        ]
        intertest_setup.deploy(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deploy_states_multivm(self):
        self.run_params["vms"] = "vm1 vm2"
        self.args.vm_strs = {"vm1": "only CentOS\nstates=state1 state2 state3\n", "vm2": "only Win10\nstates=state1 state3\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.permanent.customize_vm.vm1", "vms": "^vm1$", "get_state": "^state1$", "set_state": "^state1$"},
            {"shortname": "^internal.permanent.customize_vm.vm1", "vms": "^vm1$", "get_state": "^state2$", "set_state": "^state2$"},
            {"shortname": "^internal.permanent.customize_vm.vm1", "vms": "^vm1$", "get_state": "^state3$", "set_state": "^state3$"},
            {"shortname": "^internal.permanent.customize_vm.vm2", "vms": "^vm2$", "get_state": "^state1$", "set_state": "^state1$"},
            {"shortname": "^internal.permanent.customize_vm.vm2", "vms": "^vm2$", "get_state": "^state3$", "set_state": "^state3$"},
        ]
        intertest_setup.deploy(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_internal_stateless(self):
        self.run_params["vms"] = "vm2"
        self.args.vm_strs = {"vm2": "only Win10\nnode=set_provider\nstateless=yes\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.permanent.set_provider.vm2", "vms": "^vm2$", "get_state": "^$", "set_state": "^$"},
        ]
        intertest_setup.internal(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_internal_stateful(self):
        self.run_params["vms"] = "vm2"
        self.args.vm_strs = {"vm2": "only Win10\nnode=set_provider\nstateless=no\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "internal.permanent.set_provider.vm2", "vms": "^vm2$", "get_state": "^customize_vm$", "set_state": "^set_provider$"},
        ]
        intertest_setup.internal(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_sysupdate(self):
        self.run_params["vms"] = "vm1 vm2"
        self.args.vm_strs = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.permanent.system_update.vm1", "vms": "^vm1$"},
            {"shortname": "^internal.permanent.system_update.vm2", "vms": "^vm2$"},
        ]
        intertest_setup.sysupdate(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_boot(self):
        self.run_params["vms"] = "vm1 vm2"
        self.args.param_str += "vms=vm1 vm2\n"
        self.args.vm_strs = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.start", "start_vm": "^yes$", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.boot(self.args, self.run_params, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_download(self):
        self.run_params["vms"] = "vm1 vm2"
        self.args.param_str += "vms=vm1 vm2\n"
        self.args.vm_strs = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.download", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.download(self.args, self.run_params, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_upload(self):
        self.run_params["vms"] = "vm1 vm2"
        self.args.param_str += "vms=vm1 vm2\n"
        self.args.vm_strs = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.upload", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.upload(self.args, self.run_params, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_shutdown(self):
        self.run_params["vms"] = "vm1 vm2"
        self.args.param_str += "vms=vm1 vm2\n"
        self.args.vm_strs = {"vm1": "only CentOS\n", "vm2": "only Win10\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^internal.stateless.manage.stop", "vms": "^vm1 vm2$"},
        ]
        intertest_setup.shutdown(self.args, self.run_params, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_manual_state_manipulation(self):
        self.run_params["vms"] = "vm2"
        self.args.vm_strs = {"vm2": "only Win10\n"}
        for state_action in ["check", "pop", "push", "get", "set", "unset"]:
            DummyTestRunning.asserted_tests = [
                {"shortname": "^internal.stateless.manage.unchanged.vm2", "vms": "^vm2$",
                 "skip_image_processing": "^yes$", "vm_action": "^%s$" % state_action},
            ]
            setup_func = getattr(intertest_setup, state_action)
            setup_func(self.args, self.run_params)

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
            setup_func(self.args, self.run_params, "5m")


if __name__ == '__main__':
    unittest.main()
