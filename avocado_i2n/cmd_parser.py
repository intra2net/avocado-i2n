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

import sys
import os
import re

from avocado.core.output import LOG_JOB as log
from virttest import env_process

from . import params_parser as param
from . import state_setup
from .vmnet import VMNetwork


def params_from_cmd(config):
    """
    Take care of command line overwriting, parameter preparation,
    setup and cleanup chains, and paths/utilities for all host controls.

    :param config: command line arguments
    :type config: {str, str}
    :raises: :py:class:`ValueError` if a command line selected vm is not available
             from the configuration and thus supported or internal tests are
             restricted from the command line
    """
    sys.path.insert(1, os.path.join(param.suite_path, "utils"))

    # validate typed vm names and possible vm specific restrictions
    available_vms = param.all_vms()
    available_restrictions = param.all_restrictions()

    # defaults usage vs command line overriding
    use_tests_default = True
    with_nontrivial_restrictions = False
    use_vms_default = {vm_name: True for vm_name in available_vms}
    with_selected_vms = list(available_vms)

    # the run string includes only pure parameters
    param_dict = {}
    # the tests string includes the test restrictions while the vm strings include the ones for the vm variants
    tests_str, vm_strs = "", {vm: "" for vm in available_vms}

    # main tokenizing loop
    for cmd_param in config["params"]:
        re_param = re.match(r"(\w+)=(.*)", cmd_param)
        if re_param is None:
            log.error("Skipping malformed parameter on the command line '%s' - "
                      "must be of the form <key>=<val>", cmd_param)
            continue
        (key, value) = re_param.group(1, 2)
        if key == "only" or key == "no":
            # detect if this is the primary restriction to escape defaults
            if value in available_restrictions:
                use_tests_default = False
            # else this is an auxiliary restriction
            else:
                with_nontrivial_restrictions = True
            # main test restriction part
            tests_str += "%s %s\n" % (key, value)
        elif key.startswith("only_") or key.startswith("no_"):
            for vm_name in available_vms:
                if re.match("(only|no)_%s" % vm_name, key):
                    # escape defaults for this vm and use the command line
                    use_vms_default[vm_name] = False
                    # main vm restriction part
                    vm_strs[vm_name] += "%s %s\n" % (key.replace("_%s" % vm_name, ""), value)
        # NOTE: comma in a parameter sense implies the same as space in config file
        elif key == "vms":
            # NOTE: no restrictions of the required vms are allowed during tests since
            # these are specified by each test (allowed only for manual setup steps)
            with_selected_vms[:] = value.split(",")
            for vm_name in with_selected_vms:
                if vm_name not in available_vms:
                    raise ValueError("The vm '%s' is not among the supported vms: "
                                     "%s" % (vm_name, ", ".join(available_vms)))
        else:
            # NOTE: comma on the command line is space in a config file
            value = value.replace(",", " ")
            param_dict[key] = value
    config["param_dict"] = param_dict
    log.debug("Parsed param dict '%s'", param_dict)

    # get minimal configurations and parse defaults if no command line arguments
    config["vms_params"], config["vm_strs"] = full_vm_params_and_strs(param_dict, vm_strs,
                                                                      use_vms_default)
    config["vms_params"]["vms"] = " ".join(with_selected_vms)
    config["available_vms"] = vm_strs.copy()
    for vm_name in available_vms:
        # the keys of vm strings must be equivalent to the selected vms
        if vm_name not in with_selected_vms:
            del config["vm_strs"][vm_name]
    config["tests_params"], config["tests_str"] = full_tests_params_and_str(param_dict, tests_str,
                                                                            use_tests_default)
    config["available_restrictions"] = available_restrictions

    # control against invoking only runnable tests and empty Cartesian products
    control_config = param.Reparsable()
    control_config.parse_next_batch(base_file="sets.cfg",
                                    ovrwrt_file=param.tests_ovrwrt_file(),
                                    ovrwrt_str=config["tests_str"],
                                    ovrwrt_dict=config["param_dict"])
    control_parser = control_config.get_parser()
    if with_nontrivial_restrictions:
        log.info("%s tests with nontrivial restriction %s",
                 len(list(control_parser.get_dicts())), config["tests_str"])

    # prefix for all tests of the current run making it possible to perform multiple runs in one command
    config["prefix"] = ""

    # log into files for each major level the way it was done for autotest
    config["run.store_logging_stream"] = [":10", ":20", ":30", ":40"]

    # attach environment processing hooks
    env_process_hooks()


def full_vm_params_and_strs(param_dict, vm_strs, use_vms_default):
    """
    Add default vm parameters and strings for missing command line such.

    :param param_dict: runtime parameters used for extra customization
    :type param_dict: {str, str} or None
    :param vm_strs: command line vm-specific names and variant restrictions
    :type vm_strs: {str, str}
    :param use_vms_default: whether to use default variant restriction for a
                            particular vm
    :type use_vms_default: {str, bool}
    :returns: complete vm parameters and strings
    :rtype: (:py:class:`Params`, {str, str})
    :raises: :py:class:`ValueError` if no command line or default variant
             restriction could be found for some vm
    """
    vms_config = param.Reparsable()
    vms_config.parse_next_batch(base_file="guest-base.cfg",
                                ovrwrt_file=param.vms_ovrwrt_file(),
                                ovrwrt_dict=param_dict)
    vms_params = vms_config.get_params()
    for vm_name in param.all_vms():
        if use_vms_default[vm_name]:
            default = vms_params.get("default_only_%s" % vm_name)
            if not default:
                raise ValueError("No default variant restriction found for %s!" % vm_name)
            vm_strs[vm_name] += "only %s\n" % default
    log.debug("Parsed vm strings '%s'", vm_strs)
    return vms_params, vm_strs


def full_tests_params_and_str(param_dict, tests_str, use_tests_default):
    """
    Add default tests parameters and string for missing command line such.

    :param param_dict: runtime parameters used for extra customization
    :type param_dict: {str, str} or None
    :param str tests_str: command line variant restrictions
    :param bool use_tests_default: whether to use default primary restriction
    :returns: complete tests parameters and string
    :rtype: (:py:class:`Params`, str)
    :raises: :py:class:`ValueError` if the default primary restriction could is
             not valid (among the available ones)
    """
    tests_config = param.Reparsable()
    tests_config.parse_next_batch(base_file="groups-base.cfg",
                                  ovrwrt_file=param.tests_ovrwrt_file(),
                                  ovrwrt_dict=param_dict)
    tests_params = tests_config.get_params()
    if use_tests_default:
        default = tests_params.get("default_only", "all")
        available_restrictions = param.all_restrictions()
        if default not in available_restrictions:
            raise ValueError("Invalid primary restriction 'only=%s'! It has to be one "
                             "of %s" % (default, ", ".join(available_restrictions)))
        tests_str += "only %s\n" % default
    log.debug("Parsed tests string '%s'", tests_str)
    return tests_params, tests_str


def env_process_hooks():
    """
    Add env processing hooks to handle on/off state get/set operations
    and vmnet networking setup and instance attachment to environment.
    """
    def get_network_state(test, params, env):
        vmn = VMNetwork(test, params, env)
        vmn.setup_host_bridges()
        vmn.setup_host_services()
        env.vmnet = vmn
        type(env).get_vmnet = lambda self: self.vmnet
    def network_state(fn):
        def wrapper(test, params, env):
            get_network_state(test, params, env)
            fn(test, params, env)
        return wrapper
    def on_state(fn):
        def wrapper(test, params, env):
            params["skip_types"] = "off"
            fn(params, env)
            del params["skip_types"]
        return wrapper
    def off_state(fn):
        def wrapper(test, params, env):
            params["skip_types"] = "on"
            fn(params, env)
            del params["skip_types"]
        return wrapper
    env_process.preprocess_vm_off_hook = off_state(state_setup.get_state)
    env_process.preprocess_vm_on_hook = network_state(on_state(state_setup.get_state))
    env_process.postprocess_vm_on_hook = on_state(state_setup.set_state)
    env_process.postprocess_vm_off_hook = off_state(state_setup.set_state)
