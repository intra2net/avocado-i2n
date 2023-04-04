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
import logging as log
logging = log.getLogger('avocado.test.' + __name__)
import collections



def set_graph_logging_level(level=20):
    """
    Set the logging level specifically for the Cartesian graph.

    This determines what descriptions of the graph will be dumped
    for debugging purposes.
    """
    log.getLogger('graph').setLevel(level)
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

    def suffixes(self):
        """Test object suffixes and their variant restrictions."""
        objects = collections.OrderedDict()
        for test_object in self.objects:
            suffix = test_object.long_suffix
            if suffix in objects.keys():
                objects[suffix] += "," + test_object.params["name"]
            else:
                objects[suffix] = test_object.params["name"]
        return objects
    suffixes = property(fget=suffixes)

    def prefixes(self):
        """Test node prefixes and their variant restrictions."""
        nodes = collections.OrderedDict()
        for test_node in self.nodes:
            prefix = test_node.long_prefix
            if prefix in nodes.keys():
                nodes[prefix] += "," + test_node.params["name"]
            else:
                nodes[prefix] = test_node.params["name"]
        return nodes
    prefixes = property(fget=prefixes)

    def __init__(self):
        """Construct the test graph."""
        self.nodes = []
        self.objects = []

    def __repr__(self):
        dump = "[cartgraph] objects='%s' nodes='%s'" % (len(self.objects), len(self.nodes))
        for test_object in self.objects:
            dump = "%s\n\t%s" % (dump, str(test_object))
        for test_node in self.nodes:
            dump = "%s\n\t%s" % (dump, str(test_node))
        return dump

    def new_objects(self, objects):
        """
        Add new objects excluding (old) repeating ones as ID.

        :param objects: candidate test objects
        :type objects: [:py:class:`TestObject`] or :py:class:`TestObject`
        """
        if not isinstance(objects, list):
            objects = [objects]
        test_object_suffixes = self.suffixes.keys()
        for test_object in objects:
            if test_object.long_suffix in test_object_suffixes:
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
        test_node_prefixes = self.prefixes.keys()
        for test_node in nodes:
            if test_node.long_prefix in test_node_prefixes:
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
            assert self.nodes[i].long_prefix == setup_list[i][0], "Corrupted setup list file"
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
            str_list += "%s %i %i\n" % (test.long_prefix, should_run, should_clean)
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

    def visualize(self, dump_dir, tag=0):
        """
        Dump a visual description of the Cartesian graph at
        a given parsing/traversal step.

        :param str dump_dir: directory for the dump image
        :param str tag: tag of the dump, e.g. parsing/traversal step and slot
        """
        try:
            from graphviz import Digraph
            log.getLogger("graphviz").parent = log.getLogger("avocado.test")
        except ImportError:
            logging.warning("Couldn't visualize the Cartesian graph due to missing dependency (Graphviz)")
            return

        def get_display_id(node):
            node_id = node.long_prefix
            node_id += f"[{node.params['nets_host']}]" if node.is_occupied() else ""
            return node_id

        graph = Digraph('cartesian_graph', format='svg')
        for tnode in self.nodes:
            tid = get_display_id(tnode)
            graph.node(tid)
            for snode in tnode.setup_nodes:
                sid = get_display_id(snode)
                graph.node(sid)
                graph.edge(tid, sid)
            for cnode in tnode.cleanup_nodes:
                cid = get_display_id(cnode)
                graph.node(cid)
                graph.edge(tid, cid)
        graph.render(f"{dump_dir}/cg_{id(self)}_{tag}")

    """run/clean switching functionality"""
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
            if node_name:
                root_tests = self.get_nodes_by(param_key="name", param_val="(?:\.|^)"+node_name+"(?:\.|$)")
                # TODO: we only support vm objects at the moment
                root_tests = self.get_nodes_by(param_key="vms",
                                               param_val="(?:^|\s)%s(?:$|\s)" % object_name,
                                               subset=root_tests)
            else:
                root_tests = self.get_nodes_by(param_key="object_root", param_val="(?:\.|^)"+object_name+"(?:\.|$)")
        else:
            root_tests = self.get_nodes_by(param_key="shared_root", param_val="yes")
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
            test_node.should_scan = False
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
        """
        activity = ("" if flag else "not ") + ("running" if flag_type == "run" else "cleanup")
        logging.debug("Selecting test nodes for %s", activity)
        for test_node in self.nodes:
            name = ".".join(test_node.params["name"].split(".")[1:])
            if len(graph.get_nodes_by(param_key="name", param_val=name+"$")) == 1:
                if test_node.is_shared_root() and skip_shared_root:
                    logging.info("Skip flag for shared root")
                    continue
                if test_node.is_object_root() and skip_object_roots:
                    logging.info("Skip flag for object root")
                    continue
                logging.debug("The test %s is set to %s.", test_node.params["shortname"], activity)
                test_node.should_scan = False
                if flag_type == "run":
                    test_node.should_run = flag
                else:
                    test_node.should_clean = flag

    """get queries"""
    def get_objects_by(self, param_key="name", param_val="", subset=None):
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

    def get_object_by(self, param_key="name", param_val="", subset=None):
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
