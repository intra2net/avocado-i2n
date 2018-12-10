#!/usr/bin/env python

import unittest
import unittest.mock as mock
import os

from avocado.core import exceptions
from avocado.utils import process
from avocado.utils import lv_utils
from virttest import utils_params

from . import state_setup


@mock.patch('os.mkdir', mock.Mock(return_value=0))
@mock.patch('os.rmdir', mock.Mock(return_value=0))
@mock.patch('os.unlink', mock.Mock(return_value=0))
class StateSetupTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.run_str = ""

    def setUp(self):
        self.run_params = utils_params.Params()

        self.env = mock.MagicMock(name='env')
        self.env.get_vm = mock.MagicMock(side_effect=self._get_mock_vm)

        exists_patch = mock.patch('state_setup.os.path.exists', mock.MagicMock(side_effect=self._file_exists))
        exists_patch.start()
        self.addCleanup(exists_patch.stop)

        self.mock_vms = {}

        self.exist_switch = True

    def _get_mock_vm(self, vm_name):
        return self.mock_vms[vm_name]

    def _create_mock_vms(self):
        for vm_name in self.run_params.objects("vms"):
            self.mock_vms[vm_name] = mock.MagicMock(name=vm_name)
            self.mock_vms[vm_name].name = vm_name
            self.mock_vms[vm_name].params = self.run_params.object_params(vm_name)

    def _file_exists(self, filepath):
        # ignore ramdisk states which are too prone to errors
        if filepath.endswith(".state"):
            return False
        else:
            return self.exist_switch

    @mock.patch('state_setup.lv_utils')
    def test_show_states_offline(self, mock_lv_utils):
        self.run_params["vms"] = "vm1"
        self.run_params["check_type_vm1"] = "offline"
        self.run_params["vg_name_vm1"] = "ramdisk_vm1"
        self._create_mock_vms()

        mock_lv_utils.lv_list.return_value = ["launch1", "launch2"]
        states = state_setup.show_states(self.run_params, self.env)
        mock_lv_utils.lv_list.assert_called_once_with("ramdisk_vm1")

        self.assertIn("launch1", states)
        self.assertIn("launch2", states)
        self.assertNotIn("launch3", states)
        self.assertNotIn("root", states)

    @mock.patch('state_setup.process')
    def test_show_states_online(self, mock_process):
        self.run_params["vms"] = "vm1"
        self.run_params["check_type_vm1"] = "online"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm1"] = "/vm1/image"
        self._create_mock_vms()

        mock_process.reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        states = state_setup.show_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm1/image.qcow2 -U")

        self.assertEquals(len(states), 0)

        mock_process.reset_mock()
        mock_process.system_output.return_value = (b"1         launch   338M 2014-05-16 12:13:45   00:00:34.079"
                                                   b"2         with.dot   33.5G 2014-05-16 12:13:45   00:00:34.079")
        states = state_setup.show_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm1/image.qcow2 -U")
 
        self.assertEquals(len(states), 2)
        self.assertIn("launch", states)
        self.assertIn("with.dot", states)
        self.assertNotIn("launch2", states)
        self.assertNotIn("boot", states)

    @mock.patch('state_setup.lv_utils')
    def test_check_offline(self, mock_lv_utils):
        self.run_params["vms"] = "vm1"
        self.run_params["check_state_vm1"] = "launch"
        self.run_params["check_type_vm1"] = "offline"
        self.run_params["vg_name_vm1"] = "ramdisk_vm1"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        exists = state_setup.check_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm1", "launch")
        self.assertTrue(exists)

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        exists = state_setup.check_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm1", "launch")
        self.assertFalse(exists)

    @mock.patch('state_setup.process')
    def test_check_online(self, mock_process):
        self.run_params["vms"] = "vm1"
        self.run_params["check_state_vm1"] = "launch"
        self.run_params["check_type_vm1"] = "online"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm1"] = "/vm1/image"
        self._create_mock_vms()

        mock_process.reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        exists = state_setup.check_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm1/image.qcow2 -U")
        self.assertFalse(exists)

        mock_process.reset_mock()
        mock_process.system_output.return_value = b"1         launch   338M 2014-05-16 12:13:45   00:00:34.079"
        exists = state_setup.check_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm1/image.qcow2 -U")
        self.assertTrue(exists)

    @mock.patch('state_setup.process')
    def test_check_online_dot(self, mock_process):
        self.run_params["vms"] = "vm1"
        self.run_params["check_state_vm1"] = "with.dot"
        self.run_params["check_type_vm1"] = "online"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm1"] = "/vm1/image"
        self._create_mock_vms()

        mock_process.system_output.return_value = b"1         with.dot   33.5G 2014-05-16 12:13:45   00:00:34.079"
        exists = state_setup.check_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm1/image.qcow2 -U")
        self.assertTrue(exists)

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_check_any_all(self, _mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm1"
        self.run_params["check_state_vm1"] = "launch"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm1"] = "/vm1/image"
        self._create_mock_vms()

        mock_process.system_output.return_value = b"1         launch   338M 2014-05-16 12:13:45   00:00:34.079"
        exists = state_setup.check_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm1/image.qcow2 -U")
        self.assertTrue(exists)

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_check_any_fallback(self, mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm1"
        self.run_params["check_state_vm1"] = "launch"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm1"] = "/vm1/image"
        self.run_params["vg_name_vm1"] = "ramdisk_vm1"
        self._create_mock_vms()

        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = True
        exists = state_setup.check_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm1/image.qcow2 -U")
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm1", "launch")
        self.assertTrue(exists)

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_check_any_none(self, mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm1"
        self.run_params["check_state_vm1"] = "launch"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm1"] = "/vm1/image"
        self.run_params["vg_name_vm1"] = "ramdisk_vm1"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_process.reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = False
        exists = state_setup.check_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm1/image.qcow2 -U")
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm1", "launch")
        self.assertFalse(exists)

    @mock.patch('state_setup.lv_utils')
    def test_get_offline_aa(self, mock_lv_utils):
        self.run_params["vms"] = "vm1"
        self.run_params["get_state_vm1"] = "launch"
        self.run_params["get_type_vm1"] = "offline"
        self.run_params["get_mode_vm1"] = "aa"
        self.run_params["vg_name_vm1"] = "ramdisk_vm1"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm1"].is_alive.return_value = False
        with self.assertRaises(exceptions.TestAbortError):
            state_setup.get_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm1", "launch")
        # test online/offline switch as well
        self.mock_vms["vm1"].is_alive.assert_called_once_with()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestAbortError):
            state_setup.get_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm1", "launch")

    @mock.patch('state_setup.lv_utils')
    def test_get_offline_rx(self, mock_lv_utils):
        self.run_params["vms"] = "vm2"
        self.run_params["get_state_vm2"] = "launch"
        self.run_params["get_type_vm2"] = "offline"
        self.run_params["get_mode_vm2"] = "rx"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["lv_pointer_name"] = "current_state"
        self.run_params["vg_name_vm2"] = "ramdisk_vm2"
        self.run_params["image_name_vm2"] = "/vm2/image"
        self.run_params["image_raw_device_vm2"] = "no"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        # test online/offline switch as well
        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm2"].is_alive.return_value = False
        state_setup.get_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm2", "launch")
        self.mock_vms["vm2"].is_alive.assert_called_once_with()
        mock_lv_utils.lv_remove.assert_called_once_with('ramdisk_vm2', 'current_state')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('ramdisk_vm2', 'launch', 'current_state')

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestError):
            state_setup.get_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm2", "launch")

    @mock.patch('state_setup.lv_utils')
    def test_get_offline_ii(self, mock_lv_utils):
        self.run_params["vms"] = "vm4"
        self.run_params["get_state_vm4"] = "launch"
        self.run_params["get_type_vm4"] = "offline"
        self.run_params["get_mode_vm4"] = "ii"
        self.run_params["vg_name_vm4"] = "ramdisk_vm4"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm4"].is_alive.return_value = False
        state_setup.get_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm4", "launch")
        self.mock_vms["vm4"].is_alive.assert_called_once_with()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        state_setup.get_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm4", "launch")

    @mock.patch('state_setup.lv_utils')
    def test_get_offline_xx(self, mock_lv_utils):
        self.run_params["vms"] = "vm3"
        self.run_params["get_state_vm3"] = "launch"
        self.run_params["get_type_vm3"] = "offline"
        self.run_params["get_mode_vm3"] = "xx"
        self.run_params["vg_name_vm3"] = "ramdisk_vm3"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm3"].is_alive.return_value = False
        with self.assertRaises(exceptions.TestError):
            state_setup.get_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm3", "launch")
        self.mock_vms["vm3"].is_alive.assert_called_once_with()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestError):
            state_setup.get_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm3", "launch")

    @mock.patch('state_setup.lv_utils')
    def test_get_type_switch(self, mock_lv_utils):
        self.run_params["vms"] = "vm4"
        self.run_params["get_state_vm4"] = "launch"
        self.run_params["get_type_vm4"] = "offline"
        self.run_params["get_mode_vm4"] = "ii"
        self.run_params["vg_name_vm4"] = "ramdisk_vm4"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        self.mock_vms["vm4"].reset_mock()
        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm4"].is_alive.return_value = True
        state_setup.get_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm4", "launch")
        self.mock_vms["vm4"].is_alive.assert_called_once_with()
        self.mock_vms["vm4"].destroy.assert_called_once_with(gracefully=False)

        mock_lv_utils.reset_mock()
        self.mock_vms["vm4"].reset_mock()
        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm4"].is_alive.return_value = False
        state_setup.get_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm4", "launch")
        self.mock_vms["vm4"].is_alive.assert_called_once_with()

    @mock.patch('state_setup.process')
    def test_get_online_rx(self, mock_process):
        self.run_params["vms"] = "vm2"
        self.run_params["get_state_vm2"] = "launch"
        self.run_params["get_type_vm2"] = "online"
        self.run_params["get_mode_vm2"] = "rx"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm2"] = "/vm2/image"
        self._create_mock_vms()

        mock_process.system_output.return_value = b"1         launch   338M 2014-05-16 12:13:45   00:00:34.079"
        self.mock_vms["vm2"].is_alive.return_value = True
        # switch check if vm has to be booted
        state_setup.get_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm2/image.qcow2 -U")
        self.mock_vms["vm2"].is_alive.assert_called_once_with()
        self.mock_vms["vm2"].loadvm.assert_called_once_with('launch')

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_get_any_all_rx(self, mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm2"
        self.run_params["get_state_vm2"] = "launch"
        self.run_params["get_mode_vm2"] = "rx"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm2"] = "/vm2/image"
        self._create_mock_vms()

        # if >= 1 states prefer online
        mock_process.system_output.return_value = b"1         launch   338M 2014-05-16 12:13:45   00:00:34.079"
        # this time the online switch asks so confirm for it as well
        self.mock_vms["vm2"].is_alive.return_value = True
        state_setup.get_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm2/image.qcow2 -U")
        self.mock_vms["vm2"].is_alive.assert_called_once_with()
        self.mock_vms["vm2"].loadvm.assert_called_once_with('launch')

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_get_any_fallback_rx(self, mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm2"
        self.run_params["get_state_vm2"] = "launch"
        self.run_params["get_mode_vm2"] = "rx"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm2"] = "/vm2/image"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["lv_pointer_name"] = "current_state"
        self.run_params["vg_name_vm2"] = "ramdisk_vm2"
        self.run_params["image_name_vm2"] = "/vm2/image"
        self.run_params["image_raw_device_vm2"] = "no"
        self._create_mock_vms()

        # if only offline state choose it
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = True
        # this time the offline switch asks so confirm for it as well
        self.mock_vms["vm2"].is_alive.return_value = False
        state_setup.get_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm2/image.qcow2 -U")
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm2", "launch")
        self.mock_vms["vm2"].is_alive.assert_called_once_with()
        mock_lv_utils.lv_remove.assert_called_once_with('ramdisk_vm2', 'current_state')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('ramdisk_vm2', 'launch', 'current_state')

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_get_any_none_xi(self, mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm2"
        self.run_params["get_state_vm2"] = "launch"
        self.run_params["get_mode_vm2"] = "xi"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["vg_name_vm2"] = "ramdisk_vm2"
        self.run_params["image_name_vm2"] = "/vm2/image"
        # self.run_params["image_raw_device_vm2"] = "no"
        self._create_mock_vms()

        # if no states prefer online
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = False
        state_setup.get_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm2/image.qcow2 -U")
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm2", "launch")

    @mock.patch('state_setup.lv_utils')
    def test_set_offline_aa(self, mock_lv_utils):
        self.run_params["vms"] = "vm2"
        self.run_params["set_state_vm2"] = "launch"
        self.run_params["set_type_vm2"] = "offline"
        self.run_params["set_mode_vm2"] = "aa"
        self.run_params["skip_types"] = "online"
        self.run_params["vg_name_vm2"] = "ramdisk_vm2"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        self.mock_vms["vm2"].reset_mock()
        mock_lv_utils.lv_check.return_value = True
        with self.assertRaises(exceptions.TestAbortError):
            state_setup.set_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm2", "launch")
        self.mock_vms["vm2"].destroy.assert_called_once_with(gracefully=True)

        mock_lv_utils.reset_mock()
        self.mock_vms["vm2"].reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestAbortError):
            state_setup.set_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm2", "launch")
        self.mock_vms["vm2"].destroy.assert_called_once_with(gracefully=True)

    @mock.patch('state_setup.lv_utils')
    def test_set_offline_rx(self, mock_lv_utils):
        self.run_params["vms"] = "vm3"
        self.run_params["set_state_vm3"] = "launch"
        self.run_params["set_type_vm3"] = "offline"
        self.run_params["set_mode_vm3"] = "rx"
        self.run_params["skip_types"] = "online"
        self.run_params["vg_name_vm3"] = "ramdisk_vm3"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        self.mock_vms["vm3"].reset_mock()
        mock_lv_utils.lv_check.return_value = True
        state_setup.set_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm3", "launch")
        self.mock_vms["vm3"].destroy.assert_called_once_with(gracefully=True)

        mock_lv_utils.reset_mock()
        self.mock_vms["vm3"].reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestError):
            state_setup.set_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm3", "launch")
        self.mock_vms["vm3"].destroy.assert_called_once_with(gracefully=True)

    @mock.patch('state_setup.lv_utils')
    def test_set_offline_ff(self, mock_lv_utils):
        self.run_params["vms"] = "vm4"
        self.run_params["set_state_vm4"] = "launch"
        self.run_params["set_type_vm4"] = "offline"
        self.run_params["set_mode_vm4"] = "ff"
        self.run_params["skip_types"] = "online"
        self.run_params["vg_name_vm4"] = "ramdisk_vm4"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["lv_pointer_name"] = "current_state"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        self.mock_vms["vm4"].reset_mock()
        mock_lv_utils.lv_check.return_value = True
        state_setup.set_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm4", "launch")
        self.mock_vms["vm4"].destroy.assert_called_once_with(gracefully=True)
        mock_lv_utils.lv_remove.assert_called_once_with("ramdisk_vm4", "launch")
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('ramdisk_vm4', 'current_state', 'launch')

        mock_lv_utils.reset_mock()
        self.mock_vms["vm4"].reset_mock()
        mock_lv_utils.lv_check.return_value = False
        state_setup.set_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm4", "launch")
        self.mock_vms["vm4"].destroy.assert_called_once_with(gracefully=True)
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('ramdisk_vm4', 'current_state', 'launch')

    @mock.patch('state_setup.lv_utils')
    def test_set_offline_xx(self, mock_lv_utils):
        self.run_params["vms"] = "vm1"
        self.run_params["set_state_vm1"] = "launch"
        self.run_params["set_type_vm1"] = "offline"
        self.run_params["set_mode_vm1"] = "xx"
        self.run_params["skip_types"] = "online"
        self.run_params["vg_name_vm1"] = "ramdisk_vm1"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.return_value = True
        with self.assertRaises(exceptions.TestError):
            state_setup.set_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm1", "launch")
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=True)

        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestError):
            state_setup.set_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm1", "launch")
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=True)

    @mock.patch('state_setup.process')
    def test_set_online_ff(self, mock_process):
        self.run_params["vms"] = "vm4"
        self.run_params["set_state_vm4"] = "launch"
        self.run_params["set_type_vm4"] = "online"
        self.run_params["set_mode_vm4"] = "ff"
        self.run_params["skip_types"] = "offline"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm4"] = "/vm4/image"
        self._create_mock_vms()

        # NOTE: setting an online state assumes that the vm is online just like
        # setting an offline state assumes that the vm already exists
        mock_process.system_output.return_value = b"1         launch   338M 2014-05-16 12:13:45   00:00:34.079"
        state_setup.set_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm4/image.qcow2 -U")
        self.mock_vms["vm4"].savevm.assert_called_once_with('launch')

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_set_any_all_ff(self, mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm4"
        self.run_params["set_state_vm4"] = "launch"
        self.run_params["set_mode_vm4"] = "ff"
        self.run_params["skip_types"] = ""
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm4"] = "/vm4/image"
        self._create_mock_vms()

        # if no skipping and too many states prefer online
        mock_process.system_output.return_value = b"1         launch   338M 2014-05-16 12:13:45   00:00:34.079"
        state_setup.set_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm4/image.qcow2 -U")
        self.mock_vms["vm4"].savevm.assert_called_once_with('launch')

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_set_any_fallback_ff(self, mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm4"
        self.run_params["set_state_vm4"] = "launch"
        self.run_params["set_mode_vm4"] = "ff"
        self.run_params["skip_types"] = ""
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm4"] = "/vm4/image"
        self.run_params["vg_name_vm4"] = "ramdisk_vm4"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["lv_pointer_name"] = "current_state"
        self._create_mock_vms()

        # if no skipping with only offline state available
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = True
        state_setup.set_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm4/image.qcow2 -U")
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm4", "launch")
        self.mock_vms["vm4"].destroy.assert_called_once_with(gracefully=True)
        mock_lv_utils.lv_remove.assert_called_once_with('ramdisk_vm4', 'launch')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('ramdisk_vm4', 'current_state', 'launch')

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_set_any_none_ff(self, mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm4"
        self.run_params["set_state_vm4"] = "launch"
        self.run_params["set_mode_vm4"] = "ff"
        self.run_params["skip_types"] = ""
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm4"] = "/vm4/image"
        self.run_params["vg_name_vm4"] = "ramdisk_vm4"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["lv_pointer_name"] = "current_state"
        self._create_mock_vms()

        # if no skipping and no states prefer online
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = False
        state_setup.set_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm4/image.qcow2 -U")
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm4", "launch")
        self.mock_vms["vm4"].savevm.assert_called_once_with('launch')

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_set_any_all_skip_online(self, mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm4"
        self.run_params["set_state_vm4"] = "launch"
        self.run_params["set_mode_vm4"] = "ff"
        self.run_params["skip_types"] = "online"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm4"] = "/vm4/image"
        self._create_mock_vms()

        # skip setting the state since online is available but we skip online by parameters
        mock_process.system_output.return_value = b"1         launch   338M 2014-05-16 12:13:45   00:00:34.079"
        state_setup.set_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm4/image.qcow2 -U")

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_set_any_fallback_skip_online(self, mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm4"
        self.run_params["set_state_vm4"] = "launch"
        self.run_params["set_mode_vm4"] = "ff"
        self.run_params["skip_types"] = "online"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm4"] = "/vm4/image"
        self.run_params["vg_name_vm4"] = "ramdisk_vm4"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["lv_pointer_name"] = "current_state"
        self._create_mock_vms()

        # set the state since only offline is available and we skip online by parameters
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = True
        state_setup.set_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm4/image.qcow2 -U")
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm4", "launch")
        self.mock_vms["vm4"].destroy.assert_called_once_with(gracefully=True)
        mock_lv_utils.lv_remove.assert_called_once_with("ramdisk_vm4", "launch")
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('ramdisk_vm4', 'current_state', 'launch')

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_set_any_fallback_skip_offline(self, mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm4"
        self.run_params["set_state_vm4"] = "launch"
        self.run_params["set_mode_vm4"] = "ff"
        self.run_params["skip_types"] = "offline"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm4"] = "/vm4/image"
        self.run_params["vg_name_vm4"] = "ramdisk_vm4"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["lv_pointer_name"] = "current_state"
        self._create_mock_vms()

        # skip setting the state since only offline is available but we skip offline by parameters
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = True
        state_setup.set_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm4/image.qcow2 -U")
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm4", "launch")

    @mock.patch('state_setup.lv_utils')
    def test_unset_offline_ra(self, mock_lv_utils):
        self.run_params["vms"] = "vm1"
        self.run_params["unset_state_vm1"] = "launch"
        self.run_params["unset_type_vm1"] = "offline"
        self.run_params["unset_mode_vm1"] = "ra"
        self.run_params["vg_name_vm1"] = "ramdisk_vm1"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        state_setup.unset_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm1", "launch")

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestAbortError):
            state_setup.unset_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm1", "launch")

    @mock.patch('state_setup.lv_utils')
    def test_unset_offline_fi(self, mock_lv_utils):
        self.run_params["vms"] = "vm4"
        self.run_params["unset_state_vm4"] = "launch"
        self.run_params["unset_type_vm4"] = "offline"
        self.run_params["unset_mode_vm4"] = "fi"
        self.run_params["vg_name_vm4"] = "ramdisk_vm4"
        self.run_params["lv_pointer_name"] = "current_state"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        state_setup.unset_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm4", "launch")
        mock_lv_utils.lv_remove.assert_called_once_with("ramdisk_vm4", "launch")

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        state_setup.unset_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm4", "launch")

    @mock.patch('state_setup.lv_utils')
    def test_unset_offline_xx(self, mock_lv_utils):
        self.run_params["vms"] = "vm3"
        self.run_params["unset_state_vm3"] = "launch"
        self.run_params["unset_type_vm3"] = "offline"
        self.run_params["unset_mode_vm3"] = "xx"
        self.run_params["vg_name_vm3"] = "ramdisk_vm3"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        with self.assertRaises(exceptions.TestError):
            state_setup.unset_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm3", "launch")

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestError):
            state_setup.unset_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm3", "launch")

    @mock.patch('state_setup.process')
    def test_unset_online_fi(self, mock_process):
        self.run_params["vms"] = "vm4"
        self.run_params["unset_state_vm4"] = "launch"
        self.run_params["unset_type_vm4"] = "online"
        self.run_params["unset_mode_vm4"] = "fi"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm4"] = "/vm4/image"
        self._create_mock_vms()

        mock_process.system_output.return_value = b"1         launch   338M 2014-05-16 12:13:45   00:00:34.079"
        self.mock_vms["vm4"].monitor.send_args_cmd.return_value = ""
        state_setup.unset_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm4/image.qcow2 -U")
        self.mock_vms["vm4"].monitor.send_args_cmd.assert_called_once_with("delvm id=launch")

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_unset_any_all_fi(self, _mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm1"
        self.run_params["unset_state_vm1"] = "launch"
        self.run_params["unset_mode_vm1"] = "fi"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm1"] = "/vm1/image"
        self._create_mock_vms()

        # if >= 1 states prefer online
        mock_process.system_output.return_value = b"1         launch   338M 2014-05-16 12:13:45   00:00:34.079"
        self.mock_vms["vm1"].monitor.send_args_cmd.return_value = ""
        state_setup.unset_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm1/image.qcow2 -U")
        self.mock_vms["vm1"].monitor.send_args_cmd.assert_called_once_with("delvm id=launch")

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_unset_any_fallback_fi(self, mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm1"
        self.run_params["unset_state_vm1"] = "launch"
        self.run_params["unset_mode_vm1"] = "fi"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm1"] = "/vm1/image"
        self.run_params["vg_name_vm1"] = "ramdisk_vm1"
        self.run_params["lv_pointer_name"] = "current_state"
        self._create_mock_vms()

        # if only offline state choose it
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = True
        state_setup.unset_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm1/image.qcow2 -U")
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm1", "launch")
        mock_lv_utils.lv_remove.assert_called_once_with("ramdisk_vm1", "launch")

    @mock.patch('state_setup.lv_utils')
    def test_unset_keep_pointer(self, mock_lv_utils):
        self.run_params["vms"] = "vm1"
        self.run_params["unset_state_vm1"] = "current_state"
        self.run_params["unset_type_vm1"] = "offline"
        self.run_params["unset_mode_vm1"] = "fi"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm1"] = "/vm1/image"
        self.run_params["vg_name_vm1"] = "ramdisk_vm1"
        self.run_params["lv_pointer_name"] = "current_state"
        self._create_mock_vms()

        # if only offline state choose it
        mock_lv_utils.lv_check.return_value = True
        with self.assertRaises(ValueError):
            state_setup.unset_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm1", "current_state")

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_unset_any_none_fi(self, mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm1"
        self.run_params["unset_state_vm1"] = "launch"
        self.run_params["unset_mode_vm1"] = "fi"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm1"] = "/vm1/image"
        self.run_params["vg_name_vm1"] = "ramdisk_vm1"
        self._create_mock_vms()

        # if no states cannot do anything
        mock_process.system_output.return_value = b"NOT HERE"
        mock_lv_utils.lv_check.return_value = False
        state_setup.unset_state(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm1/image.qcow2 -U")
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm1", "launch")

    @mock.patch('state_setup.lv_utils')
    def test_check_root(self, mock_lv_utils):
        self.run_params["vms"] = "vm1"
        self.run_params["check_state_vm1"] = "root"
        self.run_params["check_type_vm1"] = "offline"
        self.run_params["vg_name_vm1"] = "ramdisk_vm1"
        self.run_params["lv_name_vm1"] = "LogVol"
        self.run_params["image_name_vm1"] = "/vm1/image"
        self._create_mock_vms()
        # the os.path.exists stub will return False
        self.exist_switch = False

        for image_format in ["qcow2", "raw", "something-else"]:
            self.run_params["image_format"] = image_format
            mock_lv_utils.reset_mock()
            mock_lv_utils.lv_check.return_value = True
            exists = state_setup.check_state(self.run_params, self.env)
            mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm1", "LogVol")
            self.assertTrue(exists)

        self.run_params["image_format"] = "img"
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        exists = state_setup.check_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm1", "LogVol")
        self.assertFalse(exists)

    def test_check_boot(self):
        self.run_params["vms"] = "vm1"
        self.run_params["check_state_vm1"] = "boot"
        self.run_params["check_type_vm1"] = "online"
        self._create_mock_vms()

        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = True
        exists = state_setup.check_state(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        self.assertTrue(exists)

        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        exists = state_setup.check_state(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        self.assertFalse(exists)

    @mock.patch('state_setup.lv_utils')
    def test_set_root(self, mock_lv_utils):
        self.run_params["vms"] = "vm2"
        self.run_params["set_size_vm2"] = "30G"
        self.run_params["vg_name_vm2"] = "ramdisk_vm2"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["pool_name"] = "thin_pool"
        self.run_params["pool_size"] = "30G"
        self.run_params["lv_size"] = "30G"
        self.run_params["lv_pointer_name"] = "current_state"
        self.run_params["image_name_vm2"] = "/vm2/image"
        self.run_params["ramdisk_sparse_filename_vm2"] = "virtual_hdd_vm2"
        self.run_params["use_tmpfs"] = "yes"
        self.run_params["ramdisk_basedir_vm2"] = "/tmp"
        self.run_params["ramdisk_vg_size_vm2"] = "40000"
        self.run_params["image_raw_device_vm2"] = "no"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.vg_check.return_value = False
        state_setup.set_root(self.run_params)
        mock_lv_utils.vg_check.assert_called_once_with("ramdisk_vm2")
        mock_lv_utils.vg_ramdisk.assert_called_once_with(None, 'ramdisk_vm2', '40000', '/tmp', 'virtual_hdd_vm2', True)
        mock_lv_utils.lv_create.assert_called_once_with('ramdisk_vm2', 'LogVol', '30G', 'thin_pool', '30G')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('ramdisk_vm2', 'LogVol', 'current_state')

        mock_lv_utils.reset_mock()
        mock_lv_utils.vg_check.return_value = True
        with self.assertRaises(exceptions.TestError):
            state_setup.set_root(self.run_params)
        mock_lv_utils.vg_check.assert_called_once_with("ramdisk_vm2")

        # force create case
        self.run_params["force_create"] = "yes"
        mock_lv_utils.reset_mock()
        mock_lv_utils.vg_check.return_value = True
        state_setup.set_root(self.run_params)
        mock_lv_utils.vg_check.assert_called_once_with("ramdisk_vm2")
        mock_lv_utils.vg_ramdisk_cleanup.assert_called_once_with('virtual_hdd_vm2', '/tmp/ramdisk_vm2', 'ramdisk_vm2', None, True)
        mock_lv_utils.vg_ramdisk.assert_called_once_with(None, 'ramdisk_vm2', '40000', '/tmp', 'virtual_hdd_vm2', True)
        mock_lv_utils.lv_create.assert_called_once_with('ramdisk_vm2', 'LogVol', '30G', 'thin_pool', '30G')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('ramdisk_vm2', 'LogVol', 'current_state')

    @mock.patch('state_setup.lv_utils')
    def test_unset_root(self, mock_lv_utils):
        self.run_params["vms"] = "vm3"
        self.run_params["vg_name_vm3"] = "ramdisk_vm3"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["lv_pointer_name"] = "current_state"
        self.run_params["image_name_vm3"] = "/vm3/image"
        self.run_params["ramdisk_sparse_filename_vm3"] = "virtual_hdd_vm3"
        self.run_params["use_tmpfs"] = "yes"
        self.run_params["ramdisk_basedir_vm3"] = "/tmp"
        self.run_params["image_raw_device_vm3"] = "no"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.vg_check.return_value = True
        state_setup.unset_root(self.run_params)
        mock_lv_utils.vg_check.assert_called_once_with('ramdisk_vm3')
        mock_lv_utils.vg_ramdisk_cleanup.assert_called_once_with('virtual_hdd_vm3', '/tmp/ramdisk_vm3', 'ramdisk_vm3', None, True)

        # test tolerance to cleanup errors
        mock_lv_utils.reset_mock()
        mock_lv_utils.vg_check.return_value = True
        mock_lv_utils.vg_ramdisk_cleanup.side_effect = exceptions.TestError("cleanup failed")
        state_setup.unset_root(self.run_params)
        mock_lv_utils.vg_check.assert_called_once_with('ramdisk_vm3')
        mock_lv_utils.vg_ramdisk_cleanup.assert_called_once_with('virtual_hdd_vm3', '/tmp/ramdisk_vm3', 'ramdisk_vm3', None, True)

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_push(self, mock_lv_utils, _mock_process):
        self.run_params["vms"] = "vm4"
        self.run_params["push_state_vm4"] = "launch"
        self.run_params["push_type_vm4"] = "offline"
        self.run_params["push_mode_vm4"] = "ff"
        self.run_params["skip_types"] = "online"
        self.run_params["lv_pointer_name"] = "current_state"
        self.run_params["vg_name_vm4"] = "ramdisk_vm4"
        self._create_mock_vms()

        mock_lv_utils.lv_check.return_value = False
        state_setup.push_state(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("ramdisk_vm4", "launch")
        self.mock_vms["vm4"].destroy.assert_called_once_with(gracefully=True)
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('ramdisk_vm4', 'current_state', 'launch')

        # test push disabled for root/boot states
        self.run_params["push_state_vm4"] = "root"
        state_setup.push_state(self.run_params, self.env)
        mock_lv_utils.assert_not_called()
        self.run_params["push_state_vm4"] = "boot"
        state_setup.push_state(self.run_params, self.env)
        mock_lv_utils.assert_not_called()

    @mock.patch('state_setup.lv_utils')
    def test_pop_offline(self, mock_lv_utils):
        self.run_params["vms"] = "vm1"
        self.run_params["pop_state_vm1"] = "launch"
        self.run_params["pop_type_vm1"] = "offline"
        self.run_params["vg_name_vm1"] = "ramdisk_vm1"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["lv_pointer_name"] = "current_state"
        self.run_params["image_name_vm1"] = "/vm1/image"
        self.run_params["image_raw_device_vm1"] = "no"
        self._create_mock_vms()

        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm1"].is_alive.return_value = False

        state_setup.pop_state(self.run_params, self.env)

        mock_lv_utils.lv_check.assert_called_with("ramdisk_vm1", "launch")
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('ramdisk_vm1', 'launch', 'current_state')
        expected = [mock.call('ramdisk_vm1', 'current_state'), mock.call('ramdisk_vm1', 'launch')]
        self.assertListEqual(mock_lv_utils.lv_remove.call_args_list, expected)

        # test pop disabled for root/boot states
        self.run_params["pop_state_vm1"] = "root"
        state_setup.pop_state(self.run_params, self.env)
        mock_lv_utils.assert_not_called()
        self.run_params["pop_state_vm1"] = "boot"
        state_setup.pop_state(self.run_params, self.env)
        mock_lv_utils.assert_not_called()

    @mock.patch('state_setup.process')
    def test_pop_online(self, mock_process):
        self.run_params["vms"] = "vm1"
        self.run_params["pop_state_vm1"] = "launch"
        self.run_params["pop_type_vm1"] = "online"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm1"] = "/vm1/image"
        self._create_mock_vms()

        mock_process.system_output.return_value = b"1         launch   338M 2014-05-16 12:13:45   00:00:34.079"
        self.mock_vms["vm1"].is_alive.return_value = True
        self.mock_vms["vm1"].monitor.send_args_cmd.return_value = ""

        state_setup.pop_state(self.run_params, self.env)

        mock_process.system_output.assert_called_with("qemu-img snapshot -l /vm1/image.qcow2 -U")
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        self.mock_vms["vm1"].loadvm.assert_called_once_with('launch')
        self.mock_vms["vm1"].monitor.send_args_cmd.assert_called_once_with("delvm id=launch")

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_check_multivm(self, mock_lv_utils, _mock_process):
        self.run_params["vms"] = "vm1 vm2"
        self.run_params["check_state"] = "launch"
        self.run_params["check_state_vm2"] = "launcher"
        self.run_params["check_type"] = "offline"
        self.run_params["vg_name_vm1"] = "ramdisk_vm1"
        self.run_params["vg_name_vm2"] = "ramdisk_vm2"
        self._create_mock_vms()

        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        exists = state_setup.check_state(self.run_params, self.env)
        expected = [mock.call("ramdisk_vm1", "launch"), mock.call("ramdisk_vm2", "launcher")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected)
        self.assertTrue(exists)

        # break on first false state check
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        exists = state_setup.check_state(self.run_params, self.env)
        expected = [mock.call("ramdisk_vm1", "launch")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected)
        self.assertFalse(exists)

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_get_multivm(self, mock_lv_utils, mock_process):
        self.run_params["vms"] = "vm1 vm2 vm3"
        self.run_params["get_state"] = "launch2"
        self.run_params["get_state_vm1"] = "launch1"
        self.run_params["get_state_vm3"] = "launch3"
        self.run_params["get_type"] = "offline"
        self.run_params["get_type_vm3"] = "online"
        self.run_params["get_mode_vm1"] = "rx"
        self.run_params["get_mode_vm2"] = "ii"
        self.run_params["get_mode_vm3"] = "aa"
        self.run_params["qemu_img_binary"] = "qemu-img"
        self.run_params["image_name_vm3"] = "/vm3/image"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["lv_pointer_name"] = "current_state"
        self.run_params["vg_name_vm1"] = "ramdisk_vm1"
        self.run_params["vg_name_vm2"] = "ramdisk_vm2"
        self.run_params["vg_name_vm3"] = "ramdisk_vm3"
        self.run_params["image_name_vm1"] = "/vm1/image"
        self.run_params["image_name_vm2"] = "/vm2/image"
        self.run_params["image_raw_device"] = "no"
        self._create_mock_vms()

        # test online/offline switch as well
        def lv_check_side_effect(_vgname, lvname):
            return True if lvname == "launch1" else False if lvname == "launch2" else False
        mock_lv_utils.lv_check.side_effect = lv_check_side_effect
        mock_process.system_output.return_value = b"1         launch3   338M 2014-05-16 12:13:45   00:00:34.079"
        self.mock_vms["vm1"].is_alive.return_value = False
        self.mock_vms["vm3"].is_alive.return_value = True

        with self.assertRaises(exceptions.TestAbortError):
            state_setup.get_state(self.run_params, self.env)

        expected = [mock.call("ramdisk_vm1", "launch1"), mock.call("ramdisk_vm2", "launch2")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /vm3/image.qcow2 -U")
        # switch check if vm has to be booted
        self.mock_vms["vm3"].is_alive.assert_called_once_with()

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_set_multivm(self, mock_lv_utils, _mock_process):
        self.run_params["vms"] = "vm2 vm3 vm4"
        self.run_params["set_state"] = "launch2"
        self.run_params["set_state_vm2"] = "launch2"
        self.run_params["set_state_vm3"] = "root"
        self.run_params["set_state_vm4"] = "launch4"
        self.run_params["set_type"] = "offline"
        self.run_params["set_mode_vm2"] = "rx"
        self.run_params["set_mode_vm3"] = "ff"
        self.run_params["set_mode_vm4"] = "aa"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["lv_size"] = "30G"
        self.run_params["lv_pointer_name"] = "current_state"
        self.run_params["pool_name"] = "thin_pool"
        self.run_params["pool_size"] = "30G"
        self.run_params["vg_name_vm2"] = "ramdisk_vm2"
        self.run_params["vg_name_vm3"] = "ramdisk_vm3"
        self.run_params["vg_name_vm4"] = "ramdisk_vm4"
        self.run_params["image_name_vm3"] = "/vm3/image"
        self.run_params["image_raw_device"] = "no"
        self.run_params["ramdisk_sparse_filename_vm3"] = "virtual_hdd_vm3"
        self.run_params["use_tmpfs"] = "yes"
        self.run_params["ramdisk_basedir"] = "/tmp"
        self.run_params["ramdisk_vg_size"] = "40000"
        self.run_params["skip_types"] = "online"
        self._create_mock_vms()
        self.exist_switch = False

        def lv_check_side_effect(_vgname, lvname):
            return True if lvname == "launch2" else False if lvname == "launch4" else False
        mock_lv_utils.lv_check.side_effect = lv_check_side_effect
        mock_lv_utils.vg_check.return_value = False

        with self.assertRaises(exceptions.TestAbortError):
            state_setup.set_state(self.run_params, self.env)

        expected = [mock.call("ramdisk_vm2", "launch2"), mock.call("ramdisk_vm3", "LogVol"), mock.call("ramdisk_vm4", "launch4")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected)
        self.mock_vms["vm2"].destroy.assert_called_once_with(gracefully=True)
        self.mock_vms["vm3"].destroy.assert_called_once_with(gracefully=True)
        self.mock_vms["vm4"].destroy.assert_called_once_with(gracefully=True)
        mock_lv_utils.vg_check.assert_called_once_with('ramdisk_vm3')
        mock_lv_utils.vg_ramdisk.assert_called_once_with(None, 'ramdisk_vm3', '40000', '/tmp', 'virtual_hdd_vm3', True)
        mock_lv_utils.lv_create.assert_called_once_with('ramdisk_vm3', 'LogVol', '30G', 'thin_pool', '30G')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('ramdisk_vm3', 'LogVol', 'current_state')

    @mock.patch('state_setup.process')
    @mock.patch('state_setup.lv_utils')
    def test_unset_multivm(self, mock_lv_utils, _mock_process):
        self.run_params["vms"] = "vm1 vm4"
        self.run_params["unset_state_vm1"] = "root"
        self.run_params["unset_state_vm4"] = "launch4"
        self.run_params["unset_type"] = "offline"
        self.run_params["unset_mode_vm1"] = "ra"
        self.run_params["unset_mode_vm4"] = "fi"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["vg_name_vm1"] = "ramdisk_vm1"
        self.run_params["vg_name_vm4"] = "ramdisk_vm4"
        self.run_params["image_name_vm1"] = "/vm1/image"
        self.run_params["image_raw_device"] = "no"
        self._create_mock_vms()
        self.exist_switch = False

        def lv_check_side_effect(_vgname, lvname):
            return True if lvname == "LogVol" else False
        mock_lv_utils.lv_check.side_effect = lv_check_side_effect

        state_setup.unset_state(self.run_params, self.env)

        expected = [mock.call("ramdisk_vm1", "LogVol"), mock.call("ramdisk_vm4", "launch4")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected)


if __name__ == '__main__':
    unittest.main()
