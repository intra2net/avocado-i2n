"""

SUMMARY
------------------------------------------------------
Utility for the main test suite data structure as well as
its substructures like test nodes and test objects.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import os
import re
import logging
from multiprocessing import SimpleQueue

from avocado.core import test
from avocado_vt.test import VirtTest
from avocado_vt.loader import VirtTestLoader
from avocado.core.runner import TestRunner
from virttest import utils_params

from . import state_setup
from . import params_parser as param


def set_graph_logging_level(level=20):
    """
    Set the logging level specifically for the Cartesian graph.

    This determines what descriptions of the graph will be dumped
    for debugging purposes.
    """
    logging.getLogger('graph').setLevel(level)
set_graph_logging_level(level=20)


class TestObject(object):
    """A wrapper for a test object used in one or more test nodes."""

    def params(self):
        """Parameters property."""
        return param.peek(self.parser)
    params = property(fget=params)

    def __init__(self, name, parser):
        """
        Construct a test object (vm) for any test nodes (tests).

        :param str name: name of the test object
        :param parser: variant configuration for the test object
        :type parser: Parser object
        """
        self.name = name
        self.parser = parser

        self.current_state = "unknown"

    def is_permanent(self):
        """
        If the test object is permanent, it can only be created manually
        (possibly through the use of manual setup steps).

        Online states on permanent test object are treated differently than
        online states on normal test object since they are preserved through
        test runs and even host shutdowns.
        """
        return self.params.get("permanent_vm", "no") == "yes"


class TestNode(object):
    """
    A wrapper for all test relevant parts like parameters, parser, used
    objects and dependencies to/from other test nodes (setup/cleanup).
    """

    def params(self):
        """Parameters (cache) property."""
        if self._params_cache is None:
            self._params_cache = param.peek(self.parser)
        return self._params_cache
    params = property(fget=params)

    def count(self):
        """Node count property."""
        return self.params["shortname"].split(".")[0]
    count = property(fget=count)

    def __init__(self, name, parser, objects):
        """
        Construct a test node (test) for any test objects (vms).

        :param str name: name of the test node
        :param parser: variant configuration for the test node
        :type parser: Parser object
        :param objects: objects participating in the test node
        :type objects: [TestObject]
        """
        self.name = name
        self.parser = parser
        self._params_cache = None

        self.should_run = True
        self.should_clean = True

        # list of objects involved in the test
        self.objects = objects

        # lists of parent and children test nodes
        self.setup_nodes = []
        self.cleanup_nodes = []
        self.visited_setup_nodes = []
        self.visited_cleanup_nodes = []

    def get_test_factory(self, job=None):
        """
        Get test factory from which the test loader will get a runnable test instance.

        :param job: avocado job object to for running or None for reporting only
        :type job: :py:class:`avocado.core.job.Job`
        :return: test class and constructor parameters
        :rtype: (type, {str, obj})
        """
        test_constructor_params = {'name': test.TestID("?", self.params["shortname"]), 'vt_params': self.params}
        if job is not None:
            test_constructor_params['job'] = job
            test_constructor_params['base_logdir'] = job.logdir
        return (VirtTest, test_constructor_params)

    def is_root(self):
        """Check if the test node is the root of all test nodes for all test objects."""
        return self.name == "root"

    def is_object_root(self):
        """Check if the test node is the root of all test nodes for some test object."""
        return self.name == self.params["vms"]

    def is_ephemeral(self):
        """
        If the test node is ephemeral its `set_state` cannot be preserved for
        longer than one cycle, i.e. if the next test stops reverting to it.

        Such test nodes are transitions from offline to online states and
        must be repeated to reuse the online states that are their end states.
        """
        for test_object in self.objects:
            object_name = test_object.name
            object_params = self.params.object_params(object_name)
            object_state = object_params.get("set_state")

            # count only test objects left with saved states
            if object_state is None or object_state == "":
                continue

            # definition 1 (with non-root offline starting state)
            if (object_params.get("get_type", "online") == "offline" and
                    object_params.get("get_state", "root") != "root" and
                    object_params.get("set_type", "online") == "online"):
                return True

            # definition 2 (with impermanent test object)
            if (not test_object.is_permanent() and
                    object_params.get("set_type", "online") == "online"):
                return True

        return False

    def is_manual(self):
        """
        If the test node is manual, its execution is disallowed and considered
        responsibility of the user.
        """
        return ".manual." in self.params["name"]

    def is_setup_ready(self):
        """
        All dependencies of the test were run or there were none, so it can
        be run as well.
        """
        return len(self.setup_nodes) == 0

    def is_cleanup_ready(self):
        """
        All dependent tests were run or there were none, so the end states
        from the test can be removed.
        """
        return len(self.cleanup_nodes) == 0

    def is_finished(self):
        """
        The test and all its dependent tests were run and the test will not
        be run anymore.
        """
        return self.is_cleanup_ready() and not self.should_run

    @staticmethod
    def comes_before(node1, node2):
        def compare_part(c1, c2):
            match1, match2 = re.match(r"^(\d+)(\w+)(.+)", c1), re.match(r"^(\d+)(\w+)(.+)", c2)
            if match1 is None and match2 is None:
                pass
            d1, b1, a1 = c1, None, None if match1 is None else match1.group(1, 2, 3)
            d2, b2, a2 = c2, None, None if match2 is None else match2.group(1, 2, 3)
            if not c1.isdigit() or not c2.isdigit():
                return str(c1) < str(c2)
            d1, d2 = int(d1), int(d2)
            if d1 != d2:
                return d1 < d2
            elif a1 != a2:
                if a1 is None:
                    return False if a2 == "a" else True  # reverse order for "c" and cleanup
                if a2 is None:
                    return True if a1 == "a" else False  # reverse order for "c" and cleanup
                return a1 < a2
            else:
                return compare_part(b1, b2)
        return compare_part(node1.count, node2.count)

    def pick_next_parent(self):
        """
        Pick the next available parent based on some priority.

        :returns: the next parent node
        :rtype: TestNode object

        The current basic priority is test name.
        """
        next_node = self.setup_nodes[0]
        for node in self.setup_nodes[1:]:
            if TestNode.comes_before(node, next_node):
                next_node = node
        return next_node

    def pick_next_child(self):
        """
        Pick the next available child based on some priority.

        :returns: the next child node
        :rtype: TestNode object

        The current basic priority is test name.

        .. todo:: more advanced scheduling can be based on different types of priority:

            1. priority to tests with objects at current states -> then at further states
               -> then at previous states;
            2. priority to tests that are leaves -> then internal;
            3. priority to tests using fewer objects -> then more objects;
        """
        next_node = self.cleanup_nodes[0]
        for node in self.cleanup_nodes[1:]:
            if TestNode.comes_before(node, next_node):
                next_node = node
        return next_node

    def visit_node(self, test_node):
        """
        Move a parent or child node to the set of visited nodes for this test.

        :param test_node: visited node
        :type test_node: TestNode object
        :raises: :py:class:`ValueError` if visited node is not directly dependent
        """
        if test_node in self.setup_nodes:
            self.setup_nodes.remove(test_node)
            self.visited_setup_nodes.append(test_node)
        elif test_node in self.cleanup_nodes:
            self.cleanup_nodes.remove(test_node)
            self.visited_cleanup_nodes.append(test_node)
        else:
            raise ValueError("Invalid test node - %s and %s are not directly dependent "
                             "in any way" % (test_node.params["shortname"], self.params["shortname"]))


class CartesianGraph(VirtTestLoader, TestRunner):
    """
    The main test suite data structure, responsible for parsing, scheduling
    and running all tests.

    This data structure uses a tree for each test object all of which overlap
    in a directed graph. All tests are using objects that can be brought to
    certain states and need some specific setup. All states can thus be saved
    and reused for other tests, resulting in a tree structure of derived states
    for each object. These object trees are then interconnected as a test might
    use multiple objects (vms) at once resulting in a directed graph. Running
    all tests is nothing more but traversing this graph in DFS-like way to
    minimize setup repetition. The policy of this traversal determines whether
    an automated setup (tests not defined by the user but needed for his/her
    tests) will be performed, ignored, overwritten, etc. The overall graph
    is extracted from the given Cartesian configuration, expanding Cartesian
    products of tests and tracing their object dependencies.
    """

    name = 'cartesian_graph'

    _args = None
    _extra_params = None
    _testnodes = []
    _testobjects = []

    def test_objects(self):
        """Test objects dictionary property."""
        objects = {}
        for test_object in self._testobjects:
            objects[test_object.name] = test_object.params["shortname"]
        return objects
    test_objects = property(fget=test_objects)

    def test_nodes(self):
        """Test nodes dictionary property."""
        nodes = {}
        for test_node in self._testnodes:
            nodes[test_node.name] = test_node.params["shortname"]
        return nodes
    test_nodes = property(fget=test_nodes)

    def __init__(self, args=None, extra_params=None, job=None, result=None):
        """
        Construct the Cartesian graph.

        :param args: command line arguments
        :type args: :py:class:`argparse.Namespace`
        :param extra_params: extra configuration parameters
        :type extra_params: {str, str}
        :param job: avocado job object
        :type job: :py:class:`avocado.core.job.Job`
        :param result: avocado result object
        :type result: :py:class:`avocado.core.result.Result`

        Since the Cartesian graph is a persistence structure used through
        both test loading and running stages, we need to be a bit hacky
        to make avocado accept this. In particular we save the test loader
        part of the initialization in static attributes and use keyword
        arguments to the constructor to allow it to be called as both types.
        """
        if args and not job:
            # called as a test loader
            self.args = CartesianGraph._args = args
            self.extra_params = CartesianGraph._extra_params = extra_params
            CartesianGraph._testnodes = self._testnodes = []
            CartesianGraph._testobjects = self._testobjects = []
            self.job = None
            self.result = None
            VirtTestLoader.__init__(self, args, extra_params)
        else:
            # called as a test runner
            self.args = args = CartesianGraph._args
            self.extra_params = extra_params = CartesianGraph._extra_params
            self._testnodes = CartesianGraph._testnodes
            self._testobjects = CartesianGraph._testobjects
            self.job = job
            self.result = result
            TestRunner.__init__(self, job, result)

    """dumping functionality"""
    def load_setup_list(self, filename="setup_list"):
        """
        Load the setup state of each node from a list file.

        :param str filename: file to load the setup information from
        """
        with open(os.path.join(self.job.logdir, filename), "r") as f:
            str_list = f.read()
        setup_list = re.findall("(\w+) (\d) (\d)", str_list)
        for i in range(len(setup_list)):
            assert self._testnodes[i].name == setup_list[i][0], "Corrupted setup list file"
            self._testnodes[i].should_run = bool(int(setup_list[i][1]))
            self._testnodes[i].should_clean = bool(int(setup_list[i][2]))

    def save_setup_list(self, filename="setup_list"):
        """
        Save the setup state of each node to a list file.

        :param str filename: file to save the setup information to
        """
        str_list = ""
        for test in self._testnodes:
            should_run = 1 if test.should_run else 0
            should_clean = 1 if test.should_clean else 0
            str_list += "%s %i %i\n" % (test.name, should_run, should_clean)
        with open(os.path.join(self.job.logdir, filename), "w") as f:
            f.write(str_list)

    def report_progress(self):
        """
        Report the total test run progress as the number and percentage
        of tests that are fully finished (will not be run again).

        The estimation includes setup tests which might be reused and therefore
        provides worst case scenario for the number of remaining tests. It also
        does not take into account the duration of each test which could vary
        significantly.
        """
        total, finished = len(self._testnodes), 0
        for tnode in self._testnodes:
            if tnode.is_finished():
                finished += 1
        logging.info("Finished %i\%i tests, %0.2f%% complete", finished, total, 100.0*finished/total)

    def visualize(self, dump_dir, n=0):
        """
        Dump a visual description of the Cartesian graph at
        a given parsing/traversal step.

        :param str dump_dir: directory for the dump image
        :param int n: number of the parsing/traversal step
        """
        try:
            from graphviz import Digraph
        except ImportError:
            logging.warning("Couldn't visualize the Cartesian graph due to missing dependency (Graphviz)")
            return

        graph = Digraph('cartesian_graph', format='svg')
        for tnode in self._testnodes:
            graph.node(tnode.name)
            for snode in tnode.setup_nodes:
                graph.node(snode.name)
                graph.edge(tnode.name, snode.name)
            for cnode in tnode.cleanup_nodes:
                graph.node(cnode.name)
                graph.edge(tnode.name, cnode.name)
        graph.render("%s/cg_%s_%s" % (dump_dir, id(self), n))

    """parsing functionality"""
    def parse_objects(self, object_strs=None, object_names="", verbose=False):
        """
        Parse all available test objects and their configurations or
        a selection of such where the selection has the form of objects parameter.
        e.g. 'vm1 vm2 vm3' for the `vms` parameter.

        :param object_strs: block of object-specific parameters and variant restrictions
        :type object_strs: {str, str}
        :param str object_names: space separated test object names
        :param bool verbose: whether to print extra messages or not
        :returns: parsed test objects
        :rtype: list
        """
        if object_strs is None:
            object_strs = {}
        if object_names == "":
            # all possible hardware-software combinations
            available_vms = param.all_vms()
        else:
            available_vms = object_names.split(" ")

        test_objects = []
        for vm_name in available_vms:
            if vm_name not in object_strs:
                object_strs[vm_name] = ""
            # all possible hardware-software combinations for a given vm
            vm_parser = param.prepare_parser(base_file="objects.cfg",
                                             base_str=param.vm_str(vm_name, ""),
                                             base_dict={"main_vm": vm_name},
                                             ovrwrt_str=object_strs[vm_name],
                                             show_dictionaries=verbose)
            for i, d in enumerate(vm_parser.get_dicts()):
                assert i < 1, "There must be exactly one configuration for %s - please restrict better" % vm_name

                # parameter postprocessing - some expansion and simplification
                vm_params = utils_params.multiply_params_per_object(d, [vm_name])
                vm_params = utils_params.object_params(vm_params, vm_name, param.all_vms())
                # NOTE: this is still not perfect - it also overwrites parameters under conditional blocks with
                # their defaults outside of the conditional blocks (newly defined parameters are preserved though)
                vm_params.pop("cdrom_cd1", None)
                vm_params.pop("cdroms", None)
                # that may later be invoked (i.e. replaced by irrelevant defaults outside of the blocks)
                vm_parser = param.update_parser(vm_parser, ovrwrt_dict=vm_params.drop_dict_internals())

                # parameter postprocessing - add custom overwrite files with custom paths, etc.
                vm_parser = param.update_parser(vm_parser, ovrwrt_file=param.vms_ovrwrt_file)

            test_objects.append(TestObject(vm_name, vm_parser))
        return test_objects

    def parse_nodes(self, nodes_str, prefix="", object_name="", verbose=False):
        """
        Parse all user defined tests (leaf nodes) using the nodes overwrite string
        and possibly restricting to a single test object for the singleton tests.

        :param str nodes_str: block of node-specific parameters and variant restrictions
        :param str prefix: extra name identifier for the test to be run
        :param str object_name: name of the test object whose configuration is reused if node if objectless
        :param bool verbose: whether to print extra messages or not
        :returns: parsed test nodes
        :rtype: list
        :raises: :py:class:`exceptions.ValueError` if the base vm is not among the vms for a node
        :raises: :py:class:`param.EmptyCartesianProduct` if no result on preselected vm
        """
        test_nodes = []
        base_object = None

        # prepare initial parser as starting configuration and got through tests
        parser = param.prepare_parser(base_file="sets.cfg", ovrwrt_str=nodes_str)
        for i, d in enumerate(parser.get_dicts()):
            name = prefix + str(i+1)
            objects, objnames, objdicts = [], [], []

            # decide about test objects participating in the test node
            if d.get("vms") is None and object_name != "":
                # case of singleton test
                d["vms"] = object_name
                d["base_vm"] = object_name
            elif d.get("vms") is None and object_name == "":
                # case of default singleton test
                d["vms"] = d["base_vm"]
            elif object_name != "":
                # case of specified object (dependency) as well as node
                fixed_vms = d["vms"].split(" ")
                assert object_name in fixed_vms, "Predefined test object %s for test node '%s' not among:"\
                                                 " %s" % (object_name, d["shortname"], d["vms"])
                assert d["base_vm"] in fixed_vms, "Base test object %s for test node '%s' not among:"\
                                                 " %s" % (d["base_vm"], d["shortname"], d["vms"])

            # get configuration of each participating object and choose the one to mix with the node
            logging.debug("Fetching test objects %s to parse a test node", d["vms"].replace(" ", ","))
            for vm_name in d["vms"].split(" "):
                vms = self._get_objects_by(param_key="main_vm", param_val="^"+vm_name+"$")
                assert len(vms) == 1, "Test object %s not existing or unique in: %s" % (vm_name, vms)
                objects.append(vms[0])
                objnames.append(vms[0].name)
                objdicts.append(vms[0].params)
                if d["base_vm"] == vms[0].name:
                    base_object = vms[0]
            if base_object is None:
                raise ValueError("Could not detect the based object among '%s' "
                                 "in the test '%s'" % (d["vms"], d["shortname"]))

            # final variant multiplication to produce final test node configuration
            logging.debug("Multiplying the vm variants by the test variants using %s", base_object.name)
            setup_dict = {}
            if len(objects) > 1:
                setup_dict = utils_params.merge_object_params(objnames, objdicts, "vms", base_object.name)
            setup_str = param.re_str(d["name"], nodes_str, tag=name)
            try:
                # combine object configurations
                parser = param.update_parser(base_object.parser, ovrwrt_dict=setup_dict)
                # now restrict to selected nodes
                parser = param.update_parser(parser, ovrwrt_str=setup_str,
                                             ovrwrt_file=param.tests_ovrwrt_file,
                                             ovrwrt_base_file="sets.cfg",
                                             show_dictionaries=verbose)
                test_nodes.append(TestNode(name + d["vms"].replace(" ", ""), parser, objects))
                logging.debug("Parsed a test '%s' with base configuration of %s",
                              d["shortname"], base_object.name)
            except param.EmptyCartesianProduct:
                # empty product on a preselected test object implies something is wrong with the selection
                if object_name != "":
                    raise
                logging.debug("Test '%s' not compatible with the %s configuration - skipping",
                              d["shortname"], base_object.name)

        return test_nodes

    def parse_object_nodes(self, nodes_str, object_strs=None,
                           prefix="", object_names="",
                           objectless=False, verbose=False):
        """
        Parse test nodes based on a selection of parsed objects.

        :param str nodes_str: block of node-specific parameters and variant restrictions
        :param object_strs: block of object-specific parameters and variant restrictions
        :type object_strs: {str, str}
        :param str prefix: extra name identifier for the test to be run
        :param str object_names: space separated test object names
        :param bool objectless: whether objectless test nodes are expected to be parsed
        :param bool verbose: whether to print extra messages or not
        :returns: parsed test nodes
        :rtype: list
        :raises: :py:class:`param.EmptyCartesianProduct` if no test variants for the given vm variants

        If objectless test nodes are expected to be parsed, we will parse them once
        for each object provided through "object_names" or available in the configs.
        Otherwise, we will parse for all objects available in the configs, then restrict
        to the ones in "object_names" if set on a test by test basis.
        """
        test_objects = []
        if objectless:
            test_objects.extend(self.parse_objects(object_strs, object_names=object_names, verbose=verbose))
        else:
            test_objects.extend(self.parse_objects(object_strs, verbose=verbose))
        if verbose:
            logging.info("%s selected vm variant(s)", len(test_objects))
        self._testobjects.extend(test_objects)

        test_nodes = []
        if objectless:
            for test_object in self._testobjects:
                object_nodes = self.parse_nodes(nodes_str, prefix=prefix,
                                                object_name=test_object.name, verbose=verbose)
                test_nodes.extend(object_nodes)
        else:
            selected_vms = [] if object_names == "" else object_names.split(" ")
            for test_node in self.parse_nodes(nodes_str, prefix=prefix, verbose=verbose):
                compatible = True
                test_vms = test_node.params.objects("vms")
                for vm_name in selected_vms:
                    if vm_name not in test_vms:
                        compatible = False
                        break
                if compatible:
                    test_nodes.append(test_node)
        if verbose:
            logging.info("%s selected test variant(s)", len(test_nodes))
        if len(test_nodes) == 0:
            object_restrictions = param.dict_to_str(self.test_objects)
            for object_str in object_strs.values():
                object_restrictions += object_str
            raise param.EmptyCartesianProduct(param.print_restriction(base_str=object_restrictions,
                                                                      ovrwrt_str=nodes_str))
        return test_nodes

    def parse_object_trees(self, param_str, nodes_str, object_strs=None,
                           prefix="", object_names="",
                           objectless=False, verbose=True):
        """
        Parse all user defined tests (leaves) and their dependencies (internal nodes)
        connecting them according to the required/provided setup states of each test
        object (vm) and the required/provided objects per test.

        :param str param_str: block of command line parameters

        The rest of the parameters are identical to the methods before.

        The parsed structure can also be viewed as a directed graph of all runnable
        tests each with connections to its dependencies (parents) and dependables (children).
        """
        # parse leaves and discover necessary setup (internal nodes)
        leaves = self.parse_object_nodes(nodes_str, object_strs, prefix=prefix, object_names=object_names,
                                         objectless=objectless, verbose=verbose)
        self._testnodes.extend(leaves)
        # NOTE: reversing here turns the leaves into a simple stack
        unresolved = sorted(list(leaves), key=lambda x: int(re.match("^(\d+)", x.name).group(1)), reverse=True)

        if logging.getLogger('graph').level <= logging.DEBUG:
            parse_dir = os.path.join(self.job.logdir, "graph_parse")
            if not os.path.exists(parse_dir):
                os.mkdir(parse_dir)
            step = 0

        while len(unresolved) > 0:
            test_node = unresolved.pop()
            for test_object in test_node.objects:
                logging.debug("Parsing dependencies of %s for object %s", test_node.params["shortname"], test_object.name)
                object_params = test_node.params.object_params(test_object.name)
                if object_params.get("get_state", "") == "":
                    continue

                # get and parse parents
                get_parents, parse_parents = self._parse_and_get_parents(test_node, test_object, param_str)
                self._testnodes.extend(parse_parents)
                unresolved.extend(parse_parents)
                parents = get_parents + parse_parents

                # connect and replicate children
                if len(parents) > 0:
                    assert parents[0] not in test_node.setup_nodes
                    assert test_node not in parents[0].cleanup_nodes
                    test_node.setup_nodes.append(parents[0])
                    parents[0].cleanup_nodes.append(test_node)
                if len(parents) > 1:
                    self._copy_branch(test_node, parents[0], parents[1:])

                if logging.getLogger('graph').level <= logging.DEBUG:
                    step += 1
                    self.visualize(parse_dir, step)

        used_objects = []
        for test_object in self._testobjects:
            object_nodes = self._get_nodes_by("vms", "^"+test_object.name+"$")
            object_roots = self._get_nodes_by("name", "(\.|^)root(\.|$)", subset=object_nodes)
            if len(object_roots) > 0:
                used_objects.append(test_object)
        self._testobjects[:] = used_objects
        if verbose:
            logging.info("%s final vm variant(s)", len(self._testobjects))

    def discover(self, references, _which_tests=None):
        """
        Discover (possible) tests from test references.

        :param references: tests references used to produce tests
        :type references: str or [str] or None
        :param which_tests: display behavior for incompatible tests
        :type which_tests: :py:class:`loader.DiscoverMode`
        :return: test factories as tuples of the test class and its parameters
        :rtype: [(type, {str, str})]
        """
        if references is not None:
            assert references.split() == self.args.params
        param_str, nodes_str, object_strs = self.args.param_str, self.args.tests_str, self.args.vm_strs
        prefix = self.args.prefix
        self.parse_object_trees(param_str, nodes_str, object_strs, prefix)
        return [n.get_test_factory() for n in self._testnodes]

    """test running functionality"""
    def run_create_test(self, object_name, param_str, tag=""):
        """
        Run the set of tests necessary for creating a given test object.

        :param str object_name: name of the test object to be created
        :param str param_str: block of command line parameters
        :param str tag: extra name identifier for the test to be run
        """
        objects = self._get_objects_by(param_key="main_vm", param_val="^"+object_name+"$")
        assert len(objects) == 1, "Test object %s not existing or unique in: %s" % (object_name, objects)
        test_object = objects[0]
        parser = param.update_parser(test_object.parser,
                                     ovrwrt_dict={"vm_action": "set",
                                                  "skip_image_processing": "yes"},
                                     ovrwrt_str=param.re_str("manage_vms.unchanged",
                                                             param_str, tag, True),
                                     ovrwrt_base_file="sets.cfg",
                                     ovrwrt_file=param.tests_ovrwrt_file)
        self.run_test_node(TestNode(object_name + ".create", parser, [test_object]))

    def run_remove_test(self, object_name, param_str, tag=""):
        """
        Run the set of tests necessary for removing a given test object.

        :param str object_name: name of the test object to be removed
        :param str param_str: block of command line parameters
        :param str tag: extra name identifier for the test to be run
        """
        objects = self._get_objects_by(param_key="main_vm", param_val="^"+object_name+"$")
        assert len(objects) == 1, "Test object %s not existing or unique in: %s" % (object_name, objects)
        test_object = objects[0]
        # since the default unset_mode is passive (ri) we need a better
        # default value for that case but still modifiable by the user
        if "unset_mode" not in param_str:
            setup_str = param_str + param.dict_to_str({"unset_mode": "fi"})
        else:
            setup_str = param_str
        parser = param.update_parser(test_object.parser,
                                     ovrwrt_dict={"vm_action": "unset",
                                                  "skip_image_processing": "yes"},
                                     ovrwrt_str=param.re_str("manage_vms.unchanged",
                                                             setup_str, tag, True),
                                     ovrwrt_base_file="sets.cfg",
                                     ovrwrt_file=param.tests_ovrwrt_file)
        self.run_test_node(TestNode(object_name + ".remove", parser, [test_object]))

    def run_install_test(self, object_name, param_str, tag=""):
        """
        Run the set of tests necessary for installing a given test object.

        :param str object_name: name of the test object to be installed
        :param str param_str: block of command line parameters
        :param str tag: extra name identifier for the test to be run
        :raises: :py:class:`NotImplementedError` if using incompatible installation variant
        """
        objects = self._get_objects_by(param_key="main_vm", param_val="^"+object_name+"$")
        assert len(objects) == 1, "Test object %s not existing or unique in: %s" % (object_name, objects)
        test_object = objects[0]

        logging.info("Configuring installation for %s", test_object.name)
        parser = param.update_parser(test_object.parser,
                                     ovrwrt_str=param.re_str("configure_install", param_str, tag, True),
                                     ovrwrt_base_file="sets.cfg",
                                     ovrwrt_file=param.tests_ovrwrt_file)
        # some parameters from the install configuration have to be used for decision about install tests
        install_params = param.peek(param.copy_parser(parser))
        status = self.run_test_node(TestNode(object_name + ".configure_install", parser, [test_object]))

        if status:
            logging.info("Installing virtual machine %s", test_object.name)
            if install_params.get("configure_install", "stepmaker") == "unattended_install":
                if ".Fedora." in test_object.params["name"] or ".CentOS." in test_object.params["name"]:
                    ovrwrt_str = param.re_str("unattended_install.cdrom.extra_cdrom_ks", param_str, tag, True)
                elif ".Windows." in test_object.params["name"]:
                    ovrwrt_str = param.re_str("unattended_install.cdrom", param_str, tag, True)
                else:
                    raise NotImplementedError("Unattended install tests are only supported on Windows and Fedora/CentOS")
                ovrwrt_dict = {}
            else:
                ovrwrt_dict = {"type": install_params.get("configure_install", "stepmaker")}
                ovrwrt_str = param.re_str("install", param_str, tag, True)
            parser = param.update_parser(test_object.parser,
                                         ovrwrt_dict=ovrwrt_dict,
                                         ovrwrt_str=ovrwrt_str,
                                         ovrwrt_base_file="sets.cfg",
                                         ovrwrt_file=param.tests_ovrwrt_file)
            self.run_test_node(TestNode(object_name + ".install", parser, [test_object]))

    def run_test_node(self, node):
        """
        A wrapper around the inherited :py:meth:`run_test`.

        :param node: test node to run
        :type node: :py:class:`TestNode`
        :return: run status of :py:meth:`run_test`
        :rtype: bool

        This is a simple wrapper to provide some default arguments
        for simplicity of invocation.
        """
        return self.run_test(node.get_test_factory(self.job), SimpleQueue(), set())

    def run_tests(self, param_str):
        """
        Run all user and system defined tests optimizing the setup reuse and
        minimizing the repetition of demanded tests.

        :param str param_str: block of command line parameters
        :raises: :py:class:`AssertionError` if some traversal assertions are violated

        The highest priority is at the setup tests (parents) since the test cannot be
        run without the required setup, then the current test, then a single child of
        its children (DFS), and finally the other children (tests that can benefit from
        the fact that this test/setup was done) followed by the other siblings (tests
        benefiting from its parent/setup.

        Of course all possible children are restricted by the user-defined "only" and
        the number of internal test nodes is minimized for achieving this goal.
        """
        root_parser = param.prepare_parser(base_dict={"set_state": ""}, base_file='guest-base.cfg')
        root = TestNode("root", root_parser, [])
        for test_object in self._testobjects:
            object_nodes = self._get_nodes_by("vms", "^"+test_object.name+"$")
            object_roots = self._get_nodes_by("name", "(\.|^)root(\.|$)", subset=object_nodes)
            root_for_object = object_roots[0]
            root_for_object.setup_nodes.append(root)
            root.cleanup_nodes.append(root_for_object)

        if logging.getLogger('graph').level <= logging.DEBUG:
            traverse_dir = os.path.join(self.job.logdir, "graph_traverse")
            if not os.path.exists(traverse_dir):
                os.mkdir(traverse_dir)
            step = 0

        traverse_path = [root]
        while not root.is_cleanup_ready():
            next = traverse_path[-1]
            if len(traverse_path) > 1:
                previous = traverse_path[-2]
            else:
                # since the loop is discontinued if len(traverse_path) == 0 or root.is_cleanup_ready()
                # a valid current node with at least one child is guaranteed
                traverse_path.append(next.pick_next_child())
                continue

            logging.debug("At test node %s which is %sready with setup, %sready with cleanup,"
                          " should %srun, and should %sbe cleaned", next.params["shortname"],
                          "not " if not next.is_setup_ready() else "",
                          "not " if not next.is_cleanup_ready() else "",
                          "not " if not next.should_run else "",
                          "not " if not next.should_clean else "")
            logging.debug("Current traverse path/stack:%s",
                          "\n".join([n.params["shortname"] for n in traverse_path]))
            # if previous in path is the child of the next, then the path is reversed
            # looking for setup so if the next is setup ready and already run, remove
            # the previous' reference to it and pop the current next from the path
            if previous in next.cleanup_nodes or previous in next.visited_cleanup_nodes:

                if next.is_setup_ready():
                    self._run_test_node(next, param_str)
                    previous.visit_node(next)
                    traverse_path.pop()
                else:
                    # inverse DFS
                    traverse_path.append(next.pick_next_parent())
            elif previous in next.setup_nodes or previous in next.visited_setup_nodes:

                # stop if test is not a setup leaf since parents have higher priority than children
                if not next.is_setup_ready():
                    traverse_path.append(next.pick_next_parent())
                    continue
                else:
                    self._run_test_node(next, param_str)

                if next.is_cleanup_ready():
                    self._clean_test_node(next, param_str)
                    for setup in next.visited_setup_nodes:
                        setup.visit_node(next)
                    traverse_path.pop()
                    self.report_progress()
                else:
                    # normal DFS
                    traverse_path.append(next.pick_next_child())
            else:
                raise AssertionError("Discontinuous path in the test dependency graph detected")

            if logging.getLogger('graph').level <= logging.DEBUG:
                step += 1
                self.visualize(traverse_dir, step)

    def run_suite(self, test_suite, _variant, _timeout=0,
                  _replay_map=None, _execution_order=None):
        """
        Run one or more tests and report with test result.

        :param test_suite: a list of tests to run
        :type test_suite: [(type, {str, str})]
        :param variants: varianter iterator to produce test params
        :type variants: :py:class:`avocado.core.varianter.Varianter`
        :param int timeout: maximum amount of time (in seconds) to execute
        :param replay_map: optional list to override test class based on test index
        :type replay_map: [None or type]
        :param str execution_order: Mode in which we should iterate through tests
                                    and variants (if None will default to
                                    :py:attr:`DEFAULT_EXECUTION_ORDER`
        :returns: a set with types of test failures
        :rtype: :py:class:`set`
        """
        assert len(test_suite) == len(self._testnodes)
        for node1, node2 in zip(test_suite, self._testnodes):
            assert node1 == node2.get_test_factory()
        summary = set()
        param_str = self.args.param_str

        # HACK: pass the constructed graph to the test using static attribute hack
        # since there is absolutely no sane way to pass through the cloud of imports
        # and circular references that autotest is doing before executing a test!
        CartesianGraph.REFERENCE = self

        objects = sorted(self.test_objects.keys())
        setup_dict = {"abort_on_error": "yes", "set_state_on_error": "",
                      "vms": " ".join(objects),
                      "main_vm": objects[0]}
        setup_str = param.dict_to_str(setup_dict)
        nodes = self.parse_nodes(param.re_str("scan_dependencies", setup_str, objectless=True),
                                 prefix="0m0s")
        self.run_test_node(TestNode("scan", nodes[0].parser, []))
        self.load_setup_list()

        self.visualize(self.job.logdir)
        self.run_tests(param_str)
        return summary

    """run/clean switching functionality"""
    def scan_object_states(self, env):
        """
        Scan for present object states to reuse tests from previous runs

        :param env: environment related to the test
        :type env: Env object
        """
        for test_node in self._testnodes:
            test_node.should_run = True
            if test_node.is_manual():
                test_node.should_run = False

            for test_object in test_node.objects:
                object_name = test_object.name
                object_params = test_node.params.object_params(object_name)
                object_state = object_params.get("set_state")

                # the test leaves an object undefined so it cannot be reused for this object
                # TODO: If at least one object state left after some of the test nodes
                # is available, the test node can be reused *for that object*.
                if object_state is None or object_state == "":
                    continue

                # the ephemeral states can be unset during the test run so cannot be counted on
                if test_node.is_ephemeral():
                    if object_params.get("reuse_ephemeral_states", "no") == "yes":
                        # NOTE: If you are running only tests that are descendants of this ephemeral test,
                        # it won't be lost throughout the run so you might as well reuse it if available
                        # before the test run commences. However, be warned that this is user responsibility.
                        # TODO: If the states are online but not on a permanent test object,
                        # we rely on the ephemeral tests. However, be warned that there is
                        # no guarantee the ephemeral test concept (i.e. offline to online
                        # state transition) will guard all possible topologies of the Cartesian
                        # graph. This works well for simple enough cases like most of our cases,
                        # more specifically cases with no online states descending from other
                        # online states unless we have a permanent object.
                        logging.warning("The state %s of %s is ephemeral but will be forcibly reused",
                                        object_state, object_name)
                    else:
                        logging.info("The state %s of %s is ephemeral (cannot be reused at any desired time)",
                                     object_state, object_name)
                        # test should be run regardless of further checks
                        continue

                # manual tests can only be run by the user and are his/her responsibility
                if test_node.is_manual():
                    # the set state has to be defined for all manual test objects
                    logging.info("The state %s of %s is expected to be manually provided",
                                 object_state, object_name)
                    # test should not be run regardless of further checks
                    continue

                # ultimate consideration of whether the state is actually present
                object_params["vms"] = object_name
                object_params["check_state"] = object_state
                object_params["check_type"] = object_params.get("set_type", "online")
                is_state_detected = state_setup.check_state(object_params, env,
                                                            print_pos=True, print_neg=True)
                # the object state has to be defined to reach this stage
                if is_state_detected:
                    test_node.should_run = False

    def flag_children(self, state_name, object_name, flag_type="run", flag=True, skip_roots=False):
        """
        Set the run/clean flag for all children of a node, whose `set_state`
        parameter is specified by the `state_name` argument.

        :param str state_name: state which is set by the parent node
        :param str object_name: test object whose state is set
        :param str flag_type: 'run' or 'clean' categorization of the children
        :param bool flag: whether the run/clean action should be executed or not
        :param bool skip_roots: whether the roots should not be flagged as well
        :raises: :py:class:`AssertionError` if obtained # of root tests is != 1
        """
        activity = ("" if flag else "not ") + ("running" if flag_type == "run" else "cleanup")
        logging.debug("Selecting test nodes for %s", activity)
        root_tests = self._get_nodes_by(param_key="set_state", param_val="^"+state_name+"$")
        root_tests = self._get_nodes_by(param_key="vms",
                                        param_val="(^|\s)%s($|\s)" % object_name,
                                        subset=root_tests)
        if len(root_tests) < 1:
            raise AssertionError("Could not retrieve state %s and flag all its children tests" % state_name)
        elif len(root_tests) > 1:
            raise AssertionError("Could not identify state %s and flag all its children tests" % state_name)
        else:
            test_node = root_tests[0]

        if not skip_roots:
            flagged = [test_node]
        else:
            flagged = []
            flagged.extend(test_node.cleanup_nodes)
        for test_node in flagged:
            logging.debug("The test %s is set for %s.", test_node.params["shortname"], activity)
            flagged.extend(test_node.cleanup_nodes)
            if flag_type == "run":
                test_node.should_run = flag
            else:
                test_node.should_clean = flag

    def flag_parent_intersection(self, graph, flag_type="run", flag=True, skip_roots=False):
        """
        Intersect the test nodes with the test nodes from another graph and
        set a run/clean flag for each one in the intersection.

        :param graph: Cartesian graph to intersect the current graph with
        :type graph: CartesianGraph object
        :param str flag_type: 'run' or 'clean' categorization of the children
        :param bool flag: whether the run/clean action should be executed or not
        :param bool skip_roots: whether the roots should not be flagged as well

        .. note:: This method only works with reusable tests, due to current lack
            of proper test identification. It is generally meant for identifying
            paths of parents and not intersections of whole graphs.
        """
        activity = ("" if flag else "not ") + ("running" if flag_type == "run" else "cleanup")
        logging.debug("Selecting test nodes for %s", activity)
        for test_node in self._testnodes:
            if len(graph._get_nodes_by(param_key="set_state",
                                       param_val="^"+test_node.params["set_state"]+"$")) == 1:
                if test_node.params["set_state"] == "root" and skip_roots:
                    continue
                logging.debug("The test %s is set for %s.", test_node.params["shortname"], activity)
                if flag_type == "run":
                    test_node.should_run = flag
                else:
                    test_node.should_clean = flag

    """internals - get/parse, duplicates, run/clean"""
    def _get_nodes_by(self, param_key="name", param_val="", subset=None):
        """
        Query all test nodes by a value in a parameter, returning a set of tests.

        Warning: The matching is using 'param LIKE %value%' instead of 'param=value'
        which is necessary for matching a subvariant if the key is the test name.
        """
        tests_selection = []
        if subset is None:
            subset = self._testnodes
        for test in subset:
            if re.search(param_val, test.params.get(param_key, "")):
                tests_selection.append(test)
        logging.debug("Retrieved %s/%s test nodes with %s = %s",
                      len(tests_selection), len(subset), param_key, param_val)
        return tests_selection

    def _get_objects_by(self, param_key="main_vm", param_val="", subset=None):
        """
        Query all test objects by a value in a parameter, returning a set of vms.

        Warning: The matching is using 'param LIKE %value%' instead of 'param=value'.
        """
        vms_selection = []
        if subset is None:
            subset = self._testobjects
        for vm in subset:
            if re.search(param_val, vm.params.get(param_key, "")):
                vms_selection.append(vm)
        logging.debug("Retrieved %s/%s test objects with %s = %s",
                      len(vms_selection), len(subset), param_key, param_val)
        return vms_selection

    def _parse_object_root(self, object_name, param_str):
        """
        Get the first test node for the given object.

        This assumes that there is only one root test node which is the one
        with the 'root' start state.
        """
        objects = self._get_objects_by(param_key="main_vm", param_val="^"+object_name+"$")
        assert len(objects) == 1, "Test object %s not existing or unique in: %s" % (object_name, objects)
        test_object = objects[0]
        setup_dict = {"set_state": "root", "set_type": "offline"}
        setup_str = param.re_str("root", param_str, objectless=True)
        root_parser = param.update_parser(test_object.parser,
                                          ovrwrt_dict=setup_dict,
                                          ovrwrt_str=setup_str,
                                          ovrwrt_file=param.tests_ovrwrt_file,
                                          ovrwrt_base_file="sets.cfg")
        for i, d in enumerate(root_parser.get_dicts()):
            logging.debug("Reached %s root %s", object_name, d["shortname"])
            assert i < 1, "There can only be one root for %s" % object_name
        return [TestNode(test_object.name, root_parser, [test_object])]

    def _get_and_parse_parent(self, test_node, test_object, param_str, setup_restr):
        """
        Perform a fast and simple check for a single parent node and
        generate it if it wasn't found during the check.

        .. note:: This method is a legacy method which works faster but
            *only* if the given test node has exactly *one* parent (per object).
        """
        get_parents = self._get_nodes_by("name", "(\.|^)%s(\.|$)" % setup_restr,
                                         subset=self._get_nodes_by("vms", "(^|\s)%s($|\s)" % test_object.name))
        parents = get_parents
        if len(get_parents) == 0:
            if setup_restr == "root":
                parse_parents = self._parse_object_root(test_object.name, param_str)
            else:
                setup_str = param.re_str(setup_restr, param_str, "", objectless=True)
                name = re.sub("(%s)" % "|".join([t.name for t in self._testobjects]), "", test_node.name) + "a"
                parse_parents = self.parse_nodes(setup_str, prefix=name, object_name=test_object.name)
            parents = parse_parents
        else:
            parse_parents = []
        # NOTE: it is possible that exactly one of multiple parents is already parsed and we don't
        # detect the node actually requiring more but again, this is legacy method and has its drawbacks
        assert len(parents) <= 1, ("Test %s has multiple setups:\n%s\nSpecify 'get_parse=advanced' to "
                                   "support this." % (test_node.params["shortname"],
                                                      "\n".join([p.params["shortname"] for p in parents])))
        return get_parents, parse_parents

    def _parse_and_get_parents(self, test_node, test_object, param_str):
        """
        Generate (if necessary) all parent test nodes for a given test
        node and test object (including the object creation root test).
        """
        get_parents, parse_parents = [], []
        object_params = test_node.params.object_params(test_object.name)
        # use get directive -> if not use get_state -> if not use root
        setup_restr = object_params.get("get", object_params.get("get_state", "root"))
        logging.debug("Parsing Cartesian setup of %s through restriction %s",
                      test_node.params["shortname"], setup_restr)

        # NOTE: in general everything should be parsed in the full functionality way
        # but for performance reasons, we will switch it off when we have the extra
        # knowledge that the current test node uses simple setup
        if object_params.get("get") is None and object_params.get("get_parse", "simple") == "simple":
            return self._get_and_parse_parent(test_node, test_object, param_str, setup_restr)
        elif object_params.get("get_parse", "advanced") != "advanced":
            raise ValueError("The setup parsing mode must be one of: 'simple', 'advanced'")

        if setup_restr == "root":
            new_parents = self._parse_object_root(test_object.name, param_str)
        else:
            setup_str = param.re_str(setup_restr, param_str, "", objectless=True)
            name = re.sub("(%s)" % "|".join([t.name for t in self._testobjects]), "", test_node.name) + "a"
            new_parents = self.parse_nodes(setup_str, prefix=name, object_name=test_object.name)
        for new_parent in new_parents:
            # BUG: a good way to get a variant valid test name was to use
            # re.sub("^(.+\.)*(all|none|minimal)\.", "", NAME)
            # but this regex performs extremely slow (much slower than string replacement)
            parent_name = ".".join(new_parent.params["name"].split(".")[2:])
            old_parents = self._get_nodes_by("name", "(\.|^)%s(\.|$)" % parent_name,
                                             subset=self._get_nodes_by("vms", "(^|\s)%s($|\s)" % test_object.name))
            assert len(old_parents) <= 1, "Full name parsing must give a unique '%s' test" % parent_name
            if len(old_parents) > 0:
                old_parent = old_parents[0]
                logging.debug("Found parsed dependency %s for %s through object %s",
                              old_parent.params["shortname"], test_node.params["shortname"], test_object.name)
                get_parents.append(old_parent)
            else:
                logging.debug("Found new dependency %s for %s through object %s",
                              new_parent.params["shortname"], test_node.params["shortname"], test_object.name)
                parse_parents.append(new_parent)
        return get_parents, parse_parents

    def _copy_branch(self, root_node, root_parent, parents):
        """
        Copy a test node and all of its descendants to provide each parent
        node with a unique successor.
        """
        to_copy = [(root_node, root_parent, parents)]
        while len(to_copy) > 0:
            child, parent, parents = to_copy.pop()

            clones = []
            for i in range(len(parents)):
                logging.debug("Duplicating test node %s for another parent %s",
                              child.params["shortname"], parents[i].params["shortname"])

                clone_variant = ".".join(child.params["name"].split(".")[1:])
                clone_name = re.sub("vm\d+", "", child.name) + "b"
                clone_name += str(i+1) + child.params["vms"].replace(" ", "")
                clone_str = param.re_str(clone_variant, tag=clone_name)
                # TODO: I am still not completely satisfied with the tagging system -
                # here it leaves a small residue which is the previous test tag
                parser = param.update_parser(child.parser,
                                             ovrwrt_str=clone_str)

                clones.append(TestNode(clone_name, parser, list(child.objects)))

                # clonse setup with the exception of unique parent copy
                for clone_setup in child.setup_nodes:
                    if clone_setup == parent:
                        clones[-1].setup_nodes.append(parents[i])
                        parents[i].cleanup_nodes.append(clones[-1])
                    else:
                        clones[-1].setup_nodes.append(clone_setup)
                        clone_setup.cleanup_nodes.append(clones[-1])

            for grandchild in child.cleanup_nodes:
                to_copy.append((grandchild, child, clones))

            self._testnodes.extend(clones)

    def _run_test_node(self, test_node, param_str):
        """Run a single test according to user defined policy and state availability."""
        # ephemeral setup can get lost and if so must be repeated
        if not test_node.should_run and test_node.is_ephemeral() and not test_node.is_cleanup_ready():
            for test_object in test_node.objects:
                object_name = test_object.name
                object_params = test_node.params.object_params(object_name)
                # if previous state is not known keep behavior assuming that the user knows what they are doing
                if object_params.get("set_state") != test_object.current_state != "unknown":
                    logging.debug("Re-running ephemeral setup %s since %s state was switched to %s",
                                  test_node.params["shortname"], test_object.name, test_object.current_state)
                    test_node.should_run = True
                    break

        if test_node.should_run:
            if test_node.is_root():
                logging.debug("Test run started from the shared root")

            # the primary setup nodes need special treatment
            elif test_node.params.get("set_state") in ["install", "root"]:
                try:
                    setup_str = param_str
                    if test_node.params["set_state"] == "root":
                        setup_str += param.dict_to_str({"set_state": "root", "set_type": "offline"})
                        self.run_create_test(test_node.params.get("vms", ""), setup_str, tag="root")
                    elif test_node.params["set_state"] == "install":
                        setup_tag = re.sub("(%s)" % "|".join([t.name for t in self._testobjects]), "", test_node.name)
                        self.run_install_test(test_node.params.get("vms", ""), setup_str, tag=setup_tag)

                except Exception as ex:
                    logging.error("Detected exception during initial setup:\n%s", ex)

            else:
                # finally, good old running of an actual test
                self.run_test_node(test_node)

            for test_object in test_node.objects:
                object_name = test_object.name
                object_params = test_node.params.object_params(object_name)
                if object_params.get("set_state") is not None and object_params.get("set_state") != "":
                    test_object.current_state = object_params.get("set_state")
            test_node.should_run = False
        else:
            logging.debug("Skipping test %s", test_node.params["shortname"])

    def _clean_test_node(self, test_node, param_str):
        """
        Cleanup any states that could be created by this node (will be skipped
        by default but the states can be removed with "unset_mode=f.").
        """
        if test_node.should_clean:
            if test_node.is_root():
                logging.debug("Test run ended at the shared root")
            else:
                for vm_name in test_node.params.objects("vms"):
                    vm_params = test_node.params.object_params(vm_name)
                    # avoid running any test unless the user really requires cleanup
                    if vm_params.get("unset_mode", "ri")[0] == "f" and vm_params.get("set_state"):
                        # NOTE: we are forcing the unset_mode to be the one defined for the test node because
                        # the unset manual step behaves differently now (all this extra complexity starts from
                        # the fact that it has different default value which is noninvasive
                        setup_str = param_str + param.dict_to_str({"unset_state": vm_params["set_state"],
                                                                   "unset_type": vm_params.get("set_type", "offline"),
                                                                   "unset_mode": vm_params.get("unset_mode", "ri")})
                        self.run_remove_test(vm_name, setup_str, tag="c" + vm_name + test_node.name)
        else:
            logging.debug("The test %s doesn't leave any states to be cleaned up", test_node.params["shortname"])
