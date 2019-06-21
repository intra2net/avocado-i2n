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

from avocado.core import test
from avocado_vt.test import VirtTest

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
        """Parameters (cache) property."""
        if self._params_cache is None:
            self.regenerate_params()
        return self._params_cache
    params = property(fget=params)

    def id(self):
        return self.name
    id = property(fget=id)

    def __init__(self, name, config):
        """
        Construct a test object (vm) for any test nodes (tests).

        :param str name: name of the test object
        :param config: variant configuration for the test object
        :type config: :py:class:`param.Reparsable`
        """
        self.name = name
        self.config = config
        self._params_cache = None

        self.current_state = "unknown"

        # TODO: integrate these features better
        self.object_str = None

    def is_permanent(self):
        """
        If the test object is permanent, it can only be created manually
        (possibly through the use of manual setup steps).

        Online states on permanent test object are treated differently than
        online states on normal test object since they are preserved through
        test runs and even host shutdowns.
        """
        return self.params.get("permanent_vm", "no") == "yes"

    def regenerate_params(self, verbose=False):
        """
        Regenerate all parameters from the current reparsable config.

        :param bool verbose: whether to show generated parameter dictionaries
        """
        self._params_cache = self.config.get_params(show_dictionaries=verbose)


class TestNode(object):
    """
    A wrapper for all test relevant parts like parameters, parser, used
    objects and dependencies to/from other test nodes (setup/cleanup).
    """

    def params(self):
        """Parameters (cache) property."""
        if self._params_cache is None:
            self.regenerate_params()
        return self._params_cache
    params = property(fget=params)

    def id(self):
        return self.name + "-" + self.params["vms"].replace(" ", "")
    id = property(fget=id)

    def count(self):
        """Node count property."""
        return self.name
    count = property(fget=count)

    def __init__(self, name, config, objects):
        """
        Construct a test node (test) for any test objects (vms).

        :param str name: name of the test node
        :param config: variant configuration for the test node
        :type config: :py:class:`param.Reparsable`
        :param objects: objects participating in the test node
        :type objects: [TestObject]
        """
        self.name = name
        self.config = config
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

    def __repr__(self):
        return self.params["shortname"]

    def get_test_factory(self, job=None):
        """
        Get test factory from which the test loader will get a runnable test instance.

        :param job: avocado job object to for running or None for reporting only
        :type job: :py:class:`avocado.core.job.Job`
        :return: test class and constructor parameters
        :rtype: (type, {str, obj})
        """
        test_constructor_params = {'name': test.TestID(self.id, self.params["shortname"]),
                                   'vt_params': self.params}
        if job is not None:
            test_constructor_params['job'] = job
            test_constructor_params['base_logdir'] = job.logdir
        return (VirtTest, test_constructor_params)

    def is_scan_node(self):
        """Check if the test node is the root of all test nodes for all test objects."""
        return self.name == "0s" and len(self.objects) == 0

    def is_create_node(self):
        """Check if the test node is the root of all test nodes for some test object."""
        return self.name == "0r" and len(self.objects) == 1

    def is_install_node(self):
        """Check if the test node is the root of all test nodes for some test object."""
        return len(self.objects) == 1 and self.params.get("set_state") == "install"

    def is_shared_root(self):
        """Check if the test node is the root of all test nodes for all test objects."""
        return self.is_scan_node()

    def is_object_root(self):
        """Check if the test node is the root of all test nodes for some test object."""
        return self.is_create_node()

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
                    object_params.get("get_state", "0root") != "0root" and
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

    def regenerate_params(self, verbose=False):
        """
        Regenerate all parameters from the current reparsable config.

        :param bool verbose: whether to show generated parameter dictionaries
        """
        self._params_cache = self.config.get_params(show_dictionaries=verbose)


class TestGraph(object):
    """
    The main parsed and traversed test data structure.

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

    def test_objects(self):
        """Test objects dictionary property."""
        objects = {}
        for test_object in self.objects:
            objects[test_object.id] = test_object.params["shortname"]
        return objects
    test_objects = property(fget=test_objects)

    def test_nodes(self):
        """Test nodes dictionary property."""
        nodes = {}
        for test_node in self.nodes:
            nodes[test_node.id] = test_node.params["shortname"]
        return nodes
    test_nodes = property(fget=test_nodes)

    def __init__(self):
        """Construct the test graph."""
        self.nodes = []
        self.objects = []

    def new_objects(self, objects):
        """
        Add new objects excluding (old) repeating ones as ID.

        :param objects: candidate test objects
        :type objects: [:py:class:`TestObject`] or :py:class:`TestObject`
        """
        if not isinstance(objects, list):
            objects = [objects]
        test_objects_ids = self.test_objects.keys()
        for test_object in objects:
            if test_object.id in test_objects_ids:
                continue
            self.objects.append(test_object)

    def new_nodes(self, nodes):
        """
        Add new nodes excluding (old) repeating ones as ID.

        :param nodes: candidate test nodes
        :type nodes: [:py:class:`TestNode`] or :py:class:`TestNode`
        """
        if not isinstance(nodes, list):
            nodes = [nodes]
        test_nodes_ids = self.test_nodes.keys()
        for test_node in nodes:
            if test_node.id in test_nodes_ids:
                continue
            self.nodes.append(test_node)

    """dumping functionality"""
    def load_setup_list(self, dump_dir, filename="setup_list"):
        """
        Load the setup state of each node from a list file.

        :param str dump_dir: directory for the dump image
        :param str filename: file to load the setup information from
        """
        with open(os.path.join(dump_dir, filename), "r") as f:
            str_list = f.read()
        setup_list = re.findall("(\w+-\w+) (\d) (\d)", str_list)
        for i in range(len(setup_list)):
            assert self.nodes[i].id == setup_list[i][0], "Corrupted setup list file"
            self.nodes[i].should_run = bool(int(setup_list[i][1]))
            self.nodes[i].should_clean = bool(int(setup_list[i][2]))

    def save_setup_list(self, dump_dir, filename="setup_list"):
        """
        Save the setup state of each node to a list file.

        :param str dump_dir: directory for the dump image
        :param str filename: file to save the setup information to
        """
        str_list = ""
        for test in self.nodes:
            should_run = 1 if test.should_run else 0
            should_clean = 1 if test.should_clean else 0
            str_list += "%s %i %i\n" % (test.id, should_run, should_clean)
        with open(os.path.join(dump_dir, filename), "w") as f:
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
        total, finished = len(self.nodes), 0
        for tnode in self.nodes:
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
        for tnode in self.nodes:
            graph.node(tnode.id)
            for snode in tnode.setup_nodes:
                graph.node(snode.id)
                graph.edge(tnode.id, snode.id)
            for cnode in tnode.cleanup_nodes:
                graph.node(cnode.id)
                graph.edge(tnode.id, cnode.id)
        graph.render("%s/cg_%s_%s" % (dump_dir, id(self), n))

    """run/clean switching functionality"""
    def scan_object_states(self, env):
        """
        Scan for present object states to reuse tests from previous runs

        :param env: environment related to the test
        :type env: Env object
        """
        for test_node in self.nodes:
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

    def flag_children(self, state_name=None, object_name=None, flag_type="run", flag=True,
                      skip_roots=False):
        """
        Set the run/clean flag for all children of a node, whose `set_state`
        parameter is specified by the `state_name` argument.

        :param state_name: state which is set by the parent node or root if None
        :type state_name: str or None
        :param object_name: test object whose state is set or shared root if None
        :type object_name: str or None
        :param str flag_type: 'run' or 'clean' categorization of the children
        :param bool flag: whether the run/clean action should be executed or not
        :param bool skip_roots: whether the roots should not be flagged as well
        :raises: :py:class:`AssertionError` if obtained # of root tests is != 1
        """
        activity = ("" if flag else "not ") + ("running" if flag_type == "run" else "cleanup")
        logging.debug("Selecting test nodes for %s", activity)
        if object_name is not None:
            state_name = "root" if state_name is None else state_name
            root_tests = self.get_nodes_by(param_key="set_state", param_val="^"+state_name+"$")
            root_tests = self.get_nodes_by(param_key="vms",
                                           param_val="(^|\s)%s($|\s)" % object_name,
                                           subset=root_tests)
        else:
            root_tests = self.get_nodes_by(param_key="name", param_val="(\.|^)0scan(\.|^)")
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

    def flag_parent_intersection(self, graph, flag_type="run", flag=True,
                                 skip_object_roots=False, skip_shared_root=False):
        """
        Intersect the test nodes with the test nodes from another graph and
        set a run/clean flag for each one in the intersection.

        :param graph: Cartesian graph to intersect the current graph with
        :type graph: CartesianGraph object
        :param str flag_type: 'run' or 'clean' categorization of the children
        :param bool flag: whether the run/clean action should be executed or not
        :param bool skip_object_roots: whether the object roots should not be flagged as well
        :param bool skip_shared_root: whether the shared root should not be flagged as well

        .. note:: This method only works with reusable tests, due to current lack
            of proper test identification. It is generally meant for identifying
            paths of parents and not intersections of whole graphs.
        """
        activity = ("" if flag else "not ") + ("running" if flag_type == "run" else "cleanup")
        logging.debug("Selecting test nodes for %s", activity)
        for test_node in self.nodes:
            if test_node.is_shared_root() or len(graph.get_nodes_by(param_key="set_state",
                    param_val="^"+test_node.params["set_state"]+"$")) == 1:
                if test_node.is_shared_root() and skip_shared_root:
                    logging.info("Skip flag for shared root")
                    continue
                if test_node.is_object_root() and skip_object_roots:
                    logging.info("Skip flag for object root")
                    continue
                logging.debug("The test %s is set to %s.", test_node.params["shortname"], activity)
                if flag_type == "run":
                    test_node.should_run = flag
                else:
                    test_node.should_clean = flag

    """get queries"""
    def get_nodes_by(self, param_key="name", param_val="", subset=None):
        """
        Query all test nodes by a value in a parameter, returning a set of tests.

        Warning: The matching is using 'param LIKE %value%' instead of 'param=value'
        which is necessary for matching a subvariant if the key is the test name.
        """
        tests_selection = []
        if subset is None:
            subset = self.nodes
        for test in subset:
            if re.search(param_val, test.params.get(param_key, "")):
                tests_selection.append(test)
        logging.debug("Retrieved %s/%s test nodes with %s = %s",
                      len(tests_selection), len(subset), param_key, param_val)
        return tests_selection

    def get_objects_by(self, param_key="main_vm", param_val="", subset=None):
        """
        Query all test objects by a value in a parameter, returning a set of vms.

        Warning: The matching is using 'param LIKE %value%' instead of 'param=value'.
        """
        vms_selection = []
        if subset is None:
            subset = self.objects
        for vm in subset:
            if re.search(param_val, vm.params.get(param_key, "")):
                vms_selection.append(vm)
        logging.debug("Retrieved %s/%s test objects with %s = %s",
                      len(vms_selection), len(subset), param_key, param_val)
        return vms_selection
