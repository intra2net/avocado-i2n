#!/usr/bin/env python

import unittest
import unittest.mock as mock
import os

from avocado import Test
from avocado.core import exceptions
from avocado.utils import process
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
from avocado_i2n.states import vmnet


@mock.patch('avocado_i2n.states.lvm.os.mkdir', mock.Mock(return_value=0))
@mock.patch('avocado_i2n.states.lvm.os.makedirs', mock.Mock(return_value=0))
@mock.patch('avocado_i2n.states.lvm.os.rmdir', mock.Mock(return_value=0))
@mock.patch('avocado_i2n.states.lvm.os.unlink', mock.Mock(return_value=0))
@mock.patch('avocado_i2n.states.lvm.shutil.rmtree', mock.Mock(return_value=0))
@mock.patch('avocado_i2n.states.pool.os.makedirs', mock.Mock(return_value=0))
class StateSetupTest(Test):

    def setUp(self):
        self.run_str = ""

        ss.BACKENDS = {"lvm": lvm.LVMBackend, "qcow2": qcow2.QCOW2Backend,
                       "lxc": lxc.LXCBackend, "btrfs": btrfs.BtrfsBackend,
                       "pool": pool.QCOW2PoolBackend, "qcow2vt": qcow2.QCOW2VTBackend,
                       "ramfile": ramfile.RamfileBackend, "vmnet": vmnet.VMNetBackend}

        # disable pool locks for easier mocking
        pool.SKIP_LOCKS = True

        self.run_params = utils_params.Params()
        self.run_params["nets"] = "net1"
        self.run_params["vms"] = "vm1"
        self.run_params["images"] = "image1"
        self.run_params["main_vm"] = "vm1"
        self.run_params["image_name_vm1"] = "vm1/image"
        self.run_params["images_base_dir"] = "/images"
        self.run_params["nets"] = "net1"
        self.run_params["states_chain"] = "nets vms images"
        self.run_params["states_nets"] = "vmnet"
        self.run_params["states_images"] = "pool"
        self.run_params["states_vms"] = "qcow2vt"
        self.run_params["check_mode"] = "rr"

        self.env = mock.MagicMock(name='env')
        self.env.get_vm = mock.MagicMock(side_effect=self._get_mock_vm)

        self.mock_vms = {}

        self.mock_file_exists = mock.MagicMock(side_effect=self._file_exists)
        exists_patch = mock.patch('avocado_i2n.states.setup.os.path.exists',
                                  self.mock_file_exists)
        exists_patch.start()
        self.addCleanup(exists_patch.stop)
        self.exist_switch = True
        self.exist_lambda = None

    def _set_image_lvm_params(self):
        self.run_params["states_images"] = "lvm"
        self.run_params["vg_name_vm1"] = "disk_vm1"
        self.run_params["lv_name"] = "LogVol"
        self.run_params["lv_pointer_name"] = "current_state"

    def _set_image_qcow2_params(self):
        self.run_params["states_images"] = "qcow2"
        self.run_params["image_format"] = "qcow2"
        self.run_params["qemu_img_binary"] = "qemu-img"

    def _set_image_pool_params(self):
        self.run_params["states_images"] = "pool"
        self.run_params["image_pool"] = "/data/pool"
        self.run_params["image_format"] = "qcow2"
        self.run_params["qemu_img_binary"] = "qemu-img"

    def _set_vm_qcow2_params(self):
        self.run_params["states_vms"] = "qcow2vt"
        self.run_params["image_format"] = "qcow2"
        self.run_params["qemu_img_binary"] = "qemu-img"

    def _set_vm_ramfile_params(self):
        self.run_params["states_vms"] = "ramfile"

    def _get_mock_vm(self, vm_name):
        return self.mock_vms[vm_name]

    def _create_mock_vms(self):
        for vm_name in self.run_params.objects("vms"):
            self.mock_vms[vm_name] = mock.MagicMock(name=vm_name)
            self.mock_vms[vm_name].name = vm_name
            self.mock_vms[vm_name].params = self.run_params.object_params(vm_name)

    def _file_exists(self, filepath):
        # avocado's test class does some unexpected monkey patching
        if filepath.endswith(".expected"):
            return False
        if self.exist_lambda:
            return self.exist_lambda(filepath)
        return self.exist_switch

    def _only_root_exists(self, vg_name, lv_name):
        return True if lv_name == "LogVol" else False

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_show_image_lvm(self, mock_lv_utils):
        """Test that state listing with the LVM backend works correctly."""
        self._set_image_lvm_params()
        self.run_params["skip_types"] = "nets nets/vms"
        self._create_mock_vms()

        # assert empty list without available states
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_list.return_value = []
        states = ss.show_states(self.run_params, self.env)
        mock_lv_utils.lv_list.assert_called_once_with("disk_vm1")
        self.assertEqual(len(states), 0)

        # assert nonempty list with available states
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_list.return_value = ["launch1", "launch2"]
        states = ss.show_states(self.run_params, self.env)
        mock_lv_utils.lv_list.assert_called_once_with("disk_vm1")
        self.assertIn("launch1", states)
        self.assertIn("launch2", states)
        self.assertNotIn("launch3", states)
        self.assertNotIn("root", states)

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_show_image_qcow2(self, mock_process):
        """Test that state listing with the QCOW2 backend works correctly."""
        self._set_image_qcow2_params()
        self.run_params["skip_types"] = "nets nets/vms"
        self._create_mock_vms()

        # assert empty list without available states
        mock_process.reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        states = ss.show_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.assertEqual(len(states), 0)

        # assert nonempty list with available states
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

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_show_vm_qcow2(self, mock_process):
        """Test that state listing with the QCOW2VT backend works correctly."""
        self._set_vm_qcow2_params()
        self.run_params["skip_types"] = "nets nets/vms/images"
        self._create_mock_vms()

        # assert empty list without available states
        mock_process.reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        states = ss.show_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.assertEqual(len(states), 0)

        # assert nonempty list with available states
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

    @mock.patch('avocado_i2n.states.ramfile.glob')
    def test_show_vm_ramfile(self, mock_glob):
        """Test that state listing with the ramfile backend works correctly."""
        self._set_vm_ramfile_params()
        self.run_params["skip_types"] = "nets nets/vms/images"
        self._create_mock_vms()

        # assert empty list without available states
        mock_glob.reset_mock()
        mock_glob.glob.return_value = []
        states = ss.show_states(self.run_params, self.env)
        mock_glob.glob.assert_called_once_with("/images/vm1/*.state")
        self.assertEqual(len(states), 0)

        # assert nonempty list with available states
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
    def test_check_image_lvm(self, mock_lv_utils):
        """Test that state checking with the LVM backend works correctly."""
        self._set_image_lvm_params()
        self.run_params["check_state_images_vm1"] = "launch"
        self._create_mock_vms()

        # assert root state is checked as a prerequisite
        # and assert actual state is checked afterwards
        expected_checks = [mock.call("disk_vm1", "LogVol"),
                           mock.call("disk_vm1", "launch")]

        # assert behavior on root and state availability
        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.return_value = True
        exists = ss.check_states(self.run_params, self.env)
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        self.assertTrue(exists)

        # assert behavior on root availability
        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.side_effect = self._only_root_exists
        exists = ss.check_states(self.run_params, self.env)
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks)
        self.assertFalse(exists)

        # assert behavior on no root availability
        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.return_value = False
        mock_lv_utils.lv_check.side_effect = None
        exists = ss.check_states(self.run_params, self.env)
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected_checks[:1])
        self.mock_vms["vm1"].destroy.assert_not_called()
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_check_image_qcow2(self, mock_process):
        """Test that state checking with the QCOW2 backend works correctly."""
        self._set_image_qcow2_params()
        self.run_params["check_state_images_vm1"] = "launch"
        self._create_mock_vms()

        self.mock_file_exists.reset_mock()
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        mock_process.system_output.return_value = b"5         launch         0 B 2021-01-18 21:24:22   00:00:44.478"
        exists = ss.check_states(self.run_params, self.env)
        # assert root state is checked as a prerequisite
        self.mock_vms["vm1"].is_alive.assert_called()
        self.mock_file_exists.assert_called_once_with("/images/vm1/image.qcow2")
        # assert actual state is checked and available
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.assertTrue(exists)

        self.mock_file_exists.reset_mock()
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        mock_process.system_output.return_value = b"NOT HERE"
        exists = ss.check_states(self.run_params, self.env)
        # assert root state is checked as a prerequisite
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        self.mock_file_exists.assert_called_once_with("/images/vm1/image.qcow2")
        # assert actual state is checked and not available
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.assertFalse(exists)

        self.mock_file_exists.reset_mock()
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        self.exist_switch = False
        exists = ss.check_states(self.run_params, self.env)
        # assert root state is checked as a prerequisite
        self.mock_vms["vm1"].is_alive.assert_called_with()
        self.mock_file_exists.assert_called_once_with("/images/vm1/image.qcow2")
        # assert actual state is not checked and not available
        mock_process.system_output.assert_not_called()
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_check_image_qcow2_boot(self, mock_process):
        """
        Test that state checking with the QCOW2 backend considers running vms.

        .. todo:: Consider whether this is a good approach to spread to other
            state backends or rid ourselves of the QCOW2(VT) hacks altogether.
        """
        self._set_image_qcow2_params()
        self.run_params["check_state_images_vm1"] = "launch"
        self._create_mock_vms()

        self.mock_file_exists.reset_mock()
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = True
        exists = ss.check_states(self.run_params, self.env)
        # assert root state is checked as a prerequisite
        # assert off switch as part of root state is checked as a prerequisite
        self.mock_vms["vm1"].is_alive.assert_called()
        self.mock_file_exists.assert_not_called()
        # assert actual state is not checked and not available
        mock_process.system_output.assert_not_called()
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_check_vm_qcow2(self, mock_process):
        """Test that state checking with the QCOW2VT backend works correctly."""
        self._set_vm_qcow2_params()
        self.run_params["check_state_vms_vm1"] = "launch"
        self._create_mock_vms()

        self.mock_file_exists.reset_mock()
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = True
        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        exists = ss.check_states(self.run_params, self.env)
        # assert root state is checked as a prerequisite
        self.mock_file_exists.assert_called_once_with("/images/vm1/image.qcow2")
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        # assert actual state is checked and available
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.assertTrue(exists)

        self.mock_file_exists.reset_mock()
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = True
        mock_process.system_output.return_value = b"NOT HERE"
        exists = ss.check_states(self.run_params, self.env)
        # assert root state is checked as a prerequisite
        self.mock_file_exists.assert_called_once_with("/images/vm1/image.qcow2")
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        # assert actual state is checked and not available
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.assertFalse(exists)

        self.mock_file_exists.reset_mock()
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        exists = ss.check_states(self.run_params, self.env)
        # assert root state is checked as a prerequisite
        self.mock_file_exists.assert_called_once_with("/images/vm1/image.qcow2")
        self.mock_vms["vm1"].is_alive.assert_called_with()
        # assert actual state is not checked and not available
        mock_process.system_output.assert_not_called()
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_check_vm_qcow2_noimage(self, mock_process):
        """
        Test that state checking with the QCOW2VT backend considers missing images.

        .. todo:: Consider whether this is a good approach to spread to other
            state backends or rid ourselves of the QCOW2(VT) hacks altogether.
        """
        self._set_vm_qcow2_params()
        self.run_params["check_state_vms_vm1"] = "launch"
        self._create_mock_vms()

        self.mock_file_exists.reset_mock()
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_switch = False
        exists = ss.check_states(self.run_params, self.env)
        # assert root state is checked as a prerequisite
        # assert missing image as part of root state is checked as a prerequisite
        self.mock_file_exists.assert_called_once_with("/images/vm1/image.qcow2")
        self.mock_vms["vm1"].is_alive.assert_not_called()
        # assert actual state is not checked and not available
        mock_process.system_output.assert_not_called()
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.ramfile.os')
    def test_check_vm_ramfile(self, mock_os):
        """Test that state checking with the ramfile backend works correctly."""
        self._set_vm_ramfile_params()
        self.run_params["check_state_vms_vm1"] = "launch"
        self._create_mock_vms()

        # restore some unmocked parts of the os module
        mock_os.path.dirname = os.path.dirname
        mock_os.path.join = os.path.join
        mock_os.path.isabs.return_value = False
        mock_os.path.exists = self.mock_file_exists

        expected_checks = [mock.call("/images/vm1/image.qcow2"),
                           mock.call("/images/vm1/launch.state")]

        self.mock_file_exists.reset_mock()
        mock_os.reset_mock()
        self.exist_switch = True
        exists = ss.check_states(self.run_params, self.env)
        self.assertListEqual(mock_os.path.exists.call_args_list, expected_checks)
        self.assertTrue(exists)

        self.mock_file_exists.reset_mock()
        mock_os.reset_mock()
        self.exist_lambda = lambda filename: filename.endswith("image.qcow2")
        exists = ss.check_states(self.run_params, self.env)
        self.assertListEqual(mock_os.path.exists.call_args_list, expected_checks)
        self.assertFalse(exists)

        self.mock_file_exists.reset_mock()
        mock_os.reset_mock()
        self.exist_lambda = None
        self.exist_switch = False
        exists = ss.check_states(self.run_params, self.env)
        mock_os.path.exists.assert_called_once_with("/images/vm1/image.qcow2")
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_check_forced_root(self, mock_process):
        """Test that state checking with a state backend can provide roots."""
        self._set_vm_qcow2_params()
        self.run_params["check_state_vms_vm1"] = "launch"
        self.run_params["check_mode"] = "ff"
        self._create_mock_vms()

        # assert root state is not detected then created to check the actual state
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        mock_process.system_output.return_value = b"NOT HERE"
        exists = ss.check_states(self.run_params, self.env)
        # assert root state is checked as a prerequisite
        self.mock_vms["vm1"].is_alive.assert_called_with()
        # assert root state is provided from the check
        self.mock_vms["vm1"].create.assert_called_once_with()
        # assert actual state is still checked and not available
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_image_lvm(self, mock_lv_utils):
        """Test that state getting with the LVM backend works with available root."""
        self._set_image_lvm_params()
        self.run_params["get_state_images_vm1"] = "launch"
        # use a nondefault policy that doesn't raise any errors here
        self.run_params["get_mode_vm1"] = "ri"
        self._create_mock_vms()

        # assert state is retrieved if available after it was checked
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_with("disk_vm1", "launch")
        mock_lv_utils.lv_remove.assert_called_once_with('disk_vm1', 'current_state')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'launch', 'current_state')

        # assert state is not retrieved if not available after it was checked
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.side_effect = self._only_root_exists
        ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_with("disk_vm1", "launch")
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_get_image_qcow2(self, mock_process):
        """Test that state getting with the QCOW2 backend works with available root."""
        self._set_image_qcow2_params()
        self.run_params["get_state_images_vm1"] = "launch"
        # use a nondefault policy that doesn't raise any errors here
        self.run_params["get_mode_vm1"] = "ri"
        self._create_mock_vms()

        # root state is available in all cases
        self.exist_switch = True
        self.mock_vms["vm1"].is_alive.return_value = False

        # assert state is retrieved if available after it was checked
        mock_process.reset_mock()
        mock_process.system_output.return_value = b"5         launch         0 B 2021-01-18 21:24:22   00:00:44.478"
        ss.get_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        mock_process.system.assert_called_once_with("qemu-img snapshot -a launch /images/vm1/image.qcow2")

        # assert state is not retrieved if not available after it was checked
        mock_process.reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        ss.get_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        mock_process.system.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_aa(self, mock_lv_utils):
        """Test that state getting works with abort policies."""
        self._set_image_lvm_params()
        self.run_params["get_state_images_vm1"] = "launch"
        self.run_params["get_mode_vm1"] = "aa"
        self._create_mock_vms()

        # assert state retrieval is aborted if state is available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        with self.assertRaises(exceptions.TestAbortError):
            ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

        # assert state retrieval is aborted if state is not available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestAbortError):
            ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_rx(self, mock_lv_utils):
        """Test that state getting works with reuse policy."""
        self._set_image_lvm_params()
        self.run_params["get_state_images_vm1"] = "launch"
        self.run_params["get_mode_vm1"] = "rx"
        self._create_mock_vms()

        # assert state retrieval is reused if available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_called_once_with('disk_vm1', 'current_state')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'launch', 'current_state')

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_ii(self, mock_lv_utils):
        """Test that state getting works with ignore policies."""
        self._set_image_lvm_params()
        self.run_params["get_state_images_vm1"] = "launch"
        self.run_params["get_mode_vm1"] = "ii"
        self._create_mock_vms()

        # assert state retrieval is ignored if state is available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

        # assert state retrieval is ignored if state is not available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_xx(self, mock_lv_utils):
        """Test that state getting detects invalid policies."""
        self._set_image_lvm_params()
        self.run_params["get_state_images_vm1"] = "launch"
        self.run_params["get_mode_vm1"] = "xx"
        self._create_mock_vms()

        # assert invalid policy x if state is available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        with self.assertRaises(exceptions.TestError):
            ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

        # assert invalid policy x if state is not available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestError):
            ss.get_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_get_vm_qcow2(self, mock_process):
        """Test that state getting with the QCOW2VT backend works with available root."""
        self._set_vm_qcow2_params()
        self.run_params["get_state_vms_vm1"] = "launch"
        # use a nondefault policy that doesn't raise any errors here
        self.run_params["get_mode_vm1"] = "ri"
        self._create_mock_vms()

        # root state is available in all cases
        self.exist_switch = True
        self.mock_vms["vm1"].is_alive.return_value = True

        # assert state is retrieved if available after it was checked
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        ss.get_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.mock_vms["vm1"].loadvm.assert_called_once_with('launch')

        # assert state is not retrieved if not available after it was checked
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        ss.get_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.mock_vms["vm1"].loadvm.assert_not_called()

    @mock.patch('avocado_i2n.states.ramfile.os')
    def test_get_vm_ramfile(self, mock_os):
        """Test that state getting with the ramdisk backend works with available root."""
        self._set_vm_ramfile_params()
        self.run_params["get_state_vms_vm1"] = "launch"
        # use a nondefault policy that doesn't raise any errors here
        self.run_params["get_mode_vm1"] = "ri"
        self._create_mock_vms()

        # restore some unmocked parts of the os module
        mock_os.path.dirname = os.path.dirname
        mock_os.path.join = os.path.join
        mock_os.path.isabs.return_value = False
        mock_os.path.exists = self.mock_file_exists

        # assert state is retrieved if available after it was checked
        self.mock_file_exists.reset_mock()
        mock_os.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_switch = True
        ss.get_states(self.run_params, self.env)
        mock_os.path.exists.assert_called_with("/images/vm1/launch.state")
        self.mock_vms["vm1"].restore_from_file.assert_called_once_with("/images/vm1/launch.state")

        # assert state is not retrieved if not available after it was checked
        self.mock_file_exists.reset_mock()
        mock_os.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_lambda = lambda filename: filename.endswith("image.qcow2")
        ss.get_states(self.run_params, self.env)
        mock_os.path.exists.assert_called_with("/images/vm1/launch.state")
        self.mock_vms["vm1"].restore_from_file.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_image_lvm(self, mock_lv_utils):
        """Test that state setting with the LVM backend works with available root."""
        self._set_image_lvm_params()
        self.run_params["set_state_images_vm1"] = "launch"
        self._create_mock_vms()

        # assert state is removed and saved if available after it was checked
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_with("disk_vm1", "launch")
        mock_lv_utils.lv_remove.assert_called_once_with("disk_vm1", "launch")
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'current_state', 'launch')

        # assert state is saved if not available after it was checked
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.side_effect = self._only_root_exists
        ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_any_call("disk_vm1", "launch")
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'current_state', 'launch')

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_set_image_qcow2(self, mock_process):
        """Test that state setting with the QCOW2 backend works with available root."""
        self._set_image_qcow2_params()
        self.run_params["set_state_images_vm1"] = "launch"
        self._create_mock_vms()

        # root state is available in all cases
        self.exist_switch = True
        self.mock_vms["vm1"].is_alive.return_value = False

        # assert state is removed and saved if available after it was checked
        mock_process.reset_mock()
        mock_process.system_output.return_value = b"5         launch         0 B 2021-01-18 21:24:22   00:00:44.478"
        ss.set_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        expected_checks = [mock.call("qemu-img snapshot -d launch /images/vm1/image.qcow2"),
                           mock.call("qemu-img snapshot -c launch /images/vm1/image.qcow2")]
        self.assertListEqual(mock_process.system.call_args_list, expected_checks)

        # assert state is saved if not available after it was checked
        mock_process.reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        ss.set_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        mock_process.system.assert_called_once_with("qemu-img snapshot -c launch /images/vm1/image.qcow2")

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_aa(self, mock_lv_utils):
        """Test that state setting works with abort policies."""
        self._set_image_lvm_params()
        self.run_params["set_state_images_vm1"] = "launch"
        self.run_params["set_mode_vm1"] = "aa"
        self._create_mock_vms()

        # assert state saving is aborted if state is available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        with self.assertRaises(exceptions.TestAbortError):
            ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

        # assert state saving is aborted if state is not available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestAbortError):
            ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_rx(self, mock_lv_utils):
        """Test that state setting works with reuse policy."""
        self._set_image_lvm_params()
        self.run_params["set_state_images_vm1"] = "launch"
        self.run_params["set_mode_vm1"] = "rx"
        self._create_mock_vms()

        # assert state saving is skipped if reusable state is available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_ff(self, mock_lv_utils):
        """Test that state setting works with force policies."""
        self._set_image_lvm_params()
        self.run_params["set_state_images_vm1"] = "launch"
        self.run_params["set_mode_vm1"] = "ff"
        self._create_mock_vms()

        # assert state saving is forced if state is available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_called_once_with("disk_vm1", "launch")
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'current_state', 'launch')

        # assert state saving is forced if state is not available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.side_effect = self._only_root_exists
        ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'current_state', 'launch')

        # assert state saving is cannot be forced if state root is not available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.side_effect = None
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestError):
            ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_set_xx(self, mock_lv_utils):
        """Test that state setting detects invalid policies."""
        self._set_image_lvm_params()
        self.run_params["set_state_images_vm1"] = "launch"
        self.run_params["set_mode_vm1"] = "xx"
        self._create_mock_vms()

        # assert invalid policy x if state is available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        with self.assertRaises(exceptions.TestError):
            ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

        # assert invalid policy x if state is not available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestError):
            ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_set_vm_qcow2(self, mock_process):
        """Test that state setting with the QCOW2VT backend works with available root."""
        self._set_vm_qcow2_params()
        self.run_params["set_state_vms_vm1"] = "launch"
        self._create_mock_vms()

        # root state is available in all cases
        self.exist_switch = True
        self.mock_vms["vm1"].is_alive.return_value = True

        # assert state is removed and saved if available after it was checked
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        ss.set_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.mock_vms["vm1"].savevm.assert_called_once_with('launch')

        # assert state is saved if not available after it was checked
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        ss.set_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.mock_vms["vm1"].savevm.assert_called_once_with('launch')

    @mock.patch('avocado_i2n.states.ramfile.os')
    def test_set_vm_ramfile(self, mock_os):
        """Test that state setting with the ramfile backend works with available root."""
        self._set_vm_ramfile_params()
        self.run_params["set_state_vms_vm1"] = "launch"
        self._create_mock_vms()

        # restore some unmocked parts of the os module
        mock_os.path.dirname = os.path.dirname
        mock_os.path.join = os.path.join
        mock_os.path.isabs.return_value = False
        mock_os.path.exists = self.mock_file_exists

        # assert state is removed and saved if available after it was checked
        self.mock_file_exists.reset_mock()
        mock_os.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_switch = True
        ss.set_states(self.run_params, self.env)
        mock_os.path.exists.assert_called_with("/images/vm1/launch.state")
        self.mock_vms["vm1"].save_to_file.assert_called_once_with("/images/vm1/launch.state")

        # assert state is saved if not available after it was checked
        self.mock_file_exists.reset_mock()
        mock_os.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_lambda = lambda filename: filename.endswith("image.qcow2")
        ss.set_states(self.run_params, self.env)
        mock_os.path.exists.assert_any_call("/images/vm1/launch.state")
        self.mock_vms["vm1"].save_to_file.assert_called_once_with("/images/vm1/launch.state")

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_unset_image_lvm(self, mock_lv_utils):
        """Test that state unsetting with the LVM backend works with available root."""
        self._set_image_lvm_params()
        self.run_params["unset_state_images_vm1"] = "launch"
        self._create_mock_vms()

        # assert state is removed if available after it was checked
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_with("disk_vm1", "launch")
        mock_lv_utils.lv_remove.assert_called_once_with("disk_vm1", "launch")
        mock_lv_utils.lv_take_snapshot.assert_not_called()

        # assert state is not removed if not available after it was checked
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.side_effect = self._only_root_exists
        ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_any_call("disk_vm1", "launch")
        mock_lv_utils.lv_remove.assert_not_called()
        mock_lv_utils.lv_take_snapshot.assert_not_called()

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_unset_image_qcow2(self, mock_process):
        """Test that state unsetting with the QCOW2 backend works with available root."""
        self._set_image_qcow2_params()
        self.run_params["unset_state_images_vm1"] = "launch"
        self._create_mock_vms()

        # root state is available in all cases
        self.exist_switch = True
        self.mock_vms["vm1"].is_alive.return_value = False

        # assert state is removed if available after it was checked
        mock_process.reset_mock()
        mock_process.system_output.return_value = b"5         launch         0 B 2021-01-18 21:24:22   00:00:44.478"
        ss.unset_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        mock_process.system.assert_called_once_with("qemu-img snapshot -d launch /images/vm1/image.qcow2")

        # assert state is not removed if not available after it was checked
        mock_process.reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        ss.unset_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        mock_process.system.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_unset_ra(self, mock_lv_utils):
        """Test that state unsetting works with reuse and abort policy."""
        self._set_image_lvm_params()
        self.run_params["unset_state_images_vm1"] = "launch"
        self.run_params["unset_mode_vm1"] = "ra"
        self._create_mock_vms()

        # assert state removal is skipped if reusable state is available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()

        # assert state removal is aborted if state is not available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestAbortError):
            ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_unset_fi(self, mock_lv_utils):
        """Test that state unsetting works with force and ignore policy."""
        self._set_image_lvm_params()
        self.run_params["unset_state_images_vm1"] = "launch"
        self.run_params["unset_mode_vm1"] = "fi"
        self._create_mock_vms()

        # assert state removal is forced if state is available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_called_once_with("disk_vm1", "launch")

        # assert state removal is ignored if state is not available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_unset_xx(self, mock_lv_utils):
        """Test that state unsetting detects invalid policies."""
        self._set_image_lvm_params()
        self.run_params["unset_state_images_vm1"] = "launch"
        self.run_params["unset_mode_vm1"] = "xx"
        self._create_mock_vms()

        # assert invalid policy x if state is available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        with self.assertRaises(exceptions.TestError):
            ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()

        # assert invalid policy x if state is not available
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        with self.assertRaises(exceptions.TestError):
            ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_unset_vm_qcow2(self, mock_process):
        """Test that state unsetting with the QCOW2VT backend works with available root."""
        self._set_vm_qcow2_params()
        self.run_params["unset_state_vms_vm1"] = "launch"
        self._create_mock_vms()

        # root state is available in all cases
        self.exist_switch = True
        self.mock_vms["vm1"].is_alive.return_value = True

        # assert state is removed if available after it was checked
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_process.system_output.return_value = b"5         launch         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        ss.unset_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.mock_vms["vm1"].monitor.send_args_cmd.assert_called_once_with('delvm id=launch')

        # assert state is not removed if not available after it was checked
        mock_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        mock_process.system_output.return_value = b"NOT HERE"
        ss.unset_states(self.run_params, self.env)
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm1/image.qcow2 -U")
        self.mock_vms["vm1"].monitor.send_args_cmd.assert_not_called()

    @mock.patch('avocado_i2n.states.ramfile.os')
    def test_unset_vm_ramfile(self, mock_os):
        """Test that state unsetting with the ramfile backend works with available root."""
        self._set_vm_ramfile_params()
        self.run_params["unset_state_vms_vm1"] = "launch"
        self._create_mock_vms()

        # restore some unmocked parts of the os module
        mock_os.path.dirname = os.path.dirname
        mock_os.path.join = os.path.join
        mock_os.path.isabs.return_value = False
        mock_os.path.exists = self.mock_file_exists

        # assert state is removed if available after it was checked
        self.mock_file_exists.reset_mock()
        mock_os.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_switch = True
        ss.unset_states(self.run_params, self.env)
        mock_os.path.exists.assert_called_with("/images/vm1/launch.state")
        mock_os.unlink.assert_called_once_with("/images/vm1/launch.state")

        # assert state is not removed if not available after it was checked
        self.mock_file_exists.reset_mock()
        mock_os.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_lambda = lambda filename: filename.endswith("image.qcow2")
        ss.unset_states(self.run_params, self.env)
        mock_os.path.exists.assert_any_call("/images/vm1/launch.state")
        mock_os.unlink.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_unset_image_lvm_keep_pointer(self, mock_lv_utils):
        """Test that LVM backend's pointer state cannot be unset."""
        self._set_image_lvm_params()
        self.run_params["unset_state_images_vm1"] = "current_state"
        self._create_mock_vms()

        mock_lv_utils.lv_check.return_value = True
        with self.assertRaises(ValueError):
            ss.unset_states(self.run_params, self.env)
        mock_lv_utils.lv_remove.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_check_root_image_lvm(self, mock_lv_utils):
        """Test that root checking with the LVM backend works."""
        self._set_image_lvm_params()
        self.run_params["check_state_images_vm1"] = "root"
        self._create_mock_vms()

        # assert root state is correctly detected
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        exists = ss.check_states(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("disk_vm1", "LogVol")
        self.assertTrue(exists)

        # assert root state is correctly not detected
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        exists = ss.check_states(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_once_with("disk_vm1", "LogVol")
        mock_lv_utils.lv_check.assert_called_once_with("disk_vm1", "LogVol")
        self.assertFalse(exists)

    def test_check_root_image_qcow2(self):
        """Test that root checking with the QCOW2 backend works."""
        self._set_image_qcow2_params()
        self.run_params["check_state_images_vm1"] = "root"
        # bonus: test for two images rather than one
        self.run_params["images_vm1"] = "image1 image2"
        self.run_params["image_name_image1_vm1"] = "vm1/image1"
        self.run_params["image_name_image2_vm1"] = "vm1/image2"
        self._create_mock_vms()

        # assert root state is correctly detected
        self.mock_vms["vm1"].is_alive.return_value = False
        self.exist_switch = True
        exists = ss.check_states(self.run_params, self.env)
        self.assertTrue(exists)

        # assert root state is correctly not detected
        self.mock_vms["vm1"].is_alive.return_value = True
        self.exist_switch = True
        exists = ss.check_states(self.run_params, self.env)
        self.assertFalse(exists)

        # assert running vms result in not completely available root state
        self.mock_vms["vm1"].is_alive.return_value = True
        self.exist_switch = False
        exists = ss.check_states(self.run_params, self.env)
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.pool.shutil')
    def test_check_root_image_pool(self, mock_shutil):
        """Test that root checking with the pool backend works."""
        self._set_image_pool_params()
        self.run_params["check_state_images_vm1"] = "root"
        # bonus: test for two images rather than one
        self.run_params["images_vm1"] = "image1 image2"
        self.run_params["image_name_image1_vm1"] = "vm1/image1"
        self.run_params["image_name_image2_vm1"] = "vm1/image2"
        self._create_mock_vms()

        self.mock_vms["vm1"].is_alive.return_value = False

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

    def test_check_root_vm_qcow2(self):
        """Test that root checking with the QCOW2VT backend works."""
        self._set_vm_qcow2_params()
        self.run_params["check_state_vms_vm1"] = "root"
        self._create_mock_vms()

        # assert root state is correctly detected
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = True
        exists = ss.check_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        self.assertTrue(exists)

        # assert root state is correctly not detected
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        exists = ss.check_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called_once_with()
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_check_root_vm_ramfile(self, mock_lv_utils):
        """Test that root checking with the ramdisk backend works."""
        self._set_vm_ramfile_params()
        self.run_params["check_state_vms_vm1"] = "root"
        # bonus: test for two images rather than one
        self.run_params["images_vm1"] = "image1 image2"
        self.run_params["image_name_image1_vm1"] = "vm1/image1"
        self.run_params["image_name_image2_vm1"] = "vm1/image2"
        self._create_mock_vms()

        self.mock_vms["vm1"].reset_mock()
        mock_lv_utils.lv_check.return_value = True

        # assert root state is correctly detected
        mock_lv_utils.reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = True
        # using LVM makes the image format free to choose
        for image_format in ["qcow2", "raw", "something-else"]:
            self.run_params["image_format"] = image_format
            exists = ss.check_states(self.run_params, self.env)
            self.assertTrue(exists)

        # assert root state is correctly not detected
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        self.run_params["image_format"] = "img"
        exists = ss.check_states(self.run_params, self.env)
        self.assertFalse(exists)

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_root_image(self, mock_lv_utils):
        """Test that root getting with an image state backend works."""
        # only test with most default backends
        self._set_image_qcow2_params()
        self.run_params["get_state_images_vm1"] = "root"
        self._create_mock_vms()

        self.mock_vms["vm1"].is_alive.return_value = False

        # cannot verify that the operation is NOOP so simply run it for coverage
        ss.get_states(self.run_params, self.env)

    @mock.patch('avocado_i2n.states.pool.shutil')
    def test_get_root_image_pool(self, mock_shutil):
        """Test that root getting with the pool backend works."""
        self._set_image_pool_params()
        self.run_params["get_state_images_vm1"] = "root"
        self._create_mock_vms()

        self.mock_vms["vm1"].is_alive.return_value = False

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
        with self.assertRaises(exceptions.TestAbortError):
            ss.get_states(self.run_params, self.env)
        mock_shutil.copy.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_get_root_vm(self, mock_lv_utils):
        """Test that root getting with an vm state backend works."""
        # only test with most default backends
        self._set_image_qcow2_params()
        self._set_vm_qcow2_params()
        self.run_params["get_state_vms_vm1"] = "root"
        self._create_mock_vms()

        # cannot verify that the operation is NOOP so simply run it for coverage
        ss.get_states(self.run_params, self.env)

    # TODO: LVM is not supposed to reach to QCOW2 but we have in-code TODO about it
    @mock.patch('avocado_i2n.states.setup.env_process', mock.Mock(return_value=0))
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    @mock.patch('avocado_i2n.states.lvm.process')
    def test_set_root_image_lvm(self, mock_process, mock_lv_utils):
        """Test that root setting with the LVM backend works."""
        self._set_image_lvm_params()
        self.run_params["set_state_images_vm1"] = "root"
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
        # TODO: LVM is still internally tied to QCOW images and needs testing otherwise
        self.run_params["image_format"] = "qcow2"
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

        # assert root state is detected and overwritten
        mock_process.reset_mock()
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = True
        ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_with('disk_vm1', 'LogVol')
        mock_process.run.assert_called_with('vgcreate disk_vm1 /dev/loop0', sudo=True)
        mock_lv_utils.lv_create.assert_called_once_with('disk_vm1', 'LogVol', '30G', pool_name='thin_pool', pool_size='30G')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'LogVol', 'current_state')

        # assert root state is not detected and created
        mock_process.reset_mock()
        mock_lv_utils.reset_mock()
        mock_lv_utils.lv_check.return_value = False
        ss.set_states(self.run_params, self.env)
        mock_lv_utils.lv_check.assert_called_with('disk_vm1', 'LogVol')
        mock_process.run.assert_called_with('vgcreate disk_vm1 /dev/loop0', sudo=True)
        mock_lv_utils.lv_create.assert_called_once_with('disk_vm1', 'LogVol', '30G', pool_name='thin_pool', pool_size='30G')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'LogVol', 'current_state')

    @mock.patch('avocado_i2n.states.setup.env_process')
    def test_set_root_image_qcow2(self, mock_env_process):
        """Test that root setting with the QCOW2 backend works."""
        self._set_image_qcow2_params()
        self.run_params["set_state_images_vm1"] = "root"
        self._create_mock_vms()

        # assert root state is detected and overwritten
        self.mock_file_exists.reset_mock()
        mock_env_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        exists_times = [True, False]
        self.exist_lambda = lambda filename: exists_times.pop(0)
        ss.set_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called()
        # called twice because QCOW2's set_root can only set missing root part
        # like only turning off the vm or only creating an image
        self.mock_file_exists.assert_called_with("/images/vm1/image.qcow2")
        mock_env_process.preprocess_image.assert_called_once()

        # assert root state is not detected and created
        self.mock_file_exists.reset_mock()
        mock_env_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        self.exist_lambda = None
        self.exist_switch = False
        ss.set_states(self.run_params, self.env)
        self.mock_vms["vm1"].is_alive.assert_called()
        # called twice because QCOW2's set_root can only set missing root part
        # like only turning off the vm or only creating an image
        self.mock_file_exists.assert_called_with("/images/vm1/image.qcow2")
        mock_env_process.preprocess_image.assert_called_once()

        # assert running vms result in setting only remaining part of root state
        self.mock_file_exists.reset_mock()
        mock_env_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = True
        self.exist_switch = True
        ss.set_states(self.run_params, self.env)
        # is vm is not alive root is not available and no need to check image existence
        self.mock_vms["vm1"].is_alive.assert_called()
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=True)
        mock_env_process.preprocess_image.assert_not_called()

    @mock.patch('avocado_i2n.states.pool.shutil')
    @mock.patch('avocado_i2n.states.pool.QCOW2Backend.set_root')
    @mock.patch('avocado_i2n.states.pool.QCOW2Backend.unset_root', mock.Mock())
    def test_set_root_image_pool(self, mock_set_root, mock_shutil):
        """Test that root setting with the pool backend works."""
        self._set_image_pool_params()
        self.run_params["set_state_images_vm1"] = "root"
        self._create_mock_vms()

        # needed to make all QCOW2 root checks pass
        self.mock_vms["vm1"].is_alive.return_value = False

        # not updating the state pool means setting the local root
        self.run_params["update_pool"] = "no"
        mock_set_root.reset_mock()
        mock_shutil.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        ss.set_states(self.run_params, self.env)
        mock_set_root.assert_called_once()
        mock_shutil.copy.assert_not_called()

        # updating the state pool means not setting the local root
        self.run_params["update_pool"] = "yes"
        mock_set_root.reset_mock()
        mock_shutil.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        ss.set_states(self.run_params, self.env)
        mock_set_root.assert_not_called()
        mock_shutil.copy.assert_called_with("/images/vm1/image.qcow2",
                                            "/data/pool/vm1/image.qcow2")

        # updating the state pool without local root must fail early
        self.run_params["update_pool"] = "yes"
        mock_set_root.reset_mock()
        mock_shutil.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.exist_lambda = lambda filename: filename.startswith("/data/pool")
        with self.assertRaises(RuntimeError):
            ss.set_states(self.run_params, self.env)
        mock_set_root.assert_not_called()
        mock_shutil.copy.assert_not_called()

    def test_set_root_vm(self):
        """Test that root setting with a vm state backend works."""
        self._set_vm_qcow2_params()
        self.run_params["set_state_vms_vm1"] = "root"
        self._create_mock_vms()

        # assert root state is not detected and created
        self.mock_vms["vm1"].is_alive.return_value = False
        ss.set_states(self.run_params, self.env)
        self.mock_vms["vm1"].create.assert_called_once_with()

        # assert running vms result in not completely available root state
        self.mock_vms["vm1"].is_alive.return_value = True
        ss.set_states(self.run_params, self.env)
        self.mock_vms["vm1"].create.assert_called_once_with()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    @mock.patch('avocado_i2n.states.lvm.vg_cleanup')
    def test_unset_root_image_lvm(self, mock_vg_cleanup, mock_lv_utils):
        """Test that root unsetting with the LVM backend works."""
        self._set_image_lvm_params()
        self.run_params["unset_state_images_vm1"] = "root"
        self.run_params["image_name_vm1"] = "vm1/image"
        self.run_params["disk_sparse_filename_vm1"] = "virtual_hdd_vm1"
        self.run_params["use_tmpfs"] = "yes"
        self.run_params["disk_basedir_vm1"] = "/tmp"
        self.run_params["image_raw_device_vm1"] = "no"
        self._create_mock_vms()

        # assert root state is detected and removed
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
    def test_unset_root_image_qcow2(self, mock_env_process, mock_os):
        """Test that root unsetting with the QCOW2 backend works."""
        self._set_image_qcow2_params()
        self.run_params["unset_state_images_vm1"] = "root"
        self._create_mock_vms()

        # assert root state is detected and removed
        mock_os.reset_mock()
        mock_env_process.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        self.mock_vms["vm1"].is_alive.return_value = False
        ss.unset_states(self.run_params, self.env)
        mock_env_process.postprocess_image.assert_called_once()
        mock_os.rmdir.assert_called_once()

        # TODO: assert running vms result in not completely available root state
        # TODO: running vm implies no root state which implies ignore or abort policy
        #self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=False)
        pass

    @mock.patch('avocado_i2n.states.pool.os')
    @mock.patch('avocado_i2n.states.setup.env_process')
    def test_unset_root_image_pool(self, mock_env_process, mock_os):
        """Test that root unsetting with the pool backend works."""
        self._set_image_pool_params()
        self.run_params["unset_state_images_vm1"] = "root"
        self._create_mock_vms()

        self.mock_vms["vm1"].is_alive.return_value = False

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

        # updating the state pool means not unsetting the local root
        self.run_params["update_pool"] = "yes"
        mock_env_process.reset_mock()
        mock_os.reset_mock()
        self.mock_vms["vm1"].reset_mock()
        ss.unset_states(self.run_params, self.env)
        mock_env_process.postprocess_image.assert_not_called()
        # TODO: partial (local only) root state implies no root and thus ignore unset only
        mock_os.unlink.assert_called_with("/data/pool/vm1/image.qcow2")

    def test_unset_root_vm(self):
        """Test that root unsetting with a vm state backend works."""
        self._set_vm_qcow2_params()
        self.run_params["unset_state_vms_vm1"] = "root"
        self._create_mock_vms()

        # assert root state is detected and removed
        ss.unset_states(self.run_params, self.env)
        self.mock_vms["vm1"].destroy.assert_called_once_with(gracefully=False)

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_push(self, mock_lv_utils, _mock_process):
        """Test that pushing with a state backend works."""
        self._set_image_lvm_params()
        self.run_params["push_state_images_vm1"] = "launch"
        self.run_params["push_mode_vm1"] = "ff"
        self._create_mock_vms()

        mock_lv_utils.lv_check.side_effect = self._only_root_exists

        ss.push_states(self.run_params, self.env)
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm1', 'current_state', 'launch')

        # test push disabled for root/boot states
        self.run_params["push_state_vm1"] = "root"
        ss.push_states(self.run_params, self.env)
        mock_lv_utils.assert_not_called()
        self.run_params["push_state_vm1"] = "boot"
        ss.push_states(self.run_params, self.env)
        mock_lv_utils.assert_not_called()

    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_pop_image(self, mock_lv_utils):
        """Test that popping with an image state backend works."""
        self._set_image_lvm_params()
        self.run_params["pop_state_images_vm1"] = "launch"
        self.run_params["image_name_vm1"] = "vm1/image"
        self.run_params["image_raw_device_vm1"] = "no"
        self._create_mock_vms()

        mock_lv_utils.lv_check.return_value = True
        self.mock_vms["vm1"].is_alive.return_value = False

        ss.pop_states(self.run_params, self.env)

        mock_lv_utils.lv_check.assert_called_with("disk_vm1", "launch")
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
    def test_pop_vm(self, mock_process):
        """Test that popping with a vm state backend works."""
        self._set_vm_qcow2_params()
        self.run_params["pop_state_vms_vm1"] = "launch"
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
        """Test that checking various states of multiple vms works."""
        self._set_image_lvm_params()
        self._set_vm_qcow2_params()
        self.run_params["vms"] = "vm1 vm2"
        self.run_params["check_state_images"] = "launch"
        self.run_params["check_state_images_vm2"] = "launcher"
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
        """Test that getting various states of multiple vms works."""
        self._set_image_lvm_params()
        self._set_vm_qcow2_params()
        self.run_params["vms"] = "vm1 vm2 vm3"
        self.run_params["get_state_images"] = "launch2"
        self.run_params["get_state_images_vm1"] = "launch1"
        self.run_params["get_state_vms_vm3"] = "launch3"
        self.run_params["get_mode_vm1"] = "rx"
        self.run_params["get_mode"] = "ii"
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
        mock_process.system_output.return_value = b"5         launch3         684 MiB 2021-01-18 21:24:22   00:00:44.478"
        self.mock_vms["vm1"].is_alive.return_value = False
        self.mock_vms["vm3"].is_alive.return_value = True

        ss.get_states(self.run_params, self.env)

        expected = [mock.call("disk_vm1", "LogVol"),
                    mock.call("disk_vm1", "launch1"),
                    mock.call("disk_vm2", "LogVol"),
                    mock.call("disk_vm2", "launch2"),
                    mock.call("disk_vm3", "LogVol"),
                    mock.call("disk_vm3", "launch2")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected)
        self.mock_vms["vm3"].is_alive.assert_called_once_with()
        mock_process.system_output.assert_called_once_with("qemu-img snapshot -l /images/vm3/image.qcow2 -U")

    # TODO: LVM is not supposed to reach to QCOW2 but we have in-code TODO about it
    @mock.patch('avocado_i2n.states.setup.env_process', mock.Mock(return_value=0))
    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    @mock.patch('avocado_i2n.states.lvm.process')
    def test_set_multivm(self, mock_process, mock_lv_utils, _mock_qcow2_process):
        """Test that setting various states of multiple vms works."""
        self._set_image_lvm_params()
        self.run_params["vms"] = "vm2 vm3 vm4"
        self.run_params["set_state_images"] = "launch2"
        self.run_params["set_state_images_vm2"] = "launch2"
        self.run_params["set_state_images_vm3"] = "root"
        self.run_params["set_state_images_vm4"] = "launch4"
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
        self.run_params["image_format"] = "raw"
        self.run_params["disk_sparse_filename_vm3"] = "virtual_hdd_vm3"
        self.run_params["use_tmpfs"] = "yes"
        self.run_params["disk_basedir"] = "/tmp"
        self.run_params["disk_vg_size"] = "40000"
        self.run_params["skip_types"] = "nets/vms"
        self._create_mock_vms()
        self.exist_switch = False

        def lv_check_side_effect(_vgname, lvname):
            return True if lvname in ["LogVol", "launch2"] else False if lvname == "launch4" else False
        mock_lv_utils.lv_check.side_effect = lv_check_side_effect
        mock_lv_utils.vg_check.return_value = False
        mock_process.run.return_value = process.CmdResult("dummy-command")

        with self.assertRaises(exceptions.TestAbortError):
            ss.set_states(self.run_params, self.env)

        expected = [mock.call("disk_vm2", "LogVol"),
                    mock.call("disk_vm2", "launch2"),
                    mock.call("disk_vm3", "LogVol"),
                    mock.call("disk_vm4", "LogVol"),
                    mock.call("disk_vm4", "launch4")]
        self.assertListEqual(mock_lv_utils.lv_check.call_args_list, expected)
        mock_process.run.assert_called_with('vgcreate disk_vm3 ', sudo=True)
        mock_lv_utils.lv_create.assert_called_once_with('disk_vm3', 'LogVol', '30G', pool_name='thin_pool', pool_size='30G')
        mock_lv_utils.lv_take_snapshot.assert_called_once_with('disk_vm3', 'LogVol', 'current_state')

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.lvm.lv_utils')
    def test_unset_multivm(self, mock_lv_utils, _mock_process):
        """Test that unsetting various states of multiple vms works."""
        self._set_image_lvm_params()
        self.run_params["vms"] = "vm1 vm4"
        self.run_params["unset_state_images_vm1"] = "root"
        self.run_params["unset_state_images_vm4"] = "launch4"
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
        """Test that QCOW2 format filter for the QCOW2 backends."""
        self._set_image_qcow2_params()
        self._create_mock_vms()

        self.mock_vms["vm1"].is_alive.return_value = False

        for do in ["check", "get", "set", "unset"]:
            self.run_params[f"{do}_state_images"] = "launch"

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
                self.run_params[f"{do}_state"] = "launch"
                with self.assertRaises(ValueError):
                    ss.BACKENDS["qcow2"]().__getattribute__(do)(self.run_params, self.env)
                    ss.BACKENDS["qcow2vt"]().__getattribute__(do)(self.run_params, self.env)
                del self.run_params[f"{do}_state"]
                mock_process.run.assert_not_called()
                self.mock_vms["vm1"].assert_not_called()

    @mock.patch('avocado_i2n.states.qcow2.process')
    @mock.patch('avocado_i2n.states.qcow2.os.path.isfile')
    def test_qcow2_convert(self, mock_isfile, mock_process):
        """Test auxiliary qcow2 module conversion functionality."""
        self._set_image_qcow2_params()
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
        """Test auxiliary pool module locks functionality."""
        self._set_image_pool_params()
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

    @mock.patch('avocado_i2n.states.qcow2.process')
    def test_skip_type(self, mock_process):
        """Test that QCOW2 format filter for the QCOW2 backends."""
        self._set_image_qcow2_params()
        self._set_vm_qcow2_params()
        self._create_mock_vms()

        for do in ["check", "get", "set", "unset"]:
            self.run_params[f"{do}_state"] = "launch"
            self.run_params["skip_types"] = "nets nets/vms nets/vms/images"

            mock_process.reset_mock()
            mock_process.system_output.return_value = b"NOT HERE"
            ss.__dict__[f"{do}_states"](self.run_params, self.env)
            mock_process.run.assert_not_called()
            self.mock_vms["vm1"].assert_not_called()


if __name__ == '__main__':
    unittest.main()
