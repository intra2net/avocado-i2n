# Copyright 2013-2023 Intranet AG and contributors
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
Utility for the main test suite substructures like test objects.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import logging as log
logging = log.getLogger('avocado.job.' + __name__)

from . import NetObject
from .. import params_parser as param


class TestEnvironment(object):

    def __init__(self, id: str):
        """
        Construct a test environment for any test nodes (tests).

        :param id: ID of the test environment
        """
        self.id = id


class TestSwarm(TestEnvironment):
    """A wrapper for a test swarm of workers traversing the graph."""

    def __init__(self, id):
        """
        Construct a test swarm (of sub-environments for execution) for any test nodes (tests).

        The rest of the arguments are inherited from the base class.
        """
        super().__init__(id)
        self.workers = []

    def __repr__(self):
        dump = f"[swarm] id='{self.id}', workers='{len(self.workers)}'"
        for worker in self.workers:
            dump = f"{dump}\n\t{worker}"
        return dump


class TestWorker(TestEnvironment):
    """A wrapper for a test worker traversing the graph."""

    run_slots = {}

    def params(self):
        """Parameters (cache) property."""
        return self.net.params
    params = property(fget=params)

    def __init__(self, id_net: NetObject):
        """
        Construct a test worker (execution environment) for any test nodes (tests).

        :param id_net: flat test net object to get configuration from

        The rest of the arguments are inherited from the base class.
        """
        super().__init__(id_net.params["shortname"])
        self.net = id_net
        self.spawner = None

    def __repr__(self):
        return f"[worker] id='{self.id}', spawner='{self.params['nets_spawner']}'"

    @staticmethod
    def slot_attributes(env_id: str) -> (str, str, str):
        env_tuple = tuple(env_id.split("/"))
        if len(env_tuple) == 1:
            env_net = ""
            env_name = "c" + env_tuple[0] if env_tuple[0] else ""
            # NOTE: at present handle empty environment id (lack of slots) as an indicator
            # of using non-isolated serial runs via the old process environment spawner
            env_type = "lxc" if env_name else "process"
        elif len(env_tuple) == 2:
            env_net = env_tuple[0]
            env_name = env_tuple[1]
            env_type = "remote"
        else:
            raise ValueError(f"Environment ID {env_id} could not be parsed")
        return env_net, env_name, env_type

    def set_up(self) -> bool:
        """
        Start the environment for executing a test node.

        :returns: whether the environment is available after current or previous start
        :raises: :py:class:`ValueError` when environment ID could not be parsed
        """
        logging.info(f"Setting up worker {self.id} environment")
        if self.params["nets_gateway"] == "":
            if self.params["nets_host"] == "":
                logging.debug("Serial runs do not have any bootable environment")
                return True
            import lxc
            cid = self.params["nets_host"]
            container = lxc.Container(cid)
            if not container.running:
                logging.info(f"Starting bootable environment {cid}")
                return container.start()
            return container.running
        else:
            # TODO: send wake-on-lan package to start remote host (assuming routable)
            logging.warning("Assuming the remote host is running for now")
            return True
