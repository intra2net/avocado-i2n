import sys
import os
import re

from avocado.core.loader import loader
from avocado.core.output import LOG_JOB as log
from avocado.core.plugin_interfaces import CLI

from . import cmd_parser
from .loader import CartesianLoader
from .runner import CartesianRunner


class Auto(CLI):

    name = 'auto'
    description = 'Autotesting using restriction-generated graph of setup state dependencies.'

    def configure(self, parser):
        """
        Add the subparser for the run action.

        :param parser: Main test runner parser.
        """
        run_subcommand_parser = parser.subcommands.choices.get('run', None)
        if run_subcommand_parser is None:
            return

        msg = 'test execution using restriction-generated graph of setup state dependencies'
        cmd_parser = run_subcommand_parser.add_argument_group(msg)
        cmd_parser.add_argument("--auto", action="store_true", help="Run in auto mode.")

    def run(self, config):
        """
        Take care of command line overwriting, parameter preparation,
        setup and cleanup chains, and paths/utilities for all host controls.
        """
        if config.get("references"):
            # graph generated tests are not 1-to-1 mapped to test references which is the
            # original invocation notion but N-to-1 and generated from just one test reference
            assert len(config["references"]) == 1, "Cartesian graph run supports maximally one test reference"
            # test references (here called test restrictions) are mixed with run (overwrite) parameters
            config["params"] = config["references"][0].split()
        elif not config.get("params"):
            config["params"] = []
        cmd_parser.params_from_cmd(config)

        loader.register_plugin(CartesianLoader)
        if config.get("auto") and config["auto"]:
            config["test_runner"] = CartesianRunner
