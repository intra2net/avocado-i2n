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

import os

from avocado.core.output import LOG_JOB as log
from avocado.core.plugin_interfaces import CLICmd

from .. import cmd_parser
from .. import intertest_setup as intertest


class Manu(CLICmd):

    name = 'manu'
    description = 'Tools using setup chains of manual steps with Cartesian graph manipulation.'

    def configure(self, parser):
        """
        Add the parser for the manual action.

        :param parser: Main test runner parser.
        """
        parser = super(Manu, self).configure(parser)
        parser.add_argument("params", default=[], nargs='*',
                            help="List of 'key=value' pairs passed to a Cartesian parser.")

    def run(self, config):
        """
        Take care of command line overwriting, parameter preparation,
        setup and cleanup chains, and paths/utilities for all host controls.
        """
        log.info("Manual setup chain started.")
        # set English environment (command output might be localized, need to be safe)
        os.environ['LANG'] = 'en_US.UTF-8'

        cmd_parser.params_from_cmd(config)
        intertest.load_addons_tools()
        run_params = config["vms_params"]

        # prepare a setup step or a chain of such
        setup_chain = run_params.objects("setup")
        for i, setup_step in enumerate(setup_chain):
            run_params["count"] = i
            setup_func = getattr(intertest, setup_step)
            setup_func(config, "0m%s" % i)

        log.info("Manual setup chain finished.")
