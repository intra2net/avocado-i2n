"""

SUMMARY
------------------------------------------------------
VPNConn object for the vmnet utility.

Copyright: Intra2net AG


CONTENTS
------------------------------------------------------
This class wraps up the utilities for managing vpn connections.

The parameters parsed at each vm are used as overwrite dictionary and
and missing ones are generated for the full configuration of the vpn
connection.


INTERFACE
------------------------------------------------------

"""


import logging

from virttest import utils_params


class VPNConn(object):
    """
    The vpnconn class - a connection object responsible
    for all VPN configuration.
    """

    """Structural vmnet properties"""
    def left(self, value=None):
        """A reference to the left vmnode of the tunnel."""
        if value is not None:
            self._left = value
        else:
            return self._left
    left = property(fget=left, fset=left)

    def right(self, value=None):
        """A reference to the right vmnode of the tunnel."""
        if value is not None:
            self._right = value
        else:
            return self._right
    right = property(fget=right, fset=right)

    def params(self, value=None):
        """The vpn generated test parameters."""
        if value is not None:
            self._params = value
        else:
            return self._params
    params = property(fget=params, fset=params)

    """Connection properties"""
    def name(self, value=None):
        """A proxy reference to the vm name."""
        if value is not None:
            self._name = value
        else:
            return self._name
    name = property(fget=name, fset=name)

    def __init__(self, name, vm1, vm2, vmnet, left_variant, psk_variant=None, roadwarrior=False):
        """
        Construct the full set of required vpn parameters for a given vpn left variant
        that are not already defined in the parameters of the two vms (left `vm1` with
        right `vm2`).

        :param str name: name of the VPN connection
        :param vm1: left side vm of the VPN tunnel
        :type vm1: VM object
        :param vm2: right side vm of the VPN tunnel
        :type vm2: VM object
        :param vmnet: the vm network simulating the internet
        :type vmnet: VMNetwork object
        :param left_variant: left side configuration (right side is determined from it)
        :type left_variant: (str, str, str)
        :param psk_variant: PSK configuration in the case PSK is used
        :type psk_variant: (str, str, str)
        :param bool roadwarrior: whether it is a roadwarrior connection

        The additional psk variant is used for a psk configuration.
        """
        vpnparams = utils_params.Params()
        right_variant = self._get_peer_variant(left_variant)
        logging.info("Preparing vpn connection parameters for each of %s and %s",
                     vm1.name, vm2.name)

        # main parameters
        vpnparams["vpnconn_%s_%s" % (name, vm1.name)] = name
        vpnparams["vpnconn_%s_%s" % (name, vm2.name)] = name
        vpnparams["vpn_side_%s_%s" % (name, vm1.name)] = "left"
        vpnparams["vpn_side_%s_%s" % (name, vm2.name)] = "right"
        vpnparams["vpnconn_lan_type_%s_%s" % (name, vm1.name)] = left_variant[0].upper()
        vpnparams["vpnconn_lan_type_%s_%s" % (name, vm2.name)] = right_variant[0].upper()
        vpnparams["vpnconn_remote_type_%s_%s" % (name, vm1.name)] = left_variant[1].upper()
        vpnparams["vpnconn_remote_type_%s_%s" % (name, vm2.name)] = right_variant[1].upper()

        netconfig1 = vmnet.interfaces["%s.onic" % vm1.name].netconfig
        vpnparams["vpnconn_remote_net_%s_%s" % (name, vm2.name)] = netconfig1.net_ip
        vpnparams["vpnconn_remote_netmask_%s_%s" % (name, vm2.name)] = netconfig1.netmask
        vpnparams["vpnconn_peer_type_%s_%s" % (name, vm2.name)] = right_variant[2].upper()
        # roadwarrior requires vm1 to be the server and vm2 the client (it is not symmetric)
        if roadwarrior is False:
            netconfig2 = vmnet.interfaces["%s.onic" % vm2.name].netconfig
            vpnparams["vpnconn_remote_net_%s_%s" % (name, vm1.name)] = netconfig2.net_ip
            vpnparams["vpnconn_remote_netmask_%s_%s" % (name, vm1.name)] = netconfig2.netmask
        else:
            vpnparams["vpnconn_remote_modeconfig_ip_%s_%s" % (name, vm1.name)] = "172.30.0.1"
        vpnparams["vpnconn_peer_type_%s_%s" % (name, vm1.name)] = left_variant[2].upper()

        # psk parameters
        if psk_variant is None:
            vpnparams["vpnconn_key_type_%s" % name] = "PUBLIC"
        else:
            vpnparams["vpnconn_key_type_%s" % name] = "PSK"
            vpnparams["vpnconn_psk_%s" % name] = psk_variant[0]
            vpnparams["vpnconn_psk_foreign_id_%s_%s" % (name, vm1.name)] = "arnold@%s" % vm2.name
            vpnparams["vpnconn_psk_foreign_id_type_%s_%s" % (name, vm1.name)] = psk_variant[1].upper()
            vpnparams["vpnconn_psk_own_id_%s_%s" % (name, vm1.name)] = "arnold@%s" % vm1.name
            vpnparams["vpnconn_psk_own_id_type_%s_%s" % (name, vm1.name)] = psk_variant[2].upper()
            vpnparams["vpnconn_psk_foreign_id_%s_%s" % (name, vm2.name)] = "arnold@%s" % vm1.name
            vpnparams["vpnconn_psk_foreign_id_type_%s_%s" % (name, vm2.name)] = psk_variant[2].upper()
            vpnparams["vpnconn_psk_own_id_%s_%s" % (name, vm2.name)] = "arnold@%s" % vm2.name
            vpnparams["vpnconn_psk_own_id_type_%s_%s" % (name, vm2.name)] = psk_variant[1].upper()

        self._params = vpnparams
        self._left = vm1
        self._right = vm2
        self._name = name

    def _get_peer_variant(self, left_variant):
        """
        Convert triple of parameters according to ipsec rules.

        Returns a triple of parameters for for the peer. Return
        default parameter where the left variant has used a more
        "exotic" value.
        """
        right_variant = ["nic", "custom", "ip"]
        if left_variant[0] == "nic":
            right_variant[1] = "custom"
        elif left_variant[0] == "internetip":
            right_variant[1] = "externalip"
        if left_variant[1] == "custom":
            right_variant[0] = "nic"
        elif left_variant[1] == "externalip":
            right_variant[0] = "internetip"
        if left_variant[2] == "dynip":
            right_variant[2] = "ip"
        elif left_variant[2] == "ip":
            right_variant[2] = "ip"
        return right_variant

    def configure_between_endpoints(self, vmnet, left_variant, psk_variant=None):
        """
        Build a vpn connection between two endpoint vms.

        :param vmnet: the vm network simulating the internet
        :type vmnet: VMNetwork object
        :param left_variant: left side configuration (right side is determined from it)
        :type left_variant: (str, str, str)
        :param psk_variant: PSK configuration in the case PSK is used
        :type psk_variant: (str, str, str)

        The left variant is a list of three parameters: `lan_type`, `remote_type`, `peer_type`.

        In addition, a psk variant can be specified (`psk`, `psk_foreign_id_type1`,
        `psk_foreign_id_type2`).
        """
        logging.info("Building vpn connection %s between %s and %s",
                     self.name, self.left.name, self.right.name)

        if psk_variant is None:
            self._import_key(self.left.platform, self.right.platform, vmnet)
            self._import_key(self.right.platform, self.left.platform, vmnet)

        # add all new vpn parameters to the already defined vm parameters
        # and throw away unnecessary parameters from this function
        vpnparams1 = self.params.object_params(self.left.name)
        vpnparams2 = self.params.object_params(self.right.name)
        vpnparams1.update(self.left.params)
        vpnparams2.update(self.right.params)
        self.left.params = vpnparams1
        self.right.params = vpnparams2

        self.configure_on_endpoint(self.left.platform, vmnet, False, False, True)
        self.configure_on_endpoint(self.right.platform, vmnet, False, False, True)

    def configure_on_endpoint(self, vm, vmnet):
        """
        Configure a vpn connection on an endopoint virtual machine.

        :param vm: vm where the VPN will be configured
        :type vm: VM object
        :param vmnet: the vm network simulating the internet
        :type vmnet: VMNetwork object

        The provided virtual machine parameters will be used
        for configuration of the vpn connection.

        The connection name can be used to also reconfigure an existing
        vpn connection.
        """
        raise NotImplementedError("Need implementation for some OS")

    def _import_key(self, from_vm, to_vm, vmnet):
        raise NotImplementedError("Need implementation for some OS")
