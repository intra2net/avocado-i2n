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


def vm_str(vms, ovrwrt_str):
    """
    Add a vm variant restriction to the overwrite string, reaching
    exactly one vm variant afterwards.

    :param str vms: vms to be kept as variants into the selection
    :param str ovrwrt_str: string where the variant restriction will be added
    :returns: restricted parameter string
    :rtype: str
    """
    variant_str = ovrwrt_str
    some_vms = vms.split(" ")
    left_vms = [vm for vm in all_vms() if vm not in some_vms]
    variant_str = "only %s\n%s" % ("..".join(some_vms), variant_str)
    variant_str = "no %s\n%s" % (",".join(left_vms), variant_str)
    return variant_str


###################################################################
# parameter manipuation for heterogeneuous variantization
###################################################################


def is_object_specific(key, param_objects):
    """
    Check if a parameter key is object specific.

    :param str key: key to be checked
    :param param_objects: parameter objects to compare against
    :type param_objects: [str]
    :returns: whether the parameter key is object specific
    :rtype: bool
    """
    for any_object_name in param_objects:
        if re.match(".+_%s$" % any_object_name, key):
            return True
    return False


def object_params(params, name, param_objects):
    """
    Prune all "_objname" params in the parameter dictionary,
    converting to general params for a preferred parameters object.

    :param params: parameters to be 'unobjectified'
    :type params: {str, str}
    :param str name: name of the parameters object whose parameters will be kept
    :param param_objects: the parameter objects to compare against
    :type param_objects: [str]
    :returns: general object-specific parameters
    :rtype: Params object
    """
    params = Params(params)
    object_params = params.object_params(name)
    for key in params.keys():
        if is_object_specific(key, param_objects):
            object_params.pop(key)
    return object_params


def objectify_params(params, name, param_objects):
    """
    Leave only "_objname" params in the parameter dictionary,
    converting general params and pruning params of different objects.

    :param params: parameters to be 'objectified'
    :type params: {str, str}
    :param str name: name of the parameters object whose parameters will be kept
    :param param_objects: the parameter objects to compare against
    :type param_objects: [str]
    :returns: specialized object-specific parameters
    :rtype: Params object

    This method is the opposite of the :py:func:`object_params` one.
    """
    objectified_params = Params(params)
    for key in params.keys():
        if not is_object_specific(key, param_objects):
            if objectified_params.get("%s_%s" % (key, name), None) is None:
                objectified_params["%s_%s" % (key, name)] = objectified_params[key]
            objectified_params.pop(key)
        elif not re.match(".+_%s$" % name, key):
            objectified_params.pop(key)
    return objectified_params


def merge_object_params(param_objects, param_dicts, objects_key="", main_object="", objectify=True):
    """
    Produce a single dictionary of parameters from multiple versions with possibly
    overlapping and conflicting parameters using object identifier.

    :param param_objects: parameter objects whose configurations will be combined
    :type param_objects: [str]
    :param param_dicts: parameter dictionaries for each parameter object
    :type param_dicts: [{str, str}]
    :param str objects_key: key for the merged parameter objects (usually vms)
    :param str main_object: the main parameter objects whose parameters will also be the default ones
    :param bool objectify: whether to objecctify the separate parameter dictionaries as preprocessing
    :returns: merged object-specific parameters
    :rtype: Params object

    The parameter containing the objects should also be specified so that it is
    preserved during the dictionary merge.

    Overlapping and conflicting parameters will be resolved if the objectify flag
    is set to True, otherwise we will assume all the parameters are objectified.
    """
    if main_object == "":
        main_object = param_objects[0]
    assert len(param_objects) == len(param_dicts), "Every parameter dictionary needs an object identifier"
    # turn into object appended parameters to make fully accessible in the end
    if objectify:
        for i in range(len(param_objects)):
            param_dicts[i] = objectify_params(param_dicts[i], param_objects[i], param_objects)
    merged_params = Params({})
    for param_dict in param_dicts:
        merged_params.update(param_dict)

    # collapse back identical parameters
    assert len(param_objects) >= 2, "At least two object dictionaries are needed for merge"
    main_index = param_objects.index(main_object)
    universal_params = object_params(param_dicts[main_index], param_objects[main_index], param_objects)
    # NOTE: remove internal parameters which don't concern us to avoid any side effects
    universal_params = universal_params.drop_dict_internals()
    for key in universal_params.keys():
        merged_params[key] = universal_params[key]
        for i in range(len(param_objects)):
            vm_key = "%s_%s" % (key, param_objects[i])
            objects_vm_key = "%s_%s" % (objects_key, param_objects[i])
            if merged_params[key] == merged_params.get(vm_key, None):
                merged_params.pop(vm_key)
            if vm_key == objects_vm_key and merged_params.get(vm_key, None) is not None:
                merged_params.pop(vm_key)

    merged_params[objects_key] = " ".join(param_objects)
    return merged_params


def multiply_params_per_object(params, param_objects):
    """
    Generate unique parameter values for each listed parameter object
    using its name.

    :param params: parameters to be extended per parameter object
    :type params: {str, str}
    :param param_objects: the parameter objects to multiply with
    :type param_objects: [str]
    :returns: multiplied object-specific parameters
    :rtype: Params object

    .. note:: If a `PREFIX` environment variable is set, the multiplied
        paramers will also be prefixed with its value. This is useful for
        performing multiple test runs in parallel.
    .. note:: Currently only implemented for vm objects.
    """
    multipled_params = Params(params)
    unique_keys = multipled_params.objects("vm_unique_keys")
    prefix = os.environ['PREFIX'] if 'PREFIX' in os.environ else 'at'
    for key in unique_keys:
        for name in param_objects:
            vmkey = "%s_%s" % (key, name)
            value = multipled_params.get(vmkey, multipled_params.get(key, ""))
            if value != "":
                # TODO: still need to handle better cases where a unique directory
                # is required (e.g. due to mount locations) like this one
                if key == "image_name" and ".lvm." in multipled_params["name"]:
                    multipled_params[vmkey] = "%s_%s/%s" % (prefix, name, value)
                else:
                    multipled_params[vmkey] = "%s_%s_%s" % (prefix, name, value)
    return multipled_params
