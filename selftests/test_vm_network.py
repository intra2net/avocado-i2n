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


class VMNetworkTest(unittest.TestCase):

    def setUp(self):
        self.vmnet = mock.MagicMock()
        self.run_params = utils_params.Params()
        self.run_params["vms"] = "vm1 vm2"
        self.run_params["nics"] = "b1 b2"
        self.run_params["nic_roles"] = "internet_nic lan_nic"
        self.run_params["internet_nic"] = "b1"
        self.run_params["lan_nic"] = "b2"
        self.run_params["mac"] = "00:00:00:00:00:00"
        self.run_params["netmask_b1"] = "255.255.0.0"
        self.run_params["netmask_b2"] = "255.255.0.0"
        self.run_params["ip_b1_vm1"] = "10.1.1.1"
        self.run_params["ip_b2_vm1"] = "172.17.1.1"
        self.run_params["ip_b1_vm2"] = "10.2.1.1"
        self.run_params["ip_b2_vm2"] = "172.18.1.1"

        self.env = mock.MagicMock(name='env')
        self.env.get_vm = mock.MagicMock(side_effect=self._get_mock_vm)

        self.mock_vms = {}

        # inline class definition and instantiation
        self.test = type('obj', (object,), {'outputdir': ''})()

    def _get_mock_vm(self, vm_name):
        return self.mock_vms[vm_name]

    def _create_mock_vms(self):
        for vm_name in self.run_params.objects("vms"):
            self.mock_vms[vm_name] = mock.MagicMock(name=vm_name)
            self.mock_vms[vm_name].name = vm_name
            self.mock_vms[vm_name].params = self.run_params.object_params(vm_name)

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
        self.assertEqual(tunnel.left_params['vpnconn_peer_ip'], '10.2.1.1')
        self.assertEqual(tunnel.right_params['vpnconn_peer_ip'], '10.1.1.1')
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

        self.assertEqual(tunnel1.left_params['vpnconn_peer_ip'], '10.2.1.1')
        self.assertEqual(tunnel1.right_params['vpnconn_peer_ip'], '10.1.1.1')
        self.assertEqual(tunnel2.left_params['vpnconn_peer_ip'], '10.3.1.1')
        self.assertEqual(tunnel1.right_params['vpnconn_peer_ip'], '10.1.1.1')
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


if __name__ == '__main__':
    unittest.main()
