"""

SUMMARY
------------------------------------------------------
Tunnel object for the vmnet utility.

Copyright: Intra2net AG


CONTENTS
------------------------------------------------------
This class wraps up the utilities for managing tunnels.

The parameters parsed at each vm are used as overwrite dictionary and
and missing ones are generated for the full configuration of the tunnel.


INTERFACE
------------------------------------------------------

"""


import logging

from virttest import utils_params


class VMTunnel(object):
    """The tunnel class."""

    """Structural properties"""
    def left(self, value=None):
        """A reference to the left node of the tunnel."""
        if value is not None:
            self._left = value
        else:
            return self._left
    left = property(fget=left, fset=left)

    def right(self, value=None):
        """A reference to the right node of the tunnel."""
        if value is not None:
            self._right = value
        else:
            return self._right
    right = property(fget=right, fset=right)

    def left_net(self, value=None):
        """A reference to the left netconfig of the tunnel."""
        if value is not None:
            self._left_net = value
        else:
            return self._left_net
    left_net = property(fget=left_net, fset=left_net)

    def right_net(self, value=None):
        """A reference to the right netconfig of the tunnel."""
        if value is not None:
            self._right_net = value
        else:
            return self._right_net
    right_net = property(fget=right_net, fset=right_net)

    def left_params(self, value=None):
        """The tunnel generated left side parameters."""
        return self.left.params.object_params(self.name)
    left_params = property(fget=left_params)

    def right_params(self, value=None):
        """The tunnel generated right side parameters."""
        return self.right.params.object_params(self.name)
    right_params = property(fget=right_params)

    def params(self, value=None):
        """The tunnel generated test parameters."""
        if value is not None:
            self._params = value
        else:
            return self._params
    params = property(fget=params, fset=params)

    """Connection properties"""
    def name(self, value=None):
        """Name for the connection."""
        if value is not None:
            self._name = value
        else:
            return self._name
    name = property(fget=name, fset=name)

    def __init__(self, name, node1, node2, left_variant, psk_variant=None, modeconfig=False):
        """
        Construct the full set of required tunnel parameters for a given tunnel left variant
        that are not already defined in the parameters of the two vms (left `node1` with
        right `node2`).

        :param str name: name of the tunnel
        :param node1: left side node of the tunnel
        :type node1: VMNode object
        :param node2: right side node of the tunnel
        :type node2: VMNode object
        :param left_variant: left side configuration (right side is determined from it)
        :type left_variant: (str, str, str)
        :param psk_variant: PSK configuration in the case PSK is used
        :type psk_variant: (str, str, str)
        :param bool modeconfig: whether it is a ModeConfig connection

        The additional psk variant is used for a psk configuration.
        """
        params = utils_params.Params()
        right_variant = self._get_peer_variant(left_variant)
        logging.info("Preparing tunnel parameters for each of %s and %s", node1.name, node2.name)

        # main parameters
        params["vpnconn_%s_%s" % (name, node1.name)] = name
        params["vpnconn_%s_%s" % (name, node2.name)] = name
        params["vpn_side_%s_%s" % (name, node1.name)] = "left"
        params["vpn_side_%s_%s" % (name, node2.name)] = "right"
        params["vpnconn_lan_type_%s_%s" % (name, node1.name)] = left_variant[0].upper()
        params["vpnconn_lan_type_%s_%s" % (name, node2.name)] = right_variant[0].upper()
        params["vpnconn_remote_type_%s_%s" % (name, node1.name)] = left_variant[1].upper()
        params["vpnconn_remote_type_%s_%s" % (name, node2.name)] = right_variant[1].upper()

        netconfig1 = node1.interfaces["onic"].netconfig
        params["vpnconn_lan_net_%s_%s" % (name, node1.name)] = netconfig1.net_ip
        params["vpnconn_lan_netmask_%s_%s" % (name, node1.name)] = netconfig1.netmask
        params["vpnconn_remote_net_%s_%s" % (name, node2.name)] = netconfig1.net_ip
        params["vpnconn_remote_netmask_%s_%s" % (name, node2.name)] = netconfig1.netmask
        params["vpnconn_peer_type_%s_%s" % (name, node2.name)] = right_variant[2].upper()
        if modeconfig is False:
            netconfig2 = node2.interfaces["onic"].netconfig
            params["vpnconn_lan_net_%s_%s" % (name, node2.name)] = netconfig2.net_ip
            params["vpnconn_lan_netmask_%s_%s" % (name, node2.name)] = netconfig2.netmask
            params["vpnconn_remote_net_%s_%s" % (name, node1.name)] = netconfig2.net_ip
            params["vpnconn_remote_netmask_%s_%s" % (name, node1.name)] = netconfig2.netmask
        else:
            netconfig2 = None
            params["vpnconn_remote_modeconfig_ip_%s_%s" % (name, node1.name)] = "172.30.0.1"
        params["vpnconn_peer_type_%s_%s" % (name, node1.name)] = left_variant[2].upper()

        # psk parameters
        if psk_variant is None:
            params["vpnconn_key_type_%s" % name] = "PUBLIC"
        else:
            params["vpnconn_key_type_%s" % name] = "PSK"
            params["vpnconn_psk_%s" % name] = psk_variant[0]
            params["vpnconn_psk_foreign_id_%s_%s" % (name, node1.name)] = "arnold@%s" % node2.name
            params["vpnconn_psk_foreign_id_type_%s_%s" % (name, node1.name)] = psk_variant[1].upper()
            params["vpnconn_psk_own_id_%s_%s" % (name, node1.name)] = "arnold@%s" % node1.name
            params["vpnconn_psk_own_id_type_%s_%s" % (name, node1.name)] = psk_variant[2].upper()
            params["vpnconn_psk_foreign_id_%s_%s" % (name, node2.name)] = "arnold@%s" % node1.name
            params["vpnconn_psk_foreign_id_type_%s_%s" % (name, node2.name)] = psk_variant[2].upper()
            params["vpnconn_psk_own_id_%s_%s" % (name, node2.name)] = "arnold@%s" % node2.name
            params["vpnconn_psk_own_id_type_%s_%s" % (name, node2.name)] = psk_variant[1].upper()

        # additional roadwarrior parameters
        if left_variant[2] == "ip":
            params["vpnconn_peer_ip_%s_%s" % (name, node1.name)] = node2.interfaces["inic"].ip
            params["vpnconn_activation_%s_%s" % (name, node1.name)] = "ALWAYS"
        elif left_variant[2] == "dynip":
            params["vpnconn_activation_%s_%s" % (name, node1.name)] = "PASSIVE"
        if right_variant[2] == "ip":
            params["vpnconn_peer_ip_%s_%s" % (name, node2.name)] = node1.interfaces["inic"].ip
            params["vpnconn_activation_%s_%s" % (name, node2.name)] = "ALWAYS"
        elif right_variant[2] == "dynip":
            params["vpnconn_activation_%s_%s" % (name, node2.name)] = "PASSIVE"

        # overwrite the base vpn parameters with other already defined tunnel parameters
        params1 = params.object_params(node1.name)
        params2 = params.object_params(node2.name)
        params1.update(node1.params)
        params2.update(node2.params)
        node1.params = params1
        node2.params = params2

        self._params = params
        self._left = node1
        self._left_net = netconfig1
        self._right = node2
        self._right_net = netconfig2
        self._name = name

        logging.info("Produced tunnel from parameters is %s", self)

    def __repr__(self):
        left_net = "none" if self.left_net is None else self.left_net.net_ip
        right_net = "none" if self.right_net is None else self.right_net.net_ip
        tunnel_tuple = (self.name, self.left.name, self.right.name, left_net, right_net)
        return "[tunnel] name='%s', left='%s', right='%s', lnet='%s', rnet='%s'" % tunnel_tuple

    def connects_nodes(self, node1, node2):
        """
        Check whether a tunnel connects two vm nodes, i.e. they are in directly connected
        as tunnel peers or indirectly in tunnel connected LANs (netconfigs).

        :param node1: one side vm of the tunnel
        :type node1: VM node
        :param node2: another side vm of the tunnel
        :type node2: VM node
        :returns: whether the tunnel connects the two nodes
        :rtype: bool
        """
        if node1 == self.left or (self.left_net and node1.in_netconfig(self.left_net)):
            return node2 == self.right or (self.right_net and node2.in_netconfig(self.right_net))
        elif node1 == self.right or (self.right_net and node1.in_netconfig(self.right_net)):
            return node2 == self.left or (self.left_net and node2.in_netconfig(self.left_net))
        else:
            return False

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

    def configure_between_endpoints(self, vmnet, left_variant, psk_variant=None,
                                    apply_extra_options=None):
        """
        Build a tunnel between two endpoint vms.

        :param vmnet: the vm network simulating the internet
        :type vmnet: VMNetwork object
        :param left_variant: left side configuration (right side is determined from it)
        :type left_variant: (str, str, str)
        :param psk_variant: PSK configuration in the case PSK is used
        :type psk_variant: (str, str, str)
        :param apply_extra_options: extra switches to apply as key exchange, firewall ruleset, etc.
        :type apply_extra_options: {str, any}

        The left variant is a list of three parameters: `lan_type`, `remote_type`, `peer_type`.

        In addition, a psk variant can be specified (`psk`, `psk_foreign_id_type1`,
        `psk_foreign_id_type2`).
        """
        logging.info("Building a tunnel %s between %s and %s",
                     self.name, self.left.name, self.right.name)

        if psk_variant is None:
            self._import_key(self.left.platform, self.right.platform, vmnet)
            self._import_key(self.right.platform, self.left.platform, vmnet)

        self.configure_on_endpoint(self.left.platform, vmnet, apply_extra_options)
        self.configure_on_endpoint(self.right.platform, vmnet, apply_extra_options)

    def configure_on_endpoint(self, vm, vmnet, apply_extra_options=None):
        """
        Configure a tunnel on an endpoint virtual machine.

        :param vm: vm where the tunnel will be configured
        :type vm: VM object
        :param vmnet: the vm network simulating the internet
        :type vmnet: VMNetwork object
        :param apply_extra_options: extra switches to apply as key exchange, firewall ruleset, etc.
        :type apply_extra_options: {str, any}

        The provided virtual machine parameters will be used
        for configuration of the tunnel.

        The tunnel name can be used to also reconfigure an existing tunnel.
        """
        if not apply_extra_options:
            apply_extra_options = {}

        node = vmnet.nodes[vm.name]
        logging.info("Configuring tunnel %s on %s", self.name, node.name)
        if node == self.left:
            node_params = self.left_params
            other = self.right
            other_params = self.right_params
        elif node == self.right:
            node_params = self.right_params
            other = self.left
            other_params = self.left_params
        else:
            raise ValueError("The configured %s is not among the tunnel endpoints %s and %s",
                             node.name, self.left.name, self.right.name)
        vpnconn_parameters = {}
        for key in node_params.keys():
            if "vpnconn" in key:
                vpnconn_parameters[key] = node_params[key]

        local1 = vmnet.interfaces["%s.onic" % vm.name]
        local2 = vmnet.interfaces["%s.onic" % other.name]
        remote1 = vmnet.interfaces["%s.inic" % vm.name]
        remote2 = vmnet.interfaces["%s.inic" % other.name]
        ip1 = other_params.get("vpnconn_nat_peer_ip", remote1.ip)
        ip2 = vpnconn_parameters.get("vpnconn_nat_peer_ip", remote2.ip)

        add_cmd = "ip tunnel add %s mode gre remote %s local %s ttl 255"
        vm.session.cmd(add_cmd % (self.name, ip2, remote1.ip))
        vm.session.cmd("ip link set %s up" % self.name)
        vm.session.cmd("ip addr add %s dev %s" % (local1.ip, self.name))
        vm.session.cmd("ip route add %s/%s dev %s" % (local2.netconfig.net_ip,
                                                      local2.netconfig.mask_bit,
                                                      self.name))

        if apply_extra_options.get("apply_firewall_ruleset", True):
            # 47 stand for GRE (Generic Routing Encapsulation)
            protocol_id = apply_extra_options.get("tunnel_protocol_id", 47)
            if other_params.get("vpnconn_nat_peer_ip") is not None:
                vm.session.cmd("iptables -I INPUT -i eth1 -p %s -j ACCEPT" % protocol_id)
            vm.session.cmd("iptables -I INPUT -i %s -p icmp -j ACCEPT" % self.name)
            vm.session.cmd("iptables -I OUTPUT -o %s -p icmp -j ACCEPT" % self.name)

    def _import_key(self, from_vm, to_vm, vmnet):
        raise NotImplementedError("Need implementation for some OS")
