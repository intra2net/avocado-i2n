#!/usr/bin/env python

import unittest
import unittest.mock as mock
import shutil
import re

from avocado.core import exceptions
from virttest import utils_params

#import unittest_importer
from avocado_i2n import vmnet
from avocado_i2n.vmnet import VMNetwork


@mock.patch.object(VMNetwork, 'ping', lambda *args, **kwargs: (0, "\n\n\n\n"))
@mock.patch.object(VMNetwork, 'port_connectivity', lambda *args, **kwargs: (1, ""))
@mock.patch.object(VMNetwork, 'https_connectivity', lambda *args, **kwargs: (0, "HTML"))
@mock.patch.object(VMNetwork, 'ftp_connectivity', lambda *args, **kwargs: (0, "hi"))
@mock.patch.object(VMNetwork, 'tftp_connectivity', lambda *args, **kwargs: (0, "hi"))
class VMNetworkTest(unittest.TestCase):

    def setUp(self):
        self.vmnet = mock.MagicMock()
        self.run_params = utils_params.Params()
        self.run_params["vms"] = "vm1 vm2"
        self.run_params["roles"] = "node1 node2"
        self.run_params["node1"] = "vm1"
        self.run_params["node2"] = "vm2"
        self.run_params["nics"] = "b1 b2"
        self.run_params["nic_roles"] = "internet_nic lan_nic"
        self.run_params["internet_nic"] = "b1"
        self.run_params["lan_nic"] = "b2"
        self.run_params["mac"] = "00:00:00:00:00:00"
        self.run_params["netmask_b1"] = "255.255.0.0"
        self.run_params["netmask_b2"] = "255.255.0.0"
        self.run_params["ip_b1_vm1"] = "10.1.0.1"
        self.run_params["ip_b2_vm1"] = "172.17.0.1"
        self.run_params["ip_b1_vm2"] = "10.2.0.1"
        self.run_params["ip_b2_vm2"] = "172.18.0.1"
        self.run_params["netdst_b1_vm1"] = "virbr0"
        self.run_params["netdst_b2_vm1"] = "virbr1"
        self.run_params["netdst_b1_vm2"] = "virbr2"
        self.run_params["netdst_b2_vm2"] = "virbr3"

        self.env = mock.MagicMock(name='env')
        self.env.get_vm = mock.MagicMock(side_effect=self._get_mock_vm)
        self.env.create_vm = mock.MagicMock(side_effect=self._create_mock_vm)

        self.mock_vms = {}

        # inline class definition and instantiation
        self.test = type('obj', (object,), {'outputdir': '', 'bindir': ''})()

    def _get_mock_vm(self, vm_name):
        return None if vm_name not in self.mock_vms else self.mock_vms[vm_name]

    def _create_mock_vm(self, vm_type, target, vm_name, vm_params, bindir):
        self.mock_vms[vm_name] = mock.MagicMock(name=vm_name)
        self.mock_vms[vm_name].name = vm_name
        self.mock_vms[vm_name].params = vm_params
        return self.mock_vms[vm_name]

    def _create_mock_vms(self):
        for vm_name in self.run_params.objects("vms"):
            self._create_mock_vm("qemu", None, vm_name,
                                 self.run_params.object_params(vm_name), "")

    def test_representation(self):
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        repr = str(self.vmnet)
        self.assertIn("[vmnet]", repr)
        self.assertIn("[node]", repr)
        self.assertIn("[iface]", repr)
        self.assertIn("[net]", repr)

    def test_get_vms(self):
        self.run_params["vms"] = "vm1"
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        vm = self.vmnet.get_single_vm()
        self.assertEqual(vm.name, "vm1")
        vm, session = self.vmnet.get_single_vm_with_session()
        self.assertEqual(vm.name, "vm1")
        self.assertEqual(vm.session, session)
        self.vmnet.nodes["vm1"].last_session = None
        vm, session, params = self.vmnet.get_single_vm_with_session_and_params()
        self.assertEqual(vm.name, "vm1")
        self.assertEqual(vm.session, session)
        self.assertEqual(vm.params, params)

        self.run_params["vms"] = "vm1 vm2"
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        with self.assertRaises(exceptions.TestError):
            self.vmnet.get_single_vm()
        vm1, vm2 = self.vmnet.get_ordered_vms()
        self.assertEqual(vm1.name, "vm1")
        self.assertEqual(vm2.name, "vm2")
        vm1, vm2 = self.vmnet.get_ordered_vms(2)
        self.assertEqual(vm1.name, "vm1")
        self.assertEqual(vm2.name, "vm2")
        with self.assertRaises(exceptions.TestError):
            vm1 = self.vmnet.get_ordered_vms(1)
        vms = self.vmnet.get_vms()
        vm1, vm2 = vms.node1, vms.node2
        self.assertEqual(vm1.name, "vm1")
        self.assertEqual(vm2.name, "vm2")
        self.vmnet.params["roles"] = "node1 node2 node3"
        self.vmnet.params["node2"] = None
        with self.assertRaises(exceptions.TestError):
            self.vmnet.get_vms()

    def test_integrate_node(self):
        # repeated vm node in the net
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        node1 = self.vmnet.nodes["vm1"]
        with self.assertRaises(AssertionError):
            self.vmnet.integrate_node(node1)

        # already initialized interfaces
        self.run_params["vms"] = "vm2"
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        with self.assertRaises(AssertionError):
            self.vmnet.integrate_node(node1)

        # correct case (ininitialized vm node interfaces)
        node1.interfaces = {}
        self.vmnet.integrate_node(node1)

        # repeated address in the netconfig
        self.run_params["ip_b1_vm2"] = "10.1.0.1"
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        node1.interfaces = {}
        with self.assertRaises(IndexError):
            self.vmnet.integrate_node(node1)

    def test_reattach_interface(self):
        self._create_mock_vms()
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        client, server = self.vmnet.get_vms()
        self.vmnet.reattach_interface(client, server)

    @mock.patch('avocado_i2n.vmnet.network.os.rename', mock.Mock(return_value=0))
    @mock.patch('avocado_i2n.vmnet.network.process', mock.Mock())
    @mock.patch('avocado_i2n.vmnet.network.utils_net')
    def test_host_networking(self, utils_net):
        self.run_params["ip_provider_b1_vm1"] = "10.1.0.254"
        self.run_params["host_b1_vm1"] = "10.1.0.254"
        self.run_params["host_set_bridge_b1_vm1"] = "yes"
        self.run_params["permanent_netdst_b1_vm1"] = "no"
        self.run_params["host_services_b1_vm1"] = "yes"
        self._create_mock_vms()

        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        vmnet.network.DNSMASQ_CONFIG = "avocado.conf"
        vmnet.network.DNSMASQ_HOSTS = "avocado-hosts.conf"
        self.vmnet.setup_host_services()
        utils_net.find_bridge_manager.get_structure.return_value = ["virbr0", "virbr2"]
        self.vmnet.setup_host_bridges()
        utils_net.find_bridge_manager.return_value = None
        self.vmnet.setup_host_bridges()

    def test_spawn_clients(self):
        self._create_mock_vms()
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)

        with self.assertRaises(NotImplementedError):
            self.vmnet.spawn_clients("vm1", 1)

        self.vmnet._register_client_at_server = mock.MagicMock()
        self.vmnet.spawn_clients("vm1", 1)

    def test_change_network_address(self):
        self.run_params["os_type"] = "windows"
        self._create_mock_vms()
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        netconfig = self.vmnet.netconfigs["10.1.0.0"]
        self.vmnet.change_network_address(netconfig, "10.3.0.1")

    def test_set_static_address(self):
        self.run_params["os_type"] = "windows"
        self._create_mock_vms()
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        client, server = self.vmnet.get_vms()
        self.vmnet.set_static_address(client, server)

    def test_configure_tunnel_between_vms_basic(self):
        self._create_mock_vms()
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        self.vmnet.configure_tunnel_between_vms("vpn1", self.mock_vms["vm1"], self.mock_vms["vm2"],
                                                local1={"type": "nic", "nic": "lan_nic"},
                                                remote1={"type": "custom", "nic": "lan_nic"},
                                                peer1={"type": "ip", "nic": "internet_nic"},
                                                auth=None)
        tunnel = self.vmnet.tunnels["vpn1"]

        # tunnel types
        self.assertEqual(tunnel.left_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel.right_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel.left_params['vpnconn_lan_type'], 'NIC')
        self.assertEqual(tunnel.right_params['vpnconn_lan_type'], 'NIC')
        self.assertEqual(tunnel.left_params['vpnconn_remote_type'], 'CUSTOM')
        self.assertEqual(tunnel.right_params['vpnconn_remote_type'], 'CUSTOM')
        self.assertEqual(tunnel.left_params['vpnconn_peer_type'], 'IP')
        self.assertEqual(tunnel.right_params['vpnconn_peer_type'], 'IP')

        # tunnel end points/sites
        self.assertEqual(tunnel.left_params['vpnconn_remote_net'], '172.18.0.0')
        self.assertEqual(tunnel.right_params['vpnconn_remote_net'], '172.17.0.0')
        self.assertEqual(tunnel.left_params['vpnconn_remote_netmask'], '255.255.0.0')
        self.assertEqual(tunnel.right_params['vpnconn_remote_netmask'], '255.255.0.0')
        self.assertEqual(tunnel.left_params['vpnconn_peer_ip'], '10.2.0.1')
        self.assertEqual(tunnel.right_params['vpnconn_peer_ip'], '10.1.0.1')
        self.assertEqual(tunnel.left_params['vpnconn_activation'], 'ALWAYS')
        self.assertEqual(tunnel.right_params['vpnconn_activation'], 'ALWAYS')

        # authentication
        self.assertEqual(tunnel.left_params['vpnconn_key_type'], 'NONE')
        self.assertEqual(tunnel.right_params['vpnconn_key_type'], 'NONE')

    @mock.patch.object(vmnet.VMTunnel, 'configure_on_endpoint', mock.MagicMock())
    def test_configure_tunnel_between_vms_internetip(self):
        self._create_mock_vms()
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        self.vmnet.configure_tunnel_between_vms("vpn1", self.mock_vms["vm1"], self.mock_vms["vm2"],
                                                local1={"type": "internetip"},
                                                remote1={"type": "custom", "nic": "lan_nic"},
                                                peer1={"type": "ip", "nic": "internet_nic"},
                                                auth=None)
        tunnel = self.vmnet.tunnels["vpn1"]

        self.assertEqual(tunnel.left_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel.right_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel.left_params['vpnconn_lan_type'], 'INTERNETIP')
        self.assertEqual(tunnel.right_params['vpnconn_lan_type'], 'NIC')
        self.assertEqual(tunnel.left_params['vpnconn_remote_type'], 'CUSTOM')
        self.assertEqual(tunnel.right_params['vpnconn_remote_type'], 'EXTERNALIP')
        self.assertEqual(tunnel.left_params['vpnconn_peer_type'], 'IP')
        self.assertEqual(tunnel.right_params['vpnconn_peer_type'], 'IP')

    @mock.patch.object(vmnet.VMTunnel, 'configure_on_endpoint', mock.MagicMock())
    def test_configure_tunnel_between_vms_externalip(self):
        self._create_mock_vms()
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        self.vmnet.configure_tunnel_between_vms("vpn1", self.mock_vms["vm1"], self.mock_vms["vm2"],
                                                local1={"type": "nic", "nic": "lan_nic"},
                                                remote1={"type": "externalip"},
                                                peer1={"type": "ip", "nic": "internet_nic"},
                                                auth=None)
        tunnel = self.vmnet.tunnels["vpn1"]

        self.assertEqual(tunnel.left_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel.right_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel.left_params['vpnconn_lan_type'], 'NIC')
        self.assertEqual(tunnel.right_params['vpnconn_lan_type'], 'INTERNETIP')
        self.assertEqual(tunnel.left_params['vpnconn_remote_type'], 'EXTERNALIP')
        self.assertEqual(tunnel.right_params['vpnconn_remote_type'], 'CUSTOM')
        self.assertEqual(tunnel.left_params['vpnconn_peer_type'], 'IP')
        self.assertEqual(tunnel.right_params['vpnconn_peer_type'], 'IP')

    @mock.patch.object(vmnet.VMTunnel, 'configure_on_endpoint', mock.MagicMock())
    def test_configure_tunnel_between_vms_dynip(self):
        self._create_mock_vms()
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        self.vmnet.configure_tunnel_between_vms("vpn1", self.mock_vms["vm1"], self.mock_vms["vm2"],
                                                local1={"type": "nic", "nic": "lan_nic"},
                                                remote1={"type": "custom", "nic": "lan_nic"},
                                                peer1={"type": "dynip", "nic": "internet_nic"},
                                                auth=None)
        tunnel = self.vmnet.tunnels["vpn1"]

        self.assertEqual(tunnel.left_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel.right_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel.left_params['vpnconn_lan_type'], 'NIC')
        self.assertEqual(tunnel.right_params['vpnconn_lan_type'], 'NIC')
        self.assertEqual(tunnel.left_params['vpnconn_remote_type'], 'CUSTOM')
        self.assertEqual(tunnel.right_params['vpnconn_remote_type'], 'CUSTOM')
        self.assertEqual(tunnel.left_params['vpnconn_peer_type'], 'DYNIP')
        self.assertEqual(tunnel.right_params['vpnconn_peer_type'], 'IP')

    def test_configure_tunnel_between_vms_psk_basic(self):
        self._create_mock_vms()
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        self.vmnet.configure_tunnel_between_vms("vpn1", self.mock_vms["vm1"], self.mock_vms["vm2"],
                                                local1={"type": "nic", "nic": "lan_nic"},
                                                remote1={"type": "custom", "nic": "lan_nic"},
                                                peer1={"type": "ip", "nic": "internet_nic"},
                                                auth={"type": "psk", "psk": "the secret",
                                                      "left_id": "arnold@vm1", "right_id": "arnold@vm2"})
        tunnel = self.vmnet.tunnels["vpn1"]

        self.assertEqual(tunnel.left_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel.right_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel.left_params['vpnconn_key_type'], 'PSK')
        self.assertEqual(tunnel.right_params['vpnconn_key_type'], 'PSK')
        self.assertEqual(tunnel.left_params['vpnconn_psk'], 'the secret')
        self.assertEqual(tunnel.right_params['vpnconn_psk'], 'the secret')
        self.assertEqual(tunnel.left_params['vpnconn_psk_own_id'], 'arnold@vm1')
        self.assertEqual(tunnel.right_params['vpnconn_psk_own_id'], 'arnold@vm2')
        self.assertEqual(tunnel.left_params['vpnconn_psk_own_id_type'], 'CUSTOM')
        self.assertEqual(tunnel.right_params['vpnconn_psk_own_id_type'], 'CUSTOM')
        self.assertEqual(tunnel.left_params['vpnconn_psk_foreign_id'], 'arnold@vm2')
        self.assertEqual(tunnel.right_params['vpnconn_psk_foreign_id'], 'arnold@vm1')
        self.assertEqual(tunnel.left_params['vpnconn_psk_foreign_id_type'], 'CUSTOM')
        self.assertEqual(tunnel.right_params['vpnconn_psk_foreign_id_type'], 'CUSTOM')

    def test_configure_tunnel_between_vms_psk_ip(self):
        self._create_mock_vms()
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        self.vmnet.configure_tunnel_between_vms("vpn1", self.mock_vms["vm1"], self.mock_vms["vm2"],
                                                local1={"type": "nic", "nic": "lan_nic"},
                                                remote1={"type": "custom", "nic": "lan_nic"},
                                                peer1={"type": "ip", "nic": "internet_nic"},
                                                auth={"type": "psk", "psk": "the secret",
                                                      "left_id": "", "right_id": ""})
        tunnel = self.vmnet.tunnels["vpn1"]

        self.assertEqual(tunnel.left_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel.right_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel.left_params['vpnconn_key_type'], 'PSK')
        self.assertEqual(tunnel.right_params['vpnconn_key_type'], 'PSK')
        self.assertEqual(tunnel.left_params['vpnconn_psk'], 'the secret')
        self.assertEqual(tunnel.right_params['vpnconn_psk'], 'the secret')
        self.assertEqual(tunnel.left_params['vpnconn_psk_own_id'], '')
        self.assertEqual(tunnel.right_params['vpnconn_psk_own_id'], '')
        self.assertEqual(tunnel.left_params['vpnconn_psk_own_id_type'], 'IP')
        self.assertEqual(tunnel.right_params['vpnconn_psk_own_id_type'], 'IP')
        self.assertEqual(tunnel.left_params['vpnconn_psk_foreign_id'], '')
        self.assertEqual(tunnel.right_params['vpnconn_psk_foreign_id'], '')
        self.assertEqual(tunnel.left_params['vpnconn_psk_foreign_id_type'], 'IP')
        self.assertEqual(tunnel.right_params['vpnconn_psk_foreign_id_type'], 'IP')

    def test_configure_tunnel_between_vms_pubkey(self):
        self._create_mock_vms()
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        try:
            self.vmnet.configure_tunnel_between_vms("vpn1", self.mock_vms["vm1"], self.mock_vms["vm2"],
                                                    local1={"type": "nic", "nic": "lan_nic"},
                                                    remote1={"type": "custom", "nic": "lan_nic"},
                                                    peer1={"type": "ip", "nic": "internet_nic"},
                                                    auth={"type": "pubkey"})
        except NotImplementedError:
            pass
        tunnel = self.vmnet.tunnels["vpn1"]

        self.assertEqual(tunnel.left_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel.right_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel.left_params['vpnconn_key_type'], 'PUBLIC')
        self.assertEqual(tunnel.right_params['vpnconn_key_type'], 'PUBLIC')

        self.assertEqual(tunnel.left_params['vpnconn_own_key_name'], 'sample-key')
        self.assertEqual(tunnel.right_params['vpnconn_foreign_key_name'], 'sample-key')

    @mock.patch.object(vmnet.VMTunnel, 'configure_on_endpoint', mock.MagicMock())
    def test_configure_vpn_route(self):
        self.run_params["vms"] += " vm3"
        self.run_params["ip_b1_vm3"] = "10.3.1.1"
        self.run_params["ip_b2_vm3"] = "172.19.1.1"

        self._create_mock_vms()
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        self.vmnet.configure_tunnel_between_vms("vpn1", self.mock_vms["vm1"], self.mock_vms["vm2"],
                                                local1={"type": "nic", "nic": "lan_nic"},
                                                remote1={"type": "custom", "nic": "lan_nic"},
                                                peer1={"type": "ip", "nic": "internet_nic"},
                                                auth=None)
        tunnel1 = self.vmnet.tunnels["vpn1"]
        self.vmnet.configure_tunnel_between_vms("vpn2", self.mock_vms["vm2"], self.mock_vms["vm3"],
                                                local1={"type": "nic", "nic": "lan_nic"},
                                                remote1={"type": "custom", "nic": "lan_nic"},
                                                peer1={"type": "ip", "nic": "internet_nic"},
                                                auth=None)
        tunnel2 = self.vmnet.tunnels["vpn2"]

        self.vmnet.configure_vpn_route([self.mock_vms["vm1"], self.mock_vms["vm2"], self.mock_vms["vm3"]],
                                       ["vpn1", "vpn2"],
                                        remote1={"type": "custom", "nic": "lan_nic"},
                                        peer1={"type": "ip", "nic": "internet_nic"},
                                        auth=None)
        route1 = self.vmnet.tunnels["vpn1fwd"]
        route2 = self.vmnet.tunnels["vpn2fwd"]

        self.assertEqual(tunnel1.left_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel1.right_params['vpnconn'], 'vpn1')
        self.assertEqual(tunnel2.left_params['vpnconn'], 'vpn2')
        self.assertEqual(tunnel2.right_params['vpnconn'], 'vpn2')
        self.assertEqual(route1.left_params['vpnconn'], 'vpn1fwd')
        self.assertEqual(route1.right_params['vpnconn'], 'vpn1fwd')
        self.assertEqual(route2.right_params['vpnconn'], 'vpn2fwd')
        self.assertEqual(route2.right_params['vpnconn'], 'vpn2fwd')

        self.assertEqual(route1.left_params['vpnconn_lan_type'], 'CUSTOM')
        self.assertEqual(route1.right_params['vpnconn_lan_type'], 'CUSTOM')
        self.assertEqual(route2.left_params['vpnconn_lan_type'], 'CUSTOM')
        self.assertEqual(route2.right_params['vpnconn_lan_type'], 'CUSTOM')

        self.assertEqual(route1.left_params['vpnconn_remote_type'],
                         tunnel1.left_params['vpnconn_remote_type'])
        self.assertEqual(route1.right_params['vpnconn_remote_type'],
                         tunnel1.right_params['vpnconn_remote_type'])
        self.assertEqual(route1.left_params['vpnconn_peer_type'],
                         tunnel1.left_params['vpnconn_peer_type'])
        self.assertEqual(route1.right_params['vpnconn_peer_type'],
                         tunnel1.right_params['vpnconn_peer_type'])

        self.assertEqual(route2.left_params['vpnconn_remote_type'],
                         tunnel2.left_params['vpnconn_remote_type'])
        self.assertEqual(route2.right_params['vpnconn_remote_type'],
                         tunnel2.right_params['vpnconn_remote_type'])
        self.assertEqual(route2.left_params['vpnconn_peer_type'],
                         tunnel2.left_params['vpnconn_peer_type'])
        self.assertEqual(route2.right_params['vpnconn_peer_type'],
                         tunnel2.right_params['vpnconn_peer_type'])

        self.assertEqual(tunnel1.right_params['vpnconn_remote_net'], '172.17.0.0')
        self.assertEqual(tunnel2.left_params['vpnconn_remote_net'], '172.19.0.0')
        self.assertEqual(tunnel1.left_params['vpnconn_remote_net'], '172.18.0.0')
        self.assertEqual(route1.left_params['vpnconn_remote_net'], '172.19.0.0')
        self.assertEqual(route1.right_params['vpnconn_remote_net'],
                         tunnel1.right_params['vpnconn_remote_net'])
        self.assertEqual(route2.right_params['vpnconn_remote_net'], '172.17.0.0')
        self.assertEqual(tunnel2.right_params['vpnconn_remote_net'], '172.18.0.0')
        self.assertEqual(route2.left_params['vpnconn_remote_net'],
                         tunnel2.left_params['vpnconn_remote_net'])

        self.assertEqual(tunnel1.left_params['vpnconn_peer_ip'], '10.2.0.1')
        self.assertEqual(tunnel1.right_params['vpnconn_peer_ip'], '10.1.0.1')
        self.assertEqual(tunnel2.left_params['vpnconn_peer_ip'], '10.3.1.1')
        self.assertEqual(tunnel1.right_params['vpnconn_peer_ip'], '10.1.0.1')
        self.assertEqual(route1.left_params['vpnconn_peer_ip'],
                         tunnel1.left_params['vpnconn_peer_ip'])
        self.assertEqual(route1.right_params['vpnconn_peer_ip'],
                         tunnel1.right_params['vpnconn_peer_ip'])
        self.assertEqual(route2.left_params['vpnconn_peer_ip'],
                         tunnel2.left_params['vpnconn_peer_ip'])
        self.assertEqual(route2.right_params['vpnconn_peer_ip'],
                         tunnel2.right_params['vpnconn_peer_ip'])

        self.assertEqual(route1.left_params['vpnconn_activation'],
                         tunnel1.left_params['vpnconn_activation'])
        self.assertEqual(route1.right_params['vpnconn_activation'],
                         tunnel1.right_params['vpnconn_activation'])
        self.assertEqual(route2.left_params['vpnconn_activation'],
                         tunnel2.left_params['vpnconn_activation'])
        self.assertEqual(route2.right_params['vpnconn_activation'],
                         tunnel2.right_params['vpnconn_activation'])

    def test_connectivity_validate(self):
        self._create_mock_vms()
        self.vmnet = VMNetwork(self.test, self.run_params, self.env)
        client, server = self.vmnet.get_vms()
        self.vmnet.reattach_interface(client, server)

        self.vmnet.ping_validate(client, server)

        # check both blocked and unclocked cases depending on what is easier
        self.vmnet.http_connectivity_validate(client, server, require_blocked=True)
        self.vmnet.https_connectivity_validate(client, server)
        self.vmnet.ssh_connectivity_validate(client, server, require_blocked=True)
        self.vmnet.ftp_connectivity_validate("hi", "path", client, server)
        self.vmnet.tftp_connectivity_validate("hi", "path", client, server)


if __name__ == '__main__':
    unittest.main()
