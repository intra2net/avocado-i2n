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
Specialized test runner for the plugin.

Copyright: Intra2net AG


INTERFACE
------------------------------------------------------

"""

import os
import logging
import signal
from multiprocessing import SimpleQueue

from avocado.plugins.runner import TestRunner
from virttest import utils_misc

from . import params_parser as param
from .cartgraph import TestGraph, TestNode


class CartesianRunner(TestRunner):
    """Test runner for Cartesian graph traversal."""

    name = 'traverser'
    description = 'Runs tests through a Cartesian graph traversal'

    """running functionality"""
    def run_test_node(self, node):
        """
        A wrapper around the inherited :py:meth:`run_test`.

        :param node: test node to run
        :type node: :py:class:`TestNode`
        :returns: run status of :py:meth:`run_test`
        :rtype: bool
        :raises: :py:class:`AssertionError` if the ran test node contains no objects

        This is a simple wrapper to provide some default arguments
        for simplicity of invocation.
        """
        if node.is_objectless():
            raise AssertionError("Cannot run test nodes not using any test objects, here %s" % node)
        # TODO: in the future we better inherit from the Runner interface in
        # avocado.core.plugin_interfaces and implement our own test node running
        # like most of the other runners do
        return self.run_test(self.job, self.result, node.get_test_factory(self.job), SimpleQueue(), set())

    def run_traversal(self, graph, params):
        """
        Run all user and system defined tests optimizing the setup reuse and
        minimizing the repetition of demanded tests.

        :param graph: test graph to traverse
        :type graph: :py:class:`TestGraph`
        :param params: runtime parameters used for extra customization
        :type params: {str, str}
        :raises: :py:class:`AssertionError` if some traversal assertions are violated

        The highest priority is at the setup tests (parents) since the test cannot be
        run without the required setup, then the current test, then a single child of
        its children (DFS), and finally the other children (tests that can benefit from
        the fact that this test/setup was done) followed by the other siblings (tests
        benefiting from its parent/setup.

        Of course all possible children are restricted by the user-defined "only" and
        the number of internal test nodes is minimized for achieving this goal.
        """
        shared_roots = graph.get_nodes_by("name", "(\.|^)0scan(\.|^)")
        assert len(shared_roots) == 1, "There can be only exactly one starting node (shared root)"
        root = shared_roots[0]

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
                    self._traverse_test_node(graph, next, params)
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
                    self._traverse_test_node(graph, next, params)

                if next.is_cleanup_ready():
                    self._reverse_test_node(graph, next, params)
                    for setup in next.visited_setup_nodes:
                        setup.visit_node(next)
                    traverse_path.pop()
                    graph.report_progress()
                else:
                    # normal DFS
                    traverse_path.append(next.pick_next_child())
            else:
                raise AssertionError("Discontinuous path in the test dependency graph detected")

            if logging.getLogger('graph').level <= logging.DEBUG:
                step += 1
                graph.visualize(traverse_dir, step)

    def run_suite(self, job, result, test_suite, _variants, _timeout=0,
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
        self.job, self.result = job, result

        graph = self._graph_from_suite(test_suite)
        summary = set()
        params = self.job.config["param_dict"]

        try:
            graph.visualize(self.job.logdir)
            self.run_traversal(graph, params)
        except KeyboardInterrupt:
            TEST_LOG.error('Job interrupted by ctrl+c.')
            summary.add('INTERRUPTED')

        self.result.end_tests()
        self.job.funcatexit.run()
        signal.signal(signal.SIGTSTP, signal.SIG_IGN)
        return summary

    """custom nodes"""
    def run_scan_node(self, graph):
        """
        Run the set of tests necessary for starting test traversal.

        :param graph: test graph to run scan node from
        :type graph: :py:class:`TestGraph`
        """
        # HACK: pass the constructed graph to the test using static attribute hack
        # since there is absolutely no sane way to pass through the cloud of imports
        # before executing a VT test (could be improved later on)
        TestGraph.REFERENCE = graph

        nodes = graph.get_nodes_by(param_key="name", param_val="(\.|^)0scan(\.|^)")
        assert len(nodes) == 1, "There can only be one shared root"
        test_node = nodes[0]
        status = self.run_test_node(test_node)

        # TODO: status is broken and is always true
        if status:
            try:
                graph.load_setup_list(self.job.logdir)
            except FileNotFoundError as e:
                logging.error("Could not parse scanned available setup, aborting as it "
                              "might be dangerous to overwrite existing undetected such")
                graph.flag_children(flag=False)

        for node in graph.nodes:
            self.result.cancelled += 1 if not node.should_run else 0

    def run_create_node(self, graph, object_name):
        """
        Run the set of tests necessary for creating a given test object.

        :param graph: test graph to run create node from
        :type graph: :py:class:`TestGraph`
        :param str object_name: name of the test object to be created
        """
        objects = graph.get_objects_by(param_key="main_vm", param_val="^"+object_name+"$")
        assert len(objects) == 1, "Test object %s not existing or unique in: %s" % (object_name, objects)
        test_object = objects[0]
        nodes = graph.get_nodes_by("name", "(\.|^)0root(\.|$)",
                                   subset=graph.get_nodes_by("vms", "(^|\s)%s($|\s)" % test_object.name))
        assert len(nodes) == 1, "There can only be one root for %s" % object_name
        test_node = nodes[0]

        if test_object.is_permanent() and not test_node.params.get_boolean("create_permanent_vm"):
            raise AssertionError("Reached a permanent object root for %s due to incorrect setup"
                                 % test_object.name)
        else:
            self.run_test_node(test_node)

    def run_install_node(self, graph, object_name, params):
        """
        Run the set of tests necessary for installing a given test object.

        :param graph: test graph to run install node from
        :type graph: :py:class:`TestGraph`
        :param str object_name: name of the test object to be installed
        :param params: runtime parameters used for extra customization
        :type params: {str, str}
        :raises: :py:class:`NotImplementedError` if using incompatible installation variant
        """
        objects = graph.get_objects_by(param_key="main_vm", param_val="^"+object_name+"$")
        assert len(objects) == 1, "Test object %s not existing or unique in: %s" % (object_name, objects)
        test_object = objects[0]
        nodes = graph.get_nodes_by("name", "(\.|^)0preinstall(\.|$)",
                                   subset=graph.get_nodes_by("vms", "(^|\s)%s($|\s)" % test_object.name))
        assert len(nodes) == 1, "There can only be one install node for %s" % object_name
        test_node = nodes[0]

        logging.info("Configuring installation for %s", test_object.name)
        # parameters and the status from the install configuration determine the install test
        install_params = test_node.params.copy()
        test_node.params.update({"set_state": "", "skip_image_processing": "yes"})
        status = self.run_test_node(test_node)

        # TODO: status is broken and is always true
        if not status:
            return

        logging.info("Installing virtual machine %s", test_object.name)
        setup_dict = {} if params is None else params.copy()
        if install_params.get("configure_install", "stepmaker") == "unattended_install":
            if test_object.params["os_type"] == "windows":
                setup_str = param.re_str("all..original..unattended_install")
            elif install_params["unattended_file"].endswith(".preseed"):
                setup_str = param.re_str("all..original..unattended_install.cdrom.in_cdrom_ks")
            elif install_params["unattended_file"].endswith(".ks"):
                setup_str = param.re_str("all..original..unattended_install.cdrom.extra_cdrom_ks")
            else:
                raise NotImplementedError("Unattended install tests are not supported for variant %s" % test_object.params["name"])
        else:
            setup_dict.update({"type": install_params.get("configure_install", "stepmaker")})
            setup_str = param.re_str("all..original..install")

        if install_params["set_type"] == "off":
            setup_dict.update({"set_state": install_params["set_state"],
                               "set_type": install_params["set_type"]})
        install_config = test_object.config.get_copy()
        install_config.parse_next_batch(base_file="sets.cfg",
                                        ovrwrt_file=param.tests_ovrwrt_file(),
                                        ovrwrt_str=setup_str,
                                        ovrwrt_dict=setup_dict)
        status = self.run_test_node(TestNode("0q", install_config, test_node.objects))

        # TODO: status is broken and is always true
        if not status:
            return

        if install_params["set_type"] == "on":
            setup_dict = {} if params is None else params.copy()
            setup_dict.update({"set_state": install_params["set_state"],
                               "set_type": install_params["set_type"],
                               "skip_image_processing": "yes"})
            setup_str = param.re_str("all..internal..manage.start")
            postinstall_config = test_object.config.get_copy()
            postinstall_config.parse_next_batch(base_file="sets.cfg",
                                                ovrwrt_file=param.tests_ovrwrt_file(),
                                                ovrwrt_str=setup_str,
                                                ovrwrt_dict=setup_dict)
            self.run_test_node(TestNode("0qq", postinstall_config, test_node.objects))

    """internals"""
    def _traverse_test_node(self, graph, test_node, params):
        """Run a single test according to user defined policy and state availability."""
        # ephemeral setup can get lost and if so must be repeated
        if not test_node.should_run and test_node.is_ephemeral() and not test_node.is_cleanup_ready():
            for test_object in test_node.objects:
                object_name = test_object.name
                object_params = test_node.params.object_params(object_name)
                # if previous state is not known keep behavior assuming that the user knows what they are doing
                required_state = object_params.get("set_state")
                if required_state != test_object.current_state != "unknown":
                    logging.debug("Re-running ephemeral setup %s since %s state was switched to %s but test requires %s",
                                  test_node.params["shortname"], test_object.name, test_object.current_state, required_state)
                    test_node.should_run = True
                    break
        if test_node.should_run:

            # the primary setup nodes need special treatment
            if params.get("dry_run", "no") == "yes":
                logging.info("Running a dry %s", test_node.params["shortname"])
            elif test_node.is_scan_node():
                logging.debug("Test run started from the shared root")
                self.run_scan_node(graph)
            elif test_node.is_create_node():
                self.run_create_node(graph, test_node.params.get("vms", ""))
            elif test_node.is_install_node():
                self.run_install_node(graph, test_node.params.get("vms", ""), params)

            # re-runnable tests need unique variant names
            elif test_node.is_ephemeral():
                original_shortname = test_node.params["shortname"]
                extra_variant = utils_misc.generate_random_string(6)
                test_node.params["shortname"] += "." + extra_variant
                self.run_test_node(test_node)
                test_node.params["shortname"] = original_shortname

            else:
                # finally, good old running of an actual test
                self.run_test_node(test_node)

            for test_object in test_node.objects:
                object_name = test_object.name
                object_params = test_node.params.object_params(object_name)
                # if a state was set it is final and the retrieved state was overwritten
                object_state = object_params.get("set_state", object_params.get("get_state"))
                if object_state is not None and object_state != "":
                    test_object.current_state = object_state
            test_node.should_run = False
        else:
            logging.debug("Skipping test %s", test_node.params["shortname"])

    def _reverse_test_node(self, graph, test_node, params):
        """
        Clean up any states that could be created by this node (will be skipped
        by default but the states can be removed with "unset_mode=f.").
        """
        if test_node.should_clean:

            if params.get("dry_run", "no") == "yes":
                logging.info("Cleaning a dry %s", test_node.params["shortname"])
            elif test_node.is_shared_root():
                logging.debug("Test run ended at the shared root")

            else:
                for vm_name in test_node.params.objects("vms"):
                    vm_params = test_node.params.object_params(vm_name)
                    # avoid running any test for unselected vms
                    if vm_name not in params.get("vms", param.all_vms()):
                        continue
                    # avoid running any test unless the user really requires cleanup and such is needed
                    if vm_params.get("unset_mode", "ri")[0] == "f" and vm_params.get("set_state"):

                        setup_dict = {} if params is None else params.copy()
                        # NOTE: we are forcing the unset_mode to be the one defined for the test node because
                        # the unset manual step behaves differently now (all this extra complexity starts from
                        # the fact that it has different default value which is noninvasive
                        setup_dict.update({"unset_state": vm_params["set_state"],
                                           "unset_type": vm_params.get("set_type", "off"),
                                           "unset_mode": vm_params.get("unset_mode", "ri")})
                        setup_dict["vm_action"] = "unset"
                        # TODO: find more flexible way to pass identical test node parameters for cleanup
                        setup_dict["images_" + vm_name] = vm_params["images"]
                        for image in vm_params.objects("images"):
                            image_params = vm_params.object_params(image)
                            setup_dict["image_name_" + image] = image_params["image_name"]
                            setup_dict["image_format_" + image] = image_params["image_format"]
                            # if any extra images were created these have to be removed now
                            if image_params.get_boolean("create_image", False):
                                setup_dict["remove_image_" + image] = "yes"
                                setup_dict["skip_image_processing"] = "no"
                        setup_str = param.re_str("all..internal..manage.unchanged")

                        objects = graph.get_objects_by(param_key="main_vm", param_val="^"+vm_name+"$")
                        assert len(objects) == 1, "Test object %s not existing or unique in: %s" % (vm_name, objects)
                        test_object = objects[0]
                        forward_config = test_object.config.get_copy()
                        forward_config.parse_next_batch(base_file="sets.cfg",
                                                        ovrwrt_file=param.tests_ovrwrt_file(),
                                                        ovrwrt_str=setup_str,
                                                        ovrwrt_dict=setup_dict)
                        self.run_test_node(TestNode("c" + test_node.name, forward_config, [test_object]))

        else:
            logging.debug("The test %s doesn't leave any states to be cleaned up", test_node.params["shortname"])

    def _graph_from_suite(self, test_suite):
        """
        Restore a Cartesian graph from the digested list of test object factories.
        """
        # HACK: pass the constructed graph to the runner using static attribute hack
        # since the currently digested test suite contains factory arguments obtained
        # from an irreversible (information destructive) approach
        graph = TestGraph.REFERENCE

        # validate the test suite refers to the same test graph
        assert len(test_suite) == len(graph.nodes)
        for node1, node2 in zip(test_suite, graph.nodes):
            assert node1 == node2.get_test_factory()

        return graph
