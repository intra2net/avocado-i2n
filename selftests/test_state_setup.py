#!/usr/bin/env python

import unittest
import unittest.mock as mock
import os

from avocado.core import exceptions
from avocado.utils import process
from avocado.utils import lv_utils
from virttest import utils_params

import unittest_importer
# use old name to reduce amount of changes in the unit tests
from avocado_i2n.states import setup as ss
from avocado_i2n.states import qcow2
from avocado_i2n.states import lvm
from avocado_i2n.states import ramfile
from avocado_i2n.states import lxc
from avocado_i2n.states import btrfs
from avocado_i2n.states import pool


@mock.patch('avocado_i2n.states.lvm.os.mkdir', mock.Mock(return_value=0))
@mock.patch('avocado_i2n.states.lvm.os.makedirs', mock.Mock(return_value=0))
@mock.patch('avocado_i2n.states.lvm.os.rmdir', mock.Mock(return_value=0))
@mock.patch('avocado_i2n.states.lvm.os.unlink', mock.Mock(return_value=0))
@mock.patch('avocado_i2n.states.lvm.shutil.rmtree', mock.Mock(return_value=0))
@mock.patch('avocado_i2n.states.pool.os.makedirs', mock.Mock(return_value=0))
class StateSetupTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.run_str = ""

        ss.OFF_BACKENDS = {"lvm": lvm.LVMBackend, "qcow2": qcow2.QCOW2Backend,
                           "lxc": lxc.LXCBackend, "btrfs": btrfs.BtrfsBackend,
                           "pool": pool.QCOW2PoolBackend}
        ss.ON_BACKENDS = {"qcow2vt": qcow2.QCOW2VTBackend,
                          "ramfile": ramfile.RamfileBackend}

        # disable pool locks for easier mocking
        pool.SKIP_LOCKS = True

    def setUp(self):
        self.run_params = utils_params.Params()
        self.run_params["vms"] = "vm1"
        self.run_params["images"] = "image1"
        self.run_params["image_name_vm1"] = "vm1/image"
        self.run_params["images_base_dir"] = "/images"
        self.run_params["off_states"] = "lvm"
        self.run_params["on_states"] = "qcow2vt"

        self.env = mock.MagicMock(name='env')
        self.env.get_vm = mock.MagicMock(side_effect=self._get_mock_vm)

        exists_patch = mock.patch('avocado_i2n.states.setup.os.path.exists', mock.MagicMock(side_effect=self._file_exists))
        exists_patch.start()
        self.addCleanup(exists_patch.stop)

        self.mock_vms = {}

        self.exist_switch = True
        self.exist_lambda = None

    def _set_off_lvm_params(self):
        self.run_params["off_states"] = "lvm"
        self.run_params["vg_name_vm1"] = "disk_vm1"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["lv_pointer_name"] = "current_state"

    def _set_off_qcow2_params(self):
        self.run_params["off_states"] = "qcow2"
        self.run_params["image_format"] = "qcow2"
        self.run_params["qemu_img_binary"] = "qemu-img"

    def _set_off_pool_params(self):
        self.run_params["off_states"] = "pool"
        self.run_params["image_pool"] = "/data/pool"
        self.run_params["image_format"] = "qcow2"
        self.run_params["qemu_img_binary"] = "qemu-img"

    def _set_on_qcow2_params(self):
        self.run_params["on_states"] = "qcow2vt"
        self.run_params["image_format"] = "qcow2"
        self.run_params["qemu_img_binary"] = "qemu-img"

    def _set_on_ramfile_params(self):
        self.run_params["on_states"] = "ramfile"

    def _get_mock_vm(self, vm_name):
        return self.mock_vms[vm_name]

    def _create_mock_vms(self):
        for vm_name in self.run_params.objects("vms"):
            self.mock_vms[vm_name] = mock.MagicMock(name=vm_name)
            self.mock_vms[vm_name].name = vm_name
            self.mock_vms[vm_name].params = self.run_params.object_params(vm_name)

    def _file_exists(self, filepath):
        if self.exist_lambda:
            return self.exist_lambda(filepath)
        return self.exist_switch

    def _only_root_exists(self, vg_name, lv_name):
        return True if lv_name == "LogVol" else False

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_show_states_off_lvm(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["check_type_vm1"] = "off"
        self._create_mock_vms()

        # test without available states
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_list.return_value = []
        states = ss.show_states(self.run_params, self.env)
        mock_lv_utils.lv_list.assert_called_once_with("disk_vm1")
        self.assertEqual(len(states), 0)

        # test with available states
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_list.return_value = ["launch1", "launch2"]
        states = ss.show_states(self.run_params, self.env)
        mock_lv_utils.lv_list.assert_called_once_with("disk_vm1")
        self.assertIn("launch1", states)
        self.assertIn("launch2", states)
        self.assertNotIn("launch3", states)
        self.assertNotIn("root", states)

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_show_states_offon_qcow2(self, mock_process):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self._create_mock_vms()

        # test without available states
        mock_process.reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        states = ss.show_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.assertEqual(len(states), 0)

        # test with available off states
        self.run_params["check_type"] = "on"
        mock_process.reset_mock()
        mock_process.system_output.return_value = (b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478\n"
                                                   b"7         with.dot       0.977 GiB 2020-12-08 10:51:49   00:02:00.006")
        states = ss.show_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.assertEqual(len(states), 2)
        self.assertIn("launch", states)
        self.assertIn("with.dot", states)
        self.assertNotIn("launch2", states)
        self.assertNotIn("boot", states)

        # test with available on states
        self.run_params["check_type"] = "off"
        mock_process.reset_mock()
        mock_process.system_output.return_value = (b"5         launch         0 B 2021-01-18 21:24:22   00:00:44.478\n"
                                                   b"7         with.dot       0 B 2020-12-08 10:51:49   00:02:00.006")
        states = ss.show_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.assertEqual(len(states), 2)
        self.assertIn("launch", states)
        self.assertIn("with.dot", states)
        self.assertNotIn("launch2", states)
        self.assertNotIn("boot", states)

    @mock.patch('avocado_i2n.states.ramfile.glob')
    def test_show_states_on_ramfile(self, mock_glob):
        self._set_off_qcow2_params()
        self._set_on_ramfile_params()
        self.run_params["check_type_vm1"] = "on"
        self._create_mock_vms()

        # test without available states
        mock_glob.reset_mock()
        mock_glob.glob.return_value = []
        states = ss.show_states(self.run_params, self.env)
        mock_glob.glob.assert_called_once_with("/images/vm1/*.state")
        self.assertEqual(len(states), 0)

        # test with available states
        mock_glob.reset_mock()
        mock_glob.glob.return_value = ["/images/vm1/launch.state", "/images/vm1/with.dot.state"]
        states = ss.show_states(self.run_params, self.env)
        mock_glob.glob.assert_called_once_with("/images/vm1/*.state")
        self.assertEqual(len(states), 2)
        self.assertIn("/images/vm1/launch.state", states)
        self.assertIn("/images/vm1/with.dot.state", states)
        self.assertNotIn("/images/vm1/launch2", states)
        self.assertNotIn("boot", states)

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_check_off_lvm(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["check_state_vm1"] = "launch"
        self.run_params["check_type_vm1"] = "off"
        self.run_params["check_opts_vm1"] = "soft_boot=yes"
        self._create_mock_vms()

        expected_checks = [mock.call("disk_vm1", "LogVol"),
                           mock.call("disk_vm1", "launch")]

        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.return_value = True
        exists = ss.check_states(self.run_params, self.env)
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=True)
        self.assertTrue(exists)

        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.side_effect = self._only_root_exists
        exists = ss.check_states(self.run_params, self.env)
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=True)
        self.assertFalse(exists)

        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.return_value = False
        mock_lv_utils.lv_check.side_effect = None
        exists = ss.check_states(self.run_params, self.env)
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks[:1])
        self.mock_vms["vm1"].destroy.assert_not_called()
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_check_offon_qcow2(self, mock_process):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["check_state_vm1"] = "launch"
        self.run_params["check_opts_vm1"] = "soft_boot=yes"
        self._create_mock_vms()

        self.run_params["check_type_vm1"] = "on"
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = True
        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        exists = ss.check_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.assertTrue(exists)

        self.run_params["check_type_vm1"] = "off"
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = True
        mock_process.system_output.return_value = b"5         launch         0 B 2021-01-18 21:24:22   00:00:44.478"
        exists = ss.check_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called()
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.assertTrue(exists)

        self.run_params["check_type_vm1"] = "any"

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = True
        mock_process.system_output.return_value = b"NOT HERE"
        exists = ss.check_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        mock_process.system_output.assert_called_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.assertFalse(exists)

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        exists = ss.check_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called_with()
        # TODO: on root existence is handled and enforced differently
        # than off root existence at the moment - need more unification
        #mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        mock_process.system_output.assert_called_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.ramfile.os')
    def test_check_on_ramfile(self, mock_os):
        self._set_off_qcow2_params()
        self._set_on_ramfile_params()
        self.run_params["check_state_vm1"] = "launch"
        self.run_params["check_type_vm1"] = "on"
        self._create_mock_vms()

        # restore some unmocked parts of the os module
        mock_os.path.dirname = os.path.dirname
        mock_os.path.join = os.path.join
        mock_os.path.isabs.return_value = False
        # we cannot use the exist switch because we also want to assert calls
        # mock_os.path.exists = self._file_exists

        mock_os.reset_mock()
        mock_os.path.exists.return_value = False
        exists = ss.check_states(self.run_params, self.env)
        mock_os.path.exists.assert_called_once_with("/images/vm1/launch.state")
        self.assertFalse(exists)

        mock_os.reset_mock()
        mock_os.path.exists.return_value = True
        exists = ss.check_states(self.run_params, self.env)
        mock_os.path.exists.assert_called_once_with("/images/vm1/launch.state")
        self.assertTrue(exists)

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_check_any_all(self, _mock_lv_utils, mock_process):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["check_state_vm1"] = "launch"
        self.run_params["off_states_vm1"] = "qcow2"
        self._create_mock_vms()

        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        exists = ss.check_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.assertTrue(exists)

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_check_any_fallback(self, mock_lv_utils, mock_process):
        self._set_off_lvm_params()
        self._set_on_qcow2_params()
        self.run_params["check_state_vm1"] = "launch"
        self._create_mock_vms()

        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = True
        exists = ss.check_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        expected_checks = [mock.call("disk_vm1", "LogVol"),
                           mock.call("disk_vm1", "launch")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        self.assertTrue(exists)

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_check_any_none(self, mock_lv_utils, mock_process):
        self._set_off_lvm_params()
        self._set_on_qcow2_params()
        self.run_params["check_state_vm1"] = "launch"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_process.reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.side_effect = self._only_root_exists
        exists = ss.check_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        expected_checks = [mock.call("disk_vm1", "LogVol"),
                           mock.call("disk_vm1", "launch")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_off_lvm(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["get_state_vm1"] = "launch"
        self.run_params["get_type_vm1"] = "off"
        self.run_params["get_mode_vm1"] = "ri"
        self.run_params["skip_types"] = "on"
        self._create_mock_vms()

        expected_checks = [mock.call("disk_vm1", "LogVol"),
                           mock.call("disk_vm1", "launch")]

        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.get_states(self.run_params, self.env)
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=False)
        mock_lv_utils.lv_remove.assert_called_once_with('disk_vm1', 'current_state')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'launch', 'current_state')

        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.side_effect = self._only_root_exists
        ss.get_states(self.run_params, self.env)
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=False)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.return_value = False
        mock_lv_utils.lv_check.side_effect = None
        ss.get_states(self.run_params, self.env)
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks[:1])
        self.mock_vms["vm1"].destroy.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_get_off_qcow2(self, mock_process):
        self._set_off_qcow2_params()
        self.run_params["get_state_vm1"] = "launch"
        self.run_params["get_type_vm1"] = "off"
        self.run_params["get_mode_vm1"] = "ri"
        self.run_params["skip_types"] = "on"
        self._create_mock_vms()

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_switch = True
        mock_process.system_output.return_value = b"5         launch         0 B 2021-01-18 21:24:22   00:00:44.478"
        ss.get_states(self.run_params, self.env)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=False)
        mock_process.system.assert_called_once_with("qemu-img snapshot -a launch /images/vm1/image.qcow2")

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_switch = True
        mock_process.system_output.return_value = b"NOT HERE"
        ss.get_states(self.run_params, self.env)
        mock_process.system.assert_not_called()

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_switch = False
        ss.get_states(self.run_params, self.env)
        mock_process.system.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_off_aa(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["get_state_vm1"] = "launch"
        self.run_params["get_type_vm1"] = "off"
        self.run_params["get_mode_vm1"] = "aa"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm1"].is_alive.return_value = False
        with self.assertRaises(exceptions.TestSkipError):
            ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()
        self.mock_vms["vm1"].is_alive.assert_called()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestSkipError):
            ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_off_rx(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["get_state_vm1"] = "launch"
        self.run_params["get_type_vm1"] = "off"
        self.run_params["get_mode_vm1"] = "rx"
        self.run_params["image_name_vm1"] = "vm1/image"
        self.run_params["image_raw_device_vm1"] = "no"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm1"].is_alive.return_value = False
        ss.get_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called()
        mock_lv_utils.lv_remove.assert_called_once_with('disk_vm1', 'current_state')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'launch', 'current_state')

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestError):
            ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_off_ii(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["get_state_vm1"] = "launch"
        self.run_params["get_type_vm1"] = "off"
        self.run_params["get_mode_vm1"] = "ii"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm1"].is_alive.return_value = False
        ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()
        self.mock_vms["vm1"].is_alive.assert_called()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_off_xx(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["get_state_vm1"] = "launch"
        self.run_params["get_type_vm1"] = "off"
        self.run_params["get_mode_vm1"] = "xx"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm1"].is_alive.return_value = False
        with self.assertRaises(exceptions.TestError):
            ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()
        self.mock_vms["vm1"].is_alive.assert_called()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestError):
            ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_get_on_qcow2vt(self, mock_process):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["get_state_vm1"] = "launch"
        self.run_params["get_type_vm1"] = "on"
        self.run_params["get_mode_vm1"] = "ri"
        self._create_mock_vms()

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        self.mock_vms["vm1"].is_alive.return_value = True
        ss.get_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        # called only if not alive
        self.mock_vms["vm1"].create.assert_not_called()
        self.mock_vms["vm1"].loadvm.assert_called_once_with('launch')

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        self.mock_vms["vm1"].is_alive.return_value = True
        ss.get_states(self.run_params, self.env)
        # called 2 times - one to check for the boot and one to set the boot
        self.mock_vms["vm1"].is_alive.assert_called()
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        # called only if not alive
        self.mock_vms["vm1"].create.assert_not_called()
        self.mock_vms["vm1"].loadvm.assert_not_called()

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        ss.get_states(self.run_params, self.env)
        # called 2 times - one to check for the boot and one to set the boot
        self.mock_vms["vm1"].is_alive.assert_called()
        self.mock_vms["vm1"].create.assert_called_once()
        self.mock_vms["vm1"].loadvm.assert_not_called()

    @mock.patch('avocado_i2n.states.ramfile.os')
    def test_get_on_ramfile(self, mock_os):
        self._set_off_qcow2_params()
        self._set_on_ramfile_params()
        self.run_params["get_state_vm1"] = "launch"
        self.run_params["get_type_vm1"] = "on"
        self.run_params["get_mode_vm1"] = "rx"
        self._create_mock_vms()

        # restore some unmocked parts of the os module
        mock_os.path.dirname = os.path.dirname
        mock_os.path.join = os.path.join
        mock_os.path.isabs.return_value = False
        # we cannot use the exist switch because we also want to assert calls
        # mock_os.path.exists = self._file_exists

        mock_os.reset_mock()
        mock_os.path.exists.return_value = True
        ss.get_states(self.run_params, self.env)
        self.mock_vms["vm1"].restore_from_file.assert_called_once_with("/images/vm1/launch.state")

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_get_on_rx(self, mock_process):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["get_state_vm1"] = "launch"
        self.run_params["get_type_vm1"] = "on"
        self.run_params["get_mode_vm1"] = "rx"
        self._create_mock_vms()

        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        self.mock_vms["vm1"].is_alive.return_value = True
        # switch check if vm has to be booted
        ss.get_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        self.mock_vms["vm1"].loadvm.assert_called_once_with('launch')

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_any_all_rx(self, mock_lv_utils, mock_process):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["get_state_vm1"] = "launch"
        self.run_params["get_mode_vm1"] = "rx"
        self._create_mock_vms()

        # if >= 1 states prefer on
        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        # this time the on switch asks so confirm for it as well
        self.mock_vms["vm1"].is_alive.return_value = True
        ss.get_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.mock_vms["vm1"].is_alive.assert_called()
        self.mock_vms["vm1"].loadvm.assert_called_once_with('launch')

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_any_fallback_rx(self, mock_lv_utils, mock_process):
        self._set_off_lvm_params()
        self._set_on_qcow2_params()
        self.run_params["get_state_vm1"] = "launch"
        self.run_params["get_mode_vm1"] = "rx"
        self.run_params["image_raw_device_vm1"] = "no"
        self._create_mock_vms()

        # if only off state choose it
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm1"].is_alive.return_value = True
        ss.get_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        expected_checks = [mock.call("disk_vm1", "LogVol"),
                           mock.call("disk_vm1", "launch")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        self.mock_vms["vm1"].is_alive.assert_called()
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=False)
        mock_lv_utils.lv_remove.assert_called_once_with('disk_vm1', 'current_state')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'launch', 'current_state')

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_any_none_xi(self, mock_lv_utils, mock_process):
        self._set_off_lvm_params()
        self._set_on_qcow2_params()
        self.run_params["get_state_vm1"] = "launch"
        self.run_params["get_mode_vm1"] = "xi"
        # self.run_params["image_raw_device_vm1"] = "no"
        self._create_mock_vms()

        # if no states prefer on
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.side_effect = self._only_root_exists
        self.mock_vms["vm1"].is_alive.return_value = True
        ss.get_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        expected_checks = [mock.call("disk_vm1", "LogVol"),
                           mock.call("disk_vm1", "launch")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_off_lvm(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_type_vm1"] = "off"
        self.run_params["set_mode_vm1"] = "ff"
        self.run_params["skip_types"] = "on"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.set_states(self.run_params, self.env)
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list,
                             [mock.call("disk_vm1", "LogVol"),
                              mock.call("disk_vm1", "launch")])
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=True)
        mock_lv_utils.lv_remove.assert_called_once_with("disk_vm1", "launch")
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'current_state', 'launch')

        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.side_effect = self._only_root_exists
        ss.set_states(self.run_params, self.env)
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list,
                             [mock.call("disk_vm1", "LogVol"),
                              mock.call("disk_vm1", "launch"),
                              # extra root check to prevent forced setting without root
                              mock.call("disk_vm1", "LogVol")])
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=True)
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'current_state', 'launch')

        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.return_value = False
        mock_lv_utils.lv_check.side_effect = None
        with self.assertRaises(exceptions.TestError):
            ss.set_states(self.run_params, self.env)
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list,
                             [mock.call("disk_vm1", "LogVol"),
                              # extra root check to prevent forced setting without root
                              mock.call("disk_vm1", "LogVol")])
        self.mock_vms["vm1"].destroy.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_set_off_qcow2(self, mock_process):
        self._set_off_qcow2_params()
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_type_vm1"] = "off"
        self.run_params["set_mode_vm1"] = "ff"
        self.run_params["skip_types"] = "on"
        self._create_mock_vms()

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_switch = True
        mock_process.system_output.return_value = b"5         launch         0 B 2021-01-18 21:24:22   00:00:44.478"
        ss.set_states(self.run_params, self.env)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=True)
        expected_checks = [mock.call("qemu-img snapshot -d launch /images/vm1/image.qcow2"),
                           mock.call("qemu-img snapshot -c launch /images/vm1/image.qcow2")]
        self.assertListEqual(mock_process.system.call_args_list, expected_checks)

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_switch = True
        mock_process.system_output.return_value = b"NOT HERE"
        ss.set_states(self.run_params, self.env)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=True)
        mock_process.system.assert_called_once_with("qemu-img snapshot -c launch /images/vm1/image.qcow2")

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_switch = False
        with self.assertRaises(exceptions.TestError):
            ss.set_states(self.run_params, self.env)
        self.mock_vms["vm1"].destroy.assert_not_called()
        mock_process.system.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_off_aa(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_type_vm1"] = "off"
        self.run_params["set_mode_vm1"] = "aa"
        self.run_params["skip_types"] = "on"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        with self.assertRaises(exceptions.TestSkipError):
            ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestSkipError):
            ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_off_rx(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_type_vm1"] = "off"
        self.run_params["set_mode_vm1"] = "rx"
        self.run_params["skip_types"] = "on"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestError):
            ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_off_ff(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_type_vm1"] = "off"
        self.run_params["set_mode_vm1"] = "ff"
        self.run_params["skip_types"] = "on"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_called_once_with("disk_vm1", "launch")
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'current_state', 'launch')

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.side_effect = self._only_root_exists
        ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'current_state', 'launch')

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.side_effect = None
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestError):
            ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_off_xx(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_type_vm1"] = "off"
        self.run_params["set_mode_vm1"] = "xx"
        self.run_params["skip_types"] = "on"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        with self.assertRaises(exceptions.TestError):
            ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestError):
            ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_set_on_qcow2vt(self, mock_process):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_type_vm1"] = "on"
        self.run_params["set_mode_vm1"] = "ff"
        self.run_params["skip_types"] = "off"
        self._create_mock_vms()

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        self.mock_vms["vm1"].is_alive.return_value = True
        ss.set_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        # called only if not alive
        self.mock_vms["vm1"].create.assert_not_called()
        self.mock_vms["vm1"].savevm.assert_called_once_with('launch')

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        self.mock_vms["vm1"].is_alive.return_value = True
        ss.set_states(self.run_params, self.env)
        # called 2 times - one to check for the boot and one to set the boot
        self.mock_vms["vm1"].is_alive.assert_called()
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        # called only if not alive
        self.mock_vms["vm1"].create.assert_not_called()
        self.mock_vms["vm1"].savevm.assert_called_once_with('launch')

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        # TODO: on states are not fully nested - we could detect state while the vm is off
        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        self.mock_vms["vm1"].is_alive.return_value = False
        ss.set_states(self.run_params, self.env)
        # called 2 times - one to check for the boot and one to set the boot
        self.mock_vms["vm1"].is_alive.assert_called()
        self.mock_vms["vm1"].create.assert_called_once()
        # TODO: on states are not fully nested - we could detect state while the vm is off
        #self.mock_vms["vm1"].savevm.assert_not_called()
        self.mock_vms["vm1"].savevm.assert_called_once_with('launch')

    @mock.patch('avocado_i2n.states.ramfile.os')
    def test_set_on_ramfile(self, mock_os):
        self._set_off_qcow2_params()
        self._set_on_ramfile_params()
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_type_vm1"] = "on"
        self.run_params["set_mode_vm1"] = "ff"
        self.run_params["skip_types"] = "off"
        self._create_mock_vms()

        # restore some unmocked parts of the os module
        mock_os.path.dirname = os.path.dirname
        mock_os.path.join = os.path.join
        mock_os.path.isabs.return_value = False
        # we cannot use the exist switch because we also want to assert calls
        # mock_os.path.exists = self._file_exists

        mock_os.reset_mock()
        mock_os.path.exists.return_value = True
        ss.set_states(self.run_params, self.env)
        self.mock_vms["vm1"].save_to_file.assert_called_once_with("/images/vm1/launch.state")

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_set_on_ff(self, mock_process):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_type_vm1"] = "on"
        self.run_params["set_mode_vm1"] = "ff"
        self.run_params["skip_types"] = "off"
        self._create_mock_vms()

        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        ss.set_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.mock_vms["vm1"].savevm.assert_called_once_with('launch')

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_any_all_ff(self, mock_lv_utils, mock_process):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_mode_vm1"] = "ff"
        self.run_params["skip_types"] = ""
        self._create_mock_vms()

        # if no skipping and too many states prefer on
        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        ss.set_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.mock_vms["vm1"].savevm.assert_called_once_with('launch')

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_any_fallback_ff(self, mock_lv_utils, mock_process):
        self._set_off_lvm_params()
        self._set_on_qcow2_params()
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_mode_vm1"] = "ff"
        self.run_params["skip_types"] = ""
        self._create_mock_vms()

        # if no skipping with only off state available
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm1"].is_alive.return_value = True
        ss.set_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        expected_checks = [mock.call("disk_vm1", "LogVol"),
                           mock.call("disk_vm1", "launch")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        self.mock_vms["vm1"].is_alive.assert_called()
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=True)
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'current_state', 'launch')

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_any_none_ff(self, mock_lv_utils, mock_process):
        self._set_off_lvm_params()
        self._set_on_qcow2_params()
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_mode_vm1"] = "ff"
        self.run_params["skip_types"] = ""
        self._create_mock_vms()

        # if no skipping and no states prefer on
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.side_effect = self._only_root_exists
        self.mock_vms["vm1"].is_alive.return_value = True
        ss.set_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        expected_checks = [mock.call("disk_vm1", "LogVol"),
                           mock.call("disk_vm1", "launch")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        self.mock_vms["vm1"].savevm.assert_called_once_with('launch')

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_any_all_skip_on(self, mock_lv_utils, mock_process):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_mode_vm1"] = "ff"
        self.run_params["skip_types"] = "on"
        self._create_mock_vms()

        # skip setting the state since on is available but we skip on by parameters
        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        ss.set_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_any_fallback_skip_on(self, mock_lv_utils, mock_process):
        self._set_off_lvm_params()
        self._set_on_qcow2_params()
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_mode_vm1"] = "ff"
        self.run_params["skip_types"] = "on"
        self._create_mock_vms()

        # set the state since only off is available and we skip on by parameters
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = True
        ss.set_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        expected_checks = [mock.call("disk_vm1", "LogVol"),
                           mock.call("disk_vm1", "launch")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=True)
        mock_lv_utils.lv_remove.assert_called_once_with("disk_vm1", "launch")
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'current_state', 'launch')

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_any_fallback_skip_off(self, mock_lv_utils, mock_process):
        self._set_off_lvm_params()
        self._set_on_qcow2_params()
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_mode_vm1"] = "ff"
        self.run_params["skip_types"] = "off"
        self._create_mock_vms()

        # skip setting the state since only off is available but we skip off by parameters
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = True
        ss.set_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        expected_checks = [mock.call("disk_vm1", "LogVol"),
                           mock.call("disk_vm1", "launch")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_unset_off_lvm(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["unset_state_vm1"] = "launch"
        self.run_params["unset_type_vm1"] = "off"
        self.run_params["unset_mode_vm1"] = "fi"
        self.run_params["lv_pointer_name"] = "current_state"
        self._create_mock_vms()

        expected_checks = [mock.call("disk_vm1", "LogVol"),
                           mock.call("disk_vm1", "launch")]

        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.unset_states(self.run_params, self.env)
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=False)
        mock_lv_utils.lv_remove.assert_called_once_with("disk_vm1", "launch")

        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.side_effect = self._only_root_exists
        ss.unset_states(self.run_params, self.env)
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=False)
        mock_lv_utils.lv_remove.assert_not_called()

        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.return_value = False
        mock_lv_utils.lv_check.side_effect = None
        ss.unset_states(self.run_params, self.env)
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks[:1])
        self.mock_vms["vm1"].destroy.assert_not_called()
        mock_lv_utils.lv_remove.assert_not_called()

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_unset_off_qcow2(self, mock_process):
        self._set_off_qcow2_params()
        self.run_params["unset_state_vm1"] = "launch"
        self.run_params["unset_type_vm1"] = "off"
        self.run_params["unset_mode_vm1"] = "fi"
        self._create_mock_vms()

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_switch = True
        mock_process.system_output.return_value = b"5         launch         0 B 2021-01-18 21:24:22   00:00:44.478"
        ss.unset_states(self.run_params, self.env)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=False)
        mock_process.system.assert_called_once_with("qemu-img snapshot -d launch /images/vm1/image.qcow2")

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_switch = True
        mock_process.system_output.return_value = b"NOT HERE"
        ss.unset_states(self.run_params, self.env)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=False)
        mock_process.lv_remove.assert_not_called()

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_switch = False
        ss.unset_states(self.run_params, self.env)
        self.mock_vms["vm1"].destroy.assert_not_called()
        mock_process.system.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_unset_off_ra(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["unset_state_vm1"] = "launch"
        self.run_params["unset_type_vm1"] = "off"
        self.run_params["unset_mode_vm1"] = "ra"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestSkipError):
            ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_unset_off_fi(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["unset_state_vm1"] = "launch"
        self.run_params["unset_type_vm1"] = "off"
        self.run_params["unset_mode_vm1"] = "fi"
        self.run_params["lv_pointer_name"] = "current_state"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_called_once_with("disk_vm1", "launch")

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_unset_off_xx(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["unset_state_vm1"] = "launch"
        self.run_params["unset_type_vm1"] = "off"
        self.run_params["unset_mode_vm1"] = "xx"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        with self.assertRaises(exceptions.TestError):
            ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestError):
            ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_unset_on_qcow2vt(self, mock_process):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["unset_state_vm1"] = "launch"
        self.run_params["unset_type_vm1"] = "on"
        self.run_params["unset_mode_vm1"] = "fi"
        self._create_mock_vms()

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        self.mock_vms["vm1"].is_alive.return_value = True
        ss.unset_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        # called only if not alive
        self.mock_vms["vm1"].create.assert_not_called()
        self.mock_vms["vm1"].monitor.send_args_cmd.assert_called_once_with('delvm id=launch')

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        self.mock_vms["vm1"].is_alive.return_value = True
        ss.unset_states(self.run_params, self.env)
        # called 2 times - one to check for the boot and one to set the boot
        self.mock_vms["vm1"].is_alive.assert_called()
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        # called only if not alive
        self.mock_vms["vm1"].create.assert_not_called()
        self.mock_vms["vm1"].monitor.send_args_cmd.assert_not_called()

        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        ss.unset_states(self.run_params, self.env)
        # called 2 times - one to check for the boot and one to set the boot
        self.mock_vms["vm1"].is_alive.assert_called()
        self.mock_vms["vm1"].create.assert_called_once()
        self.mock_vms["vm1"].monitor.send_args_cmd.assert_not_called()

    @mock.patch('avocado_i2n.states.ramfile.os')
    def test_unset_on_ramfile(self, mock_os):
        self._set_off_qcow2_params()
        self._set_on_ramfile_params()
        self.run_params["unset_state_vm1"] = "launch"
        self.run_params["unset_type_vm1"] = "on"
        self.run_params["unset_mode_vm1"] = "fi"
        self._create_mock_vms()

        # restore some unmocked parts of the os module
        mock_os.path.dirname = os.path.dirname
        mock_os.path.join = os.path.join
        mock_os.path.isabs.return_value = False
        # we cannot use the exist switch because we also want to assert calls
        # mock_os.path.exists = self._file_exists

        mock_os.reset_mock()
        mock_os.path.exists.return_value = True
        ss.unset_states(self.run_params, self.env)
        mock_os.unlink.assert_called_once_with("/images/vm1/launch.state")

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_unset_on_fi(self, mock_process):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["unset_state_vm1"] = "launch"
        self.run_params["unset_type_vm1"] = "on"
        self.run_params["unset_mode_vm1"] = "fi"
        self._create_mock_vms()

        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        self.mock_vms["vm1"].monitor.send_args_cmd.return_value = ""
        ss.unset_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.mock_vms["vm1"].monitor.send_args_cmd.assert_called_once_with("delvm id=launch")

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_unset_any_all_fi(self, _mock_lv_utils, mock_process):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["unset_state_vm1"] = "launch"
        self.run_params["unset_mode_vm1"] = "fi"
        self.run_params["off_states_vm1"] = "qcow2"
        self._create_mock_vms()

        # if >= 1 states prefer on
        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        self.mock_vms["vm1"].monitor.send_args_cmd.return_value = ""
        ss.unset_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.mock_vms["vm1"].monitor.send_args_cmd.assert_called_once_with("delvm id=launch")

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_unset_any_fallback_fi(self, mock_lv_utils, mock_process):
        self._set_off_lvm_params()
        self._set_on_qcow2_params()
        self.run_params["unset_state_vm1"] = "launch"
        self.run_params["unset_mode_vm1"] = "fi"
        self.run_params["lv_pointer_name"] = "current_state"
        self._create_mock_vms()

        # if only off state choose it
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm1"].is_alive.return_value = True
        ss.unset_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called()
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        expected_checks = [mock.call("disk_vm1", "LogVol"),
                           mock.call("disk_vm1", "launch")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        mock_lv_utils.lv_remove.assert_called_once_with("disk_vm1", "launch")

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_unset_keep_pointer(self, mock_lv_utils):
        self._set_off_lvm_params()
        self._set_on_qcow2_params()
        self.run_params["unset_state_vm1"] = "current_state"
        self.run_params["unset_type_vm1"] = "off"
        self.run_params["unset_mode_vm1"] = "fi"
        self.run_params["lv_pointer_name"] = "current_state"
        self._create_mock_vms()

        # if only off state choose it
        mock_lv_utils.lv_check.return_value = True
        with self.assertRaises(ValueError):
            ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_unset_any_none_fi(self, mock_lv_utils, mock_process):
        self._set_off_lvm_params()
        self._set_on_qcow2_params()
        self.run_params["unset_state_vm1"] = "launch"
        self.run_params["unset_mode_vm1"] = "fi"
        self._create_mock_vms()

        # if no states cannot do anything
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.side_effect = self._only_root_exists
        self.mock_vms["vm1"].is_alive.return_value = True
        ss.unset_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called()
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        expected_checks = [mock.call("disk_vm1", "LogVol"),
                           mock.call("disk_vm1", "launch")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        mock_lv_utils.lv_remove.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_check_root_off_lvm(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["check_state_vm1"] = "root"
        self.run_params["check_type_vm1"] = "off"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        exists = ss.check_states(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("disk_vm1", "LogVol")
        self.assertTrue(exists)

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        exists = ss.check_states(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("disk_vm1", "LogVol")
        self.assertFalse(exists)

    def test_check_root_off_qcow2(self):
        self._set_off_qcow2_params()
        self.run_params["check_state_vm1"] = "root"
        self.run_params["check_type_vm1"] = "off"
        self.run_params["images_vm1"] = "image1 image2"
        self.run_params["image_name_image1_vm1"] = "vm1/image1"
        self.run_params["image_name_image2_vm1"] = "vm1/image2"
        self._create_mock_vms()

        self.exist_switch = True
        exists = ss.check_states(self.run_params, self.env)
        self.assertTrue(exists)

        self.exist_switch = False
        exists = ss.check_states(self.run_params, self.env)
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.pool.shutil')
    def test_check_root_off_pool(self, mock_shutil):
        self._set_off_pool_params()
        self.run_params["check_state_vm1"] = "root"
        self.run_params["check_type_vm1"] = "off"
        self.run_params["images_vm1"] = "image1 image2"
        self.run_params["image_name_image1_vm1"] = "vm1/image1"
        self.run_params["image_name_image2_vm1"] = "vm1/image2"
        self._create_mock_vms()

        # consider local root with priority
        mock_shutil.reset_mock()
        self.exist_switch = True
        exists = ss.check_states(self.run_params, self.env)
        mock_shutil.copy.assert_not_called()
        self.assertTrue(exists)

        # consider pool root as well
        mock_shutil.reset_mock()
        self.exist_switch = False
        exists = ss.check_states(self.run_params, self.env)
        mock_shutil.copy.assert_not_called()
        self.assertFalse(exists)

        # the root state exists (and is downloaded) if its pool counterpart exists
        mock_shutil.reset_mock()
        self.exist_lambda = lambda filename: filename.startswith("/data/pool")
        exists = ss.check_states(self.run_params, self.env)
        expected_checks = [mock.call("/data/pool/vm1/image1.qcow2", "/images/vm1/image1.qcow2"),
                           mock.call("/data/pool/vm1/image2.qcow2", "/images/vm1/image2.qcow2")]
        self.assertListEqual(mock_shutil.copy.call_args_list, expected_checks)
        self.assertTrue(exists)

    def test_check_root_on_qcow2vt(self):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["check_state_vm1"] = "root"
        self.run_params["check_type_vm1"] = "on"
        self._create_mock_vms()

        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = True
        exists = ss.check_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        self.assertTrue(exists)

        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        exists = ss.check_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_check_root_on_ramfile(self, mock_lv_utils):
        self._set_off_lvm_params()
        self._set_on_ramfile_params()
        self.run_params["check_state_vm1"] = "root"
        self.run_params["check_type_vm1"] = "on"
        self.run_params["images_vm1"] = "image1 image2"
        self.run_params["image_name_image1_vm1"] = "vm1/image1"
        self.run_params["image_name_image2_vm1"] = "vm1/image2"
        self._create_mock_vms()

        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.return_value = True

        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = True
        # using LVM makes the image format free to choose
        for image_format in ["qcow2", "raw", "something-else"]:
            self.run_params["image_format"] = image_format
            exists = ss.check_states(self.run_params, self.env)
            self.assertTrue(exists)

        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        self.run_params["image_format"] = "img"
        exists = ss.check_states(self.run_params, self.env)
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_root_off(self, mock_lv_utils):
        # only test with most default backends
        self._set_off_qcow2_params()
        self.run_params["get_state_vm1"] = "root"
        self.run_params["get_type_vm1"] = "off"
        self._create_mock_vms()

        # cannot verify that the operation is NOOP so simply run it for coverage
        ss.get_states(self.run_params, self.env)

    @mock.patch('avocado_i2n.states.pool.shutil')
    def test_get_root_off_pool(self, mock_shutil):
        self._set_off_pool_params()
        self.run_params["get_state_vm1"] = "root"
        self.run_params["get_type_vm1"] = "off"
        self._create_mock_vms()

        # consider local root with priority
        self.run_params["use_pool"] = "yes"
        mock_shutil.reset_mock()
        self.exist_switch = True
        ss.get_states(self.run_params, self.env)
        mock_shutil.copy.assert_not_called()

        self.exist_lambda = lambda filename: filename.startswith("/data/pool")

        # use pool root if enabled and no local root
        self.run_params["use_pool"] = "yes"
        mock_shutil.reset_mock()
        ss.get_states(self.run_params, self.env)
        mock_shutil.copy.assert_called_with("/data/pool/vm1/image.qcow2",
                                            "/images/vm1/image.qcow2")

        # do not use pool root if disabled and no local root
        self.run_params["use_pool"] = "no"
        mock_shutil.reset_mock()
        with self.assertRaises(exceptions.TestSkipError):
            ss.get_states(self.run_params, self.env)
        mock_shutil.copy.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_root_on(self, mock_lv_utils):
        # only test with most default backends
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["get_state_vm1"] = "root"
        self.run_params["get_type_vm1"] = "on"
        self._create_mock_vms()

        # cannot verify that the operation is NOOP so simply run it for coverage
        ss.get_states(self.run_params, self.env)

    # TODO: LVM is not supposed to reach to QCOW2 but we have in-code TODO about it
    @mock.patch('avocado_i2n.states.setup.env_process', mock.Mock(return_value=0))
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    @mock.patch('avocado_i2n.states.lvm.process')
    def test_set_root_off_lvm(self, mock_process, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["set_state_vm1"] = "root"
        self.run_params["set_type_vm1"] = "off"
        self.run_params["set_mode_vm1"] = "af"
        self.run_params["set_size_vm1"] = "30G"
        self.run_params["lv_pool_name"] = "thin_pool"
        self.run_params["lv_pool_size"] = "30G"
        self.run_params["lv_size"] = "30G"
        self.run_params["image_name_vm1"] = "vm1/image"
        self.run_params["disk_sparse_filename_vm1"] = "virtual_hdd_vm1"
        self.run_params["use_tmpfs"] = "yes"
        self.run_params["disk_basedir_vm1"] = "/tmp"
        self.run_params["disk_vg_size_vm1"] = "40000"
        self.run_params["image_raw_device_vm1"] = "no"
        self._create_mock_vms()

        def process_run_side_effect(cmd, **kwargs):
            if cmd == "pvs":
                stdout = b"/dev/loop0 disk_vm1   lvm2"
            elif cmd == "losetup --find":
                stdout = b"/dev/loop0"
            elif cmd == "losetup --all":
                stdout = b"/dev/loop0: [0050]:2033 (/tmp/vm1_image1/virtual_hdd)"
            else:
                stdout = b""
            result = process.CmdResult(cmd, stdout=stdout, exit_status=0)
            return result
        mock_process.run.side_effect = process_run_side_effect
        mock_process.system.return_value = 0
        self.exist_switch = True

        mock_process.reset_mock()
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_with('disk_vm1', 'LogVol')
        mock_process.run.assert_called_with('vgcreate disk_vm1 /dev/loop0', sudo=True)
        mock_lv_utils.lv_create.assert_called_once_with('disk_vm1', 'LogVol', '30G', pool_name='thin_pool', pool_size='30G')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'LogVol', 'current_state')

        mock_process.reset_mock()
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        with self.assertRaises(exceptions.TestSkipError):
            ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_with('disk_vm1', 'LogVol')

        # force create case
        self.run_params["set_mode_vm1"] = "ff"
        mock_process.reset_mock()
        mock_lv_utils.reset_mock()
        ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_with('disk_vm1', 'LogVol')
        mock_process.run.assert_called_with('vgcreate disk_vm1 /dev/loop0', sudo=True)
        mock_lv_utils.lv_create.assert_called_once_with('disk_vm1', 'LogVol', '30G', pool_name='thin_pool', pool_size='30G')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'LogVol', 'current_state')

    @mock.patch('avocado_i2n.states.setup.env_process')
    def test_set_root_off_qcow2(self, mock_env_process):
        self._set_off_qcow2_params()
        self.run_params["set_state_vm1"] = "root"
        self.run_params["set_type_vm1"] = "off"
        self._create_mock_vms()

        ss.set_states(self.run_params, self.env)
        mock_env_process.preprocess_image.assert_called_once()

    @mock.patch('avocado_i2n.states.pool.shutil')
    @mock.patch('avocado_i2n.states.setup.env_process')
    def test_set_root_off_pool(self, mock_env_process, mock_shutil):
        self._set_off_pool_params()
        self.run_params["set_state_vm1"] = "root"
        self.run_params["set_type_vm1"] = "off"
        self._create_mock_vms()

        # not updating the state pool means setting the local root
        self.run_params["update_pool"] = "no"
        mock_env_process.reset_mock()
        mock_shutil.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        ss.set_states(self.run_params, self.env)
        mock_env_process.preprocess_image.assert_called_once()
        mock_shutil.copy.assert_not_called()
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=True)

        # updating the state pool means not setting the local root
        self.run_params["update_pool"] = "yes"
        mock_env_process.reset_mock()
        mock_shutil.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        ss.set_states(self.run_params, self.env)
        mock_env_process.preprocess_image.assert_not_called()
        mock_shutil.copy.assert_called_with("/images/vm1/image.qcow2",
                                            "/data/pool/vm1/image.qcow2")
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=True)

        # does the set update with/without local root (fail) keep remote root?
        self.run_params["update_pool"] = "yes"
        mock_env_process.reset_mock()
        mock_shutil.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_lambda = lambda filename: filename.startswith("/data/pool")
        with self.assertRaises(RuntimeError):
            ss.set_states(self.run_params, self.env)
        mock_env_process.preprocess_image.assert_not_called()
        mock_shutil.copy.assert_not_called()
        self.mock_vms["vm1"].destroy.assert_not_called()

    def test_set_root_on_qcow2vt(self):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["set_state_vm1"] = "root"
        self.run_params["set_type_vm1"] = "on"
        self._create_mock_vms()

        self.mock_vms["vm1"].is_alive.return_value = False
        ss.set_states(self.run_params, self.env)
        self.mock_vms["vm1"].create.assert_called_once_with()

    def test_set_root_on_ramfile(self):
        self._set_off_qcow2_params()
        self._set_on_ramfile_params()
        self.run_params["set_state_vm1"] = "root"
        self.run_params["set_type_vm1"] = "on"
        self._create_mock_vms()

        self.mock_vms["vm1"].is_alive.return_value = False
        ss.set_states(self.run_params, self.env)
        self.mock_vms["vm1"].create.assert_called_once_with()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    @mock.patch('avocado_i2n.states.lvm.vg_cleanup')
    def test_unset_root_off_lvm(self, mock_vg_cleanup, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["unset_state_vm1"] = "root"
        self.run_params["unset_type_vm1"] = "off"
        self.run_params["image_name_vm1"] = "vm1/image"
        self.run_params["disk_sparse_filename_vm1"] = "virtual_hdd_vm1"
        self.run_params["use_tmpfs"] = "yes"
        self.run_params["disk_basedir_vm1"] = "/tmp"
        self.run_params["image_raw_device_vm1"] = "no"
        self._create_mock_vms()

        mock_vg_cleanup.reset_mock()
        mock_lv_utils.reset_mock()
        mock_lv_utils.vg_check.return_value = True
        ss.unset_states(self.run_params, self.env)
        mock_lv_utils.vg_check.assert_called_once_with('disk_vm1')
        mock_vg_cleanup.assert_called_once_with('virtual_hdd_vm1', '/tmp/disk_vm1', 'disk_vm1', None, True)

        # test tolerance to cleanup errors
        mock_vg_cleanup.reset_mock()
        mock_lv_utils.reset_mock()
        mock_lv_utils.vg_check.return_value = True
        mock_vg_cleanup.side_effect = exceptions.TestError("cleanup failed")
        ss.unset_states(self.run_params, self.env)
        mock_lv_utils.vg_check.assert_called_once_with('disk_vm1')
        mock_vg_cleanup.assert_called_once_with('virtual_hdd_vm1', '/tmp/disk_vm1', 'disk_vm1', None, True)

    @mock.patch('avocado_i2n.states.setup.os')
    @mock.patch('avocado_i2n.states.setup.env_process')
    def test_unset_root_off_qcow2(self, mock_env_process, mock_os):
        self._set_off_qcow2_params()
        self.run_params["unset_state_vm1"] = "root"
        self.run_params["unset_type_vm1"] = "off"
        self._create_mock_vms()

        ss.unset_states(self.run_params, self.env)
        mock_env_process.postprocess_image.assert_called_once()
        mock_os.rmdir.assert_called_once()

    @mock.patch('avocado_i2n.states.pool.os')
    @mock.patch('avocado_i2n.states.setup.env_process')
    def test_unset_root_off_pool(self, mock_env_process, mock_os):
        self._set_off_pool_params()
        self.run_params["unset_state_vm1"] = "root"
        self.run_params["unset_type_vm1"] = "off"
        self._create_mock_vms()

        # retore some path capabilities in our mock module
        mock_os.path.join = os.path.join
        mock_os.path.basename = os.path.basename

        # not updating the state pool means unsetting the local root
        self.run_params["update_pool"] = "no"
        mock_env_process.reset_mock()
        mock_os.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        ss.unset_states(self.run_params, self.env)
        mock_env_process.postprocess_image.assert_called_once()
        mock_os.unlink.assert_not_called()
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=False)

        # updating the state pool means not unsetting the local root
        self.run_params["update_pool"] = "yes"
        mock_env_process.reset_mock()
        mock_os.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        ss.unset_states(self.run_params, self.env)
        mock_env_process.postprocess_image.assert_not_called()
        mock_os.unlink.assert_called_with("/data/pool/vm1/image.qcow2")
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=False)

    def test_unset_root_on_qcow2vt(self):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["unset_state_vm1"] = "root"
        self.run_params["unset_type_vm1"] = "on"
        self._create_mock_vms()

        ss.unset_states(self.run_params, self.env)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=False)

    def test_unset_root_on_ramfile(self):
        self._set_off_qcow2_params()
        self._set_on_ramfile_params()
        self.run_params["unset_state_vm1"] = "root"
        self.run_params["unset_type_vm1"] = "on"
        self._create_mock_vms()

        ss.unset_states(self.run_params, self.env)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=False)

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_push(self, mock_lv_utils, _mock_process):
        self._set_off_lvm_params()
        self.run_params["push_state_vm1"] = "launch"
        self.run_params["push_type_vm1"] = "off"
        self.run_params["push_mode_vm1"] = "ff"
        self.run_params["skip_types"] = "on"
        self.run_params["lv_pointer_name"] = "current_state"
        self._create_mock_vms()

        mock_lv_utils.lv_check.side_effect = self._only_root_exists

        ss.push_states(self.run_params, self.env)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=True)
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'current_state', 'launch')

        # test push disabled for root/boot states
        self.run_params["push_state_vm1"] = "root"
        ss.push_states(self.run_params, self.env)
        mock_lv_utils.assert_not_called()
        self.run_params["push_state_vm1"] = "boot"
        ss.push_states(self.run_params, self.env)
        mock_lv_utils.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_pop_off(self, mock_lv_utils):
        self._set_off_lvm_params()
        self.run_params["pop_state_vm1"] = "launch"
        self.run_params["pop_type_vm1"] = "off"
        self.run_params["image_name_vm1"] = "vm1/image"
        self.run_params["image_raw_device_vm1"] = "no"
        self._create_mock_vms()

        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm1"].is_alive.return_value = False

        ss.pop_states(self.run_params, self.env)

        mock_lv_utils.lv_check.assert_called_with("disk_vm1", "launch")
        self.mock_vms["vm1"].is_alive.assert_called_with()
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'launch', 'current_state')
        expected = [mock.call('disk_vm1', 'current_state'), mock.call('disk_vm1', 'launch')]
        self.assertListEqual(mock_lv_utils.lv_remove.call_args_list, expected)

        # test pop disabled for root/boot states
        self.run_params["pop_state_vm1"] = "root"
        ss.pop_states(self.run_params, self.env)
        mock_lv_utils.assert_not_called()
        self.run_params["pop_state_vm1"] = "boot"
        ss.pop_states(self.run_params, self.env)
        mock_lv_utils.assert_not_called()

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_pop_on(self, mock_process):
        self._set_off_qcow2_params()
        self._set_on_qcow2_params()
        self.run_params["pop_state_vm1"] = "launch"
        self.run_params["pop_type_vm1"] = "on"
        self._create_mock_vms()

        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        self.mock_vms["vm1"].is_alive.return_value = True
        self.mock_vms["vm1"].monitor.send_args_cmd.return_value = ""

        ss.pop_states(self.run_params, self.env)

        mock_process.system_output.assert_called_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.mock_vms["vm1"].is_alive.assert_called_with()
        self.mock_vms["vm1"].loadvm.assert_called_once_with('launch')
        self.mock_vms["vm1"].monitor.send_args_cmd.assert_called_once_with("delvm id=launch")

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_check_multivm(self, mock_lv_utils, _mock_process):
        self._set_off_lvm_params()
        self._set_on_qcow2_params()
        self.run_params["vms"] = "vm1 vm2"
        self.run_params["check_state"] = "launch"
        self.run_params["check_state_vm2"] = "launcher"
        self.run_params["check_type"] = "off"
        self.run_params["vg_name_vm1"] = "disk_vm1"
        self.run_params["vg_name_vm2"] = "disk_vm2"
        self.run_params["image_name_vm1"] = "vm1/image"
        self.run_params["image_name_vm2"] = "vm2/image"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        exists = ss.check_states(self.run_params, self.env)
        expected = [mock.call("disk_vm1", "LogVol"),
                    mock.call("disk_vm1", "launch"),
                    mock.call("disk_vm2", "LogVol"),
                    mock.call("disk_vm2", "launcher")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected)
        self.assertTrue(exists)

        # break on first false state check
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        exists = ss.check_states(self.run_params, self.env)
        expected = [mock.call("disk_vm1", "LogVol")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected)
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_multivm(self, mock_lv_utils, mock_process):
        self._set_off_lvm_params()
        self._set_on_qcow2_params()
        self.run_params["vms"] = "vm1 vm2 vm3"
        self.run_params["get_state"] = "launch2"
        self.run_params["get_state_vm1"] = "launch1"
        # TODO: restore allowing digits in the state name once the upstream Qemu
        # handles the bug reported at https://bugs.launchpad.net/qemu/+bug/1859989
        #self.run_params["get_state_vm3"] = "launch3"
        self.run_params["get_state_vm3"] = "launchX"
        self.run_params["get_type"] = "off"
        self.run_params["get_type_vm3"] = "on"
        self.run_params["get_mode_vm1"] = "rx"
        self.run_params["get_mode_vm2"] = "ii"
        self.run_params["get_mode_vm3"] = "aa"
        self.run_params["vg_name_vm1"] = "disk_vm1"
        self.run_params["vg_name_vm2"] = "disk_vm2"
        self.run_params["vg_name_vm3"] = "disk_vm3"
        self.run_params["image_name_vm1"] = "vm1/image"
        self.run_params["image_name_vm2"] = "vm2/image"
        self.run_params["image_name_vm3"] = "vm3/image"
        self.run_params["image_raw_device"] = "no"
        self._create_mock_vms()

        # test on/off switch as well
        def lv_check_side_effect(_vgname, lvname):
            return True if lvname in ["LogVol", "launch1"] else False if lvname == "launch2" else False
        mock_lv_utils.lv_check.side_effect = lv_check_side_effect
        mock_process.system_output.return_value = b"5         launchX         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        self.mock_vms["vm1"].is_alive.return_value = False
        self.mock_vms["vm3"].is_alive.return_value = True

        with self.assertRaises(exceptions.TestSkipError):
            ss.get_states(self.run_params, self.env)

        expected = [mock.call("disk_vm1", "LogVol"),
                    mock.call("disk_vm1", "launch1"),
                    mock.call("disk_vm2", "LogVol"),
                    mock.call("disk_vm2", "launch2"),
                    mock.call("disk_vm3", "LogVol")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm3/image.qcow2 -U")
        # switch check if vm has to be booted
        self.mock_vms["vm3"].is_alive.assert_called_once_with()

    # TODO: LVM is not supposed to reach to QCOW2 but we have in-code TODO about it
    @mock.patch('avocado_i2n.states.setup.env_process', mock.Mock(return_value=0))
    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    @mock.patch('avocado_i2n.states.lvm.process')
    def test_set_multivm(self, mock_process, mock_lv_utils, _mock_qcow2_process):
        self._set_off_lvm_params()
        self.run_params["vms"] = "vm2 vm3 vm4"
        self.run_params["set_state"] = "launch2"
        self.run_params["set_state_vm2"] = "launch2"
        self.run_params["set_state_vm3"] = "root"
        self.run_params["set_state_vm4"] = "launch4"
        self.run_params["set_type"] = "off"
        self.run_params["set_mode_vm2"] = "rx"
        self.run_params["set_mode_vm3"] = "ff"
        self.run_params["set_mode_vm4"] = "aa"
        self.run_params["lv_size"] = "30G"
        self.run_params["lv_pool_name"] = "thin_pool"
        self.run_params["lv_pool_size"] = "30G"
        self.run_params["vg_name_vm2"] = "disk_vm2"
        self.run_params["vg_name_vm3"] = "disk_vm3"
        self.run_params["vg_name_vm4"] = "disk_vm4"
        self.run_params["image_name_vm2"] = "vm2/image"
        self.run_params["image_name_vm3"] = "vm3/image"
        self.run_params["image_name_vm4"] = "vm4/image"
        self.run_params["image_raw_device"] = "no"
        self.run_params["disk_sparse_filename_vm3"] = "virtual_hdd_vm3"
        self.run_params["use_tmpfs"] = "yes"
        self.run_params["disk_basedir"] = "/tmp"
        self.run_params["disk_vg_size"] = "40000"
        self.run_params["skip_types"] = "on"
        self._create_mock_vms()
        self.exist_switch = False

        def lv_check_side_effect(_vgname, lvname):
            return True if lvname in ["LogVol", "launch2"] else False if lvname == "launch4" else False
        mock_lv_utils.lv_check.side_effect = lv_check_side_effect
        mock_lv_utils.vg_check.return_value = False
        mock_process.run.return_value = process.CmdResult("dummy-command")

        with self.assertRaises(exceptions.TestSkipError):
            ss.set_states(self.run_params, self.env)

        expected = [mock.call("disk_vm2", "LogVol"),
                    mock.call("disk_vm2", "launch2"),
                    mock.call("disk_vm3", "LogVol"),
                    mock.call("disk_vm4", "LogVol"),
                    mock.call("disk_vm4", "launch4")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected)
        self.mock_vms["vm2"].destroy.assert_called_once_with(gracefully=True)
        self.mock_vms["vm3"].destroy.assert_called_once_with(gracefully=True)
        self.mock_vms["vm4"].destroy.assert_called_once_with(gracefully=True)
        mock_process.run.assert_called_with('vgcreate disk_vm3 ', sudo=True)
        mock_lv_utils.lv_create.assert_called_once_with('disk_vm3', 'LogVol', '30G', pool_name='thin_pool', pool_size='30G')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm3', 'LogVol', 'current_state')

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_unset_multivm(self, mock_lv_utils, _mock_process):
        self.run_params["vms"] = "vm1 vm4"
        self.run_params["unset_state_vm1"] = "root"
        self.run_params["unset_state_vm4"] = "launch4"
        self.run_params["unset_type"] = "off"
        self.run_params["unset_mode_vm1"] = "ra"
        self.run_params["unset_mode_vm4"] = "fi"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["vg_name_vm1"] = "disk_vm1"
        self.run_params["vg_name_vm4"] = "disk_vm4"
        self.run_params["image_name_vm1"] = "vm1/image"
        self.run_params["image_name_vm4"] = "vm4/image"
        self.run_params["image_raw_device"] = "no"
        self._create_mock_vms()
        self.exist_switch = False

        mock_lv_utils.lv_check.side_effect = self._only_root_exists

        ss.unset_states(self.run_params, self.env)

        expected = [mock.call("disk_vm1", "LogVol"),
                    mock.call("disk_vm4", "LogVol"),
                    mock.call("disk_vm4", "launch4")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected)

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_qcow2_format(self, mock_process):
        self._set_off_qcow2_params()
        self.run_params["skip_types"] = "on"
        self._create_mock_vms()

        for do in ["check", "get", "set", "unset"]:
            self.run_params[f"{do}_state"] = "launch"
            self.run_params[f"{do}_type"] = "off"

            for image_format in ["incompatible", "missing"]:
                self.run_params["image_format"] = image_format
                if image_format == "missing":
                    del self.run_params["image_format"]

                mock_process.reset_mock()
                mock_process.system_output.return_value = b"NOT HERE"
                # check root format blockage
                with self.assertRaises(ValueError):
                    ss.__dict__[f"{do}_states"](self.run_params, self.env)
                # check internal format blockage
                self.run_params["image_name"] = "vm1/image"
                with self.assertRaises(ValueError):
                    ss.OFF_BACKENDS["qcow2"]().__getattribute__(do)(self.run_params, self.env)
                    ss.ON_BACKENDS["qcow2vt"]().__getattribute__(do)(self.run_params, self.env)
                mock_process.run.assert_not_called()
                self.mock_vms["vm1"].assert_not_called()

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.qcow2.os.path.isfile')
    def test_qcow2_convert(self, mock_isfile, mock_process):
        self._set_off_qcow2_params()
        self.run_params["raw_image"] = "ext_image"
        # set a generic one not restricted to vm1
        self.run_params["image_name"] = "vm1/image"
        self._create_mock_vms()

        mock_process.reset_mock()
        mock_isfile.return_value = True
        mock_process.run.return_value = process.CmdResult("dummy-command")
        qcow2.convert_image(self.run_params)
        mock_process.run.assert_called_with('qemu-img convert -c -p -O qcow2 "./ext_image" "/images/vm1/image.qcow2"',
                                            timeout=12000)

        mock_process.reset_mock()
        mock_isfile.return_value = False
        with self.assertRaises(FileNotFoundError):
            qcow2.convert_image(self.run_params)
        mock_process.run.assert_not_called()

        mock_process.reset_mock()
        mock_isfile.return_value = True
        mock_process.CmdError = process.CmdError
        result = process.CmdResult("qemu-img convert", stderr=b'..."write" lock...', exit_status=0)
        mock_process.run.side_effect = process.CmdError(result=result)
        with self.assertRaises(process.CmdError):
            qcow2.convert_image(self.run_params)
        # no convert command was executed
        mock_process.run.assert_called_once_with('qemu-img check /images/vm1/image.qcow2')

    @mock.patch('avocado_i2n.states.pool.SKIP_LOCKS', False)
    @mock.patch('avocado_i2n.states.pool.fcntl')
    def test_pool_locks(self, mock_fcntl):
        self._set_off_pool_params()
        self._create_mock_vms()

        image_locked = False
        with pool.image_lock("./image.qcow2", timeout=1) as lock:
            mock_fcntl.lockf.assert_called_once()
            image_locked = True
            mock_fcntl.reset_mock()

            # TODO: from a different process if we decide to from unit tests to
            # functional tests that add more elaborate setup like this
            #with pool.image_lock("./image.qcow2", timeout=1) as lock:
            #    mock_fcntl.lockf.assert_called_once()
            #    mock_fcntl.reset_mock()
            #mock_fcntl.lockf.assert_called_once()
            #mock_fcntl.reset_mock()

        self.assertTrue(image_locked)
        mock_fcntl.lockf.assert_called_once()


if __name__ == '__main__':
    unittest.main()
