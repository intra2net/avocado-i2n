"""

SUMMARY
------------------------------------------------------
Utility to manage local networks of vms and various topologies.

Copyright: Intra2net AG


CONTENTS
------------------------------------------------------
The main class is the VMNetwork class and is used to perform all
network related configuration for each virt test (store all its
network information, offer all the network related services it
needs, etc.). It can be used to test Proxy, Port forwarding,
VPN, NAT, etc.

Each vm is a network node and can have one of few currently supported
operating systems. For some functionality it is also required to have
at least three nics, respectivaly named "lnic" for local isolated
connection to the host, "inic" for (internet) connection to the other
nodes, and "onic" for other connection to own LAN.

Ephemeral clients are based on RIP Linux and are temporary clients
created just for the duration of a test. An arbirary number of those
can be spawned depending on test requirements and available resources.

INTERFACE
------------------------------------------------------

"""

import os
import re
import time
import logging
import collections

from avocado.utils import process
from avocado.core import exceptions
from virttest import utils_net, utils_params
import aexpect

from .iface import Interface
from .node import VMNode
from .config import Netconfig
from .vpn import VPNConn


class VMNetwork(object):
    """
    Any VMNetwork instance can be used to connect vms in various network topologies
    and to reconfigure, ping, retrieve the session of, as well as spawn clients for
    each of them.
    """

    def __init__(self, test, params, env):
        """
        Construct a network data structure given the test parameters,
        the `env` and the `test` instance.

        .. note:: The params attribute is just a shallow copy to preserve the hierarchy:
            network level params = test level params -> vmnode level params = test object params
            -> interface level params = rarely used outside of the vm network
        """
        self.params = params
        self.env = env
        self.test = test

        # component types (could be replaced with extended ones)
        self.new_vmnode = VMNode
        self.new_interface = Interface
        self.new_netconfig = Netconfig
        self.new_vpnconn = VPNConn

        # component instances
        self.vmnodes = {}
        self.interfaces = {}
        self.netconfigs = {}
        self.tunnels = {}

        for vm_name in params.objects("vms"):

            # NOTE: since the vmnet can be used outside of a test, the existence
            # of the vm object is not guaranteed as well as the updated version
            # of its parameters
            vm = env.get_vm(vm_name)
            vm_params = params.object_params(vm_name)
            if vm is None:
                vm = env.create_vm(params.get('vm_type'), params.get('target'),
                                   vm_name, vm_params, test.bindir)
            else:
                vm.params = vm_params

            self.vmnodes[vm_name] = self.new_vmnode(vm)
            self.integrate_vmnode(self.vmnodes[vm_name])
        logging.debug("Constructed network configuration:\n%s", self)

    def __repr__(self):
        dump = "[vmnet] netconfigs='%s'" % len(self.netconfigs.keys())
        for netconfig in self.netconfigs.values():
            dump = "%s\n\t%s" % (dump, str(netconfig))
            for iface in netconfig.interfaces.values():
                dump = "%s\n\t\t%s -> %s" % (dump, str(iface), str(iface.vmnode))
        return dump

    def start_all_sessions(self):
        """Start a session to each of the vm nodes."""
        for vmnode in self.vmnodes.values():
            vmnode.get_session()

    """VM node retrieval methods"""
    def _get_single_vmnode(self):
        """Get the only vm node in the network and raise error if it is not the only one."""
        if len(self.vmnodes.values()) != 1:
            raise exceptions.TestError("A multi-vm network was thought of as a single-vm network")
        else:
            return list(self.vmnodes.values())[0]

    def get_single_vm(self):
        """
        Get the only vm in the network.

        :returns: only vm in the network
        :rtype: VM object
        """
        vmnode = self._get_single_vmnode()
        return vmnode.platform

    def get_single_vm_with_session(self):
        """
        Get the only vm in the network and its only session.

        :returns: vm and its last session
        :rtype: (VM object, Session object)
        """
        vmnode = self._get_single_vmnode()
        if vmnode.last_session is None:
            self.start_all_sessions()
        return (vmnode.platform, vmnode.last_session)

    def get_ordered_vms(self, vm_num=None):
        """
        Get all N (``=vm_num``) vms in the network ordered by their name.

        :param int vm_num: number N of vms
        :returns: ordered vms
        :rtype: (VM object)
        :raises: :py:class:`exceptions.TestError` if # of vms != N
        """
        if vm_num is not None and len(self.vmnodes.values()) != vm_num:
            raise exceptions.TestError("The vm network was expected to have %s vms while "
                                       "it has %s" % (vm_num, len(self.vmnodes.values())))
        else:
            vms = []
            for key in sorted(self.vmnodes.keys()):
                vms.append(self.vmnodes[key].platform)
            return tuple(vms)

    def get_vms(self):
        """
        Get a named tuple of vms in the network with their parametrically
        defined roles.

        :returns: tuple t with t.client = <vm1 object> and t.server = <vm2 object>
        :rtype: named tuple
        :raises: :py:class:`exceptions.TestError` if some roles don't have assigned vms

        This is the main and most recommended vm retrieval method.

        Example Cartesian configuration::

            roles = "client server"
            client = "vm1"
            server = "vm2"
        """
        roles = {}
        for role in self.params.objects("roles"):
            roles[role] = self.params.get(role)
            if role is None:
                raise exceptions.TestError("No vm assigned to the role %s" % role)
        logging.debug("Roles for vms: %s", roles)

        # NOTE: fix the keys order to a particular order
        role_keys = roles.keys()
        role_tuple = collections.namedtuple("role_tuple", role_keys, verbose=False)
        role_platforms = [self.vmnodes[roles[key]].platform for key in role_keys]
        return role_tuple(*role_platforms)

    """VM network modification methods"""
    def integrate_vmnode(self, vmnode):
        """
        Add all interfaces and netconfigs resulting from a new vm node
        into the vm net, thus integrating the configuration into
        the available one.

        :param vmnode: vm node to be integrated into the vmnet
        :type vmnode: VMNode object
        """
        logging.debug("Generating all interfaces for %s", vmnode.name)
        def get_interfaces(node):
            """
            Generate new interfaces from the vm restricted parameters
            that can be retrieved from the platform.

            :returns: interfaces of the vm node
            :rtype: {str, :py:class:`Interface`}
            """
            for nic_name in node.platform.params.objects("nics"):
                nic_params = node.platform.params.object_params(nic_name)
                node.interfaces[nic_name] = self.new_interface(nic_params)
            return node.interfaces
        get_interfaces(vmnode)
        for nic_name in vmnode.interfaces.keys():
            ikey = "%s.%s" % (vmnode.name, nic_name)
            self.interfaces[ikey] = vmnode.interfaces[nic_name]
            self.interfaces[ikey].vmnode = vmnode
            logging.debug('Generated interface {0}: {1}'.format(ikey, self.interfaces[ikey]))

        logging.debug("Generating all netconfigs for %s", vmnode.name)
        for interface in vmnode.interfaces.values():
            interface_attached = False
            logging.debug("Generating netconfigs for interface {0}".format(interface))
            for netconfig in self.netconfigs.values():
                if netconfig.can_add(interface):
                    logging.debug("Adding interface {0}".format(interface))
                    netconfig.add_interface(interface)
                    interface_attached = True
                    break
            if not interface_attached:
                logging.debug("Attaching interface {0}".format(interface))
                netconfig = self.new_netconfig()
                netconfig.from_interface(interface)
                netconfig.add_interface(interface)
                self.netconfigs[netconfig.net_ip] = netconfig

    def reattach_interface(self, client, server,
                           client_nic="inic", server_nic="onic",
                           proxy_nic=""):
        """
        Reconfigure a network interface of a vm reattaching it to a different
        interface's network config.

        :param client: vm whose interace will be rattached
        :type client: VM object
        :param server: vm whose network will the interface be attached to
        :type server: VM object
        :param str client_nic: name of the nic of the client
        :param str server_nic: name of the nic of the server
        :param str proxy_nic: name of a proxyARP nic of the server

        If the `proxy_nic` is defined and the second interface (`server_nic`) is
        different than the `proxy_nic` value, it is assumed to be and turned
        into a proxyarp interface whose responses are provided by the actual
        interface defined in the `proxy_nic` parameter.

        Any processing related to the vm or the netconfig's servers
        must be performed separately.

        A typical processing for the clients is to insert a DHCP/DNS
        host, while a typical processing for the vm is to recreate it
        on top of the moved bridges with or without session.

        A typical processing for the vm is to reconfigure the nic type of
        `server_nic` to PROXYARP and its IP to the IP of `proxy_nic`.
        """
        interface = self.interfaces["%s.%s" % (client.name, client_nic)]
        ref_interface = self.interfaces["%s.%s" % (server.name, server_nic)]
        proxy_interface = None
        if proxy_nic != "" and proxy_nic != server_nic:
            proxy_interface = self.interfaces["%s.%s" % (server.name, proxy_nic)]
        netconfig = ref_interface.netconfig
        logging.debug("Reattaching %s to %s", interface, netconfig)

        # detach from the current network
        del interface.netconfig.interfaces[interface.ip]
        # attach to the new network - with validation and proper attribute update
        interface.ip = netconfig.get_allocatable_address()
        netconfig.add_interface(interface)
        if proxy_interface is not None:
            # TODO: this invalidates the network config of the ref_interface -
            # if used in more than one test it has to be improved
            del netconfig.interfaces[interface.ip]
            ref_interface.ip = proxy_interface.ip
            interface.ip = proxy_interface.netconfig.get_allocatable_address()
            interface.netconfig = proxy_interface.netconfig

        # TODO: update the vm node specific and the nic specific parameters
        self.params["netdst_%s_%s" % (client_nic, client.name)] = netconfig.netdst
        self.params["ip_%s_%s" % (client_nic, client.name)] = interface.ip
        self.params["netmask_%s_%s" % (client_nic, client.name)] = netconfig.netmask
        logging.debug("Reattached interface is now %s", interface)

    """VM network host action methods"""
    def _configure_local_dhcp(self, config_string, declarations, interface):
        if interface.netconfig is None:
            raise exceptions.TestError("The interface %s does not belong to any netconfig", interface)
        elif interface.vmnode is None:
            raise exceptions.TestError("The interface %s does come from any vm node", interface)
        elif interface.netconfig.netdst in self.params.get("host_dhcp_blacklist", ""):
            raise exceptions.TestError("The netconfig %s is blacklisted for host DHCP service!" % interface.netconfig)
        else:
            netconfig = interface.netconfig
            vmnode = interface.vmnode

        # main DHCP config
        if interface.params.get("host_dhcp_authoritative", "no") == "yes":
            if not re.search("netconfig %s netmask %s {.+?}" % (netconfig.net_ip, netconfig.netmask),
                             config_string, re.DOTALL):
                logging.info("Adding DHCP netconfig %s", netconfig.net_ip)
                netconfig_string = declarations["subnet"]
                netconfig_string = netconfig_string.replace("#IP#", netconfig.net_ip)
                netconfig_string = netconfig_string.replace("#NETMASK#", netconfig.netmask)
                netconfig_string = netconfig_string.replace("#RANGE_START#", netconfig.ip_start)
                netconfig_string = netconfig_string.replace("#RANGE_STOP#", netconfig.ip_end)
                netconfig_string = netconfig_string.replace("#DNSSERVERS#", netconfig.host_ip)
                netconfig_string = netconfig_string.replace("#ROUTERS#", netconfig.host_ip)
                logging.debug("Adding netconfig to dhcpd.conf:\n%s", netconfig_string)
                config_string += "\n" + netconfig_string
        else:
            if not re.search("dhcp-range=%s" % netconfig.netdst,
                             config_string, re.DOTALL):
                logging.info("Adding DHCP netconfig %s", netconfig.net_ip)
                netconfig_string = "dhcp-range=%s,%s,%s,%s" % (netconfig.netdst, netconfig.ip_start,
                                                               netconfig.ip_end, netconfig.netmask)
                logging.debug("Adding netconfig to dnsmasc.conf:\n%s", netconfig_string)
                config_string += "\n" + netconfig_string

        # register DHCP host in the DHCP config file
        if interface.params.get("host_dhcp_authoritative", "no") == "yes":
            if not re.search("host %s {.+?}" % vmnode.name, config_string, re.DOTALL):
                logging.info("Adding DHCP host %s", vmnode.name)
                host_string = declarations["host"]
                host_string = host_string.replace("#VMNAME#", vmnode.name)
                host_string = host_string.replace("#VMHOSTNAME#", "%s.net.lan" % vmnode.name)
                host_string = host_string.replace("#INIC_MAC#", interface.mac)
                host_string = host_string.replace("#INIC_IP#", interface.ip)
                logging.debug("Adding host to dhcpd.conf:\n%s", host_string)
                config_string += "\n" + host_string
        else:
            logging.info("Adding DHCP host %s", vmnode.name)
            host_string = "dhcp-host=%s,%s" % (interface.mac, interface.ip)
            logging.debug("Adding host to dnsmasc.conf:\n%s", host_string)
            config_string += "\n" + host_string
            # handle cases with non-authoritative DHCP only
            if (interface.params.get("host_dns_service", "no") == "no" or
                    interface.params.get("host_dns_authoritative", "no") == "yes"):
                # TODO: currently DNSMASQ does not support DHCP only mode for a subset of interfaces
                # (setting the port to 0 is the way to do it but this will disable DNS for all)
                # config_string += "\nport=0"
                config_string += "\ninterface=%s" % netconfig.netdst

        return config_string

    def _configure_local_dns(self, config_string, declarations, interface):
        if interface.netconfig is None:
            raise exceptions.TestError("The interface %s does not belong to any netconfig", interface)
        elif interface.vmnode is None:
            raise exceptions.TestError("The interface %s does come from any vm node", interface)
        elif interface.netconfig.netdst in self.params.get("host_dns_blacklist", ""):
            raise exceptions.TestError("The netconfig %s is blacklisted for host DNS service!" % interface.netconfig)
        else:
            netconfig = interface.netconfig
            vmnode = interface.vmnode

        if interface.params.get("host_dns_authoritative", "no") == "yes":
            if not re.search("view \"%s\"" % netconfig.view, config_string, re.DOTALL):

                # main DNS config
                dns_listen = re.search("listen-on port 53 {.*?}", config_string).group()[:-1]
                if netconfig.host_ip not in dns_listen:
                    config_string = config_string.replace(dns_listen, "%s %s;" % (dns_listen, netconfig.host_ip))
                dns_forwarders = re.search("forwarders {.*?}", config_string).group()[:-1]
                if netconfig.forwarder not in dns_forwarders:
                    config_string = config_string.replace(dns_forwarders, "%s %s;" % (dns_forwarders, netconfig.forwarder))

                # prepare the view
                logging.info("Adding DNS view for %s", netconfig.net_ip)
                view_string = declarations["view"]
                view_string = view_string.replace("#VIEWNAME#", netconfig.view)
                view_string = view_string.replace("#IP#", netconfig.net_ip)
                view_string = view_string.replace("#MASKBIT#", netconfig.mask_bit)
                view_string = view_string.replace("#ZONENAME#", netconfig.domain)
                view_string = view_string.replace("#ZONEREV#", netconfig.rev)
                view_string = view_string.replace("#ZONEFILE#", netconfig.view)
                logging.debug("Adding DNS view to named.conf:\n%s", view_string)
                config_string += view_string

                # DNS zone files
                fwd_string = declarations["fwd"].replace("#ZONENAME#", netconfig.domain)
                fwd_string = fwd_string.replace("#ZONEIP#", netconfig.host_ip)
                rev_string = declarations["rev"].replace("#ZONENAME#", netconfig.domain)
                rev_string = rev_string.replace("#ZONEREV#", netconfig.rev)
                fwd_string += "%s \t\t IN \t A \t %s\n" % (vmnode.name, interface.ip)
                open("/var/named/%s.fwd" % netconfig.view, "w").write(fwd_string)
                open("/var/named/%s.rev" % netconfig.view, "w").write(rev_string)

        else:
            if not re.search("interface=%s" % netconfig.netdst, config_string, re.DOTALL):

                # main DNS config
                logging.info("Adding DNS view for %s", netconfig.net_ip)
                view_string = "\n" + "interface=%s\n" % netconfig.netdst
                view_string += "domain=%s,%s/%s\n" % (netconfig.domain, netconfig.net_ip, netconfig.mask_bit)
                local_string = "local=/%s/\n" % netconfig.domain
                if local_string not in config_string:
                    view_string += local_string
                logging.debug("Adding DNS view to dnsmasc.conf:\n%s", view_string)
                config_string += view_string

                # prepare the hosts
                host_string = "%s %s\n" % (netconfig.host_ip, netconfig.domain)
                if host_string not in declarations["hosts"]:
                    declarations["hosts"] += host_string
                guest_host_string = "%s %s\n" % (interface.ip, vmnode.name)
                declarations["hosts"] += guest_host_string

                # handle cases with non-authoritative DNS only
                if (interface.params.get("host_dhcp_service", "no") == "no" or
                        interface.params.get("host_dhcp_authoritative", "no") == "yes"):
                    config_string.replace("interface=%s" % netconfig.netdst,
                                          "no-dhcp-interface=%s" % netconfig.netdst)

        return config_string

    def _configure_local_nat(self, interface, set_rules=True):
        if interface.netconfig is None:
            raise exceptions.TestError("The interface %s does not belong to any netconfig", interface)
        elif interface.vmnode is None:
            raise exceptions.TestError("The interface %s does come from any vm node", interface)
        elif interface.netconfig.netdst in self.params.get("host_dns_blacklist", ""):
            raise exceptions.TestError("The netconfig %s is blacklisted for host DNS service!" % interface.netconfig)
        else:
            netconfig = interface.netconfig
            vmnode = interface.vmnode

        internal_netdst = netconfig.netdst
        external_netdst = netconfig.ext_netdst
        rev_ops = "-i %s -o %s -m state" % (external_netdst, internal_netdst)
        post_ops = "-s %s/%s ! -d %s/%s -o %s" % (netconfig.net_ip, netconfig.mask_bit,
                                                  netconfig.net_ip, netconfig.mask_bit,
                                                  external_netdst)

        process.run("iptables -D FORWARD %s --state RELATED,ESTABLISHED -j ACCEPT" % rev_ops, ignore_status=True)
        process.run("iptables -t nat -D POSTROUTING %s -j MASQUERADE" % post_ops, ignore_status=True)

        if set_rules:
            logging.info("Adding NAT routing to the netconfig (postrouting to %s)", external_netdst)
            process.run("iptables -I FORWARD %s --state RELATED,ESTABLISHED -j ACCEPT" % rev_ops)
            process.run("iptables -t nat -I POSTROUTING %s -j MASQUERADE" % post_ops)

    def setup_host_services(self):
        """
        Provide all necessary services like DHCP, DNS and NAT
        to restrict all tests locally.
        """
        logging.info("Checking for local DHCP, DNS and NAT service requirements")
        dhcp_declarations = {}
        dns_declarations = {}
        dns_set_config = False
        dhcp_set_config = False
        dns_dhcp_set_config = False

        # load templates
        data_path = os.path.join(os.path.dirname(__file__), "templates")
        with open(os.path.join(data_path, "dhcpd.conf.template"), "r") as f:
            dhcp_string = f.read()
            dhcp_declarations["subnet"] = re.search("subnet #IP# netmask #NETMASK#+ {.+?}",
                                                    dhcp_string, re.DOTALL).group()
            dhcp_declarations["host"] = re.search("host #VMNAME# {.+?}",
                                                  dhcp_string, re.DOTALL).group()
            # load the config strings without the declarations
            dhcp_string = dhcp_string.replace("%s\n" % dhcp_declarations["subnet"], "")
            dhcp_string = dhcp_string.replace("%s\n" % dhcp_declarations["host"], "")
        with open(os.path.join(data_path, "named.conf.template"), "r") as f:
            dns_string = f.read()
            dns_declarations["all"] = open(os.path.join(data_path, "all.fwd"), "r").read()
            dns_declarations["fwd"] = open(os.path.join(data_path, "zone.fwd.template"), "r").read()
            dns_declarations["rev"] = open(os.path.join(data_path, "zone.rev.template"), "r").read()
            dns_declarations["view"] = re.search("view \"#VIEWNAME#\" .+?rev\";.+?};.+?};",
                                                 dns_string, re.DOTALL).group()
            # load the config strings without the declarations
            dns_string = dns_string.replace("%s\n" % dns_declarations["view"], "")
        with open(os.path.join(data_path, "dnsmasq.conf.template"), "r") as f:
            dns_declarations["hosts"] = open(os.path.join(data_path, "hosts.conf.template"), "r").read()
            dns_dhcp_string = f.read()

        # configure selected interfaces
        for interface in self.interfaces.values():
            # if the internet provider of the vm coincides with the host of the vm (for the current nic)
            if interface.params.get("ip_provider", "no-provider") == interface.params.get("host", "no-host"):
                netconfig = interface.netconfig
                dhcp_ops = "-i %s" % (netconfig.netdst)
                dns_ops = "-i %s -d %s" % (netconfig.netdst, netconfig.host_ip)
                fwd_ops = "-s %s/%s -i %s" % (netconfig.net_ip, netconfig.mask_bit, netconfig.netdst)

                process.run("iptables -D INPUT %s -p udp -m udp --dport 67:68 -j ACCEPT" % dhcp_ops, ignore_status=True)
                process.run("iptables -D FORWARD %s -j ACCEPT" % fwd_ops, ignore_status=True)
                if interface.params.get("host_dhcp_service", interface.params.get("host_services", "no")) == "yes":
                    process.run("iptables -I INPUT %s -p udp -m udp --dport 67:68 -j ACCEPT" % dhcp_ops)
                    process.run("iptables -I FORWARD %s -j ACCEPT" % fwd_ops)
                    if interface.params.get("host_dhcp_authoritative", "no") == "yes":
                        dhcp_string = self._configure_local_dhcp(dhcp_string, dhcp_declarations, interface)
                        dhcp_set_config = True
                    else:
                        dns_dhcp_string = self._configure_local_dhcp(dns_dhcp_string, dhcp_declarations, interface)
                        dns_dhcp_set_config = True

                process.run("iptables -D INPUT %s -p tcp -m tcp --dport 53 -j ACCEPT" % dns_ops, ignore_status=True)
                process.run("iptables -D INPUT %s -p udp -m udp --dport 53 -j ACCEPT" % dns_ops, ignore_status=True)
                if interface.params.get("host_dns_service", interface.params.get("host_services", "no")) == "yes":
                    process.run("iptables -I INPUT %s -p tcp -m tcp --dport 53 -j ACCEPT" % dns_ops)
                    process.run("iptables -I INPUT %s -p udp -m udp --dport 53 -j ACCEPT" % dns_ops)
                    if interface.params.get("host_dns_authoritative", "no") == "yes":
                        dns_string = self._configure_local_dns(dns_string, dns_declarations, interface)
                        dns_set_config = True
                    else:
                        dns_dhcp_string = self._configure_local_dns(dns_dhcp_string, dns_declarations, interface)
                        dns_dhcp_set_config = True

                # turn the host into NAT router for the netconfig
                self._configure_local_nat(interface,
                                          set_rules=interface.params.get("host_nat_service",
                                                                         interface.params.get("host_services", "no")) == "yes")

                # ports for additional (custom) services
                for port in interface.params.objects("host_additional_ports"):
                    process.run("iptables -D INPUT -i %s -p tcp --dport %s -j ACCEPT" % (netconfig.netdst, port), ignore_status=True)
                    process.run("iptables -I INPUT -i %s -p tcp --dport %s -j ACCEPT" % (netconfig.netdst, port))

            elif interface.params.get("ip_provider", "no-provider") == interface.ip:
                self_ops = "-i %s -o %s" % (interface.netconfig.netdst, interface.netconfig.netdst)
                process.run("iptables -D FORWARD %s -j ACCEPT" % self_ops, ignore_status=True)
                process.run("iptables -I FORWARD %s -j ACCEPT" % self_ops)

        # write configurations if any
        if dhcp_set_config:
            logging.debug("Writing new DHCP config file:\n%s", dhcp_string)
            dhcp_config = "/etc/dhcp/dhcpd.conf"
            if not os.path.exists("%s.bak" % dhcp_config):
                os.rename(dhcp_config, "%s.bak" % dhcp_config)
            with open(dhcp_config, "w") as f:
                f.write(dhcp_string)
            logging.debug("Resetting DHCP service")
            process.run("service dhcpd restart")  # , ignore_status = True)
        else:
            process.run("service dhcpd stop", ignore_status=True)
        if dns_set_config:
            logging.debug("Writing new DNS config file:\n%s", dns_string)
            dns_config = "/etc/named.conf"
            if not os.path.exists("%s.bak" % dns_config):
                os.rename(dns_config, "%s.bak" % dns_config)
            with open(dns_config, "w") as f:
                f.write(dns_string)
            with open("/var/named/all.fwd", "w") as f:
                f.write(dns_declarations["all"])
            logging.debug("Resetting DNS service")
            process.run("service named restart")
        else:
            process.run("service named stop", ignore_status=True)
        if dns_dhcp_set_config:
            logging.debug("Writing new DHCP/DNS config file:\n%s", dns_dhcp_string)
            dns_dhcp_config = "/etc/dnsmasq.d/avocado.conf"
            with open(dns_dhcp_config, "w") as f:
                f.write(dns_dhcp_string)
            with open("/etc/dnsmasq.d/avocado-hosts.conf", "w") as f:
                f.write(dns_declarations["hosts"])
            logging.debug("Resetting DHCP/DNS service")
            process.run("kill $(cat /var/run/avocado-dnsmasq.pid)",
                        shell=True, ignore_status=True)
            time.sleep(1)
            process.run("dnsmasq --conf-file=%s" % dns_dhcp_config)
        else:
            process.run("kill $(cat /var/run/avocado-dnsmasq.pid)",
                        shell=True, ignore_status=True)

    def _add_new_bridge(self, interface):
        netdst = interface.netconfig.netdst
        host_ip = interface.netconfig.host_ip
        netmask = interface.netconfig.netmask

        def _debug_bridge_ip(netdst):
            output = process.run('ifconfig %s | head -n 3' % netdst, shell=True)
            logging.debug('ifconfig output for %s:\n%s' % (netdst, output))

        logging.info("Adding bridge %s", netdst)
        # TODO: no original avocado-vt method could do this for us
        process.run("brctl addbr %s" % netdst)
        if interface.params.get("host", "") != "":
            logging.debug("Adding this host with ip %s to %s and bringing it up",
                          host_ip, netdst)
            # TODO: this timeout is temporary
            time.sleep(2)
            # TODO: no original avocado-vt method in utils_net like set_ip() and
            # set_netmask() could do this for us at least from the research at the time
            process.run("ifconfig %s %s netmask %s up" % (netdst, host_ip, netmask))
            # DEBUG only: See if setting the IP address worked
            _debug_bridge_ip(netdst)
        else:
            logging.debug("Bringing up interface of the bridge %s", netdst)
            utils_net.bring_up_ifname(netdst)
            _debug_bridge_ip(netdst)

    def _cleanup_bridge_interfaces(self, netdst):
        logging.debug("Resetting the bridge %s to remove unwanted interfaces", netdst)
        bridge_manager = utils_net.find_bridge_manager(netdst)
        bridges = bridge_manager.get_structure()
        logging.debug("Parsed bridge structure: %s", bridges)
        if netdst in bridges.keys():
            interfaces = bridges[netdst]["iface"]
            for ifname in interfaces:
                # BUG: a bug in avocado-vt forces us to use a direct method from the bridge manager instead
                # of the more elegant "utils_net.del_from_bridge(ifname, netdst)" which also fits better
                # our other calls - at least we managed to isolate the buggy and unimplemented interface calls
                bridge_manager.del_port(netdst, ifname)

    def setup_host_bridges(self):
        """
        Setup bridges and interfaces needed to create and isolate the network.

        The final network topology is derived entirely from the test parameters.
        """
        logging.info("Checking for any bridge requirements")
        boarding = []

        # iterate through the bridges that need our setup
        for (key, interface) in self.interfaces.items():
            vm_name, nic_name = key.split(".")
            if (interface.params.get("host_set_bridge", "yes") == "no" or
                    interface.params.get("permanent_netdst", "yes") == "yes"):
                continue

            # get any previous configuration if available - unfortunately,
            # no better way of handling missing key was available
            try:
                nic = interface.vmnode.platform.virtnet[nic_name]
            except IndexError:
                logging.debug("No nic object %s is available at %s", nic_name, vm_name)
                nic = None

            # discover and setup the nic bridge if necessary
            if nic is None:
                new_netdst = interface.netconfig.netdst
            elif nic.netdst != interface.netconfig.netdst:
                logging.debug("The retrieved nic %s has old configuration - "
                              "falling back to the available interface %s",
                              nic_name, interface)
                new_netdst = interface.netconfig.netdst
            else:
                new_netdst = nic.netdst
            # if the netdst was reset and already boarding interfaces skip this
            if new_netdst not in boarding:
                logging.debug("Updating the bridge %s of the network card %s of %s",
                              new_netdst, nic_name, vm_name)
                bridge_manager = utils_net.find_bridge_manager(new_netdst)
                # no manager for the current bridge is equivalent to the fact that it doesn't exist
                if bridge_manager is not None:
                    self._cleanup_bridge_interfaces(new_netdst)
                else:
                    self._add_new_bridge(interface)
                boarding.append(new_netdst)

            # discover and setup the nic interface on top of the nic bridge
            if nic is not None:
                new_ifname = nic.ifname
            else:
                new_ifname = None
            # if the interface is up and in particular if it exists before the upcoming test
            if new_ifname in utils_net.get_net_if():
                logging.debug("Adding back interface %s to bridge %s", new_ifname, new_netdst)
                utils_net.change_iface_bridge(new_ifname, new_netdst)
            else:
                logging.debug("Interface will be added to bridge during vm creation")

    """VM network guest action methods"""
    def spawn_clients(self, server_name, clients_num, nic="onic"):
        """
        Create and boot ephemeral clients for a given server.

        :param str server_name: name of the vm that plays the role of a server
        :param int clients_num: number of ephemeral clients to spawn
        :param str nic: name of the nic of the server
        :returns: generated ephemeral clients
        :rtype: (VM object)
        """
        server = self.vmnodes[server_name].platform
        client_params = {}
        logging.info("Spawning %i client(s) for %s", clients_num, server.name)
        client_params.update(self._generate_clients_parameters(server_name, clients_num, nic))
        self.params.update(client_params)
        new_clients = client_params["vms_%s" % server.name].strip()
        new_clients = new_clients.split(" ")
        for client_name in new_clients:
            self.params["vms"] += " %s" % client_name

            logging.debug("Registering the ephemeral vm in the environment")
            client_params = self.params.object_params(client_name)
            client = self.env.create_vm(client_params.get('vm_type'),
                                        client_params.get('target'),
                                        client_name, client_params,
                                        self.test.bindir)

            logging.debug("Integrating the ephemeral vm in the vm network")
            self.vmnodes[client_name] = self.new_vmnode(client)
            self.integrate_vmnode(self.vmnodes[client_name])

            logging.debug("Adding as an intraclient and booting the ephemeral vm")
            interface = self.vmnodes[client_name].interfaces[client_params["nics"]]
            self._register_client_at_server(interface, server, enable_dhcp=True)
            self.vmnodes[client_name].platform.create()

        # verify clients are running (2nd loop so clients boot in parallel)
        for client_name in new_clients:
            self.vmnodes[client_name].get_session(serial=True)

        # NOTE: since such clients are created on the run and don't have nics for communication
        # with the host we need to disable some automatic postprocessing functionality
        self.params["kill_unresponsive_vms"] = "no"
        return tuple([self.vmnodes[key].platform for key in new_clients])

    def _generate_clients_parameters(self, server_name, clients_num, nic="onic"):
        overwrite_dict = {}
        overwrite_dict["vms_%s" % server_name] = ""

        for i in range(clients_num):
            logging.debug("Adding client %i for %s", i, server_name)
            server_interface = self.vmnodes[server_name].interfaces[nic]

            # main
            client = "%sclient%i" % (server_name, i)
            overwrite_dict["vms_%s" % server_name] += "%s " % client
            overwrite_dict["start_vm_%s" % client] = "yes"
            overwrite_dict["kill_vm_%s" % client] = self.params.get("kill_clients", "yes")
            overwrite_dict["mem_%s" % client] = "512"
            overwrite_dict["images_%s" % client] = ""
            overwrite_dict["boot_order_%s" % client] = "dcn"
            overwrite_dict["cdroms_%s" % client] = "cd_rip"
            overwrite_dict["shell_prompt_%s" % client] = "^[\#\$]"
            overwrite_dict["isa_serials_%s" % client] = "serial1"

            # networking
            client_nic = "%snic" % client
            overwrite_dict["nics_%s" % client] = client_nic
            overwrite_dict["nic_model_%s" % client] = "e1000"

            client_mac_sub = server_interface.mac.split(":")[-2]
            new_sub = str(i + 2)
            if len(new_sub) < 2:
                new_sub = "0" + new_sub
            client_mac = server_interface.mac.replace(client_mac_sub, new_sub)
            overwrite_dict["mac_%s" % client_nic] = client_mac

            client_netconfig = server_interface.netconfig
            client_ip = client_netconfig.get_allocatable_address()
            overwrite_dict["ip_%s" % client_nic] = client_ip
            overwrite_dict["netmask_%s" % client_nic] = client_netconfig.netmask
            overwrite_dict["netdst_%s" % client_nic] = client_netconfig.netdst

        return overwrite_dict

    def _register_client_at_server(self, interface, server, enable_dhcp=True):
        """
        Register a client vm at a server vm.

        :param interface: network interface containing the new configuration
        :type interface: Interface object
        :param server: server where the (DHCP) client will be registered
        :type server: VM object
        :param bool enable_dhcp: whether to use DHCP or static IP
        """
        raise NotImplementedError("Need implementation for some OS")

    def _reconfigure_vm_nic(self, nic, interface, vm):
        """
        Reconfigure the NIC of a vm.

        :param str nic: nic name known by the vm operating system
        :param interface: network interface containing the new configuration
        :type interface: Interface object
        :param vm: vm whose nic will be reconfigured
        :type vm: VM object
        :raises: :py:class:`exceptions.TestError` if the client is an Android device
        :raises: :py:class:`exceptions.NotImplementedError` if the client is not compatible
        """
        logging.info("Reconfiguring the %s of %s", nic, vm.name)
        if vm.params["os_type"] == "windows":
            network = self.params.get("%s_wname" % nic, nic)
            netcmd = "netsh interface ip set address name=\"%s\" source=static %s %s %s 0"
            vm.session.cmd(netcmd % (network, interface.ip,
                                     interface.netconfig.netmask,
                                     interface.netconfig.gateway),
                           timeout=120)
            netcmd = "netsh interface ip add dns name=\"%s\" addr=%s index=1"
            vm.session.cmd(netcmd % (network, interface.netconfig.gateway))
        elif vm.params["os_variant"] in ["ak", "al", "am"]:
            raise exceptions.TestError("No static IP can be set for Android devices (%s)" % vm.name)
        else:
            raise NotImplementedError("Trying to configure nic on %s with an unsupported os %s" % (vm.name, vm.params["os_variant"]))

    def change_network_address(self, netconfig, new_ip, new_mask=None, new_gw=None):
        """
        Change the ip of a netconfig and more specifically of the network interface of
        any vm participating in it.

        :param netconfig: netconfig to change the IP of
        :type netconfig: Netconfig object
        :param str new_ip: new IP address for the netconfig
        :param new_mask: new network mask for the netconfig
        :type new_mask: str or None
        :param new_gw: new gateway for the netconfig
        :type new_gw: str or None

        .. note:: The network must have at least one interface in order to change its address.
        """
        logging.debug("Updating the network configuration of the vm network")
        for interface in list(netconfig.interfaces.values()):
            del netconfig.interfaces[interface.ip]
            interface.ip = netconfig.translate_address(interface, new_ip)
            netconfig.interfaces[interface.ip] = interface

        assert len(netconfig.interfaces) > 0, "The network %s must have at least one interface" % netconfig
        nic_params = list(netconfig.interfaces.values())[-1].params.copy()
        nic_params["ip"] = new_ip
        if new_mask is not None:
            nic_params["netmask"] = new_mask
        if new_gw is not None:
            nic_params["ip_provider"] = new_gw
        interface = self.new_interface(nic_params)

        del self.netconfigs[netconfig.net_ip]
        netconfig.from_interface(interface)
        netconfig.validate()
        self.netconfigs[netconfig.net_ip] = netconfig

        logging.debug("Updating the network configuration of the relevant platforms")
        for interface in netconfig.interfaces.values():
            vmnode = interface.vmnode
            logging.info("Changing the ip of %s to %s", vmnode.name, interface.ip)

            # HACK: revise dictionaries to avoid having to do reverse lookup
            for name, value in vmnode.interfaces.items():
                if value == interface:
                    interface_nic = name
            self._reconfigure_vm_nic(interface_nic, interface, vmnode.platform)

            # updating proto (higher level) params (test params -> vm params -> nic params)
            # TODO: need to update more parameters and be more flexible about the nic name
            interface.params["netmask"] = new_mask
            interface.params["ip"] = interface.ip
            vmnode.platform.params["ip_onic"] = interface.ip
            vmnode.platform.params["ip_onic_%s" % vmnode.name] = interface.ip

    def set_static_address(self, client, server,
                           client_nic="inic", server_nic="onic"):
        """
        Set a static IP address on a client vm.

        :param client: vm whose nic will get static IP
        :type client: VM object
        :param server: vm whose network will provide a free static IP
        :type server: VM object
        :param str client_nic: name of the nic of the client
        :param str server_nic: name of the nic of the server

        .. note:: This assumes running machines.
        """
        client.verify_alive()
        client_iface = self.interfaces["%s.%s" % (client.name, client_nic)]
        server_iface = self.interfaces["%s.%s" % (server.name, server_nic)]
        client_iface.netconfig.gateway = server_iface.ip
        self._reconfigure_vm_nic(client_nic, client_iface, client)

    def configure_gre_tunnel_between_vms(self, vm1, vm2, ip1=None, ip2=None):
        """
        Configure a GRE connection (tunnel) between two vms.

        :param vm1: left side vm of the tunnel
        :type vm1: VM object
        :param vm2: right side vm of the tunnel
        :type vm2: VM object
        :param str ip1: IP of the left vm
        :param str ip2: IP of the right vm

        If `ip1` and/or `ip2` are provided, they will be used as remote IPs instead
        of the default remote interface IPs. A typical use case where `ip1/ip2`
        are needed is when one or both of the vms are NAT-ed and their default
        (inic) IPs are not accessible from the outside.
        """
        net1 = "%snet" % vm2.name
        local1 = self.interfaces["%s.onic" % vm1.name]
        remote1 = self.interfaces["%s.inic" % vm1.name]
        net2 = "%snet" % vm1.name
        local2 = self.interfaces["%s.onic" % vm2.name]
        remote2 = self.interfaces["%s.inic" % vm2.name]

        add_cmd = "ip tunnel add %s mode gre remote %s local %s ttl 255"
        vm1.session.cmd(add_cmd % (net1, ip2 if ip2 is not None else remote2.ip, remote1.ip))
        vm1.session.cmd("ip link set %s up" % net1)
        vm1.session.cmd("ip addr add %s dev %s" % (local1.ip, net1))
        vm1.session.cmd("ip route add %s/%s dev %s" % (local2.netconfig.net_ip,
                                                       local2.netconfig.mask_bit,
                                                       net1))
        vm2.session.cmd(add_cmd % (net2, ip1 if ip1 is not None else remote1.ip, remote2.ip))
        vm2.session.cmd("ip link set %s up" % net2)
        vm2.session.cmd("ip addr add %s dev %s" % (local2.ip, net2))
        vm2.session.cmd("ip route add %s/%s dev %s" % (local1.netconfig.net_ip,
                                                       local1.netconfig.mask_bit,
                                                       net2))

        gre_protocol_id = 47
        if ip1 is not None:
            vm1.session.cmd("iptables -I INPUT -i eth1 -p %s -j ACCEPT" % gre_protocol_id)
        vm1.session.cmd("iptables -I INPUT -i %snet -p icmp -j ACCEPT" % vm2.name)
        vm1.session.cmd("iptables -I OUTPUT -o %snet -p icmp -j ACCEPT" % vm2.name)
        if ip2 is not None:
            vm2.session.cmd("iptables -I INPUT -i eth1 -p %s -j ACCEPT" % gre_protocol_id)
        vm2.session.cmd("iptables -I INPUT -i %snet -p icmp -j ACCEPT" % vm1.name)
        vm2.session.cmd("iptables -I OUTPUT -o %snet -p icmp -j ACCEPT" % vm1.name)

    def configure_vpn_between_vms(self, vpn_name, vm1, vm2, left_variant=None, psk_variant=None):
        """
        Configure a VPN connection (tunnel) between two vms.

        :param str vpn_name: name of the VPN connection
        :param vm1: left side vm of the VPN tunnel
        :type vm1: VM object
        :param vm2: right side vm of the VPN tunnel
        :type vm2: VM object
        :param left_variant: left side configuration (right side is determined from it)
        :type left_variant: (str, str, str)
        :param psk_variant: PSK configuration in the case PSK is used
        :type psk_variant: (str, str, str)
        """
        if left_variant is None:
            left_variant = [self.params.get("lan_type", "nic"),
                            self.params.get("remote_type", "custom"),
                            self.params.get("peer_type", "ip")]
        if psk_variant is None and self.params.get("psk", "") != "":
            psk_variant = [self.params["psk"],
                           self.params["own_id_type"],
                           self.params["foreign_id_type"]]

        left_vmnode = self.vmnodes[vm1.name]
        right_vmnode = self.vmnodes[vm2.name]
        self.tunnels[vpn_name] = self.new_vpnconn(vpn_name, left_vmnode, right_vmnode,
                                                  self, left_variant, psk_variant)
        self.tunnels[vpn_name].configure_between_endpoints(self, left_variant, psk_variant)

    def configure_vpn_on_vm(self, vpn_name, vm, apply_key_own=False,
                            apply_key_foreign=False, apply_firewall_ruleset=False):
        """
        Configure a VPN connection (tunnel) on a vm, assuming it is manually
        or independently configured on the other end.

        :param str vpn_name: name of the VPN connection
        :param vm: vm where the VPN will be configured
        :type vm: VM object
        :param bool apply_key_own: whether to apply KEY_OWN configuration
        :param bool apply_key_foreign: whether to apply KEY_FOREIGN configuration
        :param bool apply_firewall_ruleset: whether to apply FIREWALL_RULESET configuration
        :raises: :py:class:`exceptions.KeyError` if not all VPN parameters are present

        Currently the method uses only existing VPN connections.
        """
        if vpn_name not in self.tunnels:
            raise KeyError("Currently, every VPN connection has to be created defining both"
                           " ends and it can only then be configured on a single vm %s" % vm.name)

        self.tunnels[vpn_name].configure_on_endpoint(vm, self, apply_key_own,
                                                     apply_key_foreign, apply_firewall_ruleset)

    def configure_roadwarrior_vpn_on_server(self, vpn_name, server, client, apply_key_own=False,
                                            apply_key_foreign=False, apply_firewall_ruleset=False):
        """
        Configure a VPN connection (tunnel) on a vm to play the role of a VPN
        server for any individual clients to access it from the internet.

        :param str vpn_name: name of the VPN connection
        :param server: vm which will be the VPN server for roadwarrior connections
        :type server: VM object
        :param client: vm which will be connecting individual device
        :type client: VM object
        :param bool apply_key_own: whether to apply KEY_OWN configuration
        :param bool apply_key_foreign: whether to apply KEY_FOREIGN configuration
        :param bool apply_firewall_ruleset: whether to apply FIREWALL_RULESET configuration

        Regarding the client, only its parameters will be updated by this method.
        """
        left_vmnode = self.vmnodes[server.name]
        right_vmnode = self.vmnodes[client.name]
        self.tunnels[vpn_name] = self.new_vpnconn(vpn_name, left_vmnode, right_vmnode, self,
                                                  [self.params.get("lan_type", "nic"),
                                                   self.params.get("remote_type", "modeconfig"),
                                                   self.params.get("peer_type", "dynip")],
                                                  roadwarrior=True)

        # some parameter modification for the road warrior connection
        vpn_params = self.tunnels[vpn_name].params
        # add all new vpn parameters to the already defined vm parameters
        # and throw away unnecessary parameters from this function
        params1 = vpn_params.object_params(client.name)
        params2 = vpn_params.object_params(server.name)
        params1.update(client.params)
        params2.update(server.params)
        client.params = params1
        server.params = params2

        self.configure_vpn_on_vm(vpn_name, server, apply_key_own,
                                 apply_key_foreign, apply_firewall_ruleset)

    def configure_vpn_route(self, vms, vpns, left_variant=None, psk_variant=None):
        """
        Build a set of vpn connections using vpn forwarding to gain access from
        one vm to another.

        :param vms: vms to participate in the VPN route
        :type vms: [VM object]
        :param vpns: VPNs over which the route will be constructed
        :type vpns: [str]
        :param left_variant: left side configuration (right side is determined from it)
        :type left_variant: (str, str, str)
        :param psk_variant: PSK configuration in the case PSK is used
        :type psk_variant: (str, str, str)
        :raises: :py:class:`exceptions.TestError` if #vpns < #vms - 1 or #vpns < 2 or #vms < 2

        Infrastructure of point to point vpn connections must already exist.
        """
        if left_variant is None:
            left_variant = [self.params.get("lan_type", "nic"),
                            self.params.get("remote_type", "custom"),
                            self.params.get("peer_type", "ip")]
        if psk_variant is None and self.params.get("psk", "") != "":
            psk_variant = [self.params["psk"],
                           self.params["own_id_type"],
                           self.params["foreign_id_type"]]

        if len(vpns) < 2 or len(vms) < 2 or len(vpns) < len(vms) - 1:
            raise exceptions.TestError("Insufficient vpn infrastructure - unnecessary vpn forwarding")

        logging.info("Bulding vpn route %s", "-".join(vm.name for vm in vms))
        for i in range(len(vpns)):
            fvpn = "%s_fwd" % vpns[i]
            if i == 0:
                prev_net = vms[i + 1].params.object_params(vpns[i]).get("vpnconn_remote_net")
                next_net = vms[i + 1].params.object_params(vpns[i + 1]).get("vpnconn_remote_net")
            elif i == len(vpns) - 1:
                prev_net = vms[i].params.object_params(vpns[i - 1]).get("vpnconn_remote_net")
                next_net = vms[i].params.object_params(vpns[i]).get("vpnconn_remote_net")
            else:
                prev_net = vms[i - 1].params.object_params(vpns[i - 1]).get("vpnconn_remote_net")
                next_net = vms[i + 1].params.object_params(vpns[i + 1]).get("vpnconn_remote_net")
            logging.debug("Retrieved previous network %s and next network %s", prev_net, next_net)

            vms[i].params["vpnconn_lan_type_%s" % fvpn] = "CUSTOM"
            vms[i].params["vpnconn_lan_net_%s" % fvpn] = prev_net
            vms[i].params["vpnconn_remote_net_%s" % fvpn] = next_net
            vms[i + 1].params["vpnconn_lan_type_%s" % fvpn] = "CUSTOM"
            vms[i + 1].params["vpnconn_lan_net_%s" % fvpn] = next_net
            vms[i + 1].params["vpnconn_remote_net_%s" % fvpn] = prev_net

            self.configure_vpn_between_vms(fvpn, vms[i], vms[i + 1], left_variant, psk_variant)

    """VM network test methods"""
    def get_vpn_accessible_ip(self, src_vm, dst_vm, dst_vm_server=None, netconfig_num=3):
        """
        Get acessible ip from a vm to a vm given using heuristics about
        the netconfigs of the entire vm network.

        :param src_vm: source vm whose IPs are starting points
        :type src_vm: VM object
        :param dst_vm: destination vm whose IPs are ending points
        :type dst_vm: VM object
        :param dst_vm_server: explicit server (of network) for the destination vm
        :type dst_vm_server: VM object
        :param int netconfig_num: legacy parameter needed for finding IP through VPN routes
        :returns: the IP with which the destination vm can be accessed from the source vm
        :rtype: str
        :raises: :py:class:`exceptions.TestError` if the destination server is not a server or
            the source or destination vms are not on the network

        This ip can then be used for ping, tcp tests, etc.

        .. note:: Keep in mind that strict naming conventions of the vpn connections
            between netconfigs are required. When you decide about the parameters of a
            vm, you have to append them with '_vpn_X.X' where the two X are the indices
            of the netconfigs where the servers are located, sorted in ascending order.
        """
        if dst_vm_server is None:
            dst_vm_server = dst_vm
            if "client" in dst_vm_server:
                raise exceptions.TestError("The client vm %s cannot be a VPN server" % dst_vm.name)
        if "client" in dst_vm.name:
            interface = self.interfaces["%s.%s" % (dst_vm.name, dst_vm.params["nics"])]
        else:
            # NOTE: the "onic" interface is the only one used for VPN connections
            interface = self.interfaces["%s.onic" % dst_vm.name]

        def get_vpn_id():
            src_index = -1
            dst_index = -1
            for i in range(netconfig_num):
                if "vm%i" % (i+1) in src_vm.name:
                    src_index = i
                if "vm%i" % (i+1) in dst_vm.name:
                    dst_index = i
                if src_index != -1 and dst_index != -1:
                    break
            if src_index == -1:
                raise exceptions.TestError("The source vm %s could not be found in any local network" % src_vm.name)
            if dst_index == -1:
                raise exceptions.TestError("The destination vm %s could not be found in any local network" % dst_vm.name)
            if src_index == dst_index:
                raise exceptions.TestError("The source vm %s and the destination vm %s should not be located in the same network"
                                      " in order to be accessible through a VPN connection" % (src_vm.name, dst_vm.name))
            # sort indices to get the universal vpn id
            if src_index < dst_index:
                vpn_id = "vpn%s.%s" % (src_index, dst_index)
            else:
                vpn_id = "vpn%s.%s" % (dst_index, src_index)
            logging.debug("Found a vpn connection with id %s between %s and %s",
                          vpn_id, src_vm.name, dst_vm.name)
            return vpn_id

        vpn_id = get_vpn_id()
        # try to get translated ip (NAT) and if not get inner ip which is used
        # in the default vpn configuration
        if "client" in dst_vm.name:
            vpn_params = dst_vm_server.params.object_params(vpn_id)
            nat_ip_server = vpn_params.get("ip_nat")
            if nat_ip_server is not None:
                logging.debug("Obtaining translated IP address of an ephemeral client %s",
                              dst_vm.name)
                nat_ip = interface.netconfig.translate_address(interface, nat_ip_server)
                logging.debug("Retrieved network translated ip %s for %s", nat_ip, dst_vm.name)
            else:
                nat_ip = interface.ip
                logging.debug("Retrieved original ip %s for %s", nat_ip, dst_vm.name)
        else:
            vpn_params = dst_vm.params.object_params(vpn_id)
            nat_ip = vpn_params.get("ip_nat", interface.ip)
            logging.debug("Retrieved network translated ip %s for %s", nat_ip, dst_vm.name)
        return nat_ip

    def _get_accessible_ip(self, src_vm, dst_vm, dst_nic="onic", netconfig_num=3):
        # determine dst_vm server and interface
        if "client" in dst_vm.name:
            dst_vm_server_name = re.match("(vm\d+)client\d+", dst_vm.name).group(1)
            # NOTE: ephemeral clients have only one nic so force its use
            dst_iface = self.interfaces["%s.%s" % (dst_vm.name, dst_vm.params["nics"])]
        else:
            dst_vm_server_name = dst_vm.name
            dst_iface = self.interfaces["%s.%s" % (dst_vm.name, dst_nic)]
        dst_vm_server = self.vmnodes[dst_vm_server_name].platform

        # check if the source vm shares a network with a fixed destination nic
        for src_iface in self.vmnodes[src_vm.name].interfaces.values():
            if src_iface.netconfig == dst_iface.netconfig:
                logging.debug("Internal IP %s of %s is accessible to %s",
                              dst_iface.ip, dst_vm.name, src_vm.name)
                return dst_iface.ip

        # TODO: we could also do some general routing and gateway search but this is
        # rather unnecessary with the current tests' requirements

        # do a VPN search as the last resort (of what we have implemented so far)
        logging.debug("No accessible IP found in local networks, falling back to VPN search")
        return self.get_vpn_accessible_ip(src_vm, dst_vm,
                                          dst_vm_server=dst_vm_server,
                                          netconfig_num=netconfig_num)

    def verify_vpn_in_log(self, src_vm, dst_vm, log_vm=None, netconfigs_num=3):
        """
        Search for the appropriate message in the vpn log file.

        :param src_vm: source vm whose packets will be logged
        :type src_vm: VM object
        :param dst_vm: destination vm whose packets will be logged
        :type dst_vm: VM object
        :param log_vm: vm where all packets are logged
        :type log_vm: VM object
        :param int netconfig_num: legacy parameter needed for finding IP through VPN routes
        :raises: :py:class:`exceptions.TestError` if the source or destination vms are not on the network
        :raises: :py:class:`exceptions.TestFail` if the VPN packets were not logged properly

        This function requires modified firewall ruleset for the vpn connection.
        """
        if log_vm is None:
            log_vm = dst_vm
        src_index = -1
        dst_index = -1
        log_index = -1

        for i in range(netconfigs_num):
            if "vm%i" % (i+1) in src_vm.name:
                src_index = i
            if "vm%i" % (i+1) in dst_vm.name:
                dst_index = i
            if "vm%i" % (i+1) in log_vm.name:
                log_index = i
            if src_index != -1 and dst_index != -1 and log_index != -1:
                if log_index == src_index:
                    remote_index = dst_index
                elif log_index == dst_index:
                    remote_index = src_index
                else:
                    # ignore cases where the logging machine is in a different
                    # netconfig than the source and the destination machine
                    return
                if log_index == remote_index:
                    # ignore cases where the source and destination machine
                    # are in the same netconfig since no vpn connection is used
                    return
                log_message = "VPN%i.%i" % (log_index, remote_index)
                break
        if src_index == -1:
            raise exceptions.TestError("The source vm %s could not be found in any local network" % src_vm.name)
        if dst_index == -1:
            raise exceptions.TestError("The destination vm %s could not be found in any local network" % dst_vm)
        if log_index == -1:
            raise exceptions.TestError("The logging vm %s could not be found in any local network" % log_vm)

        wrong_messages = []
        for i in range(netconfigs_num):
            if i == log_index or i == remote_index:
                continue
            wrong_messages.append("VPN_%i.%i" % (log_index, i))
        deny_message = "%s_DENY" % log_message

        # BUG: there is a problem in firewall logging of VPN with NAT - skip check to test working features
        if self.params.get("report_bugs", "yes") == "yes" and log_message == "VPN0.2" and log_vm.params.get("has_logging_bug", "no") == "yes":
            log = log_vm.session.cmd("rm -f /var/log/messages")
            log = log_vm.session.cmd("/etc/init.d/rsyslog restart")
            return

        logging.info("Checking log of %s for the firewall rule tag %s ", log_vm.name, log_message)
        log = log_vm.session.cmd("cat /var/log/messages")
        if log_message not in log:
            raise exceptions.TestFail("No message with %s was found in log" % log_message)
        if deny_message in log:
            raise exceptions.TestFail("The deny message %s was found in log" % deny_message)
        for wrong_message in wrong_messages:
            if wrong_message in log:
                raise exceptions.TestFail("Wrong message %s in addition to %s was found in log" % (wrong_message, log_message))
        logging.info("Ok, resetting the messages log at %s", log_vm.name)
        log = log_vm.session.cmd("rm -f /var/log/messages")
        log = log_vm.session.cmd("/etc/init.d/rsyslog restart")

    def ping(self, src_vm=None, dst_vm=None, ping_dst=None, dst_nic="onic", netconfig_num=3):
        """
        Pings a vm from another vm to test most basic connectivity.

        :param src_vm: source vm which will ping
        :type src_vm: VM object
        :param dst_vm: destination vm which will be pinged
        :type dst_vm: VM object
        :param str ping_dst: explicit IP or domain to use for pinging
        :param str dst_nic: nic of the destination vm used if necessary to obtain accessible IP
        :param int netconfig_num: legacy parameter needed for finding IP through VPN routes

        If no source and destination vms are provided, the ping happens
        among all LAN members, throwing an exception if one of the pings fails.

        If no `ping_dst` is provided, the IP is obtained by analyzing the network topology
        from `src_vm` to `dst_vm`.

        If no `dst_vm` is provided, the ping happens directly to `ping_dst`.
        """
        if src_vm is None and dst_vm is None:
            logging.info("Commencing mutual ping of %d vms (including self ping).", len(self.vmnodes))
            failed = False

            for vmnode1 in self.vmnodes.values():
                for interface1 in vmnode1.interfaces.values():
                    for vmnode2 in self.vmnodes.values():
                        for interface2 in vmnode2.interfaces.values():
                            for netconfig in self.netconfigs.values():
                                if interface1.ip in netconfig.interfaces and interface2.ip in netconfig.interfaces:
                                    direction_str = "%s (%s) from %s (%s)" % (vmnode2.name, interface2.ip,
                                                                              vmnode1.name, interface1.ip)
                                    try:
                                        logging.debug("Pinging %s", direction_str)
                                        vmnode1.platform.session.cmd("ping -c 1 %s" % interface2.ip)
                                    except aexpect.ShellCmdError:
                                        logging.info("Failed to ping %s", direction_str)
                                        failed = True

            if failed is True:
                exceptions.TestError("Mutual ping of all LAN members unsuccessful.")
            else:
                logging.info("Mutual ping of all LAN members successful!")
                return

        if ping_dst is None:
            ping_dst = self._get_accessible_ip(src_vm, dst_vm, dst_nic=dst_nic, netconfig_num=netconfig_num)
        logging.info("Pinging %s from %s", ping_dst, src_vm.name)
        result = src_vm.session.cmd("ping %s -c 3" % ping_dst)
        logging.info(result.split("\n")[-3])

    def _ssh_client_hostname(self, src_vm, dst_vm, ssh_ip, timeout=10):
        logging.info("Retrieving host name of client %s from %s through ip %s",
                     dst_vm.name, src_vm.name, ssh_ip)
        dump = src_vm.session.cmd("echo \"\" | "
                                  "ssh -o StrictHostKeyChecking=no "
                                  "-o UserKnownHostsFile=/dev/null "
                                  "root@%s dhcpcd --dumplease eth0 | grep host_name" % ssh_ip)
        logging.debug(dump)
        dst_hostname = re.search("host_name=(\w+)", dump)
        if dst_hostname:
            dst_hostname = dst_hostname.group(1)
            logging.info("Reported host name is %s", dst_hostname)
            return dst_hostname
        raise exceptions.TestFail("No client host name found")

    def _ssh_server_hostname(self, src_vm, dst_vm, ssh_ip, timeout=10):
        logging.info("Retrieving host name of server %s from %s throught ip %s",
                     dst_vm.name, src_vm.name, ssh_ip)
        src_vm.session.sendline("ssh -o StrictHostKeyChecking=no "
                                "-o UserKnownHostsFile=/dev/null "
                                "root@%s hostname" % ssh_ip)
        expected_lines = [r"[Pp]assword:\s*$", r".*"]
        for _ in range(timeout):
            time.sleep(1)
            match, text = src_vm.session.read_until_last_line_matches(expected_lines,
                                                                      timeout=timeout,
                                                                      internal_timeout=0.5)
            logging.debug("Got answer:\n%s", text)
            if match == 0:
                logging.debug("Got password prompt, sending '%s'", dst_vm.params.get("password"))
                src_vm.session.sendline(dst_vm.params.get("password"))
            elif match == 1:
                # the extra search is due to the inability of the builtin command to match the host
                # therefore internally match all and perform the actual matching here
                dst_hostname = re.search("(\w+)\.[a-zA-Z]+", text)
                if dst_hostname:
                    dst_hostname = dst_hostname.group(1)
                    logging.info("Reported host name is %s", dst_hostname)
                    return dst_hostname
        raise exceptions.TestFail("No server host name found")

    def ssh_hostname(self, src_vm, dst_vm, dst_nic="onic", netconfig_num=3, timeout=10):
        """
        Get the host name of a vm from any other vm in the vm net
        using the SSH protocol.

        :param src_vm: source vm with the SSH client
        :type src_vm: VM object
        :param dst_vm: destination vm with the SSH server
        :type dst_vm: VM object
        :param str dst_nic: nic of the destination vm used if necessary to obtain accessible IP
        :param int netconfig_num: legacy parameter needed for finding IP through VPN routes
        :param int timeout: timeout for the SSH connection
        :returns: the hostname of the SSH server
        :rtype: str+

        This tests the TCP connectivity and verifies it leads to the
        correct machine.
        """
        ssh_ip = self._get_accessible_ip(src_vm, dst_vm, dst_nic=dst_nic, netconfig_num=netconfig_num)
        if "client" in dst_vm.name:
            return self._ssh_client_hostname(src_vm, dst_vm, ssh_ip, timeout)
        else:
            return self._ssh_server_hostname(src_vm, dst_vm, ssh_ip, timeout)

    def scp_files(self, src_path, dst_path, src_vm, dst_vm, dst_nic="onic", netconfig_num=3, timeout=10):
        """
        Copy files securely where built-in methods like :py:func:`vm.copy_files_to` fail.

        :param str src_path: source path for the securely copied files
        :param str dst_path: destination path for the securely copied files
        :param src_vm: source vm with the ssh client
        :type src_vm: VM object
        :param dst_vm: destination vm with the ssh server
        :type dst_vm: VM object
        :param str dst_nic: nic of the destination vm used if necessary to obtain accessible IP
        :param int netconfig_num: legacy parameter needed for finding IP through VPN routes
        :param int timeout: timeout for the SSH connection
        :raises: :py:class:`exceptions.TestFail` if the files couldn't be copied

        The paths `src_path` and `dst_path` must be strings, possibly with a wildcard.
        The `netconfig_num parameter` is a helper in case we use the legacy ip search (via vpn).
        """
        ssh_ip = self._get_accessible_ip(src_vm, dst_vm, dst_nic=dst_nic, netconfig_num=netconfig_num)
        logging.info("Copying files %s from %s to %s", src_path, src_vm.name, dst_vm.name)
        src_vm.session.sendline("scp -o StrictHostKeyChecking=no "
                                "-o HostKeyAlgorithms=+ssh-dss "
                                "-o UserKnownHostsFile=/dev/null "
                                "-P %s %s root@%s:%s" % (dst_vm.params.get("file_transfer_port", 22),
                                                         src_path, ssh_ip, dst_path))
        expected_lines = [r"[Pp]assword:\s*$", r".*"]
        for _ in range(timeout):
            time.sleep(1)
            match, text = src_vm.session.read_until_last_line_matches(expected_lines,
                                                                      timeout=timeout,
                                                                      internal_timeout=0.5)
            logging.debug("Got answer:\n%s", text)
            if match == 0:
                logging.debug("Got password prompt, sending '%s'", dst_vm.params.get("password"))
                src_vm.session.sendline(dst_vm.params.get("password"))
            elif match == 1:
                # the extra search is due to the inability of the builtin command to match the host
                # therefore internally match all and perform the actual matching here
                file_transfer = re.search("ETA(.+\s+100%.+)", text)
                if file_transfer:
                    logging.info(file_transfer.group(1))
                    return
        raise exceptions.TestFail("No file progress bars were found - couldn't copy %s" % src_path)

    """VM network direct access methods"""
    # TODO: evaluate if these methods will really be used
    def __len__(self):
        """Count guests in the vm network."""
        return len(self.vmnodes)

    def __getitem__(self, idx):
        """
        Index operation. Depending on whether the index given is an integer
        or a string, returns the vm at a given position or with the given
        name, respectively.

        :param idx: index or name of the retrieved vm
        :type idx: int or str
        :raises: :py:class:`exceptions.TypeError` if unexpected type is detected
        """
        if isinstance(idx, int) is True:
            vmnodes_list = sorted(self.vmnodes.keys())
            return self.vmnodes[vmnodes_list[idx]]
        elif isinstance(idx, str) is True:
            return self.vmnodes[idx]
        raise TypeError("Expected int or string, got \"%s\"." % type(idx))

    def __iter__(self):
        """Iterate over vm network members."""
        return self.vmnodes.__iter__()
