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
VMNode object for the vmnet utility.

Copyright: Intra2net AG


CONTENTS
------------------------------------------------------
This class wraps up the functionality shared among the interfaces of
the same platform like session management, etc.


INTERFACE
------------------------------------------------------

"""

import logging

import aexpect


class VMNode(object):
    """
    The vmnode class - a collection of interfaces
    sharing the same platform.
    """

    """Structural properties"""
    def interfaces(self, value=None):
        """A collection of interfaces the vm node represents."""
        if value is not None:
            self._interfaces = value
        else:
            return self._interfaces
    interfaces = property(fget=interfaces, fset=interfaces)

    def ephemeral(self):
        """Whether the vm node is ephemeral (spawned in a network)."""
        return self._ephemeral
    ephemeral = property(fget=ephemeral)

    """Platform properties"""
    def platform(self, value=None):
        """
        A reference to the virtual machine object whose network
        configuration is represented by the vm node.
        """
        if value is not None:
            self._platform = value
        else:
            return self._platform
    platform = property(fget=platform, fset=platform)

    def name(self, value=None):
        """A proxy reference to the vm name."""
        if value is not None:
            self._platform.name = value
        else:
            return self._platform.name
    name = property(fget=name, fset=name)

    def params(self, value=None):
        """
        A proxy reference to the vm params.

        .. note:: this is just a shallow copy to preserve the hierarchy:
            network level params = test level params -> vmnode level params = test object params
            -> interface level params = rarely used outside of the vm network
        """
        if value is not None:
            self._platform.params = value
        else:
            return self._platform.params
    params = property(fget=params, fset=params)

    def remote_sessions(self, value=None):
        """A proxy reference to the vm sessions."""
        if value is not None:
            self._platform.remote_sessions = value
        else:
            return self._platform.remote_sessions
    remote_sessions = property(fget=remote_sessions, fset=remote_sessions)

    def last_session(self, value=None):
        """
        A pointer to the last created vm session.

        Used to facilitate the frequent access to a single session.
        """
        if value is not None:
            self._last_session = value
        else:
            return self._last_session
    last_session = property(fget=last_session, fset=last_session)

    def __init__(self, platform, ephemeral=False):
        """
        Construct a vm node from a vm platform.

        :param platform: the vm platform that communicates in the vm network
        :type platform: VM object
        :param bool ephemeral: whether the node is ephemeral (spawned in a network)
        """
        self._interfaces = {}

        self._ephemeral = ephemeral

        self._platform = platform
        self._last_session = None

    def __repr__(self):
        vm_tuple = (self.name, len(self.remote_sessions))
        return "[node] name='%s', sessions='%s'" % vm_tuple

    def check_interface(self, condition):
        """
        Check whether one of node's interfaces satisfies a boolean condition.

        :param condition: condition to try each interface on
        :type condition: function
        :returns: the first interface satisfying the provided criteria or None
        :rtype: Interface object or None
        """
        for interface in self.interfaces.values():
            if condition(interface):
                return interface
        return None

    def get_single_interface(self):
        """
        Get a single (first) interface of the node.

        This is useful for nodes having just one interface.
        """
        return list(self.interfaces.values())[0]

    def get_session(self, serial=False):
        """
        The basic network login - get a session from a vmnode.

        :param bool serial: whether to use serial connection
        """
        self.platform.verify_alive()
        timeout = float(self.params.get("login_timeout", 240))
        logging.info("Log in to %s with timeout %s", self.name, timeout)
        if serial:
            self.last_session = self.platform.wait_for_serial_login(timeout=timeout)
        else:
            self.last_session = self.platform.wait_for_login(timeout=timeout)
        # TODO: possibly use the original vm session list or remove this wrapper entirely
        self.platform.session = self.last_session
        return self.last_session

    def reboot(self, trigger=True):
        """
        Reboot or wait for a vm node to reboot returning its last words.

        :param bool trigger: whether to trigger the reboot or just wait for it
        :raises: :py:class:`exceptions.NotImplementedError` if vm node is not a linux machine

        This is currently supported only for linux vms.
        """
        if self.params["os_type"] != "linux":
            raise NotImplementedError("Rebooting is currently only supported for linux machines")

        if trigger:
            self.last_session.cmd("reboot")

        timeout = float(self.params.get("reboot_timeout", 600))
        try:
            self.last_session.cmd("tail -f /var/log/messages", timeout)

        except aexpect.ShellProcessTerminatedError as ex:
            last_words = ex.output
        self.get_session()
        return last_words
