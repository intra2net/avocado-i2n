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
import sys

import aexpect


class VMNode(object):
    """
    The vmnode class - a collection of interfaces
    sharing the same platform.
    """

    """Structural properties"""
    def interfaces(self, value=None):
        """A collection of interfaces the vmnode represents."""
        if value is not None:
            self._interfaces = value
        else:
            return self._interfaces
    interfaces = property(fget=interfaces, fset=interfaces)

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

    def __init__(self, platform):
        """
        Construct a vm node from a vm platform.

        :param platform: the vm platform that communicates in the vm network
        :type platform: VM object
        """
        self._interfaces = {}

        self._platform = platform
        self._last_session = None

    def __repr__(self):
        vm_tuple = (self.name, len(self.remote_sessions))
        return "[node] name='%s', sessions='%s'" % vm_tuple

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

        This is currently supported only for intranators.

        :param bool trigger: whether to trigger the reboot or just wait for it
        :raises: :py:class:`exceptions.NotImplementedError` if vm node is not an intranator
        """
        if self.name not in ["vm1", "vm2", "vm3"]:
            raise NotImplementedError("Rebooting is only supported for intranators")

        if trigger:
            self.last_session.cmd("reboot")

        timeout = float(self.params.get("reboot_timeout", 600))
        try:
            self.last_session.cmd("tail -f /var/log/messages", timeout)

        except aexpect.ShellProcessTerminatedError as ex:
            last_words = ex.output
        self.get_session()
        return last_words
