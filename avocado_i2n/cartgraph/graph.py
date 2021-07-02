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
Utility for the main test suite data structure.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import os
import re
import logging

from ..states import setup as ss


def set_graph_logging_level(level=20):
    """
    Set the logging level specifically for the Cartesian graph.

    This determines what descriptions of the graph will be dumped
    for debugging purposes.
    """
    logging.getLogger('graph').setLevel(level)
set_graph_logging_level(level=20)


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

    def __repr__(self):
        dump = "[cartgraph] objects='%s' nodes='%s'" % (len(self.nodes), len(self.objects))
        for test_object in self.objects:
            dump = "%s\n\t%s" % (dump, str(test_object))
            for test_node in self.nodes:
                dump = "%s\n\t\t%s" % (dump, str(test_node))
        return dump

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
            node_params = test_node.params.copy()

            is_leaf = True
            for test_object in test_node.objects:
                object_params = test_object.object_typed_params(test_node.params)
                object_state = object_params.get("set_state")

                # the test leaves an object undefined so it cannot be reused for this object
                if object_state is None or object_state == "":
                    continue
                else:
                    is_leaf = False

                # the object state has to be defined to reach this stage
                if object_state == "root" and test_object.is_permanent():
                    test_node.should_run = False
                    break

                # ultimate consideration of whether the state is actually present
                node_params[f"check_state_{test_object.key}_{test_object.name}"] = object_state
                node_params[f"check_mode_{test_object.key}_{test_object.name}"] = object_params.get("check_mode", "rf")
                node_params[f"soft_boot_{test_object.key}_{test_object.name}"] = "no"

            if not is_leaf:
                test_node.should_run = not ss.check_states(node_params, env)
            logging.info("The test node %s %s run", test_node, "should" if test_node.should_run else "should not")

    def flag_children(self, node_name=None, object_name=None, flag_type="run", flag=True,
                      skip_roots=False):
        """
        Set the run/clean flag for all children of a parent node of a given name
        or the entire graph.

        :param node_name: name of the parent node or root if None
        :type node_name: str or None
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
            node_name = "root" if node_name is None else node_name
            root_tests = self.get_nodes_by(param_key="name", param_val="(?:\.|^)"+node_name+"(?:\.|$)")
            root_tests = self.get_nodes_by(param_key="vms",
                                           param_val="(?:^|\s)%s(?:$|\s)" % object_name,
                                           subset=root_tests)
        else:
            root_tests = self.get_nodes_by(param_key="name", param_val="(?:\.|^)0scan(?:\.|$)")
        if len(root_tests) < 1:
            raise AssertionError("Could not retrieve node %s and flag all its children tests" % node_name)
        elif len(root_tests) > 1:
            raise AssertionError("Could not identify node %s and flag all its children tests" % node_name)
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
        :type graph: :py:class:`TestGraph`
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
    def get_objects_by(self, param_key="main_vm", param_val="", subset=None):
        """
        Query all test objects by a value in a parameter, returning a set of objects.

        :param str param_key: exact key to use for the search
        :param str param_val: regex to match the object parameter values
        :param subset: a subset of test objects within the graph to search in
        :type subset: [:py:class:`TestObject`]
        :returns: a selection of objects satisfying ``key=val`` criterion
        :rtype: [:py:class:`TestObject`]
        """
        objects_selection = []
        if subset is None:
            subset = self.objects
        for test_object in subset:
            if re.search(param_val, test_object.params.get(param_key, "")):
                objects_selection.append(test_object)
        logging.debug("Retrieved %s/%s test objects with %s = %s",
                      len(objects_selection), len(subset), param_key, param_val)
        return objects_selection

    def get_object_by(self, param_key="main_vm", param_val="", subset=None):
        """
        Query all test objects by a value in a parameter, returning a unique object.

        :returns: a unique object satisfying ``key=val`` criterion
        :rtype: :py:class:`TestObject`

        The rest of the arguments are analogical to the plural version.
        """
        objects_selection = self.get_objects_by(param_key, param_val, subset)
        assert len(objects_selection) == 1, "Test object with %s=%s not existing"\
               " or unique in: %s" % (param_key, param_val, objects_selection)
        return objects_selection[0]

    def get_nodes_by(self, param_key="name", param_val="", subset=None):
        """
        Query all test nodes by a value in a parameter, returning a set of nodes.

        :param str param_key: exact key to use for the search
        :param str param_val: regex to match the object parameter values
        :param subset: a subset of test nodes within the graph to search in
        :type subset: [:py:class:`TestNode`]
        :returns: a selection of nodes satisfying ``key=val`` criterion
        :rtype: [:py:class:`TestNode`]
        """
        nodes_selection = []
        if subset is None:
            subset = self.nodes
        for test_node in subset:
            if re.search(param_val, test_node.params.get(param_key, "")):
                nodes_selection.append(test_node)
        logging.debug("Retrieved %s/%s test nodes with %s = %s",
                      len(nodes_selection), len(subset), param_key, param_val)
        return nodes_selection

    def get_node_by(self, param_key="name", param_val="", subset=None):
        """
        Query all test nodes by a value in a parameter, returning a unique node.

        :returns: a unique node satisfying ``key=val`` criterion
        :rtype: :py:class:`TestNode`

        The rest of the arguments are analogical to the plural version.
        """
        nodes_selection = self.get_nodes_by(param_key, param_val, subset)
        assert len(nodes_selection) == 1
        return nodes_selection[0]
