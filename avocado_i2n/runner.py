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
import time
import logging
import signal
import asyncio
from multiprocessing import SimpleQueue

from avocado.core import nrunner
from avocado.core.messages import MessageHandler
from avocado.core.plugin_interfaces import Runner as RunnerInterface
from avocado.core.status.repo import StatusRepo
from avocado.core.status.server import StatusServer
from avocado.core.task.runtime import RuntimeTask
from avocado.core.task.statemachine import TaskStateMachine, Worker

from . import params_parser as param
from .cartgraph import TestGraph, TestNode


class CartesianRunner(RunnerInterface):
    """Test runner for Cartesian graph traversal."""

    name = 'traverser'
    description = 'Runs tests through a Cartesian graph traversal'

    """running functionality"""
    async def _update_status(self, job):
        message_handler = MessageHandler()
        while True:
            try:
                (task_id, _, _, index) = \
                    self.status_repo.status_journal_summary.pop(0)

            except IndexError:
                await asyncio.sleep(0.05)
                continue

            message = self.status_repo.get_task_data(task_id, index)
            tasks_by_id = {str(runtime_task.task.identifier): runtime_task.task
                           for runtime_task in self.tasks}
            task = tasks_by_id.get(task_id)
            message_handler.process_message(message, task, job)

    async def run_test(self, job, node):
        """
        Run a test instance inside a subprocess.

        :param job: job that includes the test suite
        :type job: :py:class:`avocado.core.job.Job`
        :param node: test node to run
        :type node: :py:class:`TestNode`
        """
        if node.spawner is None:
            node.set_environment(job, self.slots[0])

        raw_task = nrunner.Task(node.get_runnable(), node.id_long,
                                [job.config.get('nrunner.status_server_uri')],
                                nrunner.RUNNERS_REGISTRY_PYTHON_CLASS,
                                job_id=self.job.unique_id)
        task = RuntimeTask(raw_task)
        self.tasks += [task]

        # TODO: use a single state machine for all test nodes when we are able
        # to at least add requested tasks to it safely (using its locks)
        await Worker(state_machine=TaskStateMachine([task], self.status_repo),
                     spawner=node.spawner, max_running=1,
                     task_timeout=job.config.get('task.timeout.running')).run()

    async def run_test_node(self, node, can_retry=False):
        """
        Run a node once, and optionally re-run it depending on the parameters.

        :param node: test node to run
        :type node: :py:class:`TestNode`
        :param bool can_retry: whether this node can be re-run
        :returns: run status of :py:meth:`run_test`
        :rtype: bool
        :raises: :py:class:`AssertionError` if the ran test node contains no objects

        The retry parameters are `retry_attempts` and `retry_stop`. The first is
        the maximum number of retries, and the second indicates when to stop retrying.
        The possible combinations of these values are:

        - `retry_stop = error`: retry until error or a maximum of `retry_attempts` number of times
        - `retry_stop = success`: retry until success or a maximum of `retry_attempts` number of times
        - `retry_stop = none`: retry a maximum of `retry_attempts` number of times

        Only tests with the status of pass, warning, error or failure will be retried.
        Other statuses will be ignored and the test will run only once.

        This method also works as a convenience wrapper around :py:meth:`run_test`,
        providing some default arguments.
        """
        if node.is_objectless():
            raise AssertionError("Cannot run test nodes not using any test objects, here %s" % node)

        retry_stop = node.params.get("retry_stop", "none")
        # ignore the retry parameters for nodes that cannot be re-run (need to run at least once)
        runs_left = 1 + node.params.get_numeric("retry_attempts", 0) if can_retry else 1
        # do not log when the user is not using the retry feature
        if runs_left > 1:
            logging.debug(f"Running test with retry_stop={retry_stop} and retry_attempts={runs_left}")
        assert runs_left >= 1, "retry_attempts cannot be less than zero"
        assert retry_stop in ["none", "error", "success"], "retry_stop must be one of 'none', 'error' or 'success'"

        original_shortname = node.params["shortname"]
        for r in range(runs_left):
            # appending a suffix to retries so we can tell them apart
            if r > 0:
                node.params["shortname"] = f"{original_shortname}.r{r}"

            await self.run_test(self.job, node)

            try:
                test_result = next((x for x in self.job.result.tests if x["name"].name == node.params["name"]))
                test_status = test_result["status"]
            except StopIteration:
                test_status = "ERROR"
            if test_status not in ["PASS", "WARN", "ERROR", "FAIL"]:
                # it doesn't make sense to retry with other status
                logging.info(f"Will not attempt to retry test with status {test_status}")
                break
            if retry_stop == "success" and test_status in ["PASS", "WARN"]:
                logging.info("Stopping after first successful run")
                break
            if retry_stop == "error" and test_status in ["ERROR", "FAIL"]:
                logging.info("Stopping after first failed run")
                break
        node.params["shortname"] = original_shortname
        # no need to log when test was not repeated
        if runs_left > 1:
            logging.info(f"Finished running test {r} times")

        # FIX: as VT's retval is broken (always True), we fix its handling here
        if test_status in ["ERROR", "FAIL"]:
            return False
        else:
            return True

    def _run_available_children(self, node, graph, params):
        loop = asyncio.get_event_loop()
        # TODO: parallelize only leaf nodes with just this setup node as parent for now
        # but later on run together also internal nodes if they don't modify the same vm
        run_children = [n for n in node.cleanup_nodes if len(n.setup_nodes) == 1
                        and len(n.cleanup_nodes) == 0 and n.should_run]
        while len(run_children) > 0:
            current_nodes = run_children[:len(self.slots)]
            logging.debug("Traversal advance running in parallel the tests:\n%s",
                          "\n".join([n.id_long.name for n in current_nodes]))
            if len(current_nodes) == 0:
                raise ValueError("Not enough container run slots")
            for i, n in enumerate(current_nodes):
                logging.debug(f"Running {current_nodes[i].id_long.name} in {self.slots[i]}")
                current_nodes[i].set_environment(self.job, self.slots[i])
                run_children.remove(current_nodes[i])
            to_traverse = [self._traverse_test_node(graph, n, params)
                           for n in current_nodes]
            loop.run_until_complete(asyncio.wait_for(asyncio.gather(*to_traverse),
                                                     self.job.timeout or None))

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
                os.makedirs(traverse_dir)
            step = 0

        loop = asyncio.get_event_loop()

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
            logging.debug("Current traverse path/stack:\n%s",
                          "\n".join([n.params["shortname"] for n in traverse_path]))
            # if previous in path is the child of the next, then the path is reversed
            # looking for setup so if the next is setup ready and already run, remove
            # the previous' reference to it and pop the current next from the path
            if previous in next.cleanup_nodes or previous in next.visited_cleanup_nodes:

                if next.is_setup_ready():
                    loop.run_until_complete(self._traverse_test_node(graph, next, params))
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
                    loop.run_until_complete(self._traverse_test_node(graph, next, params))

                if next.is_cleanup_ready():
                    loop.run_until_complete(self._reverse_test_node(graph, next, params))
                    for setup in next.visited_setup_nodes:
                        setup.visit_node(next)
                    traverse_path.pop()
                    graph.report_progress()
                else:
                    # parallel pocket lookahead
                    if next != root:
                        self._run_available_children(next, graph, params)
                        graph.report_progress()
                    # normal DFS
                    traverse_path.append(next.pick_next_child())
            else:
                raise AssertionError("Discontinuous path in the test dependency graph detected")

            if logging.getLogger('graph').level <= logging.DEBUG:
                step += 1
                graph.visualize(traverse_dir, step)

    def run_suite(self, job, test_suite):
        """
        Run one or more tests and report with test result.

        :param job: job that includes the test suite
        :type test_suite: :py:class:`avocado.core.job.Job`
        :param test_suite: test suite with some tests to run
        :type test_suite: :py:class:`avocado.core.suite.TestSuite`
        :returns: a set with types of test failures
        :rtype: :py:class:`set`
        """
        self.job = job

        self.status_repo = StatusRepo(job.unique_id)
        self.status_server = StatusServer(job.config.get('nrunner.status_server_listen'),
                                          self.status_repo)
        asyncio.ensure_future(self.status_server.serve_forever())

        graph = self._graph_from_suite(test_suite)
        summary = set()
        params = self.job.config["param_dict"]

        self.tasks = []
        self.slots = params.get("slots").split(" ")
        # TODO: this needs more customization
        asyncio.ensure_future(self._update_status(job))

        # TODO: fix other run_traversal calls
        try:
            graph.visualize(self.job.logdir)
            self.run_traversal(graph, params)
        except KeyboardInterrupt:
            summary.add('INTERRUPTED')

        # TODO: the avocado implementation needs a workaround here:
        # Wait until all messages may have been processed by the
        # status_updater. This should be replaced by a mechanism
        # that only waits if there are missing status messages to
        # be processed, and, only for a given amount of time.
        # Tests with non received status will always show as SKIP
        # because of result reconciliation.
        time.sleep(0.05)

        self.job.result.end_tests()
        self.job.funcatexit.run()
        self.status_server.close()
        signal.signal(signal.SIGTSTP, signal.SIG_IGN)
        return summary

    """custom nodes"""
    async def run_scan_node(self, graph):
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
        status = await self.run_test_node(test_node)
        logdir = self.job.result.tests[-1]["logdir"]

        try:
            graph.load_setup_list(logdir)
        except FileNotFoundError as e:
            logging.error("Could not parse scanned available setup, aborting as it "
                          "might be dangerous to overwrite existing undetected such")
            status = False

        if not status:
            graph.flag_children(flag=False)
        for node in graph.nodes:
            self.job.result.cancelled += 1 if not node.should_run else 0

    async def run_terminal_node(self, graph, object_name, params):
        """
        Run the set of tests necessary for creating a given test object.

        :param graph: test graph to run create node from
        :type graph: :py:class:`TestGraph`
        :param str object_name: name of the test object to be created
        :param params: runtime parameters used for extra customization
        :type params: {str, str}
        :raises: :py:class:`NotImplementedError` if using incompatible installation variant

        The current implementation with implicit knowledge on the types of test objects
        internal spawns an original (otherwise unmodified) install test.
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

        logging.info("Configuring creation/installation for %s", test_object.name)
        # parameters and the status from the install configuration determine the install test
        install_params = test_node.params.copy()
        # unset any cleanup and prepare special setup to make this a terminal node for an image
        test_node.params.update({"set_state_images": "", "skip_image_processing": "yes",
                                 # this configuration reuses and possibly creates an image
                                 "get_state_images": "install", "get_mode": "ri", "check_mode": "rf"})
        status = await self.run_test_node(test_node)

        if not status:
            logging.error("Could not configure the installation for %s", test_object.name)
            return status

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

        setup_dict.update({"set_state_images": install_params["set_state_images"]})
        install_config = test_object.config.get_copy()
        install_config.parse_next_batch(base_file="sets.cfg",
                                        ovrwrt_file=param.tests_ovrwrt_file(),
                                        ovrwrt_str=setup_str,
                                        ovrwrt_dict=setup_dict)
        return await self.run_test_node(TestNode("0t", install_config, test_node.objects))

    """internals"""
    async def _traverse_test_node(self, graph, test_node, params):
        """Run a single test according to user defined policy and state availability."""
        if test_node.should_run:

            # the primary setup nodes need special treatment
            if params.get("dry_run", "no") == "yes":
                logging.info("Running a dry %s", test_node.params["shortname"])
            elif test_node.is_scan_node():
                logging.debug("Test run started from the shared root")
                status = await self.run_scan_node(graph)
                if not status:
                    logging.error("Could not perform state scanning of %s", test_node)
            elif test_node.is_terminal_node():
                status = await self.run_terminal_node(graph, test_node.params.get("vms", ""), params)
                if not status:
                    logging.error("Could not perform the installation from %s", test_node)

            else:
                # finally, good old running of an actual test
                status = await self.run_test_node(test_node, can_retry=True)
                if not status:
                    logging.error("Got nonzero status from the test %s", test_node)

            for test_object in test_node.objects:
                object_params = test_object.object_typed_params(test_node.params)
                # if a state was set it is final and the retrieved state was overwritten
                object_state = object_params.get("set_state", object_params.get("get_state"))
                if object_state is not None and object_state != "":
                    test_object.current_state = object_state
            test_node.should_run = False
        else:
            logging.debug("Skipping test %s", test_node.params["shortname"])

    async def _reverse_test_node(self, graph, test_node, params):
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
                    if vm_name not in params.get("vms", param.all_objects("vms")):
                        continue
                    # avoid running any test unless the user really requires cleanup and such is needed
                    if vm_params.get("unset_mode", "ri")[0] == "f" and vm_params.get("set_state"):

                        setup_dict = {} if params is None else params.copy()
                        # NOTE: we are forcing the unset_mode to be the one defined for the test node because
                        # the unset manual step behaves differently now (all this extra complexity starts from
                        # the fact that it has different default value which is noninvasive
                        setup_dict.update({"unset_state": vm_params["set_state"],
                                           "unset_type": vm_params.get("set_type", "any"),
                                           "unset_mode": vm_params.get("unset_mode", "ri")})
                        setup_dict["vm_action"] = "unset"
                        # TODO: find more flexible way to pass identical test node parameters for cleanup
                        setup_dict["images_" + vm_name] = vm_params["images"]
                        for image in vm_params.objects("images"):
                            image_params = vm_params.object_params(image)
                            setup_dict["image_name_" + image] = image_params["image_name"]
                            setup_dict["image_format_" + image] = image_params["image_format"]
                            # if any extra images were created these have to be removed now
                            # TODO: this only supports QCOW2 state backends and no LVM cleanup
                            # -> combine with the TODO for unset root unification in the states setup
                            if (image_params.get_boolean("create_image", False)
                                    or image_params.get("check_mode", "rr")[0] == "f"):
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
                        await self.run_test_node(TestNode("c" + test_node.name, forward_config, [test_object]))

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
        for node1, node2 in zip(test_suite.tests, graph.nodes):
            assert node1.uri == node2.get_runnable().uri

        return graph
