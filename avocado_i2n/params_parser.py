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
Module for handling all Cartesian config parsing and
making it reusable and maximally performant.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import logging
import os
import copy
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


_devel_tp_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tp_folder"))
suite_path = settings.get_value('i2n.common', 'suite_path', default=_devel_tp_folder)
def custom_configs_dir():
    """Custom directory for all config files."""
    return os.path.join(suite_path, "configs")


_tests_ovrwrt_file = "avocado_overwrite_tests.cfg"
def tests_ovrwrt_file():
    """Overwrite config file for all tests (nodes)."""
    ovrwrt_file = os.path.join(os.environ['HOME'], _tests_ovrwrt_file)
    if not os.path.exists(ovrwrt_file):
        logging.warning("Generating a file to use for overwriting the original test parameters")
        with open(ovrwrt_file, "w") as handle:
            handle.write("# Use this config to override with test nodes configuration\n"
                         "include " + os.path.join(custom_configs_dir(), "sets-overwrite.cfg") + "\n")
    return ovrwrt_file


_vms_ovrwrt_file = "avocado_overwrite_vms.cfg"
def vms_ovrwrt_file():
    """Overwrite config file for all vms (objects)."""
    ovrwrt_file = os.path.join(os.environ['HOME'], _vms_ovrwrt_file)
    if not os.path.exists(ovrwrt_file):
        logging.warning("Generating a file to use for overwriting the original vm parameters")
        with open(ovrwrt_file, "w") as handle:
            handle.write("# Use this config to override with test objects configuration\n"
                         "include " + os.path.join(custom_configs_dir(), "objects-overwrite.cfg") + "\n")
    return ovrwrt_file


###################################################################
# main parameter parsing methods
###################################################################


class ParsedContent():
    """Class for parsed content of a general type."""

    def __init__(self, content):
        """Initialize the parsed content."""
        self.content = content

    def reportable_form(self):
        """
        Parsed content representation used in reports of parsing steps.

        :returns: resulting report-compatible string
        :rtype: str
        :raises :py:class:`NotImlementedError` as this is an abstract method
        """
        raise NotImlementedError("Parsed content is an abstract class with no parsalbe form")

    def parsable_form(self):
        """
        Convert parameter content into parsable string.

        :returns: resulting parsable string
        :rtype: str
        :raises :py:class:`NotImlementedError` as this is an abstract method
        """
        raise NotImlementedError("Parsed content is an abstract class with no parsalbe form")


class ParsedFile(ParsedContent):
    """Class for parsed content of file type."""

    def __init__(self, content):
        """Initialize the parsed content."""
        super().__init__(content)
        self.filename = content

    def reportable_form(self):
        """
        Parsed file representation used in reports of parsing steps.

        Arguments are identical to the ones of the parent class.
        """
        return "\tParsed file:\n\t\t%s\n" % self.content

    def parsable_form(self):
        """
        Convert parameter file name into parsable string.

        :returns: resulting parsable string
        :rtype: str
        """
        return "include %s\n" % self.content


class ParsedStr(ParsedContent):
    """Class for parsed content of string type."""

    def reportable_form(self):
        """
        Parsed string representation used in reports of parsing steps.

        Arguments are identical to the ones of the parent class.
        """
        return "\tParsed string:\n\t\t%s\n" % self.content.rstrip("\n").replace("\n", "\n\t\t")

    def parsable_form(self):
        """
        Convert parameter string into parsable string.

        :returns: resulting parsable string
        :rtype: str

        This is equivalent to the string since the string
        is parsable by definition.
        """
        return self.content


class ParsedDict(ParsedContent):
    """Class for parsed content of dictionary type."""

    def reportable_form(self):
        """
        Parsed dictionary representation used in reports of parsing steps.

        Arguments are identical to the ones of the parent class.
        """
        return "\tParsed dictionary:\n\t\t%s\n" % self.parsable_form().rstrip("\n").replace("\n", "\n\t\t")

    def parsable_form(self):
        """
        Convert parameter dictionary into parsable string.

        :returns: resulting parsable string
        :rtype: str
        """
        param_str = ""
        for (key, value) in self.content.items():
            param_str += "%s = %s\n" % (key, value)
        return param_str


class Reparsable():
    """
    Class to represent quickly parsable Cartesian configuration,
    producing both parser and parameters (parser dicts) on demand.
    """

    def __init__(self):
        """Initialize the parsable structure."""
        self.steps = []

    def parse_next_file(self, pfile):
        """
        Add a file parsing step.

        :param str pfile: file to be parsed next

        If the parsable file has a relative form (not and absolute path), it
        will be searched in the relative test suite config directory.
        """
        if os.path.isabs(pfile):
            filename = pfile
        else:
            filename = os.path.join(custom_configs_dir(), pfile)
        self.steps.append(ParsedFile(filename))

    def parse_next_str(self, pstring):
        """
        Add a string parsing step.

        :param str pstring: string to be parsed next
        """
        self.steps.append(ParsedStr(pstring))

    def parse_next_dict(self, pdict):
        """
        Add a dictionary parsing step.

        :param pdict: dictionary to be parsed next
        :type pdict: {str, str}
        """
        self.steps.append(ParsedDict(pdict))

    def parse_next_batch(self,
                         base_file=None, base_str="", base_dict=None,
                         ovrwrt_file=None, ovrwrt_str="", ovrwrt_dict=None):
        """
        Parse a batch of base file, string, and dictionary, and possibly an
        overwrite file (with custom parameters at the user's home location).

        :param base_file: file to be parsed first
        :type base_file: str or None
        :param base_str: string to be parsed first
        :type base_str: str or None
        :param base_dict: params to be added first
        :type base_dict: {str, str} or None
        :param ovrwrt_file: file to be parsed last
        :type ovrwrt_file: str or None
        :param ovrwrt_str: string to be parsed last
        :type ovrwrt_str: str or None
        :param ovrwrt_dict: params to be added last
        :type ovrwrt_dict: {str, str} or None

        The priority of the setting follows the order of the arguments:
        Dictionary with some parameters is topmost, string with some
        parameters is next and the file with parameters is taken as a base.
        The overwriting version is taken last, the base version first.
        """
        if base_file:
            self.parse_next_file(base_file)
        if base_str:
            self.parse_next_str(base_str)
        if base_dict:
            self.parse_next_dict(base_dict)
        if ovrwrt_file:
            self.parse_next_file(ovrwrt_file)
        if ovrwrt_str:
            self.parse_next_str(ovrwrt_str)
        if ovrwrt_dict:
            self.parse_next_dict(ovrwrt_dict)

    def get_parser(self,
                   show_restriction=False, show_dictionaries=False,
                   show_dict_fullname=False, show_dict_contents=False,
                   show_empty_cartesian_product=True):
        """
        Get a basic parameters parser with its dictionaries.

        :param bool show_restriction: whether to show the restriction strings
        :param bool show_dictionaries: whether to show the obtained variants
        :param bool show_dict_fullname: whether to show the variant fullname rather than its shortname
        :param bool show_dict_contents: whether to show the obtained variant parameters
        :param bool show_empty_cartesian_product: whether to check and show the resulting cartesian product

        :returns: resulting parser
        :rtype: :py:class:`cartesian_config.Parser`
        :raises: :py:class:`EmptyCartesianProduct` if no combination of the restrictions exists
        """
        parser = cartesian_config.Parser()
        hostname = os.environ.get("PREFIX", os.environ.get("HOSTNAME", "avocado"))
        parser.parse_string("hostname = %s\n" % hostname)

        for step in self.steps:
            if isinstance(step, ParsedFile):
                parser.parse_file(step.filename)
            if isinstance(step, ParsedStr):
                parser.parse_string(step.content)
            if isinstance(step, ParsedDict):
                parser.parse_string(step.parsable_form())

        # log any required information and detect empty Cartesian product
        if show_restriction:
            logging.debug(self.print_parsed())
        if show_dictionaries or show_empty_cartesian_product:
            options = collections.namedtuple("options", ['repr_mode', 'fullname', 'contents'])
            peek_parser = self.get_parser(show_dictionaries=False, show_empty_cartesian_product=False)
            # break generator into first detectable entry and rest to reuse it better
            peek_generator = peek_parser.get_dicts()
            if show_empty_cartesian_product:
                try:
                    peek_dict = peek_generator.__next__()
                    if show_dictionaries:
                        cartesian_config.print_dicts(options(False, show_dict_fullname, show_dict_contents),
                                                     (peek_dict,))
                        cartesian_config.print_dicts(options(False, show_dict_fullname, show_dict_contents),
                                                     peek_generator)
                except StopIteration:
                    raise EmptyCartesianProduct(self.print_parsed()) from None
            else:
                cartesian_config.print_dicts(options(False, show_dict_fullname, show_dict_contents),
                                             peek_generator)

        return parser

    def get_params(self, list_of_keys=None,
                   show_restriction=False, show_dictionaries=False,
                   show_dict_fullname=False, show_dict_contents=False):
        """
        Get a single parameter dictionary from the currently parsed configuration.

        The parameter dictionary is always validated for existence (nonempty
        Cartesian product) and uniqueness (no more than one final variant).

        :param list_of_keys: list of parameters key in the final selection
        :type list_of_keys: [str] or None
        :returns: first variant dictionary from all current parsed steps
        :rtype: :py:class:`Params`
        :raises: :py:class:`AssertionError` if the parameter dictionary is not unique

        The rest of the arguments are identical to the ones from :py:method:`get_parser`.
        """
        parser = self.get_parser(show_restriction=show_restriction,
                                 show_dictionaries=show_dictionaries,
                                 show_dict_fullname=show_dict_fullname,
                                 show_dict_contents=show_dict_contents,
                                 show_empty_cartesian_product=True)

        for i, d in enumerate(parser.get_dicts()):
            if i == 0:
                default_params = d
            assert i < 1, "There must be at most one configuration for the restriction:\n%s" % self.print_parsed()

        if list_of_keys is None:
            selected_params = default_params
        else:
            selected_params = {key: default_params[key] for key in list_of_keys}
        return Params(selected_params)

    def get_copy(self):
        """
        Get a copy of the current reparsable that can safely be updated further.

        :returns: a copy of self with all current parsed steps in an independent list
        :rtype: :py:class:`Reparsable`

        The rest of the arguments are identical to the ones from :py:method:`get_parser`.
        """
        new = Reparsable()
        new.steps = copy.copy(self.steps)
        return new

    def print_parsed(self):
        """
        Return printable information about what was parsed so far.

        :returns: structured text of the base/ovrwrt file/str/dict parse steps
        :rtype: str
        """
        restriction = "Parsing parameters with the following configuration:\n"
        for step in self.steps:
            restriction += step.reportable_form()
        return restriction


###################################################################
# overwrite string and overwrite dictionary automation methods
###################################################################


def all_restrictions():
    """
    Return all vms that can be passed for any test configuration.

    :returns: all available (from configuration) vms
    :rtype: [str]
    """
    rep = Reparsable()
    rep.parse_next_file("groups-base.cfg")
    return rep.get_params(list_of_keys=["main_restrictions"]).objects("main_restrictions")


def all_vms():
    """
    Return all vms that can be passed for any test configuration.

    :returns: all available (from configuration) vms
    :rtype: [str]
    """
    rep = Reparsable()
    rep.parse_next_file("guest-base.cfg")
    return rep.get_params(list_of_keys=["vms"]).objects("vms")


def main_vm():
    """
    Return the default main vm that can be passed for any test configuration.

    :returns: main available (from configuration) vm
    :rtype: str or None
    """
    rep = Reparsable()
    rep.parse_next_file("guest-base.cfg")
    return rep.get_params(list_of_keys=["main_vm"]).get("main_vm")


def re_str(variant_str, base_str="", tag=""):
    """
    Add a variant restriction to the base string, optionally
    adding a custom tag as well.

    :param str variant_str: variant restriction
    :param str base_str: string where the variant restriction will be added
    :param str tag: additional tag to the variant combination
    :returns: restricted parameter string
    :rtype: str
    """
    if tag != "":
        variant_str = "variants:\n    - %s:\n        only %s\n" % (tag, variant)
    else:
        variant_str = "only %s\n" % variant_str
    return base_str + variant_str


def vm_str(variant_strs, base_str=""):
    """
    Add a vm variant restriction to the base string, reaching
    exactly one vm variant afterwards.

    :param variant_strs: variant restrictions for each vm as key, value pair
    :type variant_strs: {str, str}
    :param str base_str: string where the variant restriction will be added
    :returns: restricted parameter string
    :rtype: str
    """
    vms, variant_str = "", ""
    for vm, variant in variant_strs.items():
        subvariant = "".join(["    " + l + "\n" for l in variant.rstrip("\n").split("\n")])
        variant_str += "%s:\n%s" % (vm, subvariant)
        vms += " " + vm
    variant_str += "join" + vms + "\n"
    return base_str + variant_str
