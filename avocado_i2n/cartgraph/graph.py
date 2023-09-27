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
Main test suite data structure containing tests as nodes in graph
and their dependencies or edges as stateful objects.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import os
import re
import logging as log
logging = log.getLogger('avocado.job.' + __name__)
import collections
import itertools

from .. import params_parser as param
from . import TestNode, TestWorker, TestObject, NetObject, VMObject, ImageObject


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

    logdir = None

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

    @staticmethod
    def clone_branch(copy_node, copy_object, copy_parents):
        """
        Clone a test node and all of its descendants as a branch path within the graph.

        This is done to provide each parent node with a unique successor.
        """
        test_nodes = []
        to_copy = [(copy_node, copy_parents)]

        while len(to_copy) > 0:
            clone_source, parents = to_copy.pop()
            clones = []
            logging.debug("Duplicating test node %s for multiple parents:\n%s",
                          clone_source.params["shortname"],
                          "\n".join([p.params["shortname"] for p in parents]))
            for i, parent in enumerate(parents):
                if i == 0:
                    child = clone_source
                else:
                    clone_name = clone_source.prefix + "d" + str(i)
                    clone_config = clone_source.config.get_copy()
                    clone = TestNode(clone_name, clone_config, clone_source.objects[0])
                    clone.regenerate_params()

                    # clone setup with the exception of unique parent copy
                    for clone_setup in clone_source.setup_nodes:
                        if clone_setup == parents[0]:
                            clone.setup_nodes.append(parent)
                            parent.cleanup_nodes.append(clone)
                        else:
                            clone.setup_nodes.append(clone_setup)
                            clone_setup.cleanup_nodes.append(clone)

                    child = clone
                    clones.append(child)

                state_suffixes = f"_{copy_object.key}_{copy_object.suffix}"
                state_suffixes += f"_{copy_object.composites[0].suffix}" if copy_object.key == "images" else ""

                parent_object_params = copy_object.object_typed_params(parent.params)
                parent_state = parent_object_params.get("set_state", "")
                child.params["shortname"] += "." + parent_state
                child.params["name"] += "." + parent_state
                child.params["get_state" + state_suffixes] = parent_state
                child_object_params = copy_object.object_typed_params(child.params)
                child_state = child_object_params.get("set_state", "")
                if child_state:
                    child.params["set_state" + state_suffixes] = child_state + "." + parent_state

            for grandchild in clone_source.cleanup_nodes:
                to_copy.append((grandchild, [clone_source, *clones]))
            test_nodes.extend(clones)

        return test_nodes

    def __init__(self):
        """Construct the test graph."""
        self.objects = []
        self.nodes = []
        self.workers = {}

    def __repr__(self):
        dump = "[cartgraph] objects='%s' nodes='%s'" % (len(self.objects), len(self.nodes))
        for test_object in self.objects:
            dump = "%s\n\t%s" % (dump, str(test_object))
        for test_node in self.nodes:
            dump = "%s\n\t%s" % (dump, str(test_node))
        return dump

    def new_objects(self, objects: list[TestObject] or TestObject) -> None:
        """
        Add new objects excluding (old) repeating ones as ID.

        :param objects: candidate test objects
        """
        if not isinstance(objects, list):
            objects = [objects]
        test_object_suffixes = self.suffixes.keys()
        for test_object in objects:
            if test_object.long_suffix in test_object_suffixes:
                continue
            self.objects.append(test_object)

    def new_nodes(self, nodes: list[TestNode] or TestNode) -> None:
        """
        Add new nodes excluding (old) repeating ones as ID.

        :param nodes: candidate test nodes
        """
        if not isinstance(nodes, list):
            nodes = [nodes]
        test_node_prefixes = self.prefixes.keys()
        for test_node in nodes:
            if test_node.long_prefix in test_node_prefixes:
                continue
            self.nodes.append(test_node)

    def new_workers(self, workers: list[TestWorker] or TestWorker) -> None:
        """
        Add new workers excluding (old) repeating ones as ID.

        :param workers: candidate test workers
        """
        if not isinstance(workers, list):
            workers = [workers]
        for worker in workers:
            self.workers[worker.params["shortname"]] = worker

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
            self.nodes[i].should_run = lambda x: bool(int(setup_list[i][1]))
            self.nodes[i].should_clean = lambda x: bool(int(setup_list[i][2]))

    def save_setup_list(self, dump_dir, filename="setup_list"):
        """
        Save the setup state of each node to a list file.

        :param str dump_dir: directory for the dump image
        :param str filename: file to save the setup information to
        """
        str_list = ""
        for test in self.nodes:
            should_run = 1 if test.should_run() else 0
            should_clean = 1 if test.should_clean() else 0
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
            # we count with additional eagerness for at least one worker
            if tnode.is_eagerly_finished():
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
            log.getLogger("graphviz").parent = log.getLogger("avocado.job")
        except ImportError:
            logging.warning("Couldn't visualize the Cartesian graph due to missing dependency (Graphviz)")
            return

        def get_display_id(node):
            node_id = node.long_prefix
            node_id += f"[{node.params['nets_host']}/{node.params['nets_host']}]" if node.is_occupied() else ""
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
    def flag_children(self, node_name=None, object_name=None,
                      flag_type="run", flag=lambda self, slot: slot not in self.workers,
                      skip_parents=False, skip_children=False):
        """
        Set the run/clean flag for all children of a parent node of a given name.

        :param node_name: name of the parent node or root if None
        :type node_name: str or None
        :param object_name: test object whose state is set or shared root if None
        :type object_name: str or None
        :param str flag_type: 'run' or 'clean' categorization of the children
        :param function flag: whether and when the run/clean action should be executed
        :param bool skip_parents: whether the parents should not be flagged (just children)
        :param bool skip_children: whether the children should not be flagged (just roots)
        :raises: :py:class:`AssertionError` if obtained # of root tests is != 1

        ..note:: Works only with connected graphs and will skip any disconnected nodes.
        """
        activity = "running" if flag_type == "run" else "cleanup"
        logging.debug(f"Flagging test nodes for {activity}")
        if object_name is None and node_name is None:
            root_tests = self.get_nodes_by(param_key="shared_root", param_val="yes")
        elif node_name is None:
            root_tests = self.get_nodes_by(param_key="object_root", param_val="(?:-|\.|^)"+object_name+"(?:-|\.|$)")
        else:
            root_tests = self.get_nodes_by(param_key="name", param_val="(?:\.|^)"+node_name+"(?:\.|$)")
            if object_name:
                # TODO: we only support vm objects at the moment
                root_tests = self.get_nodes_by(param_key="vms",
                                               param_val="(?:^|\s)"+object_name+"(?:$|\s)",
                                               subset=root_tests)
        if len(root_tests) < 1:
            raise AssertionError(f"Could not retrieve node with name {node_name} and flag all its children tests")
        elif len(root_tests) > 1:
            raise AssertionError(f"Could not identify node with name {node_name} and flag all its children tests")
        else:
            test_node = root_tests[0]

        if not skip_parents:
            flagged = [test_node]
        else:
            flagged = []
            flagged.extend(test_node.cleanup_nodes)
        while len(flagged) > 0:
            test_node = flagged.pop()
            logging.debug(f"The test {test_node} is assigned custom {activity} policy")
            if flag_type == "run":
                test_node.should_run = flag.__get__(test_node)
            else:
                test_node.should_clean = flag.__get__(test_node)
            if not skip_children:
                flagged.extend(test_node.cleanup_nodes)

    def flag_intersection(self, graph,
                          flag_type="run", flag=lambda self, slot: slot not in self.workers,
                          skip_object_roots=False, skip_shared_root=False):
        """
        Set the run/clean flag for all test nodes intersecting with the test nodes from another graph.

        :param graph: Cartesian graph to intersect the current graph with
        :type graph: :py:class:`TestGraph`
        :param str flag_type: 'run' or 'clean' categorization of the children
        :param function flag: whether and when the run/clean action should be executed
        :param bool skip_object_roots: whether the object roots should not be flagged as well
        :param bool skip_shared_root: whether the shared root should not be flagged as well

        ..note:: Works also with disconnected graphs and will not skip any disconnected nodes.
        """
        activity = "running" if flag_type == "run" else "cleanup"
        logging.debug(f"Flagging test nodes for {activity}")
        for test_node in self.nodes:
            name = ".".join(test_node.params["name"].split(".")[1:])
            matching_nodes = graph.get_nodes_by(param_key="name", param_val=name+"$")
            if len(matching_nodes) == 0:
                logging.debug(f"Skip flag for non-overlaping {test_node}")
                continue
            elif len(matching_nodes) > 1:
                raise ValueError(f"Cannot map {test_node} into a unique test node from {graph}")
            if test_node.is_shared_root() and skip_shared_root:
                logging.info("Skip flag for shared root")
                continue
            if test_node.is_object_root() and skip_object_roots:
                logging.info("Skip flag for object root")
                continue
            logging.debug(f"The test {test_node} is assigned custom {activity} policy")
            if flag_type == "run":
                test_node.should_run = flag.__get__(test_node)
            else:
                test_node.should_clean = flag.__get__(test_node)

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

    """parsing functionality"""
    @staticmethod
    def parse_flat_objects(suffix: str, category: str, restriction: str = "",
                           params: dict[str, str] = None) -> list[TestObject]:
        """
        Parse a flat object for each variant of a suffix satisfying a restriction.

        :param suffix: suffix to expand into variant objects
        :param category: category of the suffix that will determine the type of the objects
        :param restriction: restriction for the generated variants
        :param params: additional parameters to add to or overwrite all objects' parameters
        """
        params = {} if not params else params
        params_str = param.ParsedDict(params).parsable_form()
        restriction = category if not restriction else restriction

        if category == "images":
            raise TypeError("Multi-variant image test objects are not supported.")
        object_class = NetObject if category == "nets" else VMObject

        test_objects = []
        # pick a suffix and all its variants via join operation
        config = param.Reparsable()
        config.parse_next_batch(base_file=f"{category}.cfg",
                                base_str=param.join_str({suffix: "only " + restriction + "\n"}, params_str),
                                ovrwrt_file=param.ovrwrt_file("objects"))
        for d in config.get_parser().get_dicts():
            variant_config = config.get_copy()
            variant_config.parse_next_str("only " + d["name"])

            test_object = object_class(suffix, variant_config)
            test_object.regenerate_params()
            test_objects += [test_object]

        return test_objects

    @staticmethod
    def parse_composite_objects(suffix: str, category: str, restriction: str = "",
                                component_restrs: dict[str, str] = None,
                                params: dict[str, str] = None, verbose: bool = False) -> list[TestObject]:
        """
        Parse a composite object for each variant from joined component variants.

        :param suffix: suffix to expand into variant objects
        :param category: category of the suffix that will determine the type of the objects
        :param restriction: restriction for the composite generated variants
        :param component_restrs: object-specific suffixes (keys) and variant restrictions (values) for the components
        :param params: runtime parameters used for extra customization
        :param verbose: whether to print extra messages or not
        :returns: parsed test objects
        """
        params = {} if not params else params
        params_str = param.ParsedDict(params).parsable_form()
        restriction = category if not restriction else restriction
        if component_restrs is None:
            # TODO: all possible default suffixes, currently only vms supported
            component_restrs = {suffix: "" for suffix in param.all_objects("vms")}

        if category == "images":
            raise TypeError("Multi-variant image test objects are not supported.")
        object_class = NetObject if category == "nets" else VMObject
        top_restriction = {suffix: "only " + restriction + "\n"}
        vm_restrs = component_restrs if category == "nets" else top_restriction
        main_vm = param.main_vm() if len(vm_restrs.keys()) > 1 else list(vm_restrs.keys())[0]

        test_objects = []
        # all possible component object combinations for a given composite object
        config = param.Reparsable()
        # TODO: an unexpected order of joining in the Cartesian config requires us to parse nets first
        # instead of the more reasonable vms followed by nets
        if category == "nets":
            config.parse_next_batch(base_file="nets.cfg",
                                    base_str=param.join_str(top_restriction, params_str),
                                    base_dict={})
        config.parse_next_batch(base_file="vms.cfg",
                                base_str=param.join_str(vm_restrs, params_str),
                                # make sure we have the final word on parameters we use to identify objects
                                base_dict={"main_vm": main_vm})
        config.parse_next_file(param.vms_ovrwrt_file())
        for i, d in enumerate(config.get_parser().get_dicts()):
            variant_config = config.get_copy()
            test_object = object_class(suffix, variant_config)

            if category == "vms":
                variant_config.parse_next_str("only " + d["name"])
            elif category == "nets":
                # TODO: joined variants do not support follow-up restrictions to generalize this to nets,
                # this includes stacked vm-specific restrictions or any other join-generic such
                test_object.dict_index = i
            # TODO: the Cartesian parser does not support checkpoint dictionaries
            #test_object.config = param.Reparsable()
            #test_object.config.parse_next_dict(d)
            test_object.regenerate_params()

            if verbose:
                print(f"{test_object.key.rstrip('s')}    {test_object.suffix}:  {test_object.params['shortname']}")
            test_objects += [test_object]

        return test_objects

    @staticmethod
    def parse_suffix_objects(category: str, suffix_restrs: dict[str, str] = None,
                             params: dict[str, str] = None, verbose: bool = False, flat: bool = False) -> list[TestObject]:
        """
        Parse all available test objects and their configuration determined by available suffixes.

        :param category: category of suffixes that will determine the type of the objects
        :param suffix_restrs: object-specific suffixes (keys) and variant restrictions (values) for the final objects
        :param params: runtime parameters used for extra customization
        :param verbose: whether to print extra messages or not
        :param flat: whether to parse flat or composite objects
        :returns: parsed test objects
        """
        if suffix_restrs is None:
            # all possible default suffixes
            selected_suffixes = param.all_objects(category)
            suffix_restrs = {suffix: "" for suffix in selected_suffixes}
        else:
            selected_suffixes = suffix_restrs.keys()

        test_objects = []
        for suffix in selected_suffixes:
            if flat:
                test_objects += TestGraph.parse_flat_objects(suffix, category, suffix_restrs[suffix], params=params)
            else:
                test_objects += TestGraph.parse_composite_objects(suffix, category, suffix_restrs[suffix],
                                                                  params=params, verbose=verbose)

        return test_objects

    @staticmethod
    def parse_object_from_objects(suffix: str, category: str, test_objects: tuple[TestObject],
                                  params: dict[str, str] = None, verbose: bool = False) -> list[TestObject]:
        """
        Parse a unique composite object from joined already parsed component objects.

        :param suffix: suffix to expand into variant objects
        :param category: category of the suffix that will determine the type of the objects
        :param test_objects: fully parsed test objects to parse the composite from
        :param params: runtime parameters used for extra customization
        :param verbose: whether to print extra messages or not
        :returns: parsed test objects
        :raises: :py:class:`exceptions.AssertionError` if the parsed composite is not unique
        """
        setup_dict = {} if params is None else params.copy()
        setup_dict.update({f"object_id_{o.suffix}": o.id for o in test_objects})
        object_strs = {o.suffix: o.final_restr for o in test_objects}
        composite_objects = TestGraph.parse_composite_objects(suffix, category, component_restrs=object_strs,
                                                              params=setup_dict, verbose=verbose)

        if len(composite_objects) > 1:
            raise AssertionError(f"No unique composite could be parsed using {test_objects}\n"
                                 f"Parsed multiple composite objects: {composite_objects}")
        composite = composite_objects[0]

        for test_object in test_objects:
            composite.components.append(test_object)
            test_object.composites.append(composite)

        return composite

    @staticmethod
    def parse_components_for_object(test_object: TestObject, category: str, restriction: str = "",
                                    params: dict[str, str] = None, verbose: bool = False, unflatten: bool = False) -> list[TestObject]:
        """
        Parse all component objects for an already parsed composite object.

        :param test_object: fully parsed test object to parse for components of
        :param category: category of the suffix that will determine the type of the objects
        :param restriction: restriction for the unflattened object if needed
        :param params: runtime parameters used for extra customization
        :param verbose: whether to print extra messages or not
        :param unflatten: whether to unflatten flat objects with their components
        """
        test_objects = []
        if category == "images":
            return test_objects
        if category == "vms":
            vm = test_object
            for image_name in vm.params.objects("images"):
                image_suffix = f"{image_name}_{vm.suffix}"
                config = param.Reparsable()
                config.parse_next_dict(vm.params.object_params(image_name))
                image = ImageObject(image_suffix, config)
                test_objects.append(image)
                vm.components.append(image)
                image.composites.append(vm)
            if unflatten:
                test_objects += TestGraph.parse_composite_objects(vm.suffix, "vms", restriction, params=params, verbose=verbose)
            return test_objects

        net = test_object
        suffix_variants = {}
        selected_vms = net.params.objects("vms") or param.all_objects("vms")
        for vm_name in selected_vms:

            # TODO: the images don't have variant suffix definitions so just
            # take the vm generic variant and join it with itself, i.e. here
            # all possible hardware-software combinations as variants of the same vm slot
            vms = TestGraph.parse_composite_objects(vm_name, "vms", restriction=net.params.get("only_" + vm_name, "vms"),
                                                    params=params, verbose=verbose)

            suffix_variants[f"{vm_name}_{net.suffix}"] = vms
            test_objects.extend(vms)

            # currently unique handling for nested image test objects
            for vm in vms:
                TestGraph.parse_components_for_object(vm, "vms", params=params)

        if unflatten:
            # NOTE: due to limitation in Cartesian config vms are not parsed as composite objects
            # all possible vm combinations as variants of the same net slot
            for combination in itertools.product(*suffix_variants.values()):
                net = TestGraph.parse_object_from_objects(net.suffix, "nets", combination, params=params, verbose=verbose)
                test_objects.append(net)

        return test_objects

    @staticmethod
    def parse_net_from_object_strs(object_strs):
        """
        Parse a default net with object strings as compatibility.

        :param object_strs: object restrictions
        :type object_strs: {str, str}
        """
        config = param.Reparsable()
        config.parse_next_dict({"vms": " ".join(list(object_strs.keys()))})
        config.parse_next_dict({f"only_{s}": object_strs[s] for s in object_strs})
        return NetObject("net1", config)

    @staticmethod
    def parse_flat_nodes(param_dict=None, nodes_str=""):
        """
        Parse flat nodes as a generator in order to compose with test objects.

        :param param_dict: extra parameters to be used as overwrite dictionary
        :type param_dict: {str, str} or None
        :param str nodes_str: block of node-specific variant restrictions
        """
        early_config = param.Reparsable()
        early_config.parse_next_file("sets.cfg")
        early_config.parse_next_str(nodes_str)
        early_config.parse_next_dict(param_dict)
        test_node = TestNode("0", early_config, NetObject("net0", early_config))
        for i, d in enumerate(early_config.get_parser().get_dicts()):
            test_node.prefix = str(i)
            test_node._params_cache = d
            yield test_node

    @staticmethod
    def parse_node_from_object(test_object, param_dict=None, param_str="", prefix=""):
        """
        Get the original install test node for the given object.

        :param test_object: fully parsed test object to parse the node from
        :type: test_object: :py:class:`NetObject`
        :param param_dict: extra parameters to be used as overwrite dictionary
        :type param_dict: {str, str} or None
        :param str param_str: string block of parameters to be used as overwrite string
        :param str prefix: extra name identifier for the test to be run
        :returns: parsed test node for the object
        :rtype: :py:class:`TestNode`
        :raises: :py:class:`ValueError` if the node is parsed from a non-net object
        :raises: :py:class:`param.EmptyCartesianProduct` if a vm variant is not compatible
                 with another vm variant within the same test node
        """
        if test_object.key != "nets":
            raise ValueError("Test node could be parsed only from test objects of the "
                             "same composition level, currently only test nets")
        config = test_object.config.get_copy()
        config.parse_next_batch(base_file="sets.cfg",
                                ovrwrt_file=param.tests_ovrwrt_file(),
                                ovrwrt_str=param_str,
                                ovrwrt_dict=param_dict)
        test_node = TestNode(prefix, config, test_object)
        test_node.regenerate_params()
        for vm_name in test_node.params.objects("vms"):
            if test_node.params.get(f"only_{vm_name}"):
                for vm_variant in test_node.params[f"only_{vm_name}"].split(","):
                    # TODO: have to check the separate objects!
                    if vm_variant.strip() in test_node.params["name"]:
                        break
                else:
                    raise param.EmptyCartesianProduct("Mutually incompatible vm variants")
        return test_node

    def parse_and_get_objects_for_node(self, test_node: TestNode, params: dict[str, str] = None) -> list[TestObject]:
        """
        Generate or reuse all component test objects for a given test node.

        Decide about test objects participating in the test node returning the
        final selection of such and the main object for the test.

        :param test_node: fully parsed test node to check the components from
        :param params: runtime parameters used for extra customization
        """
        d, graph = test_node.params, self
        object_name = d.get("object_suffix", "")
        object_type = d.get("object_type", "")
        object_variant = d.get("object_id", ".*").replace(object_name + "-", "")

        all_vms = param.all_objects(key="vms")
        def needed_vms():
            # case of singleton test node
            if d.get("vms") is None:
                if object_type != "nets":
                    if object_name:
                        # as the object depending on this node might not be a vm
                        # and thus a suffix, we have to obtain the relevant vm (suffix)
                        vms = [object_name.split("_")[-1]]
                    else:
                        vms = [d.get("main_vm", param.main_vm())]
                else:
                    vms = []
                    for vm_name in all_vms:
                        if re.search("(\.|^)" + vm_name + "(\.|$)", object_variant):
                            vms += [vm_name]
            else:
                # case of leaf test node or even specified object (dependency) as well as node
                vms = d["vms"].split(" ")
            return vms
        vms = needed_vms()
        dropped_vms = set(all_vms) - set(vms)
        logging.debug(f"Fetching nets composed of {', '.join(vms)} to parse {d['shortname']} nodes")

        get_vms = {}
        for vm_name in vms:
            # get vm objects of all variants with the current suffix
            get_vms[vm_name] = [o for o in graph.objects if o.key == "vms" and o.suffix == vm_name]
            # mix of regex and own OR operator to restrict down to compatible variants
            filtered_vms = []
            for vm_variant in d.get(f"only_{vm_name}", ".*").split(","):
                vm_restr = "(\.|^)" + vm_variant.strip() + "(\.|$)"
                filtered_vms += graph.get_objects_by(param_val=vm_restr, subset=get_vms[vm_name])
            get_vms[vm_name] = filtered_vms
            # dependency filter for child node object has to be applied too
            if vm_name == object_name or (object_type == "images" and object_name.endswith(f"_{vm_name}")):
                get_vms[vm_name] = graph.get_objects_by(param_val="(\.|^)" + object_variant + "(\.|$)", subset=get_vms[vm_name])
            if len(get_vms[vm_name]) == 0:
                raise ValueError(f"Could not fetch any objects for suffix {vm_name} "
                                 f"in the test {d['shortname']}")
            get_vms[vm_name] = sorted(get_vms[vm_name], key=lambda x: x.id)

        previous_nets = [o for o in graph.objects if o.key == "nets"]
        # dependency filter for child node object has to be applied too
        if object_variant and object_type == "nets":
            previous_nets = graph.get_objects_by(param_val="(\.|^)" + object_variant + "(\.|$)", subset=previous_nets)
        get_nets, parse_nets = {"net1": []}, {"net1": []}
        # all possible vm combinations as variants of the same net slot
        for combination in itertools.product(*get_vms.values()):
            # filtering for nets based on complete vm object variant names from the product
            reused_nets, filtered_nets = [], list(previous_nets)
            for vm_object in combination:
                vm_restr = "(\.|^)" + vm_object.component_form + "(\.|$)"
                filtered_nets = graph.get_objects_by(param_val=vm_restr, subset=filtered_nets)
            # additional filtering for nets based on dropped vm suffixes
            for get_net in filtered_nets:
                for vm_suffix in dropped_vms:
                    if re.search("(\.|^)" + vm_suffix + "(\.|$)", get_net.params["name"]):
                        logging.info(f"Test net {get_net} not (right-)compatible with the test node "
                                     f"{d['shortname']} configuration and contains a redundant {vm_suffix}")
                        break
                else:
                    reused_nets += [get_net]
            if len(reused_nets) == 1:
                get_nets["net1"] += [reused_nets[0]]
            elif len(reused_nets) == 0:
                logging.debug(f"Parsing a new net from vms {', '.join(vms)} for {d['shortname']}")
                net = TestGraph.parse_object_from_objects("net1", "nets", combination, params=params, verbose=False)
                parse_nets["net1"] += [net]
                graph.objects += [net]
            else:
                raise ValueError("Multiple nets reusable for the same vm variant combination:\n{reused_nets}")
        get_nets["net1"] = sorted(get_nets["net1"], key=lambda x: x.id)
        parse_nets["net1"] = sorted(parse_nets["net1"], key=lambda x: x.id)

        logging.debug(f"{len(get_nets['net1'])} test nets will be reused for {d['shortname']} "
                      f"with {len(parse_nets['net1'])} newly parsed ones")
        return get_nets["net1"] + parse_nets["net1"]

    def parse_nodes(self, param_dict=None, nodes_str="", prefix="", verbose=False):
        """
        Parse all user defined tests (leaf nodes) using the nodes restriction string
        and possibly restricting to a single test object for the singleton tests.

        :param param_dict: extra parameters to be used as overwrite dictionary
        :type param_dict: {str, str} or None
        :param str nodes_str: block of node-specific variant restrictions
        :param str prefix: extra name identifier for the test to be run
        :param bool verbose: whether to print extra messages or not
        :returns: parsed test nodes
        :rtype: [:py:class:`TestNode`]
        :raises: :py:class:`param.EmptyCartesianProduct` if no result on preselected vm

        All already parsed test objects will be used to also validate test object
        uniqueness and main test object.
        """
        test_nodes = []

        # prepare initial parser as starting configuration and get through tests
        for i, node in enumerate(self.parse_flat_nodes(param_dict, nodes_str)):

            # get configuration of each participating object and choose the one to mix with the node
            try:
                test_nets = self.parse_and_get_objects_for_node(node, params=param_dict)
            except ValueError:
                logging.debug(f"Could not get or construct a test net that is (right-)compatible "
                              f"with the test node {node.params['shortname']} configuration - skipping")
                continue

            # produce a test node variant for each reused test net variant
            logging.debug(f"Parsing {node.params['name']} customization for {test_nets}")
            for j, net in enumerate(test_nets):
                try:
                    j_prefix = "b" + str(j) if j > 0 else ""
                    node_prefix = prefix + str(i+1) + j_prefix
                    test_node = self.parse_node_from_object(net, param_dict, param.re_str(node.params['name']),
                                                            prefix=node_prefix)
                    logging.debug(f"Parsed a test node {test_node.params['shortname']} from "
                                  f"two-way compatible test net {net}")
                    # provide dynamic fingerprint to an original object root node
                    if re.search("(\.|^)original(\.|$)", test_node.params["name"]):
                        test_node.params["object_root"] = node.params.get("object_id", net.id)
                except param.EmptyCartesianProduct:
                    # empty product in cases like parent (dependency) nodes imply wrong configuration
                    if node.params.get("require_existence", "no") == "yes":
                        raise
                    logging.debug(f"Test net {net} not (left-)compatible with the test node "
                                  f"{node.params['shortname']} configuration - skipping")
                else:
                    if verbose:
                        print(f"test    {test_node.prefix}:  {test_node.params['shortname']}")
                    test_nodes.append(test_node)

        return test_nodes

    @staticmethod
    def parse_object_nodes(param_dict=None, nodes_str="", object_strs=None,
                           prefix="", verbose=False):
        """
        Parse test nodes based on a selection of parsable objects.

        :returns: parsed test nodes and test objects
        :rtype: ([:py:class:`TestNode`], [:py:class:`TestObject`])
        :raises: :py:class:`param.EmptyCartesianProduct` if no test variants for the given vm variants

        The rest of the parameters are identical to the methods before.

        We will parse all available objects in the configs, then parse all
        selected nodes and finally restrict to the selected objects specified
        via the object strings (if set) on a test by test basis.
        """
        test_nodes, test_objects = [], []
        # starting object restrictions could be specified externally
        object_strs = {} if object_strs is None else object_strs

        graph = TestGraph()
        graph.objects = TestGraph.parse_components_for_object(TestGraph.parse_net_from_object_strs(object_strs), "nets",
                                                              params=param_dict, verbose=False, unflatten=False)
        # the parsed test nodes are already fully restricted by the available test objects
        graph.nodes = graph.parse_nodes(param_dict, nodes_str, prefix=prefix, verbose=True)
        for test_node in graph.nodes:
            test_nodes.append(test_node)
            for test_object in test_node.objects:
                if test_object.key == "vms":
                    if test_object not in test_objects:
                        test_objects.append(test_object)
                        test_objects.extend(test_object.components)
                        if verbose:
                            print("vm    %s:  %s" % (test_object.suffix, test_object.params["shortname"]))
            # reuse additionally parsed net (node-level) objects
            if test_node.objects[0] not in test_objects:
                test_objects.append(test_node.objects[0])

        # handle empty product of node and object variants
        if len(test_nodes) == 0:
            object_restrictions = param.join_str(object_strs)
            config = param.Reparsable()
            config.parse_next_str(object_restrictions)
            config.parse_next_str(nodes_str)
            config.parse_next_dict(param_dict)
            raise param.EmptyCartesianProduct(config.print_parsed())
        if verbose:
            print("%s selected test variant(s)" % len(test_nodes))
            print("%s selected vm variant(s)" % len([t for t in test_objects if t.key == "vms"]))

        return test_nodes, test_objects

    def parse_and_get_nodes_for_node_and_object(self, test_node: TestNode, test_object: TestObject,
                                                params: dict[str, str] = None) -> tuple[list[TestNode], list[TestNode]]:
        """
        Generate or reuse all parent test nodes for a given test node and test object.

        This includes the terminal test used for the object creation.

        :param test_node: fully parsed test node to check the dependencies from
        :param test_object: fully parsed test object to identify a unique node dependency
        :param params: runtime parameters used for extra customization
        """
        graph = self
        object_params = test_object.object_typed_params(test_node.params)
        # objects can appear within a test without any prior dependencies
        setup_restr = object_params["get"]
        setup_obj_resr = test_object.component_form
        logging.debug("Cartesian setup of %s for %s uses restriction %s",
                      test_object.long_suffix, test_node.params["shortname"], setup_restr)

        # speedup for handling already parsed unique parent cases
        get_parent = graph.get_nodes_by("name", "(\.|^)%s(\.|$)" % setup_restr,
                                        subset=graph.get_nodes_by("name",
                                                                  "(\.|^)%s(\.|$)" % setup_obj_resr))
        # the vm whose dependency we are parsing may not be restrictive enough so reuse optional other
        # objects variants of the current test node - cloning is only supported in the node restriction
        if len(get_parent) > 1:
            for test_object in test_node.objects:
                object_parents = graph.get_nodes_by("name", "(\.|^)%s(\.|$)" % test_object.component_form,
                                                    subset=get_parent)
                get_parent = object_parents if len(object_parents) > 0 else get_parent
            if len(get_parent) > 0:
                return get_parent, []
        if len(get_parent) == 1:
            return get_parent, []
        setup_dict = {} if params is None else params.copy()
        setup_dict.update({"object_suffix": test_object.long_suffix,
                           "object_type": test_object.key,
                           "object_id": test_object.id,
                           "require_existence": "yes"})
        setup_str = param.re_str("all.." + setup_restr)
        name = test_node.prefix + "a"
        new_parents = self.parse_nodes(setup_dict, setup_str, prefix=name)
        if len(get_parent) == 0:
            return [], new_parents

        get_parents, parse_parents = [], []
        for new_parent in new_parents:
            # BUG: a good way to get a variant valid test name was to use
            # re.sub("^(.+\.)*(all|normal|minimal|...)\.", "", NAME)
            # but this regex performs extremely slow (much slower than string replacement)
            parent_name = ".".join(new_parent.params["name"].split(".")[1:])
            old_parents = graph.get_nodes_by("name", "(\.|^)%s(\.|$)" % parent_name,
                                             subset=graph.get_nodes_by("name",
                                                                       "(\.|^)%s(\.|$)" % setup_obj_resr))
            if len(old_parents) > 0:
                for old_parent in old_parents:
                    logging.debug("Found parsed dependency %s for %s through object %s",
                                  old_parent.params["shortname"], test_node.params["shortname"], test_object.suffix)
                    if old_parent not in get_parents:
                        get_parents.append(old_parent)
            else:
                logging.debug("Found new dependency %s for %s through object %s",
                              new_parent.params["shortname"], test_node.params["shortname"], test_object.suffix)
                parse_parents.append(new_parent)
        return get_parents, parse_parents

    @staticmethod
    def parse_workers(param_dict: dict[str, str] = None) -> list[TestWorker]:
        """
        Parse all workers with special strings provided by the runtime.

        :param param_dict: extra parameters to be used as overwrite dictionary
        :returns: parsed test workers sorted by name with used ones having runtime strings
        """
        test_workers = []
        for suffix in param.all_objects("nets"):
            for flat_net in TestGraph.parse_flat_objects(suffix, "nets", params=param_dict):
                test_workers += [TestWorker(flat_net)]
        slot_workers = sorted(test_workers, key=lambda x: x.params["name"])

        TestWorker.run_slots = {}

        # TODO: slots is runtime parameter to deprecate for the sake of overwritable configuration
        slots = param_dict.get("slots", "").split(" ")
        for i in range(min(len(slots), len(slot_workers))):
            env_net, env_name, env_type = TestWorker.slot_attributes(slots[i])
            if env_net not in TestWorker.run_slots:
                TestWorker.run_slots[env_net] = {}
            TestWorker.run_slots[env_net][env_name] = env_type
            slot_workers[i].params["runtime_str"] = slots[i]

        return slot_workers

    @staticmethod
    def parse_object_trees(param_dict=None, nodes_str="", object_strs=None,
                           prefix="", verbose=False, with_shared_root=True):
        """
        Parse all user defined tests (leaves) and their dependencies (internal nodes)
        connecting them according to the required/provided setup states of each test
        object (vm) and the required/provided objects per test node (test).

        :param bool with_shared_root: whether to connect all object trees via shared root node
        :returns: parsed graph of test nodes and test objects
        :rtype: :py:class:`TestGraph`

        The rest of the parameters are identical to the methods before.

        The parsed structure can also be viewed as a directed graph of all runnable
        tests each with connections to its dependencies (parents) and dependables (children).
        """
        graph = TestGraph()
        graph.new_workers(TestGraph.parse_workers(param_dict))

        # parse leaves and discover necessary setup (internal nodes)
        leaves, stubs = TestGraph.parse_object_nodes(param_dict, nodes_str, object_strs,
                                                     prefix=prefix, verbose=verbose)
        graph.nodes.extend(leaves)
        graph.objects.extend(stubs)
        # NOTE: reversing here turns the leaves into a simple stack
        unresolved = sorted(leaves, key=lambda x: int(re.match("^(\d+)", x.prefix).group(1)), reverse=True)

        if log.getLogger('graph').level <= log.DEBUG:
            parse_dir = os.path.join(graph.logdir, "graph_parse")
            if not os.path.exists(parse_dir):
                os.makedirs(parse_dir)
            step = 0

        while len(unresolved) > 0:
            test_node = unresolved.pop()
            for test_object in test_node.objects:
                logging.debug(f"Parsing dependencies of {test_node.params['shortname']} "
                              f"for object {test_object.long_suffix}")
                object_params = test_object.object_typed_params(test_node.params)
                object_dependency = object_params.get("get")
                # handle nodes without dependency for the given object
                if not object_dependency:
                    continue
                # handle partially loaded nodes with already satisfied dependency
                if len(test_node.setup_nodes) > 0 and test_node.has_dependency(object_dependency, test_object):
                    logging.debug("Dependency already parsed through duplication or partial dependency resolution")
                    continue

                # get and parse parents
                get_parents, parse_parents = graph.parse_and_get_nodes_for_node_and_object(test_node, test_object, param_dict)
                graph.nodes.extend(parse_parents)
                unresolved.extend(parse_parents)
                parents = get_parents + parse_parents

                # connect and replicate children
                if len(parents) > 0:
                    assert parents[0] not in test_node.setup_nodes, f"{parents[0]} not in {test_node.setup_nodes}"
                    assert test_node not in parents[0].cleanup_nodes, f"{test_node} not in {parents[0].cleanup_nodes}"
                    test_node.setup_nodes.append(parents[0])
                    parents[0].cleanup_nodes.append(test_node)
                if len(parents) > 1:
                    clones = TestGraph.clone_branch(test_node, test_object, parents)
                    graph.nodes.extend(clones)
                    unresolved.extend(clones)

                if log.getLogger('graph').level <= log.DEBUG:
                    step += 1
                    graph.visualize(parse_dir, str(step))
            test_node.validate()

        if with_shared_root:
            graph.parse_shared_root_from_object_trees(param_dict)
        return graph

    def parse_shared_root_from_object_trees(self, param_dict=None):
        """
        Parse the shared root node from used test objects (roots) into a connected graph.

        :param bool verbose: whether to connect all object trees via shared root node
        :returns: parsed graph of test nodes and test objects
        :rtype: :py:class:`TestGraph`

        The rest of the parameters are identical to the methods before.
        """
        object_roots = []
        for test_node in self.nodes:
            if len(test_node.setup_nodes) == 0:
                if not test_node.is_object_root():
                    logging.warning(f"{test_node} is not an object root but will be treated as such")
                object_roots.append(test_node)
        setup_dict = {} if param_dict is None else param_dict.copy()
        setup_dict.update({"shared_root" : "yes",
                           "vms": " ".join(sorted(list(set(o.suffix for o in self.objects if o.key == "vms"))))})
        setup_str = param.re_str("all..internal..noop")
        root_for_all = TestGraph.parse_node_from_object(NetObject("net0", param.Reparsable()),
                                                        setup_dict, setup_str, prefix="0s")
        logging.debug(f"Parsed shared root {root_for_all.params['shortname']}")
        self.nodes.append(root_for_all)
        for root_for_object in object_roots:
            root_for_object.setup_nodes = [root_for_all]
            root_for_all.cleanup_nodes.append(root_for_object)
        root_for_all.should_run = lambda x: False

        return root_for_all
