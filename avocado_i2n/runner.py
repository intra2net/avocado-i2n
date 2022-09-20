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
import logging as log
logging = log.getLogger('avocado.test.' + __name__)
import signal
import asyncio
log.getLogger('asyncio').parent = log.getLogger('avocado.test')

from avocado.core.nrunner.task import TASK_DEFAULT_CATEGORY, Task
from avocado.core.messages import MessageHandler
from avocado.core.plugin_interfaces import Runner as RunnerInterface
from avocado.core.status.repo import StatusRepo
from avocado.core.status.server import StatusServer
from avocado.core.teststatus import STATUSES_MAPPING
from avocado.core.task.runtime import RuntimeTask
from avocado.core.task.statemachine import TaskStateMachine, Worker

from . import params_parser as param
from .cartgraph import TestGraph, TestNode


class CartesianRunner(RunnerInterface):
    """Test runner for Cartesian graph traversal."""

    name = 'traverser'
    description = 'Runs tests through a Cartesian graph traversal'

    @property
    def all_tests_ok(self):
        """
        Evaluate if all tests run under this runner have an ok status.

        :returns: whether all tests ended with acceptable status
        :rtype: bool
        """
        mapped_status = {STATUSES_MAPPING[t["status"]] for t in self.job.result.tests}
        return all(mapped_status)

    def __init__(self):
        """Construct minimal attributes for the Cartesian runner."""
        self.tasks = []
        self.slots = []

        self.status_repo = None
        self.status_server = None

    """running functionality"""
    async def _update_status(self, job):
        message_handler = MessageHandler()
        while True:
            try:
                (_, task_id, _, index) = \
                    self.status_repo.status_journal_summary_pop()

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
        if not node.is_occupied():
            default_slot = self.slots[0] if len(self.slots) > 0 else ""
            node.set_environment(job, default_slot)
        # once the slot is set (here or earlier), the hostname reflects it
        hostname = node.params["hostname"]
        hostname = "localhost" if not hostname else hostname
        logging.debug(f"Running {node.id} on {hostname}")

        if not self.status_repo:
            self.status_repo = StatusRepo(job.unique_id)
            self.status_server = StatusServer(job.config.get('nrunner.status_server_listen'),
                                              self.status_repo)
            asyncio.ensure_future(self.status_server.serve_forever())
            # TODO: this needs more customization
            asyncio.ensure_future(self._update_status(job))

        raw_task = Task(node.get_runnable(), node.id_test,
                        [job.config.get('nrunner.status_server_uri')],
                        category=TASK_DEFAULT_CATEGORY,
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
        if runs_left < 1:
            raise ValueError("Value of retry_attempts cannot be less than zero")
        if retry_stop not in ["none", "error", "success"]:
            raise ValueError("Value of retry_stop must be 'none', 'error' or 'success'")

        original_prefix = node.prefix
        for r in range(runs_left):
            # appending a suffix to retries so we can tell them apart
            if r > 0:
                node.prefix = original_prefix + f"r{r}"
            uid = node.long_prefix
            name = node.params["name"]

            await self.run_test(self.job, node)

            try:
                test_result = next((x for x in self.job.result.tests if x["name"].name == name and x["name"].uid == uid))
                test_status = test_result["status"]
            except StopIteration:
                test_status = "ERROR"
                logging.info("Test result wasn't found and cannot be extracted")
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
        node.prefix = original_prefix
        logging.info(f"Finished running test with status {test_status}")
        # no need to log when test was not repeated
        if runs_left > 1:
            logging.info(f"Finished running test {r+1} times")

        # FIX: as VT's retval is broken (always True), we fix its handling here
        if test_status in ["ERROR", "FAIL"]:
            return False
        else:
            return True

    async def run_traversal(self, graph, params, slot):
        """
        Run all user and system defined tests optimizing the setup reuse and
        minimizing the repetition of demanded tests.

        :param graph: test graph to traverse
        :type graph: :py:class:`TestGraph`
        :param params: runtime parameters used for extra customization
        :type params: {str, str}
        :param str slot: id name for the worker traversing the graph
        :raises: :py:class:`AssertionError` if some traversal assertions are violated

        The highest priority is at the setup tests (parents) since the test cannot be
        run without the required setup, then the current test, then a single child of
        its children (DFS), and finally the other children (tests that can benefit from
        the fact that this test/setup was done) followed by the other siblings (tests
        benefiting from its parent/setup.

        Of course all possible children are restricted by the user-defined "only" and
        the number of internal test nodes is minimized for achieving this goal.
        """
        shared_roots = graph.get_nodes_by("shared_root", "yes")
        assert len(shared_roots) == 1, "There can be only exactly one starting node (shared root)"
        root = shared_roots[0]

        if log.getLogger('graph').level <= log.DEBUG:
            traverse_dir = os.path.join(self.job.logdir, "graph_traverse")
            if not os.path.exists(traverse_dir):
                os.makedirs(traverse_dir)

        traverse_path = [root]
        occupied_at, occupied_wait = None, 0.0
        while not root.is_cleanup_ready():
            next = traverse_path[-1]
            if len(traverse_path) > 1:
                previous = traverse_path[-2]
            else:
                # since the loop is discontinued if len(traverse_path) == 0 or root.is_cleanup_ready()
                # a valid current node with at least one child is guaranteed
                traverse_path.append(next.pick_next_child())
                continue
            if next.is_occupied():
                # ending with an occupied node would mean we wait for a permill of its duration
                test_duration = next.params.get_numeric("test_timeout", 3600)
                occupied_timeout = round(max(test_duration/1000, 0.1), 2)
                if next == occupied_at:
                    if occupied_wait > test_duration:
                        raise RuntimeError(f"Worker {slot} spent {occupied_wait:.2f} seconds waiting for "
                                           f"occupied node of maximum test duration {test_duration:.2f}")
                    occupied_wait += occupied_timeout
                else:
                    # reset as we are waiting for a different node now
                    occupied_wait = 0.0
                occupied_at = next
                logging.debug(f"Worker {slot} stepping back from already occupied test node {next} for "
                              f"a period of {occupied_timeout} seconds (total time spent: {occupied_wait:.2f})")
                traverse_path.pop()
                await asyncio.sleep(occupied_timeout)
                continue

            logging.debug("Worker %s at test node %s which is %sready with setup, %sready with cleanup,"
                          " should %srun, should %sbe cleaned, and %sbe scanned",
                          slot, next.params["shortname"],
                          "not " if not next.is_setup_ready() else "",
                          "not " if not next.is_cleanup_ready() else "",
                          "not " if not next.should_run else "",
                          "not " if not next.should_clean else "",
                          "not " if not next.should_scan else "")
            logging.debug("Current traverse path/stack for %s:\n%s", slot,
                          "\n".join([n.params["shortname"] for n in traverse_path]))
            # if previous in path is the child of the next, then the path is reversed
            # looking for setup so if the next is setup ready and already run, remove
            # the previous' reference to it and pop the current next from the path
            if previous in next.cleanup_nodes or previous in next.visited_cleanup_nodes:

                if next.is_setup_ready():
                    previous.visit_node(next)
                    await self._traverse_test_node(graph, next, params, slot)
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
                    await self._traverse_test_node(graph, next, params, slot)

                if next.is_cleanup_ready():
                    for setup in next.visited_setup_nodes:
                        # test node could be reversed by a previous worker
                        if next not in setup.visited_cleanup_nodes:
                            setup.visit_node(next)
                    await self._reverse_test_node(graph, next, params, slot)
                    traverse_path.pop()
                    graph.report_progress()
                else:
                    # normal DFS
                    traverse_path.append(next.pick_next_child())
            else:
                raise AssertionError("Discontinuous path in the test dependency graph detected")

            if log.getLogger('graph').level <= log.DEBUG:
                graph.visualize(traverse_dir, f"{time.time():.4f}_{slot}")

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
        # TODO: this needs more customization
        asyncio.ensure_future(self._update_status(job))

        loop = asyncio.get_event_loop()

        graph = self._graph_from_suite(test_suite)
        summary = set()
        params = self.job.config["param_dict"]

        self.tasks = []
        self.slots = params.get("slots", "").split(" ")

        try:
            graph.visualize(self.job.logdir)

            to_traverse = [self.run_traversal(graph, params, s) for s in self.slots]
            loop.run_until_complete(asyncio.wait_for(asyncio.gather(*to_traverse),
                                                     self.job.timeout or None))

            if not self.all_tests_ok:
                # the summary is a set so only a single failed test is enough
                summary.add('FAIL')
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
        object_suffix, object_variant = object_name.split("-")[:1][0], "-".join(object_name.split("-")[1:])
        object_image, object_vm = object_suffix.split("_")
        objects = graph.get_objects_by(param_val="^"+object_variant+"$",
                                       subset=graph.get_objects_by("images", object_suffix.split("_")[0]))
        vms = [o for o in objects if o.key == "vms"]
        assert len(vms) == 1, "Test object %s's vm not existing or unique in: %s" % (object_name, objects)
        test_object = objects[0]

        nodes = graph.get_nodes_by("object_root", object_name)
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
        status = await self.run_test_node(TestNode("0t", install_config, test_node.objects[0]),
                                          can_retry=True)
        if not status:
            logging.error("Could not configure the installation for %s on %s", object_vm, object_image)
            return status

        logging.info("Installing virtual machine %s", test_object.suffix)
        test_node.params["type"] = test_node.params["configure_install"]
        return await self.run_test_node(test_node, can_retry=True)

    """internals"""
    async def _traverse_test_node(self, graph, test_node, params, slot):
        """Run a single test according to user defined policy and state availability."""
        if not test_node.is_occupied():
            test_node.set_environment(self.job, slot)
        else:
            return

        if test_node.should_scan:
            test_node.scan_states()
            test_node.should_scan = False
        if test_node.should_run:

            # the primary setup nodes need special treatment
            if params.get("dry_run", "no") == "yes":
                logging.info("Running a dry %s", test_node.params["shortname"])
            elif test_node.is_shared_root():
                logging.debug("Test run on %s started from the shared root", slot)
            elif test_node.is_object_root():
                status = await self.run_terminal_node(graph, test_node.params["object_root"], params)
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
            logging.debug("Skipping test %s on %s", test_node.params["shortname"], slot)

        # free the node for traversal by other workers
        test_node.spawner = None

    async def _reverse_test_node(self, graph, test_node, params, slot):
        """
        Clean up any states that could be created by this node (will be skipped
        by default but the states can be removed with "unset_mode=f.").
        """
        if test_node.should_clean:

            if params.get("dry_run", "no") == "yes":
                logging.info("Cleaning a dry %s", test_node.params["shortname"])
            elif test_node.is_shared_root():
                logging.debug("Test run on %s ended at the shared root", slot)

            elif test_node.produces_setup():
                setup_dict = {} if params is None else params.copy()
                setup_dict["vm_action"] = "unset"
                setup_dict["vms"] = test_node.params["vms"]
                # the cleanup will be performed if at least one selected object has a cleanable state
                has_selected_object_setup = False
                for test_object in test_node.objects:
                    object_params = test_object.object_typed_params(test_node.params)
                    object_state = object_params.get("set_state")
                    if not object_state:
                        continue

                    # avoid running any test unless the user really requires cleanup and such is needed
                    if object_params.get("unset_mode", "ri")[0] != "f":
                        continue
                    # avoid running any test for unselected vms
                    if test_object.key == "nets":
                        logging.warning("Net state cleanup is not supported")
                        continue
                    vm_name = test_object.suffix if test_object.key == "vms" else test_object.composites[0].suffix
                    if vm_name in params.get("vms", param.all_objects("vms")):
                        has_selected_object_setup = True
                    else:
                        continue

                    # TODO: cannot remove ad-hoc root states, is this even needed?
                    if test_object.key == "vms":
                        vm_params = object_params
                        setup_dict["images_" + vm_name] = vm_params["images"]
                        for image_name in vm_params.objects("images"):
                            image_params = vm_params.object_params(image_name)
                            setup_dict[f"image_name_{image_name}_{vm_name}"] = image_params["image_name"]
                            setup_dict[f"image_format_{image_name}_{vm_name}"] = image_params["image_format"]
                            if image_params.get_boolean("create_image", False):
                                setup_dict[f"remove_image_{image_name}_{vm_name}"] = "yes"
                                setup_dict["skip_image_processing"] = "no"

                    # reverse the state setup for the given test object
                    unset_suffixes = f"_{test_object.key}_{test_object.suffix}"
                    unset_suffixes += f"_{vm_name}" if test_object.key == "images" else ""
                    # NOTE: we are forcing the unset_mode to be the one defined for the test node because
                    # the unset manual step behaves differently now (all this extra complexity starts from
                    # the fact that it has different default value which is noninvasive
                    setup_dict.update({f"unset_state{unset_suffixes}": object_state,
                                       f"unset_mode{unset_suffixes}": object_params.get("unset_mode", "ri")})

                if has_selected_object_setup:
                    logging.info("Cleaning up %s on %s", test_node, slot)
                    setup_str = param.re_str("all..internal..manage.unchanged")
                    net = test_node.objects[0]
                    forward_config = net.config.get_copy()
                    forward_config.parse_next_batch(base_file="sets.cfg",
                                                    ovrwrt_file=param.tests_ovrwrt_file(),
                                                    ovrwrt_str=setup_str,
                                                    ovrwrt_dict=setup_dict)
                    await self.run_test_node(TestNode(test_node.prefix + "c", forward_config, net))
                else:
                    logging.info("No need to clean up %s on %s", test_node, slot)

        else:
            logging.debug("The test %s should not be cleaned up on %s", test_node.params["shortname"], slot)

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
