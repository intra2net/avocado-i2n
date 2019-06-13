"""

SUMMARY
------------------------------------------------------
Module for handling all Cartesian config parsing and
further customization (wrapper of virt config parsing).

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import logging
import os
import re
import copy
import shutil
import collections

from virttest import cartesian_config
from virttest.utils_params import Params
from avocado.core.settings import settings


class EmptyCartesianProduct(Exception):
    """Empty Cartesian product of variants"""

    def __init__(self, message):
        """
        Initialize an empty Cartesian product exception.

        :param str message: additional message about the excaption
        """
        message = "Empty Cartesian product of parameters!\n" + message
        message = "Check for self-excluding variants in your current configuration:\n" + message
        super(EmptyCartesianProduct, self).__init__(message)


###################################################################
# preprocessing
###################################################################


default_tp_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tp_folder"))
custom_configs_dir = settings.get_value('i2n.common', 'suite_path', default=default_tp_folder)
custom_configs_dir = os.path.join(custom_configs_dir, "configs")
tests_ovrwrt_file = "avocado_overwrite_tests.cfg"
vms_ovrwrt_file = "avocado_overwrite_vms.cfg"
if not os.path.exists(os.path.join(os.environ['HOME'], tests_ovrwrt_file)):
    logging.warning("Generating a file to use for overwriting the original test parameters")
    shutil.copyfile(os.path.join(custom_configs_dir, "sets-overwrite.cfg"),
                    os.path.join(os.environ['HOME'], tests_ovrwrt_file))
if not os.path.exists(os.path.join(os.environ['HOME'], vms_ovrwrt_file)):
    logging.warning("Generating a file to use for overwriting the original vm parameters")
    shutil.copyfile(os.path.join(custom_configs_dir, "objects-overwrite.cfg"),
                    os.path.join(os.environ['HOME'], vms_ovrwrt_file))


###################################################################
# main parameter parsing methods
###################################################################


def print_restriction(base_file="", base_str="", ovrwrt_file="", ovrwrt_str=""):
    """
    Return any available information about a parser restriction.

    :param str base_file: file to be parsed first
    :param str base_str: string to be parsed first
    :param str ovrwrt_file: file to be parsed last
    :param str ovrwrt_str: string to be parsed last
    :returns: structured text of the base/ovrwrt file/string contents
    :rtype: str
    """
    restriction = "Parsing parameters with the following configuration:\n"
    restriction += "\tBase file:\n\t\t%s\n" % base_file if base_file != "" else ""
    restriction += "\tBase string:\n\t\t%s\n" % base_str.replace("\n", "\n\t\t") if base_str != "" else ""
    restriction += "\tOverwrite file:\n\t\t%s\n" % ovrwrt_file if ovrwrt_file != "" else ""
    restriction += "\tOverwrite string:\n\t\t%s\n" % ovrwrt_str.replace("\n", "\n\t\t") if ovrwrt_str != "" else ""
    return restriction


def copy_parser(parser):
    """
    Copy a parser in the most efficient way possible.

    :param parser: source parser to copy from
    :type parser: Parser object
    :returns: new parser copy
    :rtype: Parser object
    """
    new_parser = cartesian_config.Parser()
    new_parser.node.content = copy.copy(parser.node.content)
    new_parser.node.children = copy.copy(parser.node.children)
    new_parser.node.labels = copy.copy(parser.node.labels)
    return new_parser


def prepare_parser(base_dict=None, base_str="", base_file=None,
                   ovrwrt_dict=None, ovrwrt_str="", ovrwrt_file=None,
                   show_restriction=False, show_dictionaries=False,
                   show_dict_fullname=False, show_dict_contents=False):
    """
    Get a basic parameters parser with its dictionaries.

    :param base_file: file to be parsed first
    :type base_file: str or None
    :param str base_str: string to be parsed first
    :param base_dict: params to be added first
    :type base_dict: {str, str} or None

    :param ovrwrt_file: file to be parsed last
    :type ovrwrt_file: str or None
    :param str ovrwrt_str: string to be parsed last
    :param ovrwrt_dict: params to be added last
    :type ovrwrt_dict: {str, str} or None

    :param bool show_restriction: whether to show the restriction strings
    :param bool show_dictionaries: whether to show the obtained variants
    :param bool show_dict_fullname: whether to show the variant fullname rather than its shortname
    :param bool show_dict_contents: whether to show the obtained variant parameters

    :returns: resulting parser
    :rtype: Parser object
    :raises: :py:class:`EmptyCartesianProduct` if no combination of the restrictions exists

    The priority of the setting follows the order of the arguments:
    Dictionary with some parameters is topmost, string with some
    parameters is next and the file with parameters is taken as a base.
    The overwriting version is taken last, the base version first.
    """
    parser = cartesian_config.Parser()
    hostname = os.environ.get("PREFIX", os.environ.get("HOSTNAME", "avocado"))
    parser.parse_string("hostname = %s\n" % hostname)

    # configuration base
    if base_file is not None:
        parser.parse_file(os.path.join(custom_configs_dir, base_file))
    if base_dict is not None:
        base_str += dict_to_str(base_dict)
    parser.parse_string(base_str)

    # configuration top
    if ovrwrt_file is not None:
        parser.parse_file(os.path.join(os.environ['HOME'], ovrwrt_file))
    if ovrwrt_dict is not None:
        ovrwrt_str += dict_to_str(ovrwrt_dict)
    parser.parse_string(ovrwrt_str)

    # log any required information
    if show_restriction:
        logging.debug(print_restriction(base_file=base_file, base_str=base_str,
                                        ovrwrt_file=ovrwrt_file, ovrwrt_str=ovrwrt_str))
    if show_dictionaries:
        options = collections.namedtuple("options", ['repr_mode', 'fullname', 'contents'])
        cartesian_config.print_dicts(options(False, show_dict_fullname, show_dict_contents), parser.get_dicts())

    # detect empty Cartesian product
    try:
        parser.get_dicts().__next__()
    except StopIteration:
        raise EmptyCartesianProduct(print_restriction(base_file=base_file, base_str=base_str,
                                                      ovrwrt_file=ovrwrt_file, ovrwrt_str=ovrwrt_str)) from None

    return parser


def update_parser(parser, ovrwrt_dict=None, ovrwrt_str="",
                  ovrwrt_file=None, ovrwrt_base_file=None,
                  show_restriction=False, show_dictionaries=False,
                  show_dict_fullname=False, show_dict_contents=False):
    """
    Get a new independent parser from an old already provided one.

    :param ovrwrt_base_file: file to be parsed first
    :type ovrwrt_base_file: str or None
    :param ovrwrt_file: file to be parsed last
    :type ovrwrt_file: str or None
    :param str ovrwrt_str: string to be parsed last
    :param ovrwrt_dict: params to be added last
    :type ovrwrt_dict: {str, str} or None

    :param bool show_restriction: whether to show the restriction strings
    :param bool show_dictionaries: whether to show the obtained variants
    :param bool show_dict_fullname: whether to show the variant fullname rather than its shortname
    :param bool show_dict_contents: whether to show the obtained variant parameters

    :returns: resulting parser
    :rtype: Parser object
    :raises: :py:class:`EmptyCartesianProduct` if no combination of the restrictions exists
    """
    parser = copy_parser(parser)

    # configuration update
    if ovrwrt_base_file is not None:
        parser.parse_file(os.path.join(custom_configs_dir, ovrwrt_base_file))
    if ovrwrt_file is not None:
        parser.parse_file(os.path.join(os.environ['HOME'], ovrwrt_file))
    if ovrwrt_dict is not None:
        ovrwrt_str += dict_to_str(ovrwrt_dict)
    parser.parse_string(ovrwrt_str)

    # log any required information
    if show_restriction:
        logging.debug(print_restriction(base_file=ovrwrt_base_file,
                                        ovrwrt_file=ovrwrt_file, ovrwrt_str=ovrwrt_str))
    if show_dictionaries:
        options = collections.namedtuple("options", ['repr_mode', 'fullname', 'contents'])
        cartesian_config.print_dicts(options(False, show_dict_fullname, show_dict_contents), parser.get_dicts())

    # detect empty Cartesian product
    try:
        parser.get_dicts().__next__()
    except StopIteration:
        raise EmptyCartesianProduct(print_restriction(base_file=ovrwrt_base_file,
                                                      ovrwrt_file=ovrwrt_file, ovrwrt_str=ovrwrt_str)) from None

    return parser


def prepare_params(list_of_keys=None,
                   base_dict=None, base_str="", base_file=None,
                   ovrwrt_dict=None, ovrwrt_str="", ovrwrt_file=None,
                   show_restriction=False, show_dictionaries=False,
                   show_dict_fullname=False, show_dict_contents=False):
    """
    Get listed parameters from the main configuration file (used for defaults).

    :param list_of_keys: list of parameters key in the final selection
    :type list_of_keys: [str] or None
    :returns: first variant dictionary from the prepared parser
    :rtype: Params object

    The rest of the parameters are identical to the methods before.

    For specifying the product for the parameters, the overwrite string with 'only'
    can be used. Otherwise, 'only parse_params' together with default product is
    used as a dummy restriction to get the parameters but avoid Cartesian explosion.
    So if you specify `only` be careful for such possibility.
    """
    parser = prepare_parser(base_dict=base_dict, base_str=base_str, base_file=base_file,
                            ovrwrt_dict=ovrwrt_dict, ovrwrt_str=ovrwrt_str, ovrwrt_file=ovrwrt_file,
                            show_restriction=show_restriction,
                            show_dictionaries=show_dictionaries,
                            show_dict_fullname=show_dict_fullname,
                            show_dict_contents=show_dict_contents)
    return peek(parser)


###################################################################
# overwrite string and overwrite dictionary automation methods
###################################################################


def all_vms():
    """
    Return all vms that can be passed for any test configuration.

    :returns: all available (from configuration) vms
    :rtype: list
    """
    return prepare_params(list_of_keys=["vms"], base_file="guest-base.cfg").objects("vms")


def peek(parser, list_of_keys=None):
    """
    Peek into a parsed dictionary.

    :param parser: parser to get the first variant dictionary from
    :type parser: Parser object
    :param list_of_keys: list of parameters key in the final selection
    :type list_of_keys: [str] or None
    :returns: the first variant dictionary from the prepared parser
    :rtype: Params object
    """
    default_params = parser.get_dicts().__next__()
    if list_of_keys is None:
        selected_params = default_params
    else:
        selected_params = {key: default_params[key] for key in list_of_keys}
    return Params(selected_params)


def dict_to_str(param_dict):
    """
    Convert parameter dictionary into parameter string.

    :param param_dict: parameters dictionary to be converted
    :type param_dict: {str, str}
    :returns: resulting parameter string
    :rtype: str
    """
    param_str = ""
    for (key, value) in param_dict.items():
        param_str += "%s = %s\n" % (key, value)
    return param_str


def re_str(variant, ovrwrt_str="", tag="", objectless=False):
    """
    Add a variant restriction to the overwrite string, optionally
    adding a custom tag as well.

    :param str variant: variant restriction
    :param str ovrwrt_str: string where the variant restriction will be added
    :param str tag: additional tag to the variant combination
    :param bool objectless: whether the restricted test variants have specified any test objects
    :returns: restricted parameter string
    :rtype: str
    """
    if tag != "":
        subtest_variant = "variants:\n    - %s:\n        only %s\n" % (tag, variant)
    else:
        subtest_variant = "only %s\n" % variant
    if objectless:
        setup_variant = "only nonleaves\n"
    else:
        setup_variant = ""
    ovrwrt_str = subtest_variant + ovrwrt_str + setup_variant
    return ovrwrt_str


def vm_str(vms, variant_strs):
    """
    Add a vm variant restriction to the overwrite string, reaching
    exactly one vm variant afterwards.

    :param str vms: vms to be kept as variants into the selection
    :param variant_strs: variant restrictions for each vm as key, value pair
    :type variant_strs: {str, str}
    :returns: restricted parameter string
    :rtype: str
    """
    variant_str = ""
    for vm, variant in variant_strs.items():
        subvariant = "".join(["    " + l + "\n" for l in variant.split("\n")])
        variant_str += "%s:\n%s" % (vm, subvariant)
    variant_str += "join " + vms + "\n"
    return variant_str
