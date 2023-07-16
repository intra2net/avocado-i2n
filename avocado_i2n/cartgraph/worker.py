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

    def __init__(self, id):
        """
        Construct a test worker (execution environment) for any test nodes (tests).

        The rest of the arguments are inherited from the base class.
        """
        super().__init__(id)
        self.spawner = "lxc"

    def __repr__(self):
        return f"[worker] id='{self.id}', spawner='{self.spawner}'"

    def set_up(self) -> bool:
        """
        Start the environment for executing a test node.

        :returns: whether the environment is available after current or previous start
        :raises: :py:class:`ValueError` when environment ID could not be parsed
        """
        env_tuple = tuple(self.id.split("/"))
        if len(env_tuple) == 1:
            if env_tuple[0] == "":
                logging.debug("Serial runs do not have any bootable environment")
                return True
            import lxc
            cid = "c" + self.id
            container = lxc.Container(cid)
            if not container.running:
                logging.info(f"Starting bootable environment {cid}")
                return container.start()
            return container.running
        elif len(env_tuple) == 2:
            # TODO: send wake-on-lan package to start remote host (assuming routable)
            logging.warning("Assuming the remote host is running for now")
            return True
        else:
            raise ValueError(f"Environment ID {self.id} could not be parsed")
