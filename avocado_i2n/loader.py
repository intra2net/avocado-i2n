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
import logging

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
    def parse_objects(self, param_dict=None, object_strs=None, verbose=False):
        """
        Parse all available test objects and their configurations or
        a selection of such where the selection is defined by the object
        string keys.

        :param param_dict: runtime parameters used for extra customization
        :type param_dict: {str, str} or None
        :param object_strs: object-specific names and variant restrictions
        :type object_strs: {str, str}
        :param bool verbose: whether to print extra messages or not
        :returns: parsed test objects
        :rtype: [:py:class:`TestObject`]
        """
        if object_strs is None:
            # all possible hardware-software combinations
            selected_vms = param.all_objects("vms")
            object_strs = {vm_name: "" for vm_name in selected_vms}
        else:
            selected_vms = object_strs.keys()

        # TODO: multi-object-variant runs are not fully supported yet so empty strings
        # will not result in "all variants" as they are supposed to but in validation error
        # - override with unique defaults for now
        from .cmd_parser import full_vm_params_and_strs
        available_object_strs = {vm_name: "" for vm_name in param.all_objects("vms")}
        available_object_strs.update(object_strs)
        use_vms_default = {vm_name: available_object_strs[vm_name] == "" for vm_name in available_object_strs}
        _, object_strs = full_vm_params_and_strs(param_dict, available_object_strs,
                                                 use_vms_default=use_vms_default)

        # TODO: this is only generalized up to the current value of the stateful object chain
        parsed_param_dict = param.ParsedDict(param_dict).parsable_form()
        test_objects = []
        for net_name in param.all_objects("nets"):
            net_vms = param.all_objects("vms", [net_name])
            objstrs = {vm_name: object_strs[vm_name] for vm_name in net_vms}
            # all possible vm combinations for a given net
            config = param.Reparsable()
            config.parse_next_batch(base_file="objects.cfg",
                                    base_str=param.join_str(objstrs, parsed_param_dict),
                                    ovrwrt_file=param.vms_ovrwrt_file())
            test_object = NetObject(net_name, config)
            test_object.regenerate_params()
            test_objects += [test_object]

            for vm_name in net_vms:
                vm_images = param.all_objects("images", [net_name, vm_name])
                # TODO: the images don't have variant suffix definitions so just
                # take the vm generic variant and join it with itself
                objstr = {vm_name: object_strs[vm_name]}
                # all possible hardware-software combinations for a given vm
                config = param.Reparsable()
                config.parse_next_batch(base_file="objects.cfg",
                                        base_str=param.join_str(objstr, parsed_param_dict),
                                        # make sure we have the final word on parameters we use to identify objects
                                        base_dict={"main_vm": vm_name},
                                        ovrwrt_file=param.vms_ovrwrt_file())
                test_object = VMObject(vm_name, config)
                test_object.regenerate_params()
                if verbose:
                    print("vm    %s:  %s" % (test_object.name, test_object.params["shortname"]))
                # the original restriction is an optional but useful attribute
                test_object.object_str = object_strs[vm_name]
                test_objects.append(test_object)
                test_objects[0].components.append(test_object)
                test_object.composites.append(test_objects[0])

                # an extra run for nested image test objects
                for image_name in vm_images:
                    config = param.Reparsable()
                    config.parse_next_dict(test_object.params.object_params(image_name))
                    test_objects.append(ImageObject(f"{vm_name}/{image_name}", config))
                    test_object.components.append(test_objects[-1])
                    test_objects[-1].composites.append(test_object)

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
        :raises: :py:class:`AssertionError` if the node is parsed from a non-net object
        """
        if test_object.key != "nets":
            raise AssertionError("Test node could be parsed only from test objects of the "
                                 "same composition level, currently only test nets")
        config = test_object.config.get_copy()
        config.parse_next_batch(base_file="sets.cfg",
                                ovrwrt_file=param.tests_ovrwrt_file(),
                                ovrwrt_str=param_str,
                                ovrwrt_dict=param_dict)
        test_node = TestNode(prefix, config, test_object)
        test_node.regenerate_params()
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
        :raises: :py:class:`exceptions.ValueError` if the base vm is not among the vms for a node
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
            test_net, main_object_name = self._fetch_net_from_node_params(test_graph, param_dict, d)

            # 0scan shared root is parsable through the default procedure here
            if "0root" in d["name"]:
                test_nodes += [self.parse_terminal_node(test_net, param_dict, prefix=prefix)]
                continue

            # final variant multiplication to produce final test node configuration
            logging.debug("Parsing a %s customization for %s", d["name"], test_net)

            # each test node assumes one net object that could be reused or should be initialy parsed
            test_node = self.parse_node_from_object(test_net, param_dict, param.re_str(d["name"]),
                                                    prefix=prefix + str(i+1))

            # the original restriction is an optional but useful attribute
            test_node.node_str = nodes_str
            try:
                test_node.regenerate_params()
                if verbose:
                    print("test    %s:  %s" % (test_node.name, test_node.params["shortname"]))
                logging.debug("Parsed a test '%s' with main test object %s",
                              d["shortname"], main_object_name)
                test_nodes.append(test_node)
            except param.EmptyCartesianProduct:
                # empty product in cases like parent (dependency) nodes imply wrong configuration
                if d.get("require_existence", "no") == "yes":
                    raise
                logging.debug("Test '%s' not compatible with the %s configuration - skipping",
                              d["shortname"], main_object_name)

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
        selected_objects = set() if object_strs is None else set(object_strs.keys())
        used_objects = set()

        initial_object_strs = {vm_name: "" for vm_name in param.all_objects("vms")}
        initial_object_strs.update(object_strs)
        graph = TestGraph()
        graph.objects = self.parse_objects(param_dict, initial_object_strs, verbose=False)
        for test_object in graph.objects:
            if test_object.name in selected_objects:
                # no networks are stored at this stage, just selected vms and their images
                test_objects.append(test_object)
                test_objects.extend(test_object.components)

        for test_node in self.parse_nodes(graph, param_dict, nodes_str,
                                          prefix=prefix, verbose=verbose):
            test_vms = test_node.params.objects("vms")
            for vm_name in test_vms:
                if vm_name not in selected_objects:
                    break
            else:
                # reuse additionally parsed net (node-level) objects
                if test_node.objects[0] not in test_objects:
                    test_objects.append(test_node.objects[0])
                test_nodes.append(test_node)
                used_objects.update(test_vms)

        if len(test_nodes) == 0:
            object_restrictions = param.ParsedDict(graph.test_objects).parsable_form()
            object_strs = {} if object_strs is None else object_strs
            for object_str in object_strs.values():
                object_restrictions += object_str
            config = param.Reparsable()
            config.parse_next_str(object_restrictions)
            config.parse_next_str(nodes_str)
            config.parse_next_dict(param_dict)
            raise param.EmptyCartesianProduct(config.print_parsed())
        if verbose:
            print("%s selected test variant(s)" % len(test_nodes))
            graph.objects = test_objects.copy()
            for test_object in graph.objects:
                if test_object.name in used_objects:
                    print("vm    %s:  %s" % (test_object.name, test_object.params["shortname"]))
                elif test_object.key == "vms":
                    test_objects.remove(test_object)
                    for component in test_object.components:
                        test_objects.remove(component)
            print("%s selected vm variant(s)" % len([t for t in test_objects if t.key == "vms"]))

        return test_nodes, test_objects

    def parse_object_trees(self, param_dict=None, nodes_str="", object_strs=None,
                           prefix="", verbose=False):
        """
        Parse all user defined tests (leaves) and their dependencies (internal nodes)
        connecting them according to the required/provided setup states of each test
        object (vm) and the required/provided objects per test node (test).

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
        unresolved = sorted(leaves, key=lambda x: int(re.match("^(\d+)", x.id).group(1)), reverse=True)

        if logging.getLogger('graph').level <= logging.DEBUG:
            parse_dir = os.path.join(self.logdir, "graph_parse")
            if not os.path.exists(parse_dir):
                os.makedirs(parse_dir)
            step = 0

        while len(unresolved) > 0:
            test_node = unresolved.pop()
            for test_object in test_node.objects:
                logging.debug(f"Parsing dependencies of {test_node.params['shortname']} for object {test_object.id}")
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
                    assert parents[0] not in test_node.setup_nodes
                    assert test_node not in parents[0].cleanup_nodes
                    test_node.setup_nodes.append(parents[0])
                    parents[0].cleanup_nodes.append(test_node)
                if len(parents) > 1:
                    clones = self._copy_branch(test_node, test_object, parents)
                    graph.nodes.extend(clones)
                    unresolved.extend(clones)

                if logging.getLogger('graph').level <= logging.DEBUG:
                    step += 1
                    graph.visualize(parse_dir, step)
            test_node.validate()

        # finally build the shared root node from used test objects (roots)
        used_objects, used_roots = [], []
        for test_object in graph.objects:
            # TODO: only root nodes for suffixed objects are supported at the moment
            if test_object.key != "vms":
                continue
            object_nodes = graph.get_nodes_by("vms", "^"+test_object.name+"$")
            object_roots = graph.get_nodes_by("name", "(\.|^)0root(\.|$)", subset=object_nodes)
            if len(object_roots) > 0:
                used_objects.append(test_object)
                used_roots.append(object_roots[0])
        graph.objects[:] = used_objects
        assert len(used_objects) > 0, "The parsed test nodes don't seem to use any vm objects"
        for shared_root in graph.get_nodes_by("name", "(\.|^)0scan(\.|$)"):
            graph.nodes.remove(shared_root)
        root_for_all = self.parse_scan_node(graph, param_dict)
        graph.nodes.append(root_for_all)
        for root_for_object in used_roots:
            root_for_object.setup_nodes = [root_for_all]
            root_for_all.cleanup_nodes.append(root_for_object)

        return graph

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

    """custom nodes"""
    def parse_scan_node(self, graph, param_dict=None, prefix=""):
        """
        Get the first test node for all objects.

        :param graph: test graph to parse root node from
        :type graph: :py:class:`TestGraph`
        :param param_dict: runtime parameters used for extra customization
        :type param_dict: {str, str} or None
        :param str prefix: extra name identifier for the test to be run
        :returns: parsed shared root node
        :rtype: :py:class:`TestNode`

        This assumes that there is only one shared root test node.
        """
        objects = sorted(graph.test_objects.keys())
        setup_dict = {} if param_dict is None else param_dict.copy()
        setup_dict.update({"abort_on_error": "yes", "set_state_on_error": "",
                           # we need network root setup to provide vm root setup (e.g. bridges)
                           "get_state_vms": "", "get_state_images": "",
                           "skip_image_processing": "yes",
                           "vms": " ".join(objects),
                           "main_vm": objects[0]})
        setup_str = param.re_str("all..internal..0scan")
        nodes = self.parse_nodes(graph, setup_dict, setup_str)
        assert len(nodes) == 1, "There can only be one shared root"
        # TODO: scanning all test objects becomes increasingly monolithic and infeasible
        main_net = [o for o in graph.objects if o.key == "nets"][0]
        scan_node = TestNode(prefix + "0s", nodes[0].config, main_net)
        scan_node.regenerate_params()
        logging.debug("Parsed shared root %s", scan_node.params["shortname"])
        return scan_node

    def parse_terminal_node(self, test_object, param_dict=None, prefix=""):
        """
        Get the original install test node for the given object.

        :param test_object: fully parsed test object to parse the node from
        :type: test_object: :py:class:`NetObject`
        :param param_dict: runtime parameters used for extra customization
        :type param_dict: {str, str} or None
        :param str prefix: extra name identifier for the test to be run
        :returns: original parsed object install node as object root node
        :rtype: :py:class:`TestNode`

        This assumes that there is only one root test node which is the one
        with the 'root' start state.
        """
        setup_dict = {} if param_dict is None else param_dict.copy()

        object_suffix = setup_dict.get("object_suffix", test_object.id)
        object_type = setup_dict.get("object_type", test_object.key)
        object_id = setup_dict.get("object_id", test_object.id_long)

        if object_type == "images":
            setup_dict.update({"get_images": "",
                               "set_state_images": "install",
                               "object_root": object_id})
            setup_str = param.re_str("all..internal..0root")
        elif object_type == "vms":
            setup_dict.update({"get_vms": "",
                               "object_root": object_id})
            setup_str = param.re_str("all..internal..start")
        elif object_type == "nets":
            setup_dict.update({"get_nets": "",
                               "set_state_nets": "default",
                               "object_root": object_id})
            setup_str = param.re_str("all..internal..unchanged")

        terminal_node = self.parse_node_from_object(test_object, setup_dict, setup_str, prefix=prefix+"0t")
        logging.debug("Parsed %s terminal node for %s",
                      object_suffix, terminal_node.params["shortname"])
        return terminal_node

    """internals"""
    def _fetch_net_from_node_params(self, graph, param_dict, d):
        """
        Decide about test objects participating in the test node returning the
        final selection of such and the main object for the test.
        """
        object_name = d.get("object_suffix", "")
        object_type = d.get("object_type", "")
        object_variant = d.get("object_id", ".*").replace(object_name + "-", "")

        main_vm = d.get("main_vm", param.main_vm())
        if object_name and object_type != "nets":
            # as the object depending on this node might not be a vm
            # and thus a suffix, we have to obtain the relevant vm (suffix)
            main_vm = object_name.split("/")[0]
        # case of singleton test node
        if d.get("vms") is None:
            vms = [main_vm]
        else:
            # case of leaf test node or even specified object (dependency) as well as node
            vms = d["vms"].split(" ")
            assert main_vm in vms, "Main test object %s for test node '%s' not among:"\
                                   " %s" % (main_vm, d["shortname"], ", ".join(vms))

        logging.debug("Fetching a net composed of %s to parse %s nodes", ", ".join(vms), d["shortname"])
        fetched_nets, fetched_vms = None, {}
        for vm_name in vms:
            vm_variant = object_variant if vm_name == object_name else ".*"
            vm_name_restr = "(\.|^)" + vm_variant + "(\.|$)"
            vm_node_restr = "(\.|^)" + d.get("only_%s" % vm_name, ".*") + "(\.|$)"
            objects = graph.get_objects_by(param_key="main_vm", param_val="^"+vm_name+"$",
                                           subset=graph.get_objects_by(param_val=vm_node_restr,
                                                                       subset=graph.get_objects_by(param_val=vm_name_restr)))
            net_objects = set(o for o in objects if o.key == "nets")
            fetched_nets = net_objects if fetched_nets is None else fetched_nets.intersection(net_objects)
            fetched_vms[vm_name] = [o for o in objects if o.key == "vms"]
            if len(fetched_vms[vm_name]) == 0:
                raise ValueError("Could not fetch any objects for '%s' "
                                 "in the test '%s'" % (vm_name, d["shortname"]))

        if len(fetched_nets) > 1:
            raise ValueError("No unique networks could be fetched using '%s' "
                             "in the test '%s'" % (", ".join(vms), d["shortname"]))
        elif len(fetched_nets) == 0:
            logging.debug("No reusable network could be fetched using '%s' "
                          "in the test '%s', parsing one" % (", ".join(vms), d["shortname"]))
            objstrs = {}
            for vm_name in vms:
                if len(fetched_vms[vm_name]) == 1:
                    objstrs[vm_name] = "only " + fetched_vms[vm_name][0].params["name"]
                else:
                    # TODO: we don't support restriction reuse for more elaborate cases
                    objstrs[vm_name] = ""
            # reuse custom network that isn't parsed yet
            config = param.Reparsable()
            config.parse_next_batch(base_file="objects.cfg",
                                    # TODO: the current suffix operators make it nearly impossible to overwrite
                                    # object parameters with object specific values after the suffix operator is
                                    # applied with the exception of special regex operator within the config
                                    base_str=param.join_str(objstrs, param.ParsedDict(param_dict).parsable_form()),
                                    base_dict={"main_vm": main_vm},
                                    ovrwrt_file=param.vms_ovrwrt_file())
            main_net = NetObject("net1", config.get_copy())
            for vm_name in vms:
                # TODO: we don't support more than one variant atm
                main_net.components.append(fetched_vms[vm_name][0])
            main_net.regenerate_params()
            graph.objects += [main_net]

        main_net = list(fetched_nets)[0] if len(fetched_nets) == 1 else main_net
        return main_net, main_vm

    def _parse_and_get_parents(self, graph, test_node, test_object, param_dict=None):
        """
        Generate (if necessary) all parent test nodes for a given test
        node and test object (including the object creation root test).
        """
        object_params = test_object.object_typed_params(test_node.params)
        # objects can appear within a test without any prior dependencies
        setup_restr = object_params["get"]
        setup_obj_resr = test_object.id_long.split("-")[1]
        logging.debug("Cartesian setup of %s for %s uses restriction %s",
                      test_object.id, test_node.params["shortname"], setup_restr)

        # speedup for handling already parsed unique parent cases
        if setup_restr == "0root":
            get_parent = graph.get_nodes_by("object_root", "^" + test_object.id_long + "$")
        else:
            get_parent = graph.get_nodes_by("name", "(\.|^)%s(\.|$)" % setup_restr,
                                            subset=graph.get_nodes_by("name",
                                                                      "(\.|^)%s(\.|$)" % setup_obj_resr))
        if len(get_parent) == 1:
            return get_parent, []
        setup_dict = {} if param_dict is None else param_dict.copy()
        setup_dict.update({"object_suffix": test_object.id,
                           "object_type": test_object.key,
                           "object_id": test_object.id_long,
                           "require_existence": "yes"})
        setup_str = param.re_str("all.." + setup_restr)
        name = test_node.name + "a"
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
                                  old_parent.params["shortname"], test_node.params["shortname"], test_object.name)
                    if old_parent not in get_parents:
                        get_parents.append(old_parent)
            else:
                logging.debug("Found new dependency %s for %s through object %s",
                              new_parent.params["shortname"], test_node.params["shortname"], test_object.name)
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
                    clone_name = clone_source.name + "d" + str(i)
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

                parent_object_params = copy_object.object_typed_params(parent.params)
                parent_state = parent_object_params.get("set_state", "")
                child.params["shortname"] += "." + parent_state
                child.params["name"] += "." + parent_state
                child.params["get_state_" + copy_object.name] = parent_state
                child_object_params = copy_object.object_typed_params(child.params)
                child_state = child_object_params.get("set_state", "")
                if child_state:
                    child.params["set_state_" + copy_object.name] += "." + parent_state

            for grandchild in clone_source.cleanup_nodes:
                to_copy.append((grandchild, [clone_source, *clones]))
            test_nodes.extend(clones)

        return test_nodes
