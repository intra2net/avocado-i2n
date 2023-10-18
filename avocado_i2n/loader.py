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
Specialized test loader for the plugin.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import logging as log
logging = log.getLogger('avocado.job.' + __name__)

from avocado.core.plugin_interfaces import Resolver
from avocado.core.resolver import ReferenceResolution, ReferenceResolutionResult

from .cartgraph import TestGraph


class CartesianLoader(Resolver):
    """Test loader for Cartesian graph parsing."""

    name = 'cartesian_loader'
    description = 'Loads tests from initial Cartesian product'

    def __init__(self, config=None, extra_params=None):
        """
        Construct the Cartesian loader.

        :param config: command line arguments
        :type config: {str, str}
        :param extra_params: extra configuration parameters
        :type extra_params: {str, str}
        """
        extra_params = {} if not extra_params else extra_params
        self.logdir = extra_params.pop('logdir', ".")
        super().__init__()

    def resolve(self, reference):
        """
        Discover (possible) tests from test references.

        :param reference: tests reference used to produce tests
        :type reference: str or None
        :returns: test factories as tuples of the test class and its parameters
        :rtype: [(type, {str, str})]
        """
        if reference is not None:
            assert reference.split() == self.config["params"]

        params, restriction = self.config["param_dict"], self.config["tests_str"]
        return ReferenceResolution(reference, ReferenceResolutionResult.SUCCESS,
                                   TestGraph.parse_flat_nodes(restriction, params))
