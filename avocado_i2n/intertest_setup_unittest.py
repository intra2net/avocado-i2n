#!/usr/bin/env python

import unittest
import unittest.mock as mock
import re

from avocado.core import exceptions
from virttest import utils_params

from . import intertest_setup
from .cartesian_graph import CartesianGraph, TestNode


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


def _job_from_parser(graph, name, parser):
    # jobless run delegation - simply pass to another mock function
    graph.run_test_node(TestNode(name, parser, []))


def mock_run_test_node(_self, node):
    return DummyTestRunning(node)


@mock.patch('intertest_setup._job_from_parser', _job_from_parser)
@mock.patch.object(CartesianGraph, 'run_test_node', mock_run_test_node)
class IntertestSetupTest(unittest.TestCase):

    def setUp(self):
        DummyTestRunning.asserted_tests = []
        DummyTestRunning.fail_switch = False

        self.args = mock.MagicMock()
        self.args.param_str = ""
        self.args.vm_strs = {}
        self.run_params = utils_params.Params()

    def test_full(self):
        self.run_params["vms"] = "vm2 vm3"
        self.args.vm_strs = {"vm2": "only Business_Server\n", "vm3": "only Security_Gateway\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^5mm.internal.stateless.manage_vms.unchanged.vm2", "vms": "^vm2$", "unset_state": "^root$"},
            {"shortname": "^5mm.internal.stateless.manage_vms.unchanged.vm3", "vms": "^vm3$", "unset_state": "^root$"},
            {"shortname": "^5m.internal.stateless.manage_vms.unchanged.vm2", "vms": "^vm2$", "set_state": "^root$"},
            {"shortname": "^5m.internal.stateless.manage_vms.unchanged.vm3", "vms": "^vm3$", "set_state": "^root$"},
            {"shortname": "^5.internal.stateless.configure_install.vm2", "vms": "^vm2$"},
            {"shortname": "^5.original.install", "vms": "^vm2$", "cdrom_cd1": ".*business-server.*\.iso$"},
            {"shortname": "^5.internal.stateless.configure_install.vm3", "vms": "^vm3$"},
            {"shortname": "^5.original.install", "vms": "^vm3$", "cdrom_cd1": ".*security-gateway.*\.iso$"},
            {"shortname": "^5.internal.permanent.customize_vm", "vms": "^vm2$", "redeploy_only": "^no$"},
            {"shortname": "^5.internal.permanent.customize_vm", "vms": "^vm3$", "redeploy_only": "^no$"},
            {"shortname": "^5.internal.stateless.manage_vms.unchanged", "vms": "^vm2$", "set_state": "^customize_vm$"},
            {"shortname": "^5.internal.stateless.manage_vms.unchanged", "vms": "^vm3$", "set_state": "^customize_vm$"},
        ]
        intertest_setup.full(self.args, self.run_params, tag="5")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_update(self):
        self.run_params["vms"] = "vm1"
        self.run_params["dry_run"] = "yes"
        self.args.vm_strs = {"vm1": "only Network_Security\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^2m.internal.stateless.manage_vms.unchanged.vm1", "vms": "^vm1$", "get_state": "^install$"},
            {"shortname": "^2.internal.permanent.customize_vm.vm1", "vms": "vm1", "redeploy_only": "^no$"},
            {"shortname": "^2.internal.stateless.manage_vms.unchanged.vm1", "vms": "^vm1$", "set_state": "^customize_vm$"},
        ]
        intertest_setup.update(self.args, self.run_params, tag="2")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_graphfull_default(self):
        self.run_params["vms"] = "vm2 vm3"
        self.args.vm_strs = {"vm2": "only Business_Server\n", "vm3": "only Security_Gateway\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^1rmm.internal.stateless.manage_vms.unchanged.vm2", "vms": "^vm2$", "unset_state": "^root$"},
            {"shortname": "^1rmm.internal.stateless.manage_vms.unchanged.vm3", "vms": "^vm3$", "unset_state": "^root$"},
            {"shortname": "^root.internal.stateless.manage_vms.unchanged.vm2", "vms": "^vm2$", "set_state": "^root$"},
            {"shortname": "^1r1a1.internal.stateless.configure_install.vm2", "vms": "^vm2$"},
            {"shortname": "^1r1a1.original.install.vm2", "vms": "^vm2$", "cdrom_cd1": ".*business-server.*\.iso$"},
            {"shortname": "^1r1.internal.permanent.customize_vm.vm2", "vms": "^vm2$"},
            {"shortname": "^root.internal.stateless.manage_vms.unchanged.vm3", "vms": "^vm3$", "set_state": "^root$"},
            {"shortname": "^1r1a1.internal.stateless.configure_install.vm3", "vms": "^vm3$"},
            {"shortname": "^1r1a1.original.install.vm3", "vms": "^vm3$", "cdrom_cd1": ".*security-gateway.*\.iso$"},
            {"shortname": "^1r1.internal.permanent.customize_vm.vm3", "vms": "^vm3$"},
        ]
        intertest_setup.graphfull(self.args, self.run_params, tag="1r")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_graphfull_custom(self):
        self.run_params["vms"] = "vm2 vm3"
        self.run_params["state_vm2"] = "customize_vm"
        self.run_params["state_vm3"] = "set_provider"
        self.args.vm_strs = {"vm2": "only Business_Server\n", "vm3": "only Security_Gateway\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^1rmm.internal.stateless.manage_vms.unchanged.vm2", "vms": "^vm2$", "unset_state": "^root$"},
            {"shortname": "^1rmm.internal.stateless.manage_vms.unchanged.vm3", "vms": "^vm3$", "unset_state": "^root$"},
            {"shortname": "^root.internal.stateless.manage_vms.unchanged.vm2", "vms": "^vm2$", "set_state": "^root$"},
            {"shortname": "^1r1a1.internal.stateless.configure_install.vm2", "vms": "^vm2$"},
            {"shortname": "^1r1a1.original.install.vm2", "vms": "^vm2$", "cdrom_cd1": ".*business-server.*\.iso$"},
            {"shortname": "^1r1.internal.permanent.customize_vm.vm2", "vms": "^vm2$"},
            {"shortname": "^root.internal.stateless.manage_vms.unchanged.vm3", "vms": "^vm3$", "set_state": "^root$"},
            {"shortname": "^1r1a1a1.internal.stateless.configure_install.vm3", "vms": "^vm3$"},
            {"shortname": "^1r1a1a1.original.install.vm3", "vms": "^vm3$", "cdrom_cd1": ".*security-gateway.*\.iso$"},
            {"shortname": "^1r1a1.internal.permanent.customize_vm.vm3", "vms": "^vm3$"},
            {"shortname": "^1r1.internal.permanent.set_provider.vm3", "vms": "^vm3$"},
        ]
        intertest_setup.graphfull(self.args, self.run_params, tag="1r")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_graphfull_root(self):
        self.run_params["vms"] = "vm2 vm3"
        self.run_params["state_vm2"] = "customize_vm"
        self.run_params["state_vm3"] = "root"
        self.args.vm_strs = {"vm2": "only Business_Server\n", "vm3": "only Security_Gateway\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^1rmm.internal.stateless.manage_vms.unchanged.vm2", "vms": "^vm2$", "unset_state": "^root$"},
            {"shortname": "^1rmm.internal.stateless.manage_vms.unchanged.vm3", "vms": "^vm3$", "unset_state": "^root$"},
            {"shortname": "^root.internal.stateless.manage_vms.unchanged.vm2", "vms": "^vm2$", "set_state": "^root$"},
            {"shortname": "^1r1a1.internal.stateless.configure_install.vm2", "vms": "^vm2$"},
            {"shortname": "^1r1a1.original.install.vm2", "vms": "^vm2$", "cdrom_cd1": ".*business-server.*\.iso$"},
            {"shortname": "^1r1.internal.permanent.customize_vm.vm2", "vms": "^vm2$"},
            {"shortname": "^1r.internal.stateless.manage_vms.unchanged.vm3", "vms": "^vm3$", "set_state": "^root$"},
        ]
        intertest_setup.graphfull(self.args, self.run_params, tag="1r")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_graphupdate_default(self):
        self.run_params["vms"] = "vm4"
        self.run_params["remove_set"] = "minimal"
        self.args.vm_strs = {"vm1": "only Business_Server\n", "vm2": "only Security_Gateway\n", "vm3": "only Security_Gateway\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": ".+internal.stateless.manage_vms.unchanged.vm4", "vms": "^vm4$", "unset_state": "^linux_firefox$"},
            {"shortname": ".+internal.stateless.manage_vms.unchanged.vm4", "vms": "^vm4$", "unset_state": "^linux_virtuser$"},
            {"shortname": "^01.internal.permanent.customize_vm.vm4", "vms": "^vm4$"},
        ]
        intertest_setup.graphupdate(self.args, self.run_params, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_graphupdate_custom(self):
        self.run_params["vms"] = "vm4"
        self.run_params["remove_set"] = "minimal"
        self.run_params["from_state"] = "install"
        self.run_params["to_state"] = "linux_virtuser"
        self.args.vm_strs = {"vm1": "only Business_Server\n", "vm2": "only Security_Gateway\n", "vm3": "only Security_Gateway\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": ".+internal.stateless.manage_vms.unchanged.vm4", "vms": "^vm4$", "unset_state": "^linux_firefox$"},
            {"shortname": ".+internal.permanent.customize_vm.vm4", "vms": "^vm4$", "get_state": "^install$"},
            {"shortname": "01.internal.permanent.linux_virtuser.vm4", "vms": "^vm4$", "get_state": "^customize_vm$"},
        ]
        intertest_setup.graphupdate(self.args, self.run_params, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_windows(self):
        self.run_params["with_outlook"] = "no"
        self.run_params["vms"] = "vm50 vm5"
        self.args.vm_strs = {"vm50": "only WinXP\n", "vm5": "only Win10\n"}

        DummyTestRunning.asserted_tests = [
            {"shortname": "^ut.internal.stateless.manage_vms.start.vm50.virtio_blk.smp2.virtio_net.WinXP.i386.sp3$", "vms": "^vm50$", "set_state": "^windows_online$"},
            {"shortname": "^ut.internal.permanent.windows_virtuser.vm50.virtio_blk.smp2.virtio_net.WinXP.i386.sp3$", "vms": "^vm50$", "get_state": "^customize_vm$", "set_state": "^windows_virtuser$"},
            {"shortname": "^ut.internal.stateless.manage_vms.start.vm5.smp2.Win10.x86_64$", "vms": "^vm5$", "set_state": "^windows_online$"},
            {"shortname": "^ut.internal.permanent.windows_virtuser.vm5.smp2.Win10.x86_64$", "vms": "^vm5$", "get_state": "^customize_vm$", "set_state": "^windows_virtuser$"},
        ]
        intertest_setup.windows(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

        self.run_params["with_outlook"] = "2013"

        DummyTestRunning.asserted_tests = [
            {"shortname": "^ut.internal.stateless.manage_vms.start.vm50.virtio_blk.smp2.virtio_net.WinXP.i386.sp3$", "vms": "^vm50$", "set_state": "^windows_online$"},
            {"shortname": "^ut.internal.permanent.windows_virtuser.vm50.virtio_blk.smp2.virtio_net.WinXP.i386.sp3$", "vms": "^vm50$", "get_state": "^customize_vm$", "set_state": "^windows_virtuser$"},
            {"shortname": "^ut.internal.manual.outlook_prep.ol2013.vm50.virtio_blk.smp2.virtio_net.WinXP.i386.sp3$", "vms": "^vm50$", "get_state": "^windows_online$", "set_state": "^outlook_prep$"},
            {"shortname": "^ut.internal.stateless.manage_vms.start.vm5.smp2.Win10.x86_64$", "vms": "^vm5$", "set_state": "^windows_online$"},
            {"shortname": "^ut.internal.permanent.windows_virtuser.vm5.smp2.Win10.x86_64$", "vms": "^vm5$", "get_state": "^customize_vm$", "set_state": "^windows_virtuser$"},
            {"shortname": "^ut.internal.manual.outlook_prep.ol2013.vm5.smp2.Win10.x86_64$", "vms": "^vm5$", "get_state": "^windows_online$", "set_state": "^outlook_prep$"},
        ]
        intertest_setup.windows(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_develop(self):
        self.run_params["vms"] = "vm4 vm5"
        self.args.vm_strs = {"vm1": "only Security_Gateway\n", "vm2": "only Security_Gateway\n", "vm3": "only Security_Gateway\n"}

        DummyTestRunning.asserted_tests = [
            {"shortname": "^01.internal.manual.develop.generator.vm4", "vms": "^vm4 vm5$"},
        ]
        intertest_setup.develop(self.args, self.run_params, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_install(self):
        self.run_params["vms"] = "vm1 vm4"
        self.args.vm_strs = {"vm1": "only Security_Gateway\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^ut.internal.stateless.configure_install.vm1", "vms": "^vm1$"},
            {"shortname": "^ut.original.install.vm1", "vms": "^vm1$", "cdrom_cd1": ".*security-gateway.*\.iso$"},
            {"shortname": "^ut.internal.stateless.configure_install.vm4", "vms": "^vm4$"},
            {"shortname": "^ut.original.unattended_install.cdrom.extra_cdrom_ks.default_install.aio_threads.vm4", "vms": "^vm4$"},
        ]
        intertest_setup.install(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deploy_stateless(self):
        self.run_params["vms"] = "vm1 vm4"
        self.args.vm_strs = {"vm1": "only Network_Security\nstateless=yes\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^ut.internal.permanent.customize_vm.vm1", "vms": "^vm1$", "get_state": "^$", "set_state": "^$"},
            {"shortname": "^ut.internal.permanent.customize_vm.vm4", "vms": "^vm4$", "get_state": "^$", "set_state": "^$"},
        ]
        intertest_setup.deploy(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deploy_stateful(self):
        self.run_params["vms"] = "vm1 vm4"
        self.args.vm_strs = {"vm1": "only Network_Security\nstateless=no\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^ut.internal.permanent.customize_vm.vm1", "vms": "^vm1$", "get_state": "^install$", "set_state": "^customize_vm$"},
            {"shortname": "^ut.internal.permanent.customize_vm.vm4", "vms": "^vm4$", "get_state": "^$", "set_state": "^$"},
        ]
        intertest_setup.deploy(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deploy_states(self):
        self.run_params["vms"] = "vm50"
        self.args.vm_strs = {"vm50": "only WinXP\nstates=state1 state2\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^ut.internal.permanent.customize_vm.vm50", "vms": "^vm50$", "get_state": "^state1$", "set_state": "^state1$"},
            {"shortname": "^ut2.internal.permanent.customize_vm.vm50", "vms": "^vm50$", "get_state": "^state2$", "set_state": "^state2$"},
        ]
        intertest_setup.deploy(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_deploy_states_multivm(self):
        self.run_params["vms"] = "vm50 vm70"
        self.args.vm_strs = {"vm50": "only WinXP\nstates=state1 state2 state3\n", "vm70": "only Win7\nstates=state1 state3\n", }
        DummyTestRunning.asserted_tests = [
            {"shortname": "^ut.internal.permanent.customize_vm.vm50", "vms": "^vm50$", "get_state": "^state1$", "set_state": "^state1$"},
            {"shortname": "^ut2.internal.permanent.customize_vm.vm50", "vms": "^vm50$", "get_state": "^state2$", "set_state": "^state2$"},
            {"shortname": "^ut3.internal.permanent.customize_vm.vm50", "vms": "^vm50$", "get_state": "^state3$", "set_state": "^state3$"},
            {"shortname": "^ut.internal.permanent.customize_vm.vm70", "vms": "^vm70$", "get_state": "^state1$", "set_state": "^state1$"},
            {"shortname": "^ut2.internal.permanent.customize_vm.vm70", "vms": "^vm70$", "get_state": "^state3$", "set_state": "^state3$"},
        ]
        intertest_setup.deploy(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_internal_stateless(self):
        self.run_params["vms"] = "vm50"
        self.args.vm_strs = {"vm50": "only WinXP\nnode=outlook_prep..ol2003\nstateless=yes\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^ut.internal.manual.outlook_prep.ol2003", "vms": "^vm50$", "get_state": "^$", "set_state": "^$"},
        ]
        intertest_setup.internal(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_internal_stateful(self):
        self.run_params["vms"] = "vm50"
        self.args.vm_strs = {"vm50": "only WinXP\nnode=client_install..ol2003\nstateless=no\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "ut.internal.permanent.client_install.ol2003", "vms": "^vm50$", "get_state": "^outlook_prep$", "set_state": "^client_install$"},
        ]
        intertest_setup.internal(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_sysupdate(self):
        self.run_params["vms"] = "vm1 vm2"
        self.args.vm_strs = {"vm1": "only Security_Gateway\n", "vm2": "only Business_Server\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^ut.internal.permanent.system_update.vm1", "vms": "^vm1$"},
            {"shortname": "^ut.internal.permanent.system_update.vm2", "vms": "^vm2$"},
        ]
        intertest_setup.sysupdate(self.args, self.run_params, tag="ut")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_boot(self):
        self.run_params["vms"] = "vm2 vm4"
        self.args.param_str += "vms=vm2 vm4\n"
        self.args.vm_strs = {"vm1": "only Security_Gateway\n", "vm2": "only Security_Gateway\n", "vm3": "only Security_Gateway\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^01.internal.stateless.manage_vms.start", "start_vm": "^yes$", "vms": "^vm2 vm4$"},
        ]
        intertest_setup.boot(self.args, self.run_params, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_download(self):
        self.run_params["vms"] = "vm2 vm4"
        self.args.param_str += "vms=vm2 vm4\n"
        self.args.vm_strs = {"vm1": "only Security_Gateway\n", "vm2": "only Security_Gateway\n", "vm3": "only Security_Gateway\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^01.internal.stateless.manage_vms.download", "vms": "^vm2 vm4$"},
        ]
        intertest_setup.download(self.args, self.run_params, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_upload(self):
        self.run_params["vms"] = "vm2 vm4"
        self.args.param_str += "vms=vm2 vm4\n"
        self.args.vm_strs = {"vm1": "only Security_Gateway\n", "vm2": "only Security_Gateway\n", "vm3": "only Security_Gateway\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^01.internal.stateless.manage_vms.upload", "vms": "^vm2 vm4$"},
        ]
        intertest_setup.upload(self.args, self.run_params, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_shutdown(self):
        self.run_params["vms"] = "vm2 vm4"
        self.args.param_str += "vms=vm2 vm4\n"
        self.args.vm_strs = {"vm1": "only Security_Gateway\n", "vm2": "only Security_Gateway\n", "vm3": "only Security_Gateway\n"}
        DummyTestRunning.asserted_tests = [
            {"shortname": "^01.internal.stateless.manage_vms.stop", "vms": "^vm2 vm4$"},
        ]
        intertest_setup.shutdown(self.args, self.run_params, tag="0")
        self.assertEqual(len(DummyTestRunning.asserted_tests), 0, "Some tests weren't run: %s" % DummyTestRunning.asserted_tests)

    def test_manual_state_manipulation(self):
        self.run_params["vms"] = "vm2"
        self.args.vm_strs = {"vm2": "only Business_Server\n"}
        for state_action in ["check", "pop", "push", "get", "set", "unset"]:
            DummyTestRunning.asserted_tests = [
                {"shortname": ".*internal.stateless.manage_vms.unchanged.vm2", "vms": "^vm2$",
                 "skip_image_processing": "^yes$", "vm_action": "^%s$" % state_action},
            ]
            setup_func = getattr(intertest_setup, state_action)
            setup_func(self.args, self.run_params)

        for state_action in ["create", "clean"]:
            DummyTestRunning.asserted_tests = [
                {"shortname": "^5m.internal.stateless.manage_vms.unchanged.vm2", "vms": "^vm2$",
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
