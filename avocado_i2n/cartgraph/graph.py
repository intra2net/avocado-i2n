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
Main test suite data structure containing tests as nodes in a bidirected graph
with edges to their dependencies (parents) and dependables (children) but also
with a separate edge for each stateful object.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import os
import re
import time
import logging as log
logging = log.getLogger('avocado.job.' + __name__)
import collections
import itertools
import asyncio

from .. import params_parser as param
from . import PrefixTreeNode, PrefixTree, TestNode, TestWorker, TestObject, NetObject, VMObject, ImageObject


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

    def _clone_branch(self, copy_node, copy_object, copy_parents):
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
                    # in-place changes of the clone source
                    child = clone_source
                else:
                    clone_name = clone_source.prefix + "d" + str(i)
                    clone_config = clone_source.recipe.get_copy()
                    clone = TestNode(clone_name, clone_config)
                    clone.set_objects_from_net(clone_source.objects[0])
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
                variants = child.params["name"].split(".")
                delimiter = variants[variants.index("vms")-1]
                child.params["shortname"] = child.params["shortname"].replace(delimiter, delimiter + "." + parent_state, 1)
                child.params["name"] = child.params["name"].replace(delimiter, delimiter + "." + parent_state, 1)
                # child has been modified for cloning and needs re-bridging with other such nodes
                bridges = self.get_nodes_by("name", child.bridged_form)
                for bridge in bridges:
                    child.bridge_node(bridge)
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

        self.nodes_index = PrefixTree()

        # TODO: these attributes must interface with jobs and runners
        self.logdir = TestGraph.logdir
        self.runner = None

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
        for test_node in nodes:
            self.nodes.append(test_node)
            self.nodes_index.insert(test_node)

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
            log.getLogger("graphviz").parent = log.getLogger("avocado.job")
        except ImportError:
            logging.warning("Couldn't visualize the Cartesian graph due to missing dependency (Graphviz)")
            return

        def get_display_id(node):
            node_id = node.long_prefix
            node_id += f"[{node.started_worker}]" if node.is_occupied(node.started_worker) else ""
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
            root_tests = self.get_nodes_by_name(node_name)
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

    """parse and get functionality"""
    def get_objects_by(self, param_key: str = "name", param_val: str = "", subset: list[TestObject] = None) -> list[TestObject]:
        """
        Query all test objects by a value in a parameter, returning a list of objects.

        :param param_key: exact key to use for the search
        :param param_val: regex to match the object parameter values
        :param subset: a subset of test objects within the graph to search in
        :returns: a selection of objects satisfying ``key=val`` criterion
        """
        regex = re.compile(param_val)
        subset = self.objects if subset is None else subset
        objects = [o for o in subset if param_key in o.params and regex.search(o.params[param_key])]
        logging.debug(f"Retrieved {len(objects)}/{len(subset)} test objects with {param_key} = {param_val}")
        return objects

    def get_object_by(self, param_key: str = "name", param_val: str = "", subset: list[TestObject] = None) -> TestObject:
        """
        Query all test objects by a value in a parameter, returning a unique object.

        :returns: a unique object satisfying ``key=val`` criterion

        The rest of the arguments are analogical to the plural version.
        """
        objects = self.get_objects_by(param_key, param_val, subset)
        assert len(objects) == 1, f"Test object with {param_key}={param_val} not existing"\
               f" or unique in: {objects}"
        return objects[0]

    def get_nodes_by_name(self, name: str = "") -> list[TestNode]:
        """
        Query all test nodes by their name, returning a list of matching nodes.

        :param name: variant-composition name as part of the complete node name
        :returns: a selection of objects satisfying name inclusion criterion
        """
        nodes = self.nodes_index.get(name)
        logging.debug(f"Retrieved {len(nodes)}/{len(self.nodes)} test nodes with name like {name}")
        return nodes

    def get_nodes_by(self, param_key: str = "name", param_val: str = "", subset: list[TestNode] = None) -> list[TestNode]:
        """
        Query all test nodes by a value in a parameter, returning a list of nodes.

        :param param_key: exact key to use for the search
        :param param_val: regex to match the object parameter values
        :param subset: a subset of test nodes within the graph to search in
        :returns: a selection of nodes satisfying ``key=val`` criterion
        """
        regex = re.compile(param_val)
        subset = self.nodes if subset is None else subset
        nodes = [n for n in subset if param_key in n.params and regex.search(n.params[param_key])]
        logging.debug(f"Retrieved {len(nodes)}/{len(subset)} test nodes with {param_key} = {param_val}")
        return nodes

    def get_node_by(self, param_key: str = "name", param_val: str = "", subset: list[TestNode] = None) -> TestNode:
        """
        Query all test nodes by a value in a parameter, returning a unique node.

        :returns: a unique node satisfying ``key=val`` criterion

        The rest of the arguments are analogical to the plural version.
        """
        nodes = self.get_nodes_by(param_key, param_val, subset)
        assert len(nodes) == 1, f"Test node with {param_key}={param_val} not existing"\
               f" or unique in: {nodes}"
        return nodes[0]

    @staticmethod
    def parse_flat_objects(suffix: str, category: str, restriction: str = "",
                           params: dict[str, str] = None) -> list[TestObject]:
        """
        Parse a flat object for each variant of a suffix satisfying a restriction.

        :param suffix: suffix to expand into variant objects
        :param category: category of the suffix that will determine the type of the objects
        :param restriction: restriction for the generated variants
        :param params: additional parameters to add to or overwrite all objects' parameters
        :returns: a list of parsed flat test objects
        """
        params = params or {}
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
            # TODO: this causes a separate re-parsing for each object
            test_object.regenerate_params()
            # TODO: consider generator as performance option also for flat and composite objects
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
        params = params or {}
        params_str = param.ParsedDict({k: v for k, v in params.items() if not k.startswith("only_")}).parsable_form()
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
        # TODO: even the new order is not good enough for multi-vm test nodes
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
        params = params or {}
        setup_dict = {k: v for k, v in params.items() if not k.startswith("only_")}
        setup_dict.update({f"object_id_{o.suffix}": o.id for o in test_objects})
        # TODO: this should have been "only_*" but the Cartesian config limitation disallowing
        # conditional overwriting means we should not define this parameter in advance in order
        # to fully consider "only_*" object restrictions from nodes parsed from such nets
        setup_dict.update({f"object_only_{o.suffix}": o.component_form for o in test_objects})
        object_strs = {o.suffix: "only " + o.component_form + "\n" for o in test_objects}
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

        :param test_object: flat or fully parsed test object to parse for components of
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

            # TODO: the images don't have variant suffix definitions so just take the vm generic variant and join
            # it with itself, i.e. here all possible hardware-software combinations as variants of the same vm slot
            # TODO: parsing vms from a full net does not guarantee the full net has the component id-s and restrictions
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
    def parse_net_from_object_strs(suffix: str, object_strs: dict[str, str] = None) -> NetObject:
        """
        Parse a default net with object strings as compatibility.

        :param suffix: suffix of the net to parse
        :param object_strs: vm restrictions as component restrictions for the net
        :returns: default net object
        """
        config = param.Reparsable()
        config.parse_next_dict({"nets": suffix})
        config.parse_next_dict({"vms": " ".join(list(object_strs.keys()))})
        config.parse_next_dict({f"only_{s}": object_strs[s].replace("only ", "") for s in object_strs})
        return NetObject(suffix, config)

    @staticmethod
    def parse_flat_nodes(restriction: str = "", params: dict[str, str] = None) -> list[TestNode]:
        """
        Parse a flat node for each variant of satisfying a restriction.

        :param restriction: block of node-specific variant restrictions
        :param params: runtime parameters used for extra customization
        :returns: a list of parsed flat test nodes
        """
        params = params or {}

        config = param.Reparsable()
        config.parse_next_batch(base_file=f"sets.cfg",
                                base_str=param.re_str(restriction),
                                base_dict=params)

        test_nodes = []
        for i, d in enumerate(config.get_parser().get_dicts()):
            variant_config = config.get_copy()
            variant_config.parse_next_str("only " + d["name"])

            test_node = TestNode(str(i), variant_config)
            # TODO: this causes a separate re-parsing for each node
            test_node.regenerate_params()
            # TODO: consider generator as performance option also for flat and composite nodes
            test_nodes += [test_node]

        return test_nodes

    @staticmethod
    def parse_node_from_object(test_object: TestObject, restriction: str = "",
                               prefix: str = "", params: dict[str, str] = None) -> TestNode:
        """
        Get the original install test node for the given object.

        :param test_object: fully parsed test object to parse the node from, typically a test net
        :param restriction: restriction for the generated variants
        :param prefix: extra name identifier for the test to be run
        :param params: runtime parameters used for extra customization
        :returns: parsed test node for the object
        :raises: :py:class:`ValueError` if the node is parsed from a non-net object
        :raises: :py:class:`param.EmptyCartesianProduct` if a vm variant is not compatible
                 with another vm variant within the same test node
        """
        if test_object.key != "nets":
            raise ValueError("Test node could be parsed only from test objects of the "
                             "same composition level, currently only test nets")
        for component in test_object.components:
            if f"only_{component.suffix}" in test_object.params:
                raise RuntimeError("A vm restriction found in a test net that a node is "
                                   "parsed from, not yet supported by the Cartesian config")

        setup_dict = params.copy() if params else {}
        setup_dict.update({"nets": test_object.suffix})
        config = test_object.config.get_copy()
        config.parse_next_batch(base_file="sets.cfg",
                                ovrwrt_file=param.tests_ovrwrt_file(),
                                ovrwrt_str=param.re_str(restriction),
                                ovrwrt_dict=setup_dict)
        test_node = TestNode(prefix, config)
        test_node.set_objects_from_net(test_object)
        test_node.regenerate_params()
        for vm_name in test_node.params.objects("vms"):
            if test_node.params.get(f"only_{vm_name}"):
                for vm_variant in test_node.params[f"only_{vm_name}"].split(","):
                    # TODO: have to check the separate objects!
                    if vm_variant.strip() in test_node.params["name"]:
                        break
                else:
                    raise param.EmptyCartesianProduct(f"{test_node} has incompatible {vm_name} "
                                                      f"restriction {test_node.params[f'only_{vm_name}']}")
        return test_node

    def parse_and_get_objects_for_node_and_object(self, test_node: TestNode, test_object: TestObject,
                                                  params: dict[str, str] = None) -> (list[TestObject], list[TestObject]):
        """
        Generate or reuse all component test objects for a given test node.

        Decide about test objects participating in the test node returning the
        final selection of such and the main object for the test.

        :param test_node: possibly flat test node to parse and get objects for
        :param test_object: possibly flat test object to get network suffixes from (currently mostly a flat net)
        :param params: runtime parameters used for extra customization
        :returns: a tuple of all reused and newly parsed test objects
        """
        if not isinstance(test_object, NetObject):
            raise NotImplementedError("Can only parse objects for node and net for now")
        object_name = test_node.params.get("object_suffix", "")
        object_type = test_node.params.get("object_type", "")
        object_variant = test_node.params.get("object_id", ".*").replace(object_name + "-", "")
        node_name = test_node.params["shortname"]

        all_vms = param.all_objects(key="vms")
        def needed_vms():
            # case of singleton test node
            if test_node.params.get("vms") is None:
                if object_type != "nets":
                    if object_name:
                        # as the object depending on this node might not be a vm
                        # and thus a suffix, we have to obtain the relevant vm (suffix)
                        vms = [object_name.split("_")[-1]]
                    else:
                        vms = [test_node.params.get("main_vm", param.main_vm())]
                else:
                    vms = []
                    for vm_name in all_vms:
                        if re.search("(\.|^)" + vm_name + "(\.|$)", object_variant):
                            vms += [vm_name]
            else:
                # case of leaf test node or even specified object (dependency) as well as node
                vms = test_node.params["vms"].split(" ")
            return vms
        vms = needed_vms()
        dropped_vms = set(all_vms) - set(vms)
        logging.debug(f"Fetching nets composed of {', '.join(vms)} to parse {node_name} nodes")

        get_vms, parse_vms = {}, {}
        for vm_name in vms:
            # get vm objects of all variants with the current suffix
            get_vms[vm_name] = [o for o in self.objects if o.key == "vms" and o.suffix == vm_name]
            if len(get_vms[vm_name]) == 0:
                logging.debug(f"Parsing a new vm {vm_name} for the test {node_name}")
                parse_vms[vm_name] = TestGraph.parse_composite_objects(vm_name, "vms", "", params=params)
                self.objects += parse_vms[vm_name]
                for vm in parse_vms[vm_name]:
                    self.objects += TestGraph.parse_components_for_object(vm, "vms", params=params)
                get_vms[vm_name] = parse_vms[vm_name]
            # mix of regex and own OR operator to restrict down to compatible variants
            filtered_vms = []
            needed_restr = test_node.params.get(f"only_{vm_name}", "")
            supported_restr = test_object.params.get(f"only_{vm_name}", test_object.params.get(f"object_only_{vm_name}", ""))
            logging.debug(f"Needed vms have restriction '{needed_restr}' and the supported vms have restriction '{supported_restr}'")
            for needed_variant, supported_variant in itertools.product(needed_restr.split(","), supported_restr.split(",")):
                needed, supported = needed_variant.strip() or ".*", supported_variant.strip() or ".*"
                filtered_vms += self.get_objects_by(param_val="(\.|^)"+needed+"(\.|$)",
                                                    subset=self.get_objects_by(param_val="(\.|^)"+supported+"(\.|$)",
                                                                               subset=get_vms[vm_name]))
            get_vms[vm_name] = filtered_vms
            # dependency filter for child node object has to be applied too
            if vm_name == object_name or (object_type == "images" and object_name.endswith(f"_{vm_name}")):
                get_vms[vm_name] = self.get_objects_by(param_val="(\.|^)" + object_variant + "(\.|$)", subset=get_vms[vm_name])
            if len(get_vms[vm_name]) == 0:
                raise ValueError(f"Could not fetch any objects for suffix {vm_name} "
                                 f"in the test {node_name}")
            get_vms[vm_name] = sorted(get_vms[vm_name], key=lambda x: x.id)

        previous_nets = [o for o in self.objects if o.key == "nets" and o.suffix == test_object.suffix]
        # dependency filter for child node object has to be applied too
        if object_variant and object_type == "nets":
            previous_nets = self.get_objects_by(param_val="(\.|^)" + object_variant + "(\.|$)", subset=previous_nets)
        get_nets, parse_nets = {test_object.suffix: []}, {test_object.suffix: []}
        # all possible vm combinations as variants of the same net slot
        for combination in itertools.product(*get_vms.values()):
            # filtering for nets based on complete vm object variant names from the product
            reused_nets, filtered_nets = [], list(previous_nets)
            for vm_object in combination:
                vm_restr = "(\.|^)" + vm_object.component_form + "(\.|$)"
                filtered_nets = self.get_objects_by(param_val=vm_restr, subset=filtered_nets)
            # additional filtering for nets based on dropped vm suffixes
            for get_net in filtered_nets:
                for vm_suffix in dropped_vms:
                    if re.search("(\.|^)" + vm_suffix + "(\.|$)", get_net.params["name"]):
                        logging.debug(f"Test net {get_net} not (right-)compatible with the test node "
                                      f"{node_name} configuration and contains a redundant {vm_suffix}")
                        break
                else:
                    reused_nets += [get_net]
            if len(reused_nets) == 1:
                get_nets[test_object.suffix] += [reused_nets[0]]
            elif len(reused_nets) == 0:
                logging.debug(f"Parsing a new net from vms {', '.join(vms)} for {node_name}")
                setup_dict = {} if params is None else params.copy()
                setup_dict.update({key: value for key, value in test_object.params.items() if key.startswith("nets_")})
                net = TestGraph.parse_object_from_objects(test_object.suffix, test_object.key, combination,
                                                          params=setup_dict, verbose=False)
                parse_nets[test_object.suffix] += [net]
                self.objects += [net]
            else:
                raise ValueError("Multiple nets reusable for the same vm variant combination:\n{reused_nets}")
        get_nets[test_object.suffix] = sorted(get_nets[test_object.suffix], key=lambda x: x.id)
        parse_nets[test_object.suffix] = sorted(parse_nets[test_object.suffix], key=lambda x: x.id)

        logging.debug(f"{len(get_nets[test_object.suffix])} test nets will be reused for {node_name} "
                      f"with {len(parse_nets[test_object.suffix])} newly parsed ones")
        return get_nets[test_object.suffix], parse_nets[test_object.suffix]

    def parse_composite_nodes(self, restriction: str = "", test_object: TestObject = None, prefix: str = "",
                              params: dict[str, str] = None, verbose: bool = False) -> list[TestNode]:
        """
        Parse all user defined tests (leaf nodes) using the nodes restriction string
        and possibly restricting to a single test object for the singleton tests.

        :param restriction: block of node-specific variant restrictions
        :param test_object: possibly flat test object to compose the node on top of, typically a test net
        :param prefix: extra name identifier for the test to be run
        :param params: runtime parameters used for extra customization
        :param verbose: whether to print extra messages or not
        :returns: parsed test nodes
        :raises: :py:class:`param.EmptyCartesianProduct` if no result on preselected vm

        All already parsed test objects will be used to also validate test object
        uniqueness and main test object.
        """
        test_nodes = []

        # prepare initial parser as starting configuration and get through tests
        for i, node in enumerate(self.parse_flat_nodes(restriction, params=params)):

            # get configuration of each participating object and choose the one to mix with the node
            try:
                get_nets, parse_nets = self.parse_and_get_objects_for_node_and_object(node, test_object, params=params)
                test_nets = get_nets + parse_nets
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
                    test_node = self.parse_node_from_object(net, node.params['name'],
                                                            prefix=node_prefix, params=params)
                    logging.info(f"Parsed a test node {test_node.params['shortname']} from "
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
    def parse_object_nodes(worker: TestWorker = None, restriction: str = "", prefix: str = "", object_strs: dict[str, str] = None,
                           params: dict[str, str] = None, verbose: bool = False) -> tuple[list[TestNode], list[TestObject]]:
        """
        Parse test nodes based on a selection of parsable objects.

        :param worker: worker to parse the objects and nodes with or none for backward compatibility
        :param restriction: block of node-specific variant restrictions
        :param prefix: extra name identifier for the test to be run
        :param object_strs: vm restrictions as component restrictions for the nets and thus nodes
        :param params: runtime parameters used for extra customization
        :param verbose: whether to print extra messages or not
        :returns: parsed test nodes and test objects
        :raises: :py:class:`param.EmptyCartesianProduct` if no test variants for the given vm variants

        The rest of the parameters are identical to the methods before.

        We will parse all available objects in the configs, then parse all
        selected nodes and finally restrict to the selected objects specified
        via the object strings (if set) on a test by test basis.
        """
        test_nodes, test_objects = [], []
        # starting object restrictions could be specified externally
        object_strs = {} if object_strs is None else object_strs
        if worker:
            worker.params.update({f"only_{s}": object_strs[s].replace("only ", "") for s in object_strs})

        flat_net = worker.net if worker else TestGraph.parse_net_from_object_strs("net1", object_strs)
        objects = TestGraph.parse_components_for_object(flat_net, "nets",
                                                        params=params, verbose=False, unflatten=False)
        # the parsed test nodes are already fully restricted by the available test objects
        nodes = TestGraph().parse_composite_nodes(restriction, flat_net, prefix, params=params, verbose=True)
        logging.info(f"Intersecting {len(nodes)} initially parsed nodes with {len(objects)} initially parsed objects")
        object_ids = [o.id for o in objects]
        for test_node in nodes:
            node_vms = [o for o in test_node.objects if o.key == "vms"]
            for test_object in node_vms:
                if test_object.id not in object_ids:
                    logging.warning(f"Dropping test node as required {test_object} not in {test_node}")
                    break
            else:
                test_nodes.append(test_node)
                # test node is valid according to the object restriction, now add its objects as valid ones
                for test_object in node_vms:
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
            config = param.Reparsable()
            config.parse_next_str(param.join_str(object_strs))
            config.parse_next_str(param.re_str(restriction))
            config.parse_next_dict(params)
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
        :returns: a tuple of all reused and newly parsed test nodes
        """
        object_params = test_object.object_typed_params(test_node.params)
        object_dependency = object_params.get("get")
        # handle nodes without dependency for the given object
        if not object_dependency:
            return [], []
        # TODO: partially loaded nodes are supposed to be already handled
        # handle partially loaded nodes with already satisfied dependency
        if len(test_node.setup_nodes) > 0 and test_node.has_dependency(object_dependency, test_object):
            logging.debug("Dependency already parsed through duplication or partial dependency resolution")
            return [], []

        # objects can appear within a test without any prior dependencies
        setup_restr = object_params["get"]
        setup_obj_restr = test_object.component_form
        setup_net_restr = test_node.objects[0].suffix
        logging.debug(f"Cartesian setup of {test_object.long_suffix} for {test_node.params['shortname']} "
                      f"uses restriction {setup_restr}")

        # speedup for handling already parsed unique parent cases
        filtered_parents = self.get_nodes_by_name(setup_restr)
        filtered_parents = self.get_nodes_by("name", f"(\.|^){setup_obj_restr}(\.|$)",
                                             subset=filtered_parents)
        filtered_parents = self.get_nodes_by("name", f"(\.|^){setup_net_restr}(\.|$)",
                                             subset=filtered_parents)
        # the vm whose dependency we are parsing may not be restrictive enough so reuse optional other
        # objects variants of the current test node - cloning is only supported in the node restriction
        if len(filtered_parents) > 1:
            for test_object in test_node.objects:
                object_parents = self.get_nodes_by("name", f"(\.|^){test_object.component_form}(\.|$)",
                                                   subset=filtered_parents)
                filtered_parents = object_parents if len(object_parents) > 0 else filtered_parents
            if len(filtered_parents) > 0:
                logging.debug(f"Reusing {len(filtered_parents)} parent nodes for {test_node}")
                return filtered_parents, []
        if len(filtered_parents) == 1:
            logging.debug(f"Reusing a unique parent node {filtered_parents[0]} for {test_node}")
            return filtered_parents, []

        # main parsing entry point for the parents
        setup_dict = {} if params is None else params.copy()
        setup_dict.update({"object_suffix": test_object.long_suffix,
                           "object_type": test_object.key,
                           "object_id": test_object.id,
                           "require_existence": "yes"})
        name = test_node.prefix + "a"
        new_parents = self.parse_composite_nodes("all.." + setup_restr, test_node.objects[0], name, params=setup_dict)
        if len(filtered_parents) == 0:
            return [], new_parents

        get_parents, parse_parents = [], []
        for new_parent in new_parents:
            old_parents = self.get_nodes_by_name(new_parent.setless_form)
            old_parents = self.get_nodes_by("name", f"(\.|^){setup_obj_restr}(\.|$)",
                                            subset=old_parents)
            if len(old_parents) > 0:
                for old_parent in old_parents:
                    logging.debug(f"Found parsed dependency {old_parent.params['shortname']} for "
                                  f"{test_node.params['shortname']} through object {test_object.suffix}")
                    if old_parent not in get_parents:
                        get_parents.append(old_parent)
            else:
                logging.debug(f"Found new dependency {new_parent.params['shortname']} for "
                              f"{test_node.params['shortname']} through object {test_object.suffix}")
                parse_parents.append(new_parent)
        return get_parents, parse_parents

    def parse_branches_for_node_and_object(self, test_node: TestNode, test_object: TestObject,
                                           params: dict[str, str] = None) -> tuple[list[TestNode], list[TestNode], list[TestNode]]:
        """
        Parse all objects, parent object dependencies, and child clones for the current node and object.

        :param test_node: possibly flat test node to parse and get nodes for
        :param test_object: possibly flat test object to get network suffixes from (currently mostly a flat net)
        :param params: runtime parameters used for extra customization
        :returns: a tuple of all reused and newly parsed parent test nodes as well as final child test nodes
        """
        if test_node.is_flat():
            old_children = self.get_nodes_by_name(test_node.setless_form)
            old_children = self.get_nodes_by("name", f"(\.|^){test_object.component_form}(\.|$)",
                                             subset=old_children)
            if len(old_children) > 0:
                for old_child in old_children:
                    logging.debug(f"Found parsed expansion {old_child.params['shortname']} for flat node "
                                  f"{test_node.params['shortname']} through object {test_object.suffix}")
                children = []
            else:
                logging.debug(f"Will newly expand flat {test_node.params['shortname']} for {test_object.suffix}")
                children = self.parse_composite_nodes(test_node.params["name"],
                                                      test_object, test_node.prefix, params=params)
        else:
            # TODO: cannot get nodes by (prefix tree index) name due to current limitations in the bridged form
            old_bridges = self.get_nodes_by("name", test_node.bridged_form)
            for bridge in old_bridges:
                test_node.bridge_node(bridge)
            children = [test_node]

        parents = []
        for child in list(children):
            for component in child.objects:
                logging.debug(f"Parsing dependencies of {child.params['shortname']} "
                              f"for object {component.long_suffix}")

                get_parents, parse_parents = self.parse_and_get_nodes_for_node_and_object(child, component, params)
                # the graph node cache has to be updated as early as possible to avoid redundancy
                self.new_nodes(parse_parents)
                parents += parse_parents
                more_parents = get_parents + parse_parents

                # connect and replicate children
                if len(more_parents) > 0:
                    assert more_parents[0] not in child.setup_nodes, f"{more_parents[0]} not in {child.setup_nodes}"
                    assert child not in more_parents[0].cleanup_nodes, f"{child} not in {more_parents[0].cleanup_nodes}"
                    child.setup_nodes.append(more_parents[0])
                    more_parents[0].cleanup_nodes.append(child)
                if len(more_parents) > 1:
                    children += self._clone_branch(child, component, more_parents)

        self.new_nodes(children if test_node.is_flat() else [c for c in children if c != test_node])
        return parents, children

    def parse_paths_to_object_roots(self, test_node: TestNode, test_object: TestObject,
                                    params: dict[str, str] = None) -> list[tuple[list[TestNode], list[TestNode], TestNode]]:
        """
        Parse the setup paths from a flat node to the terminal nodes of all its objects.

        :param test_node: possibly flat test node to parse and get the complete graph paths for
        :param test_object: possibly flat test object to get network suffixes from (currently mostly a flat net)
        :param params: runtime parameters used for extra customization
        :returns: a generator of all resolved pairs of parents and children
        """
        unresolved = [test_node]
        while len(unresolved) > 0:
            test_node = unresolved.pop()
            parents, children = self.parse_branches_for_node_and_object(test_node, test_object, params)
            if not test_node.is_flat():
                children.remove(test_node)
            unresolved.extend(parents)
            unresolved.extend(children)
            yield parents, children, test_node

    def parse_shared_root_from_object_roots(self, params: dict[str, str] = None) -> TestNode:
        """
        Parse the shared root node from used test objects (roots) into a connected graph.

        :param params: runtime parameters used for extra customization
        :returns: parsed shared root node of all object trees
        """
        object_roots = []
        for test_node in self.nodes:
            if len(test_node.setup_nodes) == 0:
                if not test_node.is_object_root():
                    logging.warning(f"{test_node} is not an object root but will be treated as such")
                object_roots.append(test_node)
        setup_dict = {} if params is None else params.copy()
        setup_dict.update({"shared_root" : "yes",
                           "vms": " ".join(sorted(list(set(o.suffix for o in self.objects if o.key == "vms"))))})
        root_for_all = TestGraph.parse_node_from_object(NetObject("net0", param.Reparsable()),
                                                        "all..internal..noop", prefix="0s", params=setup_dict)
        logging.debug(f"Parsed shared root {root_for_all.params['shortname']}")
        self.new_nodes(root_for_all)
        for root_for_object in object_roots:
            root_for_object.setup_nodes = [root_for_all]
            root_for_all.cleanup_nodes.append(root_for_object)
        root_for_all.should_run = lambda x: False

        return root_for_all

    @staticmethod
    def parse_workers(params: dict[str, str] = None) -> list[TestWorker]:
        """
        Parse all workers with special strings provided by the runtime.

        :param params: extra parameters to be used as overwrite dictionary
        :returns: parsed test workers sorted by name with used ones having runtime strings
        """
        params = params or {}

        suffixes = params.get("nets", "").split(" ") if params.get("nets") else param.all_objects("nets")
        # providing slots can overwrite the initial selection of nets
        slots = params.get("slots", "").split(" ")
        if params.get("slots") is not None:
            suffixes = suffixes[:len(slots)]
        else:
            slots = [None for s in suffixes]

        TestWorker.run_slots = {}
        test_workers = []
        for suffix, slot in zip(suffixes, slots):
            # TODO: currently we truly support only one flat net per suffix
            for flat_net in TestGraph.parse_flat_objects(suffix, "nets", params=params):
                test_worker = TestWorker(flat_net)
                test_workers += [test_worker]
            if slot is not None:
                test_worker.overwrite_with_slot(slot)

            _, worker_suffix, swarm_suffix = test_worker.params["name"].split(".")
            if swarm_suffix not in TestWorker.run_slots:
                TestWorker.run_slots[swarm_suffix] = {}
            TestWorker.run_slots[swarm_suffix][worker_suffix] = test_worker

        return test_workers

    @staticmethod
    def parse_object_trees(worker: TestWorker = None, restriction: str = "", prefix: str = "", object_strs: dict[str, str] = None,
                           params: dict[str, str] = None, verbose: bool = False, with_shared_root: bool =True) -> "TestGraph":
        """
        Parse a complete test graph.

        :param worker: worker traversing the graph with or none for backward compatibility
        :param restriction: block of node-specific variant restrictions
        :param prefix: extra name identifier for the test to be run
        :param object_strs: vm restrictions as component restrictions for the nets and thus nodes
        :param params: runtime parameters used for extra customization
        :param verbose: whether to print extra messages or not
        :param with_shared_root: whether to connect all object trees via shared root node
        :returns: parsed graph of test nodes and test objects

        Parse all user defined tests (leaves) and their dependencies (internal nodes)
        connecting them according to the required/provided setup states of each test
        object (vm) and the required/provided objects per test node (test), obtaining
        and independent graph copy for each worker.
        """
        graph = TestGraph()
        if not worker:
            graph.new_workers(TestGraph.parse_workers(params))
            workers = graph.workers.values()
        else:
            workers = [worker]

        for i, worker in enumerate(workers):
            logging.info(f"Parsing a copy of the object trees for {worker.id}")
            # parse leaves and discover necessary setup (internal nodes)
            leaves, stubs = TestGraph.parse_object_nodes(worker, restriction, object_strs=object_strs,
                                                         prefix=prefix, params=params, verbose=verbose)
            graph.new_nodes(leaves)
            # TODO: to make such changes more gradual at least for now reuse vms and image (<net) objects
            if i == 0:
                graph.objects.extend(stubs)
            else:
                graph.objects.extend(s for s in stubs if s.key == "nets")
            leaves = sorted(leaves, key=lambda x: int(re.match("^(\d+)", x.prefix).group(1)))

            if log.getLogger('graph').level <= log.DEBUG:
                parse_dir = os.path.join(graph.logdir, "graph_parse")
                if not os.path.exists(parse_dir):
                    os.makedirs(parse_dir)
                step = 0

            for test_node in leaves:
                for _, _, current in graph.parse_paths_to_object_roots(test_node, worker.net, params):

                    if log.getLogger('graph').level <= log.DEBUG:
                        step += 1
                        graph.visualize(parse_dir, str(step))
                    current.validate()

        if with_shared_root:
            graph.parse_shared_root_from_object_roots(params)
        return graph

    """traverse functionality"""
    async def traverse_terminal_node(self, object_name: str, worker: TestWorker, params: dict[str, str]) -> bool:
        """
        Traverse an extra set of tests necessary for creating a given test object.

        :param object_name: name of the test object to be created
        :param worker: worker traversing the terminal node
        :param params: runtime parameters used for extra customization
        :returns: whether the terminal node was run successfully or not
        :raises: :py:class:`NotImplementedError` if using incompatible installation variant

        The current implementation with implicit knowledge on the types of test objects
        internally spawns an original (otherwise unmodified) install test.
        """
        object_suffix, object_variant = object_name.split("-")[:1][0], "-".join(object_name.split("-")[1:])
        object_image, object_vm = object_suffix.split("_")
        objects = self.get_objects_by(param_val="^"+object_variant+"$",
                                      subset=self.get_objects_by("images", object_suffix.split("_")[0]))
        vms = [o for o in objects if o.key == "vms"]
        assert len(vms) == 1, "Test object %s's vm not existing or unique in: %s" % (object_name, objects)
        test_object = objects[0]

        nodes = self.get_nodes_by("object_root", object_name, subset=self.get_nodes_by_name(worker.id))
        assert len(nodes) == 1, "There should exist one unique root for %s" % object_name
        test_node = nodes[0]

        if test_object.is_permanent() and not test_node.params.get_boolean("create_permanent_vm"):
            raise AssertionError("Reached a permanent object root for %s due to incorrect setup"
                                 % test_object.suffix)

        logging.info("Configuring creation/installation for %s on %s", object_vm, object_image)
        setup_dict = test_node.params.copy()
        setup_dict.update({} if params is None else params.copy())
        setup_dict.update({"type": "shared_configure_install", "check_mode": "rr",  # explicit root handling
                           # overwrite some params inherited from the modified install node
                           f"set_state_images_{object_image}_{object_vm}": "root", "start_vm": "no"})
        install_config = test_object.config.get_copy()
        install_config.parse_next_batch(base_file="sets.cfg",
                                        ovrwrt_file=param.tests_ovrwrt_file(),
                                        ovrwrt_str=param.re_str("all..noop"),
                                        ovrwrt_dict=setup_dict)
        pre_node = TestNode("0t", install_config)
        pre_node.results = list(test_node.results)
        pre_node.set_objects_from_net(test_node.objects[0])
        pre_node.started_worker = worker
        status = await self.runner.run_test_node(pre_node)
        if not status:
            logging.error("Could not configure the installation for %s on %s", object_vm, object_image)
            return status

        logging.info("Installing virtual machine %s", test_object.suffix)
        test_node.params["type"] = test_node.params["configure_install"]
        return await self.runner.run_test_node(test_node)

    async def traverse_node(self, test_node: TestNode, worker: TestWorker, params: dict[str, str]) -> None:
        """
        Traverse a test node according to a given run policy and additional runner conditions.

        :param test_node: node to be traversed
        :param worker: worker traversing the terminal node
        :param params: runtime parameters used for extra customization
        """
        if test_node.is_occupied(worker):
            return
        test_node.started_worker = worker

        # add previous results if traversed for the first time (could be parsed on demand)
        if len(test_node.results) == 0:
            test_name = test_node.params["name"]
            test_node.results += [r for r in self.runner.previous_results if r["name"] == test_name]
        # add shared pool and result based setup locations
        test_node.pull_locations()

        if test_node.should_run(worker):

            # the primary setup nodes need special treatment
            if params.get("dry_run", "no") == "yes":
                logging.info(f"Worker {worker.id} skipping via dry test run {test_node}")
            elif test_node.is_flat():
                logging.debug(f"Worker {worker.id} skipping a flat node {test_node}")
            elif test_node.is_shared_root():
                logging.debug(f"Worker {worker.id} starting from the shared root")
            elif test_node.is_object_root():
                status = await self.traverse_terminal_node(test_node.params["object_root"], worker, params)
                if not status:
                    logging.error(f"Worker {worker.id} could not perform installation from {test_node}")

            else:
                # finally, good old running of an actual test
                logging.info(f"Worker {worker.id} running the test node {test_node}")
                status = await self.runner.run_test_node(test_node)
                if not status:
                    logging.error(f"Worker {worker.id} got nonzero status from the test {test_node}")

            for test_object in test_node.objects:
                object_params = test_object.object_typed_params(test_node.params)
                # if a state was set it is final and the retrieved state was overwritten
                object_state = object_params.get("set_state", object_params.get("get_state"))
                if object_state is not None and object_state != "":
                    test_object.current_state = object_state

        else:
            logging.debug(f"Worker {worker.id} skipping test {test_node}")

        # register workers that have traversed (and not necessarily run which uses results) both leaf
        # and internal nodes (and not necessarily setup from above cases which could use picked children)
        test_node.finished_worker = worker
        test_node.started_worker = None

    async def reverse_node(self, test_node: TestNode, worker: TestWorker, params: dict[str, str]) -> None:
        """
        Reverse or traverse in the opposite direction a test node according to a given clean policy.

        :param test_node: node to be reversed (traversed in the opposite direction)
        :param worker: worker reversing the terminal node
        :param params: runtime parameters used for extra customization

        The reversal consists of cleanup or sync of any states that could be created by this node
        instead of running via the test runner which is done for the traversal.
        """
        if test_node.is_occupied(worker):
            return
        test_node.started_worker = worker
        if test_node.should_clean(worker):

            if params.get("dry_run", "no") == "yes":
                logging.info(f"Worker {worker.id} not cleaning via dry test run {test_node}")
            elif test_node.is_flat():
                logging.debug(f"Worker {worker.id} not cleaning a flat node {test_node}")
            elif test_node.is_shared_root():
                logging.debug(f"Worker {worker.id} ending at the shared root")

            elif test_node.produces_setup():
                test_node.sync_states(params)

        else:
            logging.debug(f"Worker {worker.id} should not clean up {test_node}")
        test_node.started_worker = None

    async def traverse_object_trees(self, worker: TestWorker, params: dict[str, str]) -> None:
        """
        Run all user and system defined tests optimizing the setup reuse and
        minimizing the repetition of demanded tests.

        :param worker: worker traversing the graph
        :param params: runtime parameters used for extra customization
        :raises: :py:class:`AssertionError` if some traversal assertions are violated

        The highest priority is at the setup tests (parents) since the test cannot be
        run without the required setup, then the current test, then a single child of
        its children (DFS), and finally the other children (tests that can benefit from
        the fact that this test/setup was done) followed by the other siblings (tests
        benefiting from its parent/setup.

        Of course all possible children are restricted by the user-defined "only" and
        the number of internal test nodes is minimized for achieving this goal.
        """
        logging.debug(f"Worker {worker.id} starting complete graph traversal with parameters {params}")
        shared_roots = self.get_nodes_by("shared_root", "yes")
        assert len(shared_roots) == 1, "There can be only exactly one starting node (shared root)"
        root = shared_roots[0]

        if log.getLogger('graph').level <= log.DEBUG:
            traverse_dir = os.path.join(self.logdir, "graph_traverse")
            if not os.path.exists(traverse_dir):
                os.makedirs(traverse_dir)

        traverse_path = [root]
        occupied_at, occupied_wait = None, 0.0
        while not root.is_cleanup_ready(worker):
            next = traverse_path[-1]
            if len(traverse_path) > 1:
                previous = traverse_path[-2]
            else:
                # since the loop is discontinued if len(traverse_path) == 0 or root.is_cleanup_ready()
                # a valid current node with at least one child is guaranteed
                traverse_path.append(next.pick_child(worker))
                continue

            if next.is_flat() and not next.is_unrolled(worker):
                for parents, siblings, current in self.parse_paths_to_object_roots(next, worker.net, params):
                    if current == next:
                        if len(siblings) == 0:
                            logging.warning(f"Could not compose flat node {next} due to test object incompatibility")
                            next.is_unrolled = lambda x: True
                        # the parsed leaf composite nodes should be traversed as children of the leaf flat node
                        for child in siblings:
                            child.setup_nodes.append(next)
                            next.cleanup_nodes.append(child)
                    for parent in parents:
                        if parent.is_object_root():
                            parent.setup_nodes.append(root)
                            root.cleanup_nodes.append(parent)

            if next.is_occupied(worker):
                # ending with an occupied node would mean we wait for a permill of its duration
                test_duration = next.params.get_numeric("test_timeout", 3600) * next.params.get_numeric("max_tries", 1)
                occupied_timeout = round(max(test_duration/1000, 0.1), 2)
                if next == occupied_at:
                    if occupied_wait > test_duration:
                        raise RuntimeError(f"Worker {worker.id} spent {occupied_wait:.2f} seconds waiting for "
                                           f"occupied node of maximum test duration {test_duration:.2f}")
                    occupied_wait += occupied_timeout
                else:
                    # reset as we are waiting for a different node now
                    occupied_wait = 0.0
                occupied_at = next
                logging.debug(f"Worker {worker.id} stepping back from already occupied test node {next} for "
                              f"a period of {occupied_timeout} seconds (total time spent: {occupied_wait:.2f})")
                traverse_path.pop()
                await asyncio.sleep(occupied_timeout)
                continue

            logging.debug("Worker %s at test node %s which is %sready with setup and %sready with cleanup",
                          worker.id, next.params["shortname"],
                          "not " if not next.is_setup_ready(worker) else "",
                          "not " if not next.is_cleanup_ready(worker) else "")
            logging.debug("Current traverse path/stack for %s:\n%s", worker.id,
                          "\n".join([n.params["shortname"] for n in traverse_path[-5:]]))
            # if previous in path is the child of the next, then the path is reversed
            # looking for setup so if the next is setup ready and already run, remove
            # the previous' reference to it and pop the current next from the path
            if previous in next.cleanup_nodes:

                if next.is_setup_ready(worker):
                    await self.traverse_node(next, worker, params)
                    if next == root or not next.should_rerun(worker):
                        previous.drop_parent(next, worker)
                    traverse_path.pop()
                else:
                    # inverse DFS
                    traverse_path.append(next.pick_parent(worker))
            elif previous in next.setup_nodes:

                # stop if test is not a setup leaf since parents have higher priority than children
                if not next.is_setup_ready(worker):
                    traverse_path.append(next.pick_parent(worker))
                    continue
                else:
                    await self.traverse_node(next, worker, params)
                    # cleanup nodes that should be retried postpone traversal down
                    if next.should_rerun(worker):
                        traverse_path.pop()
                        continue

                if next.is_cleanup_ready(worker):
                    self.report_progress()

                    # capture premature cleanup ready cases (only cleanup ready due to unparsed nodes)
                    unexplored_nodes = [node for node in self.nodes if node.is_flat() and not node.is_unrolled(worker)]
                    if len(unexplored_nodes) > 0:
                        # postpone cleaning up current node since it might have newly added children
                        traverse_path.append(root)
                        traverse_path.append(root.pick_child(worker))
                        continue

                    for setup in next.setup_nodes:
                        setup.drop_child(next, worker)
                    await self.reverse_node(next, worker, params)
                    traverse_path.pop()
                else:
                    # normal DFS
                    traverse_path.append(next.pick_child(worker))
            elif next == root:
                # discontinuous paths allowed via the shared root (waiting cleanup and else)
                traverse_path.pop()
            else:
                raise AssertionError("Discontinuous path in the test dependency graph detected")

            if log.getLogger('graph').level <= log.DEBUG:
                self.visualize(traverse_dir, f"{time.time():.4f}_{worker.id}")

        assert traverse_path == [root], f"Unfinished traverse path detected {traverse_path}"
        traverse_path.pop()
