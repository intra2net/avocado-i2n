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

from avocado_vt.loader import VirtTestLoader

from . import params_parser as param
from .cartgraph import TestGraph, TestNode, TestObject


class CartesianLoader(VirtTestLoader):
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
        self.logdir = extra_params.pop('logdir', ".")
        super().__init__(config, extra_params)
        # VT is still behind taking on the new config structure (once done remove this)
        self.config = vars(self.args)

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
            selected_vms = param.all_vms()
            object_strs = {vm_name: "" for vm_name in selected_vms}
        else:
            selected_vms = object_strs.keys()

        # TODO: multi-object-variant runs are not fully supported yet so empty strings
        # will not result in "all variants" as they are supposed to but in validation error
        # - override with unique defaults for now
        from .cmd_parser import full_vm_params_and_strs
        available_object_strs = {vm_name: "" for vm_name in param.all_vms()}
        available_object_strs.update(object_strs)
        use_vms_default = {vm_name: available_object_strs[vm_name] == "" for vm_name in available_object_strs}
        _, object_strs = full_vm_params_and_strs(param_dict, available_object_strs,
                                                 use_vms_default=use_vms_default)

        test_objects = []
        for vm_name in selected_vms:
            objstr = {vm_name: object_strs[vm_name]}
            # all possible hardware-software combinations for a given vm
            config = param.Reparsable()
            config.parse_next_batch(base_file="objects.cfg",
                                    # TODO: the current suffix operators make it nearly impossible to overwrite
                                    # object parameters with object specific values after the suffix operator is
                                    # applied with the exception of special regex operator within the config
                                    base_str=param.vm_str(objstr, param.ParsedDict(param_dict).parsable_form()),
                                    # make sure we have the final word on parameters we use to identify objects
                                    base_dict={"main_vm": vm_name},
                                    ovrwrt_file=param.vms_ovrwrt_file())

            test_object = TestObject(vm_name, config)
            test_object.regenerate_params()
            if verbose:
                print("vm    %s:  %s" % (test_object.name, test_object.params["shortname"]))
            # the original restriction is an optional but useful attribute
            test_object.object_str = object_strs[vm_name]
            test_objects.append(test_object)

        return test_objects

    def parse_node_from_object(self, test_object, param_dict=None, param_str="", prefix=""):
        """
        Get the original install test node for the given object.

        :param test_object: fully parsed test object to parse the node from
        :type: test_object: :py:class:`TestObject`
        :param param_dict: extra parameters to be used as overwrite dictionary
        :type param_dict: {str, str} or None
        :param str param_str: string block of parameters to be used as overwrite string
        :param str prefix: extra name identifier for the test to be run
        :returns: parsed test node for the object
        :rtype: :py:class:`TestNode`
        """
        config = test_object.config.get_copy()
        config.parse_next_batch(base_file="sets.cfg",
                                ovrwrt_file=param.tests_ovrwrt_file(),
                                ovrwrt_str=param_str,
                                ovrwrt_dict=param_dict)
        test_node = TestNode(prefix, config, [test_object])
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
        main_object = None
        test_nodes = []

        # prepare initial parser as starting configuration and get through tests
        early_config = param.Reparsable()
        early_config.parse_next_file("sets.cfg")
        early_config.parse_next_str(nodes_str)
        early_config.parse_next_dict(param_dict)
        for i, d in enumerate(early_config.get_parser().get_dicts()):
            name = prefix + str(i+1)
            objects, objstrs = [], {}

            # get configuration of each participating object and choose the one to mix with the node
            d["vms"], d["main_vm"] = self._determine_objects_for_node_params(d)
            logging.debug("Fetching test objects %s to parse a test node", d["vms"].replace(" ", ", "))
            for vm_name in d["vms"].split(" "):
                vms = test_graph.get_objects_by(param_key="main_vm", param_val="^"+vm_name+"$")
                assert len(vms) == 1, "Test object %s not existing or unique in: %s" % (vm_name, vms)
                objects.append(vms[0])
                if d["main_vm"] == vms[0].name:
                    main_object = vms[0]
            if main_object is None:
                raise ValueError("Could not detect the main object among '%s' "
                                 "in the test '%s'" % (d["vms"], d["shortname"]))

            # 0scan shared root is parsable through the default procedure here
            if "0root" in d["name"]:
                test_nodes += [self.parse_create_node(obj, param_dict, prefix=prefix) for obj in objects]
                continue
            elif "0preinstall" in d["name"]:
                test_nodes += [self.parse_install_node(obj, param_dict, prefix=prefix) for obj in objects]
                continue

            # final variant multiplication to produce final test node configuration
            logging.debug("Multiplying the vm variants by the test variants using %s", main_object.name)
            # combine object configurations
            for test_object in objects:
                objstrs[test_object.name] = test_object.object_str
            config = param.Reparsable()
            config.parse_next_batch(base_file="objects.cfg",
                                    # TODO: the current suffix operators make it nearly impossible to overwrite
                                    # object parameters with object specific values after the suffix operator is
                                    # applied with the exception of special regex operator within the config
                                    base_str=param.vm_str(objstrs, param.ParsedDict(param_dict).parsable_form()),
                                    base_dict={"main_vm": main_object.name},
                                    ovrwrt_file=param.vms_ovrwrt_file())
            config.parse_next_batch(base_file="sets.cfg",
                                    ovrwrt_file=param.tests_ovrwrt_file(),
                                    ovrwrt_str=param.re_str(d["name"]),
                                    ovrwrt_dict=param_dict)

            test_node = TestNode(name, config, objects)
            # the original restriction is an optional but useful attribute
            test_node.node_str = nodes_str
            try:
                test_node.regenerate_params()
                if verbose:
                    print("test    %s:  %s" % (test_node.name, test_node.params["shortname"]))
                logging.debug("Parsed a test '%s' with main test object %s",
                              d["shortname"], main_object.name)
                test_nodes.append(test_node)
            except param.EmptyCartesianProduct:
                # empty product in cases like parent (dependency) nodes imply wrong configuration
                if d.get("require_existence", "no") == "yes":
                    raise
                logging.debug("Test '%s' not compatible with the %s configuration - skipping",
                              d["shortname"], main_object.name)

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
        selected_objects = [] if object_strs is None else object_strs.keys()
        compatible_objects = {obj: False for obj in selected_objects}

        initial_object_strs = {vm_name: "" for vm_name in param.all_vms()}
        initial_object_strs.update(object_strs)
        graph = TestGraph()
        graph.objects = self.parse_objects(param_dict, initial_object_strs, verbose=False)
        for test_object in graph.objects:
            if test_object.name in selected_objects:
                test_objects.append(test_object)

        for test_node in self.parse_nodes(graph, param_dict, nodes_str,
                                          prefix=prefix, verbose=verbose):
            test_vms = test_node.params.objects("vms")
            for vm_name in test_vms:
                if vm_name not in selected_objects:
                    break
            else:
                test_nodes.append(test_node)
                for vm_name in test_vms:
                    if vm_name in selected_objects:
                        compatible_objects[vm_name] = True

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
                if compatible_objects[test_object.name]:
                    print("vm    %s:  %s" % (test_object.name, test_object.params["shortname"]))
                else:
                    test_objects.remove(test_object)
            print("%s selected vm variant(s)" % len(test_objects))

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
                os.mkdir(parse_dir)
            step = 0

        while len(unresolved) > 0:
            test_node = unresolved.pop()
            for test_object in test_node.objects:
                logging.debug("Parsing dependencies of %s for object %s", test_node.params["shortname"], test_object.name)
                object_params = test_node.params.object_params(test_object.name)
                object_dependency = object_params.get("get", object_params.get("get_state", ""))
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

        # finally build the shared root node from used test objects (roots)
        used_objects, used_roots = [], []
        for test_object in graph.objects:
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

    def discover(self, references, _which_tests=None):
        """
        Discover (possible) tests from test references.

        :param references: tests references used to produce tests
        :type references: str or [str] or None
        :param which_tests: display behavior for incompatible tests
        :type which_tests: :py:class:`loader.DiscoverMode`
        :returns: test factories as tuples of the test class and its parameters
        :rtype: [(type, {str, str})]
        """
        if references is not None:
            assert references.split() == self.config["params"]
        param_dict, nodes_str, object_strs = self.config["param_dict"], self.config["tests_str"], self.config["vm_strs"]
        prefix = self.config["prefix"]

        graph = self.parse_object_trees(param_dict, nodes_str, object_strs,
                                        prefix=prefix, verbose=self.config["subcommand"]!="list")
        test_suite = [n.get_test_factory() for n in graph.nodes]

        # HACK: pass the constructed graph to the runner using static attribute hack
        # since the currently digested test suite contains factory arguments obtained
        # from an irreversible (information destructive) approach
        TestGraph.REFERENCE = graph

        return test_suite

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
                           "skip_image_processing": "yes",
                           "vms": " ".join(objects),
                           "main_vm": objects[0]})
        setup_str = param.re_str("all..internal..0scan")
        nodes = self.parse_nodes(graph, setup_dict, setup_str)
        assert len(nodes) == 1, "There can only be one shared root"
        scan_node = TestNode(prefix + "0s", nodes[0].config, graph.objects)
        scan_node.regenerate_params()
        logging.debug("Reached shared root %s", scan_node.params["shortname"])
        return scan_node

    def parse_create_node(self, test_object, param_dict=None, prefix=""):
        """
        Get the first test node for the given object.

        :param test_object: fully parsed test object to parse the node from
        :type: test_object: :py:class:`TestObject`
        :param param_dict: runtime parameters used for extra customization
        :type param_dict: {str, str} or None
        :param str prefix: extra name identifier for the test to be run
        :returns: parsed object root node
        :rtype: :py:class:`TestNode`

        This assumes that there is only one root test node which is the one
        with the 'root' start state.
        """
        setup_dict = {} if param_dict is None else param_dict.copy()
        setup_dict.update({"set_state": "root",
                           "vm_action": "set", "skip_image_processing": "yes"})
        setup_str = param.re_str("all..internal..0root")
        create_node = self.parse_node_from_object(test_object, setup_dict, setup_str, prefix=prefix+"0r")
        logging.debug("Reached %s root %s", test_object.name, create_node.params["shortname"])
        return create_node

    def parse_install_node(self, test_object, param_dict=None, prefix=""):
        """
        Get the original install test node for the given object.

        :param test_object: fully parsed test object to parse the node from
        :type: test_object: :py:class:`TestObject`
        :param param_dict: runtime parameters used for extra customization
        :type param_dict: {str, str} or None
        :param str prefix: extra name identifier for the test to be run
        :returns: original parsed object install node
        :rtype: :py:class:`TestNode`
        """
        setup_dict = {} if param_dict is None else param_dict.copy()
        setup_dict.update({"get": "0root", "set_state": "install"})
        setup_str = param.re_str("all..internal..0preinstall")
        install_node = self.parse_node_from_object(test_object, setup_dict, setup_str, prefix=prefix+"0p")
        logging.debug("Reached %s install configured by %s", test_object.name, install_node.params["shortname"])
        return install_node

    """internals"""
    def _determine_objects_for_node_params(self, d):
        """
        Decide about test objects participating in the test node returning the
        final selection of such and the main object for the test.
        """
        main_vm = d.get("main_vm", param.main_vm())
        # case of singleton test node
        if d.get("vms") is None:
            return main_vm, main_vm
        # case of leaf test node or even specified object (dependency) as well as node
        fixed_vms = d["vms"].split(" ")
        assert main_vm in fixed_vms, "Main test object %s for test node '%s' not among:"\
                                     " %s" % (d["main_vm"], d["shortname"], d["vms"])
        return d["vms"], main_vm

    def _parse_and_get_parents(self, graph, test_node, test_object, param_dict=None):
        """
        Generate (if necessary) all parent test nodes for a given test
        node and test object (including the object creation root test).
        """
        object_params = test_node.params.object_params(test_object.name)
        # use get directive -> if not use get_state -> if not use root
        setup_restr = object_params.get("get", object_params.get("get_state", "0root"))
        setup_opts = object_params.get_dict("get_opts")
        logging.debug("Parsing Cartesian setup of %s through restriction %s",
                      test_node.params["shortname"], setup_restr)

        if setup_restr == "0root":
            new_parents = [self.parse_create_node(test_object, param_dict)]
        elif setup_restr == "0preinstall":
            new_parents = [self.parse_install_node(test_object, param_dict)]
        elif setup_opts.get("switch") is not None:
            switch = setup_opts.get("switch")
            reverse = "off" if switch == "on" else "on"
            logging.debug("Adding an ephemeral test to switch from %s to %s states for %s",
                          switch, reverse, test_object.name)
            setup_dict = {} if param_dict is None else param_dict.copy()
            setup_dict.update({"get": setup_restr,
                               "get_state": object_params.get("get_state"),
                               "set_state": object_params.get("get_state"),
                               "get_type": reverse, "set_type": switch,
                               "main_vm": test_object.name, "require_existence": "yes"})
            setup_str = param.re_str("all..internal..manage.start")
            name = test_node.name + "b"
            test_node.params["get_type_" + test_object.name] = switch
            old_parents = graph.get_nodes_by("name", "(\.|^)manage.start(\.|$)",
                                             subset=graph.get_nodes_by("vms", "(^|\s)%s($|\s)" % test_object.name,
                                                                       subset=graph.get_nodes_by("get_state",
                                                                                                 object_params.get("get_state"))))
            if len(old_parents) > 0:
                return old_parents, []
            new_parents = self.parse_nodes(graph, setup_dict, setup_str, prefix=name)
            assert len(new_parents) == 1, "There could be only one autogenerated ephemeral variant"
            return [], new_parents
        else:
            # speedup for handling already parsed unique parent cases
            get_parent = graph.get_nodes_by("name", "(\.|^)%s(\.|$)" % setup_restr,
                                             subset=graph.get_nodes_by("vms", "(^|\s)%s($|\s)" % test_object.name))
            if len(get_parent) == 1:
                return get_parent, []
            setup_dict = {} if param_dict is None else param_dict.copy()
            setup_dict.update({"main_vm": test_object.name, "require_existence": "yes"})
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
                                             subset=graph.get_nodes_by("vms", "(^|\s)%s($|\s)" % test_object.name))
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
                    clone = TestNode(clone_name, clone_config, list(clone_source.objects))
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

                parent_object_params = parent.params.object_params(copy_object.name)
                parent_state = parent_object_params.get("set_state", "")
                child.params["shortname"] += "." + parent_state
                child.params["name"] += "." + parent_state
                child.params["get_state_" + copy_object.name] = parent_state
                child_object_params = child.params.object_params(copy_object.name)
                child_state = child_object_params.get("set_state", "")
                if child_state:
                    child.params["set_state_" + copy_object.name] += "." + parent_state

            for grandchild in clone_source.cleanup_nodes:
                to_copy.append((grandchild, [clone_source, *clones]))
            test_nodes.extend(clones)

        return test_nodes
