import sys
import os
import re

from avocado.core.output import LOG_JOB as log
from avocado.core.plugin_interfaces import CLICmd

from . import cmd_parser
from . import params_parser as param
from . import intertest_setup as intertest


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

    def run(self, args):
        """
        Take care of command line overwriting, parameter preparation,
        setup and cleanup chains, and paths/utilities for all host controls.
        """
        log.info("Manual setup chain started.")
        # set English environment (command output might be localized, need to be safe)
        os.environ['LANG'] = 'en_US.UTF-8'

        cmd_parser.params_from_cmd(args)

        run_config = param.Reparsable()
        run_config.parse_next_batch(base_file="guest-base.cfg",
                                    ovrwrt_file=param.vms_ovrwrt_file,
                                    ovrwrt_str=args.param_str,
                                    ovrwrt_dict={"vms": " ".join(args.selected_vms)})
        run_params = run_config.get_params()
        # prepare a setup step or a chain of such
        run_params["count"] = 0
        setup_chain = run_params["setup"].split()
        for setup_step in setup_chain:
            setup_func = getattr(intertest, setup_step)
            setup_func(args, run_params, "0m%s" % run_params["count"])
            run_params["count"] += 1

        log.info("Manual setup chain finished.")
