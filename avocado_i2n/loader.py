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
Specialized test loader for the plugin.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import os
import re
import logging as log
logging = log.getLogger('avocado.job.' + __name__)
import itertools

from avocado.core.plugin_interfaces import Resolver
from avocado.core.resolver import ReferenceResolution, ReferenceResolutionResult

from . import params_parser as param
from .cartgraph import TestGraph, TestNode, NetObject, VMObject, ImageObject


class CartesianLoader(Resolver):
    """Test loader for Cartesian graph parsing."""

    name = 'cartesian_graph'
    description = 'Loads tests by Cartesian graph parsing'

    def __init__(self, config=None, extra_params=None):
        """
        Construct the Cartesian loader.

        :param config: command line arguments
        :type config: {str, str}
        :param extra_params: extra configuration parameters
        :type extra_params: {str, str}
        """
        extra_params = {} if not extra_params else extra_params
        self.logdir = extra_params.pop('logdir', ".")
        super().__init__()

    """parsing functionality"""
    def parse_object_variants(self, param_dict=None, object_strs=None, verbose=False):
        """
        Parse composite test objects with variants from joined component variants.

        :param param_dict: runtime parameters used for extra customization
        :type param_dict: {str, str} or None
        :param object_strs: object-specific names and variant restrictions
        :type object_strs: {str, str}
        :param bool verbose: whether to print extra messages or not
        :returns: parsed test objects
        :rtype: [:py:class:`TestObject`]

        ..todo:: Support is limited to just parsing nets from vms for the time
                 being due to a vm-only supported suffixes for `object_strs`.
        """
        parsed_param_dict = param.ParsedDict(param_dict).parsable_form()
        test_objects = []

        object_suffix = param_dict.get("object_suffix", "net1")
        object_type = param_dict.get("object_type", "nets")
        if object_type == "images":
            raise TypeError("Multi-variant image test objects are not supported.")
        object_class = NetObject if object_type == "nets" else VMObject
        main_vm = param.main_vm() if len(object_strs.keys()) > 1 else list(object_strs.keys())[0]

        # all possible component object combinations for a given composite object
        config = param.Reparsable()
        config.parse_next_batch(base_file="objects.cfg",
                                base_str=param.join_str(object_strs, parsed_param_dict),
                                # make sure we have the final word on parameters we use to identify objects
                                base_dict={"main_vm": main_vm},
                                ovrwrt_file=param.vms_ovrwrt_file())
        for d in config.get_parser().get_dicts():
            variant_config = config.get_copy()
            if object_type == "vms":
                variant_config.parse_next_str("only " + d["name"])
            else:
                # TODO: joined variants do not support follow-up restrictions to generalize this to nets,
                # this includes stacked vm-specific restrictions or any other join-generic such
                #for vm_name in object_strs.keys():
                #    variant_config.parse_next_str(vm_name + ": only " + object_strs[vm_name])
                logging.warning("Parsing nets can only be redone from single vm variants")

            test_object = object_class(object_suffix, variant_config)
            # TODO: the Cartesian parser does not support checkpoint dictionaries
            #test_object.config = param.Reparsable()
            #test_object.config.parse_next_dict(d)
            test_object.regenerate_params()

            if verbose:
                print(f"{test_object.key.rstrip('s')}    {test_object.suffix}:  {test_object.params['shortname']}")
            test_objects += [test_object]

        return test_objects

    def parse_object_from_objects(self, test_objects, param_dict=None, verbose=False):
        """
        Parse a unique composite object from joined already parsed component objects.

        :param test_objects: fully parsed test objects to parse the composite from
        :type: test_objects: (:py:class:`TestObject`)
        :param param_dict: runtime parameters used for extra customization
        :type param_dict: {str, str} or None
        :param bool verbose: whether to print extra messages or not
        :returns: parsed test objects
        :rtype: [:py:class:`TestObject`]
        :raises: :py:class:`exceptions.AssertionError` if the parsed composite is not unique
        """
        setup_dict = {} if param_dict is None else param_dict.copy()
        setup_dict.update({f"object_id_{o.suffix}": o.id for o in test_objects})
        object_strs = {o.suffix: o.final_restr for o in test_objects}
        composite_objects = self.parse_object_variants(setup_dict, object_strs, verbose=verbose)

        if len(composite_objects) > 1:
            raise AssertionError(f"No unique composite could be parsed using {test_objects}\n"
                                 f"Parsed multiple composite objects: {composite_objects}")
        composite = composite_objects[0]

        for test_object in test_objects:
            composite.components.append(test_object)
            test_object.composites.append(composite)

        return composite

    def parse_objects(self, param_dict=None, object_strs=None, verbose=False, skip_nets=False):
        """
        Parse all available test objects and their configurations or
        a selection of such where the selection is defined by the object
        string keys.

        :param param_dict: runtime parameters used for extra customization
        :type param_dict: {str, str} or None
        :param object_strs: object-specific names and variant restrictions
        :type object_strs: {str, str}
        :param bool verbose: whether to print extra messages or not
        :param bool skip_nets: whether to skip parsing nets from current vms
        :returns: parsed test objects
        :rtype: [:py:class:`TestObject`]
        """
        if object_strs is None:
            # all possible hardware-software combinations
            selected_vms = param.all_objects("vms")
            object_strs = {vm_name: "" for vm_name in selected_vms}
        else:
            selected_vms = object_strs.keys()

        # TODO: this is only generalized up to the current value of the stateful object chain "nets vms images"
        test_objects = []
        suffix_variants = {}
        for net_name in param.all_objects("nets"):
            net_vms = param.all_objects("vms", [net_name])
            for vm_name in net_vms:
                if vm_name not in selected_vms:
                    continue

                # TODO: the images don't have variant suffix definitions so just
                # take the vm generic variant and join it with itself
                objstr = {vm_name: object_strs[vm_name]}
                setup_dict = {} if param_dict is None else param_dict.copy()
                setup_dict.update({"object_suffix": vm_name, "object_type": "vms"})
                # all possible hardware-software combinations as variants of the same vm slot
                vms = self.parse_object_variants(setup_dict, object_strs=objstr, verbose=verbose)

                suffix_variants[f"{vm_name}_{net_name}"] = vms
                test_objects.extend(vms)

                # currently unique handling for nested image test objects
                for vm in vms:
                    for image_name in vm.params.objects("images"):
                        image_suffix = f"{image_name}_{vm_name}"
                        config = param.Reparsable()
                        config.parse_next_dict(vm.params.object_params(image_name))
                        config.parse_next_dict({"object_suffix": image_suffix, "object_type": "images"})
                        image = ImageObject(image_suffix, config)
                        test_objects.append(image)
                        vm.components.append(image)
                        image.composites.append(vm)

            # all possible vm combinations as variants of the same net slot
            if not skip_nets:
                for combination in itertools.product(*suffix_variants.values()):
                    setup_dict = {} if param_dict is None else param_dict.copy()
                    setup_dict.update({"object_suffix": net_name, "object_type": "nets"})
                    net = self.parse_object_from_objects(combination, param_dict=setup_dict, verbose=verbose)
                    test_objects.append(net)

        return test_objects

    def parse_node_from_object(self, test_object, param_dict=None, param_str="", prefix=""):
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
                    if vm_variant in test_node.params["name"]:
                        break
                else:
                    raise param.EmptyCartesianProduct("Mutually incompatible vm variants")
        return test_node

    def parse_nodes(self, test_graph, param_dict=None, nodes_str="", prefix="", verbose=False):
        """
        Parse all user defined tests (leaf nodes) using the nodes restriction string
        and possibly restricting to a single test object for the singleton tests.

        :param test_graph: test graph of already parsed test objects used to also
                           validate test object uniqueness and main test object
        :type test_graph: :py:class:`TestGraph`
        :param param_dict: runtime parameters used for extra customization
        :type param_dict: {str, str} or None
        :param str nodes_str: block of node-specific variant restrictions
        :param str prefix: extra name identifier for the test to be run
        :param bool verbose: whether to print extra messages or not
        :returns: parsed test nodes
        :rtype: [:py:class:`TestNode`]
        :raises: :py:class:`param.EmptyCartesianProduct` if no result on preselected vm
        """
        test_nodes = []

        # prepare initial parser as starting configuration and get through tests
        early_config = param.Reparsable()
        early_config.parse_next_file("sets.cfg")
        early_config.parse_next_str(nodes_str)
        early_config.parse_next_dict(param_dict)
        for i, d in enumerate(early_config.get_parser().get_dicts()):

            # get configuration of each participating object and choose the one to mix with the node
            try:
                test_nets = self._parse_and_get_nets_from_node_params(test_graph, param_dict, d)
            except ValueError:
                logging.debug(f"Could not get or construct a test net that is (right-)compatible "
                              f"with the test node {d['shortname']} configuration - skipping")
                continue

            # produce a test node variant for each reused test net variant
            logging.debug(f"Parsing {d['name']} customization for {test_nets}")
            for j, net in enumerate(test_nets):
                try:
                    j_prefix = "b" + str(j) if j > 0 else ""
                    node_prefix = prefix + str(i+1) + j_prefix
                    test_node = self.parse_node_from_object(net, param_dict, param.re_str(d['name']),
                                                            prefix=node_prefix)
                    logging.debug(f"Parsed a test node {test_node.params['shortname']} from "
                                  f"two-way compatible test net {net}")
                    # provide dynamic fingerprint to an original object root node
                    if re.search("(\.|^)original(\.|$)", test_node.params["name"]):
                        test_node.params["object_root"] = d.get("object_id", net.id)
                except param.EmptyCartesianProduct:
                    # empty product in cases like parent (dependency) nodes imply wrong configuration
                    if d.get("require_existence", "no") == "yes":
                        raise
                    logging.debug(f"Test net {net} not (left-)compatible with the test node "
                                  f"{d['shortname']} configuration - skipping")
                else:
                    if verbose:
                        print(f"test    {test_node.prefix}:  {test_node.params['shortname']}")
                    test_nodes.append(test_node)

        return test_nodes

    def parse_object_nodes(self, param_dict=None, nodes_str="", object_strs=None,
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
        graph.objects = self.parse_objects(param_dict, object_strs, verbose=False, skip_nets=True)
        # the parsed test nodes are already fully restricted by the available test objects
        graph.nodes = self.parse_nodes(graph, param_dict, nodes_str, prefix=prefix, verbose=True)
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

    def parse_object_trees(self, param_dict=None, nodes_str="", object_strs=None,
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

        # parse leaves and discover necessary setup (internal nodes)
        leaves, stubs = self.parse_object_nodes(param_dict, nodes_str, object_strs,
                                                prefix=prefix, verbose=verbose)
        graph.nodes.extend(leaves)
        graph.objects.extend(stubs)
        # NOTE: reversing here turns the leaves into a simple stack
        unresolved = sorted(leaves, key=lambda x: int(re.match("^(\d+)", x.prefix).group(1)), reverse=True)

        if log.getLogger('graph').level <= log.DEBUG:
            parse_dir = os.path.join(self.logdir, "graph_parse")
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
                get_parents, parse_parents = self._parse_and_get_parents(graph, test_node, test_object, param_dict)
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
                    clones = self._copy_branch(test_node, test_object, parents)
                    graph.nodes.extend(clones)
                    unresolved.extend(clones)

                if log.getLogger('graph').level <= log.DEBUG:
                    step += 1
                    graph.visualize(parse_dir, str(step))
            test_node.validate()

        if with_shared_root:
            self.parse_shared_root_from_object_trees(graph, param_dict)
        return graph

    def parse_shared_root_from_object_trees(self, test_graph, param_dict=None):
        """
        Parse the shared root node from used test objects (roots) into a connected graph.

        :param bool verbose: whether to connect all object trees via shared root node
        :returns: parsed graph of test nodes and test objects
        :rtype: :py:class:`TestGraph`

        The rest of the parameters are identical to the methods before.
        """
        object_roots = []
        for test_node in test_graph.nodes:
            if len(test_node.setup_nodes) == 0:
                if not test_node.is_object_root():
                    logging.warning(f"{test_node} is not an object root but will be treated as such")
                object_roots.append(test_node)
        setup_dict = {} if param_dict is None else param_dict.copy()
        setup_dict.update({"shared_root" : "yes",
                           "vms": " ".join(sorted(list(set(o.suffix for o in test_graph.objects if o.key == "vms"))))})
        setup_str = param.re_str("all..internal..noop")
        root_for_all = self.parse_node_from_object(NetObject("net0", param.Reparsable()),
                                                   setup_dict, setup_str, prefix="0s")
        logging.debug(f"Parsed shared root {root_for_all.params['shortname']}")
        test_graph.nodes.append(root_for_all)
        for root_for_object in object_roots:
            root_for_object.setup_nodes = [root_for_all]
            root_for_all.cleanup_nodes.append(root_for_object)
        root_for_all.should_run = lambda x: False

        return root_for_all

    def resolve(self, reference):
        """
        Discover (possible) tests from test references.

        :param reference: tests reference used to produce tests
        :type reference: str or None
        :returns: test factories as tuples of the test class and its parameters
        :rtype: [(type, {str, str})]
        """
        if reference is not None:
            assert reference.split() == self.config["params"]
        param_dict, nodes_str, object_strs = self.config["param_dict"], self.config["tests_str"], self.config["vm_strs"]
        prefix = self.config["prefix"]

        graph = self.parse_object_trees(param_dict, nodes_str, object_strs,
                                        prefix=prefix, verbose=self.config["subcommand"]!="list")
        runnables = [n.get_runnable() for n in graph.nodes]

        # HACK: pass the constructed graph to the runner using static attribute hack
        # since the currently digested test suite contains factory arguments obtained
        # from an irreversible (information destructive) approach
        TestGraph.REFERENCE = graph

        return ReferenceResolution(reference, ReferenceResolutionResult.SUCCESS, runnables)

    """internals"""
    def _parse_and_get_nets_from_node_params(self, graph, param_dict, d):
        """
        Decide about test objects participating in the test node returning the
        final selection of such and the main object for the test.
        """
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
                vm_restr = "(\.|^)" + vm_object.params["name"] + "(\.|$)"
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
                setup_dict = {} if param_dict is None else param_dict.copy()
                setup_dict.update({"object_suffix": "net1", "object_type": "nets",
                                    "vms": " ".join(vms)})
                net = self.parse_object_from_objects(combination, param_dict=setup_dict, verbose=False)
                parse_nets["net1"] += [net]
                graph.objects += [net]
            else:
                raise ValueError("Multiple nets reusable for the same vm variant combination:\n{reused_nets}")
        get_nets["net1"] = sorted(get_nets["net1"], key=lambda x: x.id)
        parse_nets["net1"] = sorted(parse_nets["net1"], key=lambda x: x.id)

        logging.debug(f"{len(get_nets['net1'])} test nets will be reused for {d['shortname']} "
                      f"with {len(parse_nets['net1'])} newly parsed ones")
        return get_nets["net1"] + parse_nets["net1"]

    def _parse_and_get_parents(self, graph, test_node, test_object, param_dict=None):
        """
        Generate (if necessary) all parent test nodes for a given test
        node and test object (including the object creation root test).
        """
        object_params = test_object.object_typed_params(test_node.params)
        # objects can appear within a test without any prior dependencies
        setup_restr = object_params["get"]
        setup_obj_resr = test_object.id.split("-", maxsplit=1)[1]
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
                object_parents = graph.get_nodes_by("name", "(\.|^)%s(\.|$)" % test_object.params["name"],
                                                    subset=get_parent)
                get_parent = object_parents if len(object_parents) > 0 else get_parent
            if len(get_parent) > 0:
                return get_parent, []
        if len(get_parent) == 1:
            return get_parent, []
        setup_dict = {} if param_dict is None else param_dict.copy()
        setup_dict.update({"object_suffix": test_object.long_suffix,
                           "object_type": test_object.key,
                           "object_id": test_object.id,
                           "require_existence": "yes"})
        setup_str = param.re_str("all.." + setup_restr)
        name = test_node.prefix + "a"
        new_parents = self.parse_nodes(graph, setup_dict, setup_str, prefix=name)
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

    def _copy_branch(self, copy_node, copy_object, copy_parents):
        """
        Copy a test node and all of its descendants to provide each parent
        node with a unique successor.
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
