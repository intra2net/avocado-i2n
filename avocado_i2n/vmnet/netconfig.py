# Copyright 2013-2020 Intranet AG and contributors
#
# avocado-i2n is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# avocado-i2n is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with avocado-i2n.  If not, see <http://www.gnu.org/licenses/>.

"""

SUMMARY
------------------------------------------------------
Network configuration object for the VM network.

Copyright: Intra2net AG


CONTENTS
------------------------------------------------------
It contains the network configuration, offers network services like
IP address allocation, translation, and validation, and consists
of Interface objects that share this network configuration.


INTERFACE
------------------------------------------------------

"""


import logging
import ipaddress

from avocado.core import exceptions


class VMNetconfig(object):
    """
    The netconfig class - a collection of interfaces
    sharing the same network configuration.
    """

    """Structural properties"""
    def interfaces(self, value=None):
        """A collection of interfaces the netconfig represents."""
        if value is not None:
            self._interfaces = value
        else:
            return self._interfaces
    interfaces = property(fget=interfaces, fset=interfaces)

    """Configuration properties"""
    def netdst(self, value=None):
        """
        The bridge where Qemu will redirect the packets.

        Plays the role of the network connectivity skeleton.
        """
        if value is not None:
            self._netdst = value
        else:
            return self._netdst
    netdst = property(fget=netdst, fset=netdst)

    def netmask(self, value=None):
        """The netmask used by the participating network interfaces."""
        if value is not None:
            self._netmask = value
        else:
            return self._netmask
    netmask = property(fget=netmask, fset=netmask)

    def mask_bit(self, value=None):
        """The netmask bit used by the participating network interfaces."""
        if value is not None:
            interface = ipaddress.ip_interface("%s/%s" % (self.net_ip, value))
            self.netmask = str(interface.network.netmask)
        else:
            # producing the mask bit from the netmask is not provided by
            # Python so reimplement it here
            if self.netmask is None:
                return None
            netmask = self.netmask.split('.')
            binary_str = ''
            for octet in netmask:
                binary_str += bin(int(octet))[2:].zfill(8)
            return str(len(binary_str.rstrip('0')))
    mask_bit = property(fget=mask_bit, fset=mask_bit)

    def gateway(self, value=None):
        """The gateway ip used by the participating network interfaces."""
        if value is not None:
            self._gateway = value
        else:
            return self._gateway
    gateway = property(fget=gateway, fset=gateway)

    def net_ip(self, value=None):
        """The network ip used by the participating network interfaces."""
        if value is not None:
            self._net_ip = value
        else:
            return self._net_ip
    net_ip = property(fget=net_ip, fset=net_ip)

    def host_ip(self, value=None):
        """
        IP of the host for the virtual machine if it participates in the
        local network (and therefore in the netcofig).
        """
        if value is not None:
            self._host_ip = value
        else:
            return self._host_ip
    host_ip = property(fget=host_ip, fset=host_ip)

    def range(self, value=None):
        """
        IP range of addresses that can be allocated to joining vms
        (new interfaces that join the netconfig).

        To set a different ip_start and ip_end, i.e. different boundaries,
        use the setter of this property.

        .. note:: Used for any DHCP configuration.
        """
        if value is not None:
            self._range = value
        else:
            return self._range
    range = property(fget=range, fset=range)

    def ip_start(self):
        """Beginning of the IP range."""
        minint = 0 if len(self.range) == 0 else min(self.range.keys())
        return str(ipaddress.IPv4Address(self.net_ip) + minint)
    ip_start = property(fget=ip_start)

    def ip_end(self, value=None):
        """End of the IP range."""
        maxint = 0 if len(self.range) == 0 else max(self.range.keys())
        return str(ipaddress.IPv4Address(self.net_ip) + maxint)
    ip_end = property(fget=ip_end)

    def domain(self, value=None):
        """
        DNS domain name for the local network.

        .. note:: Used for host-based DNS configuration.
        """
        if value is not None:
            self._domain = value
        else:
            return self._domain
    domain = property(fget=domain, fset=domain)

    def forwarder(self, value=None):
        """
        DNS forwarder address for the local network.

        .. note:: Used for host-based DNS configuration.
        """
        if value is not None:
            self._forwarder = value
        else:
            return self._forwarder
    forwarder = property(fget=forwarder, fset=forwarder)

    def rev(self, value=None):
        """
        DNS reverse lookup table name for the local network.

        .. note:: Used for host-based DNS configuration.
        """
        if value is not None:
            self._rev = value
        else:
            return self._rev
    rev = property(fget=rev, fset=rev)

    def view(self, value=None):
        """
        DNS view name for the local network.

        .. note:: Used for host-based DNS configuration.
        """
        if value is not None:
            self._view = value
        else:
            return self._view
    view = property(fget=view, fset=view)

    def ext_netdst(self, value=None):
        """
        External network destination to which we route
        after network translation.

        .. note:: Used for host-based NAT configuration.
        """
        if value is not None:
            self._ext_netdst = value
        else:
            return self._ext_netdst
    ext_netdst = property(fget=ext_netdst, fset=ext_netdst)

    def __init__(self):
        """Construct a nonconfigured netconfig."""
        self._interfaces = {}

        self._netdst = None
        self._netmask = None
        self._gateway = None
        self._net_ip = None
        self._host_ip = None

        self._range = None
        self._domain = None
        self._forwarder = None
        self._rev = None
        self._view = None

        self._ext_netdst = None

    def __repr__(self):
        net_tuple = (self.net_ip, self.netmask, self.netdst)
        return "[net] addr='%s', netmask='%s', netdst='%s'" % net_tuple

    def _get_network_ip(self, ip, bit):
        interface = ipaddress.ip_interface("%s/%s" % (ip, bit))
        return str(interface.network.network_address)

    def from_interface(self, interface):
        """
        Construct all netconfig parameters from the provided interface or reset
        them with respect to that interface if they were already set.

        :param interface: reference interface for the configuration
        :type interface: Interface object
        """
        # main
        self.netdst = interface.params.get("netdst")
        self.netmask = interface.params["netmask"]
        self.gateway = interface.params.get("ip_provider", "0.0.0.0")
        self.net_ip = self._get_network_ip(interface.ip, self.mask_bit)
        self.host_ip = interface.params.get("host")

        # DHCP specific
        pool_range = interface.params.get("range", "100-200").split("-")
        self.range = {i: False for i in range(int(pool_range[0]),
                                              int(pool_range[1])+1)}

        # DNS specific
        self.domain = interface.params.get("domain_provider")
        self.forwarder = interface.params.get("default_dns_forwarder")
        # TODO: generate this more appropriately
        self.rev = ".".join(reversed(self.net_ip.split(".")[:-1]))
        if self.domain is not None:
            self.view = "%s-%s" % (self.domain, self.net_ip)

        # NAT specific
        self.ext_netdst = interface.params.get("postrouting_netdst")

    def add_interface(self, interface):
        """
        Add an interface to the netconfig, performing the necessary registrations
        and finishing with validation of the interface configuration.

        :param interface: interface to add to the netconfig
        :type interface: Interface object
        """
        self.interfaces[interface.ip] = interface
        self.interfaces[interface.ip].netconfig = self
        self.validate()

    def has_interface(self, interface):
        """
        Check whether an interface already belongs to the netconfig.

        :param interface: interface to check in the netconfig
        :type interface: Interface object
        :returns: whether the interface is already present in the netconfig
        :rtype: bool
        """
        return interface.ip in self.interfaces.keys()

    def can_add_interface(self, interface):
        """
        Check if an interface can be added to the netconfig based on its
        desired IP address and throw Exceptions if it is already present
        or the netmask does not coincide (misconfiguration errors).

        :param interface: interface to add to the netconfig
        :type interface: Interface object
        :returns: whether the interface can be added
        :rtype: bool
        :raises: :py:class:`exceptions.IndexError` if interface is already present or incompatible
        """
        if self.has_interface(interface):
            raise IndexError("Interface %s already present in the "
                             "network %s" % (interface.ip, self.net_ip))
        interface_net_ip = self._get_network_ip(interface.ip, self.mask_bit)
        if interface_net_ip == self.net_ip and interface.params["netmask"] != self.netmask:
            raise IndexError("Interface %s has different netmask %s from the "
                             "network %s (%s)" % (interface.ip, interface.params["netmask"],
                                                  self.net_ip, self.netmask))
        return interface_net_ip == self.net_ip

    def validate(self):
        """
        Check for sanity of the netconfigs parameters.

        :raises: :py:class:`exceptions.TestError` if the validation fails
        """
        logging.debug("Validating the parameter derived netconfig %s", self)

        # validate network addresses
        addresses = {}
        # NOTE: it is possible that either the host was never defined or was later on disabled
        if self.host_ip is not None and self.host_ip != "":
            addresses["host"] = ipaddress.ip_interface('%s/%s' % (self.host_ip, self.mask_bit))
        assert self.ip_start is not None
        assert self.ip_end is not None
        addresses["ip_start"] = ipaddress.ip_interface('%s/%s' % (self.ip_start, self.mask_bit))
        addresses["ip_end"] = ipaddress.ip_interface('%s/%s' % (self.ip_end, self.mask_bit))

        own = ipaddress.ip_interface('%s/%s' % (self.net_ip, self.mask_bit))
        for key in addresses.keys():
            if addresses[key] not in own.network:
                raise exceptions.TestError("The predefined %s %s is not in the netconfig"
                                           " %s" % (key, addresses[key], self.net_ip))

        # validate interfaces
        for interface in self.interfaces.values():
            assert interface.netconfig == self
            assert self.interfaces[interface.ip] == interface

            ip = ipaddress.ip_interface('%s/%s' % (interface.ip, self.mask_bit))
            if ip not in own.network:
                raise exceptions.TestError("The interface with ip %s is not in the netconfig"
                                           " %s" % (ip, self.net_ip))

    def get_allocatable_address(self):
        """
        Return the next IP address in the pool of available IPs that
        can be used by DHCP clients in the network.
        """
        for val in self.range:
            if self.range[val] is False:
                self.range[val] = True
                new_address = val
                break
        else:
            raise IndexError("IP address range (%d) exhausted."
                             % len(self.range))
        net_ip = ipaddress.IPv4Address(str(self.net_ip))
        return str(ipaddress.IPv4Address(str(net_ip + new_address)))

    def translate_address(self, ip, nat_ip):
        """
        Return the NAT translated IP of an interface or alternatively the IP
        of an interface masked by a desired network address.

        :param interface: interface to translate
        :type interface: Interface object
        :param str nat_ip: NATed IP to use for reference
        :returns: the translated IP of the interface
        :rtype: str
        """
        source_ip = ipaddress.IPv4Address(ip)
        source_part = int(source_ip) - int(ipaddress.IPv4Address(str(self.net_ip)))
        target_iface = ipaddress.ip_interface("%s/%s" % (nat_ip, self.mask_bit))
        target_part = int(target_iface.network.network_address)
        translated_ip = ipaddress.IPv4Address(source_part + target_part)
        return str(translated_ip)
