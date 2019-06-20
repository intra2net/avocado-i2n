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
from .cartesian_graph import TestGraph, TestNode, TestObject


class CartesianLoader(VirtTestLoader):
    """Test loader for Cartesian graph parsing."""

    name = 'cartesian_graph'

    def __init__(self, args=None, extra_params=None):
        """
        Construct the Cartesian loader.

        :param args: command line arguments
        :type args: :py:class:`argparse.Namespace`
        :param extra_params: extra configuration parameters
        :type extra_params: {str, str}
        """
        self.logdir = extra_params.pop('logdir', None)
        super().__init__(args, extra_params)

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
        :rtype: [:py:class:`TestObject`]
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
                                             base_str=param.vm_str(vm_name, object_strs),
                                             base_dict={"main_vm": vm_name},
                                             ovrwrt_file=param.vms_ovrwrt_file,
                                             show_dictionaries=verbose)
            for i, d in enumerate(vm_parser.get_dicts()):
                assert i < 1, "There must be exactly one configuration for %s - please restrict better" % vm_name

                # TODO: parameter postprocessing - to be simplified later on
                test_object = TestObject(vm_name, vm_parser)
                test_object.object_str = object_strs[vm_name]

            test_objects.append(test_object)
        return test_objects

    def parse_nodes(self, nodes_str, graph, prefix="", object_name="", verbose=False):
        """
        Parse all user defined tests (leaf nodes) using the nodes overwrite string
        and possibly restricting to a single test object for the singleton tests.

        :param str nodes_str: block of node-specific parameters and variant restrictions
        :param graph: test graph of already parsed test objects
        :type graph: :py:class:`TestGraph`
        :param str prefix: extra name identifier for the test to be run
        :param str object_name: name of the test object whose configuration is reused if node if objectless
        :param bool verbose: whether to print extra messages or not
        :returns: parsed test nodes
        :rtype: [:py:class:`TestNode`]
        :raises: :py:class:`exceptions.ValueError` if the base vm is not among the vms for a node
        :raises: :py:class:`param.EmptyCartesianProduct` if no result on preselected vm
        """
        main_object = None
        test_nodes = []

        # prepare initial parser as starting configuration and get through tests
        test_parser = param.prepare_parser(base_file="sets.cfg", ovrwrt_str=nodes_str)
        for i, d in enumerate(test_parser.get_dicts()):
            name = prefix + str(i+1)
            objects, objstrs = [], {}

            # decide about test objects participating in the test node
            if d.get("vms") is None and object_name != "":
                # case of singleton test
                d["vms"] = object_name
                d["main_vm"] = object_name
            elif d.get("vms") is None and object_name == "":
                # case of default singleton test
                d["main_vm"] = d.get("main_vm", param.main_vm())
                d["vms"] = d["main_vm"]
            elif object_name != "":
                # case of specified object (dependency) as well as node
                d["main_vm"] = d.get("main_vm", param.main_vm())
                fixed_vms = d["vms"].split(" ")
                assert object_name in fixed_vms, "Predefined test object %s for test node '%s' not among:"\
                                                 " %s" % (object_name, d["shortname"], d["vms"])
            else:
                # case of leaf node
                d["main_vm"] = d.get("main_vm", param.main_vm())
                fixed_vms = d["vms"].split(" ")
                assert d["main_vm"] in fixed_vms, "Main test object %s for test node '%s' not among:"\
                                                 " %s" % (d["main_vm"], d["shortname"], d["vms"])

            # get configuration of each participating object and choose the one to mix with the node
            logging.debug("Fetching test objects %s to parse a test node", d["vms"].replace(" ", ", "))
            for vm_name in d["vms"].split(" "):
                vms = graph.get_objects_by(param_key="main_vm", param_val="^"+vm_name+"$")
                assert len(vms) == 1, "Test object %s not existing or unique in: %s" % (vm_name, vms)
                objects.append(vms[0])
                if d["main_vm"] == vms[0].name:
                    main_object = vms[0]
            if main_object is None:
                raise ValueError("Could not detect the main object among '%s' "
                                 "in the test '%s'" % (d["vms"], d["shortname"]))

            # final variant multiplication to produce final test node configuration
            logging.debug("Multiplying the vm variants by the test variants using %s", main_object.name)
            setup_str = param.re_str(d["name"], nodes_str)
            try:
                # combine object configurations
                for test_object in objects:
                    objstrs[test_object.name] = test_object.object_str
                vm_parser = param.prepare_parser(base_file="objects.cfg",
                                                 base_str=param.vm_str(d["vms"], objstrs),
                                                 base_dict={"main_vm": main_object.name},
                                                 ovrwrt_file=param.vms_ovrwrt_file,
                                                 ovrwrt_str="",
                                                 ovrwrt_dict={})
                parser = param.update_parser(vm_parser,
                                             ovrwrt_base_file="sets.cfg",
                                             ovrwrt_file=param.tests_ovrwrt_file,
                                             ovrwrt_str=setup_str,
                                             ovrwrt_dict={},
                                             show_dictionaries=verbose)
                test_nodes.append(TestNode(name, parser, objects))
                logging.debug("Parsed a test '%s' with main test object %s",
                              d["shortname"], main_object.name)
            except param.EmptyCartesianProduct:
                # empty product on a preselected test object implies something is wrong with the selection
                if object_name != "":
                    raise
                logging.debug("Test '%s' not compatible with the %s configuration - skipping",
                              d["shortname"], main_object.name)

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
        :returns: parsed test nodes and test objects
        :rtype: ([:py:class:`TestNode`], [:py:class:`TestObject`])
        :raises: :py:class:`param.EmptyCartesianProduct` if no test variants for the given vm variants

        If objectless test nodes are expected to be parsed, we will parse them once
        for each object provided through "object_names" or available in the configs.
        Otherwise, we will parse for all objects available in the configs, then restrict
        to the ones in "object_names" if set on a test by test basis.
        """
        test_nodes, test_objects = [], []
        if objectless:
            test_objects.extend(self.parse_objects(object_strs, object_names=object_names, verbose=verbose))
        else:
            test_objects.extend(self.parse_objects(object_strs, verbose=verbose))
        if verbose:
            logging.info("%s selected vm variant(s)", len(test_objects))

        graph = TestGraph()
        graph.objects = test_objects
        if objectless:
            for test_object in test_objects:
                object_nodes = self.parse_nodes(nodes_str, graph, prefix=prefix,
                                                object_name=test_object.name, verbose=verbose)
                test_nodes.extend(object_nodes)
        else:
            selected_vms = [] if object_names == "" else object_names.split(" ")
            for test_node in self.parse_nodes(nodes_str, graph, prefix=prefix, verbose=verbose):
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
            object_restrictions = param.dict_to_str(graph.test_objects)
            for object_str in object_strs.values():
                object_restrictions += object_str
            raise param.EmptyCartesianProduct(param.print_restriction(base_str=object_restrictions,
                                                                      ovrwrt_str=nodes_str))

        return test_nodes, test_objects

    def parse_object_trees(self, param_str, nodes_str, object_strs=None,
                           prefix="", object_names="",
                           objectless=False, verbose=True):
        """
        Parse all user defined tests (leaves) and their dependencies (internal nodes)
        connecting them according to the required/provided setup states of each test
        object (vm) and the required/provided objects per test.

        :param str param_str: block of command line parameters
        :returns: parsed graph of test nodes and test objects
        :rtype: :py:class:`TestGraph`

        The rest of the parameters are identical to the methods before.

        The parsed structure can also be viewed as a directed graph of all runnable
        tests each with connections to its dependencies (parents) and dependables (children).
        """
        graph = TestGraph()

        # parse leaves and discover necessary setup (internal nodes)
        leaves, stubs = self.parse_object_nodes(nodes_str, object_strs, prefix=prefix, object_names=object_names,
                                                objectless=objectless, verbose=verbose)
        graph.nodes.extend(leaves)
        graph.objects.extend(stubs)
        # NOTE: reversing here turns the leaves into a simple stack
        unresolved = sorted(list(leaves), key=lambda x: int(re.match("^(\d+)", x.id).group(1)), reverse=True)

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
                if object_params.get("get_state", "") == "":
                    continue

                # get and parse parents
                get_parents, parse_parents = self._parse_and_get_parents(graph, test_node, test_object, param_str)
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
                    graph.nodes += self._copy_branch(test_node, parents[0], parents[1:])

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
        root_for_all = self.parse_scan_node(graph, param_str)
        for root_for_object in used_roots:
            root_for_object.setup_nodes.append(root_for_all)
            root_for_all.cleanup_nodes.append(root_for_object)
        if verbose:
            logging.info("%s final vm variant(s)", len(graph.objects))
        graph.nodes.append(root_for_all)

        return graph

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

        graph = self.parse_object_trees(param_str, nodes_str, object_strs, prefix)
        test_suite = [n.get_test_factory() for n in graph.nodes]

        # HACK: pass the constructed graph to the runner using static attribute hack
        # since the currently digested test suite contains factory arguments obtained
        # from an irreversible (information destructive) approach
        TestGraph.REFERENCE = graph

        return test_suite

    """custom nodes"""
    def parse_scan_node(self, graph, param_str):
        """
        Get the first test node for all objects.

        :param graph: test graph to parse root node from
        :type graph: :py:class:`TestGraph`
        :param str param_str: block of command line parameters

        This assumes that there is only one shared root test node.
        """
        objects = sorted(graph.test_objects.keys())
        setup_dict = {"abort_on_error": "yes", "set_state_on_error": "",
                      "vms": " ".join(objects),
                      "main_vm": objects[0]}
        setup_str = param.dict_to_str(setup_dict) + param_str
        nodes = self.parse_nodes(param.re_str("0scan", setup_str, objectless=True), graph)
        for i, d in enumerate(nodes[0].parser.get_dicts()):
            logging.debug("Reached shared root %s", d["shortname"])
            assert i < 1, "There can only be one shared root"
        return TestNode("0s", nodes[0].parser, [])

    def parse_create_node(self, graph, object_name, param_str):
        """
        Get the first test node for the given object.

        :param graph: test graph to parse root node from
        :type graph: :py:class:`TestGraph`
        :param str object_name: name of the test object whose configuration is reused if node if objectless
        :param str param_str: block of command line parameters

        This assumes that there is only one root test node which is the one
        with the 'root' start state.
        """
        objects = graph.get_objects_by(param_key="main_vm", param_val="^"+object_name+"$")
        assert len(objects) == 1, "Test object %s not existing or unique in: %s" % (object_name, objects)
        test_object = objects[0]
        setup_dict = {"set_state": "root", "set_type": "offline"}
        setup_str = param.re_str("0root", param_str, objectless=True)
        parser = param.update_parser(test_object.parser,
                                     ovrwrt_base_file="sets.cfg",
                                     ovrwrt_file=param.tests_ovrwrt_file,
                                     ovrwrt_str=setup_str,
                                     ovrwrt_dict=setup_dict)
        for i, d in enumerate(parser.get_dicts()):
            logging.debug("Reached %s root %s", object_name, d["shortname"])
            assert i < 1, "There can only be one root for %s" % object_name
        return [TestNode("0r", parser, [test_object])]

    """internals - get/parse, duplicates"""
    def _get_and_parse_parent(self, graph, test_node, test_object, param_str, setup_restr):
        """
        Perform a fast and simple check for a single parent node and
        generate it if it wasn't found during the check.

        .. note:: This method is a legacy method which works faster but
            *only* if the given test node has exactly *one* parent (per object).
        """
        get_parents = graph.get_nodes_by("name", "(\.|^)%s(\.|$)" % setup_restr,
                                         subset=graph.get_nodes_by("vms", "(^|\s)%s($|\s)" % test_object.name))
        parents = get_parents
        if len(get_parents) == 0:
            if setup_restr == "0root":
                parse_parents = self.parse_create_node(graph, test_object.name, param_str)
            else:
                setup_str = param.re_str(setup_restr, param_str, objectless=True)
                name = test_node.name + "a"
                parse_parents = self.parse_nodes(setup_str, graph, prefix=name, object_name=test_object.name)
            parents = parse_parents
        else:
            parse_parents = []
        # NOTE: it is possible that exactly one of multiple parents is already parsed and we don't
        # detect the node actually requiring more but again, this is legacy method and has its drawbacks
        assert len(parents) <= 1, ("Test %s has multiple setups:\n%s\nSpecify 'get_parse=advanced' to "
                                   "support this." % (test_node.params["shortname"],
                                                      "\n".join([p.params["shortname"] for p in parents])))
        return get_parents, parse_parents

    def _parse_and_get_parents(self, graph, test_node, test_object, param_str):
        """
        Generate (if necessary) all parent test nodes for a given test
        node and test object (including the object creation root test).
        """
        get_parents, parse_parents = [], []
        object_params = test_node.params.object_params(test_object.name)
        # use get directive -> if not use get_state -> if not use root
        setup_restr = object_params.get("get", object_params.get("get_state", "0root"))
        logging.debug("Parsing Cartesian setup of %s through restriction %s",
                      test_node.params["shortname"], setup_restr)

        # NOTE: in general everything should be parsed in the full functionality way
        # but for performance reasons, we will switch it off when we have the extra
        # knowledge that the current test node uses simple setup
        if object_params.get("get") is None and object_params.get("get_parse", "simple") == "simple":
            return self._get_and_parse_parent(graph, test_node, test_object, param_str, setup_restr)
        elif object_params.get("get_parse", "advanced") != "advanced":
            raise ValueError("The setup parsing mode must be one of: 'simple', 'advanced'")

        if setup_restr == "0root":
            new_parents = self.parse_create_node(graph, test_object.name, param_str)
        else:
            setup_str = param.re_str(setup_restr, param_str, objectless=True)
            name = test_node.name + "a"
            new_parents = self.parse_nodes(setup_str, graph, prefix=name, object_name=test_object.name)
        for new_parent in new_parents:
            # BUG: a good way to get a variant valid test name was to use
            # re.sub("^(.+\.)*(all|none|minimal)\.", "", NAME)
            # but this regex performs extremely slow (much slower than string replacement)
            parent_name = ".".join(new_parent.params["name"].split(".")[1:])
            old_parents = graph.get_nodes_by("name", "(\.|^)%s(\.|$)" % parent_name,
                                             subset=graph.get_nodes_by("vms", "(^|\s)%s($|\s)" % test_object.name))
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
        test_nodes = []
        to_copy = [(root_node, root_parent, parents)]
        while len(to_copy) > 0:
            child, parent, parents = to_copy.pop()

            clones = []
            for i in range(len(parents)):
                logging.debug("Duplicating test node %s for another parent %s",
                              child.params["shortname"], parents[i].params["shortname"])

                clone_variant = child.params["name"]
                clone_name = child.name + "b" + str(i+1)
                clone_str = param.re_str(clone_variant)
                parser = param.update_parser(child.parser,
                                             ovrwrt_str=clone_str)

                clones.append(TestNode(clone_name, parser, list(child.objects)))

                # clone setup with the exception of unique parent copy
                for clone_setup in child.setup_nodes:
                    if clone_setup == parent:
                        clones[-1].setup_nodes.append(parents[i])
                        parents[i].cleanup_nodes.append(clones[-1])
                    else:
                        clones[-1].setup_nodes.append(clone_setup)
                        clone_setup.cleanup_nodes.append(clones[-1])

            for grandchild in child.cleanup_nodes:
                to_copy.append((grandchild, child, clones))

            test_nodes.extend(clones)

        return test_nodes
