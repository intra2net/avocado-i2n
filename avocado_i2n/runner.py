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
import json
import logging as log
logging = log.getLogger('avocado.job.' + __name__)
import signal
import asyncio
log.getLogger('asyncio').parent = log.getLogger('avocado.job')

from avocado.core.job import Job
from avocado.core.nrunner.task import TASK_DEFAULT_CATEGORY, Task
from avocado.core.messages import MessageHandler
from avocado.core.plugin_interfaces import SuiteRunner as RunnerInterface
from avocado.core.status.repo import StatusRepo
from avocado.core.status.server import StatusServer
from avocado.core.suite import TestSuite
from avocado.core.teststatus import STATUSES_MAPPING
from avocado.core.task.runtime import RuntimeTask, PreRuntimeTask, PostRuntimeTask
from avocado.core.task.statemachine import TaskStateMachine, Worker
from avocado.core.dispatcher import SpawnerDispatcher

from .cartgraph import TestGraph, TestWorker, TestNode


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

        self.status_repo = None
        self.status_server = None

        self.skip_tests = []

    """running functionality"""
    async def _update_status(self):
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
            message_handler.process_message(message, task, self.job)

    async def run_test_task(self, node):
        """
        Run a test instance inside a subprocess.

        :param node: test node to run
        :type node: :py:class:`TestNode`
        """
        host = node.params["nets_host"] or "process"
        gateway = node.params["nets_gateway"] or "localhost"
        spawner = node.params["nets_spawner"]
        logging.debug(f"Running {node.id} on {gateway}/{host} using {spawner} isolation")

        if node.worker.spawner is None:
            raise RuntimeError(f"Worker {node.worker} cannot spawn tasks")
        if not self.status_repo:
            self.status_repo = StatusRepo(self.job.unique_id)
            self.status_server = StatusServer(self.job.config.get('run.status_server_listen'),
                                              self.status_repo)
            asyncio.ensure_future(self.status_server.serve_forever())
            # TODO: this needs more customization
            asyncio.ensure_future(self._update_status())

        status_server_uri = self.job.config.get('run.status_server_uri')
        node.regenerate_vt_parameters()
        raw_task = Task(node, node.id_test,
                        [status_server_uri],
                        category=TASK_DEFAULT_CATEGORY,
                        job_id=self.job.unique_id)
        raw_task.runnable.output_dir = os.path.join(self.job.test_results_path,
                                                    raw_task.identifier.str_filesystem)
        task = RuntimeTask(raw_task)
        config = self.test_suite.config if hasattr(self, "test_suite") else self.job.config
        pre_tasks = PreRuntimeTask.get_tasks_from_test_task(
            task,
            1,
            self.job.test_results_path,
            None,
            status_server_uri,
            self.job.unique_id,
            config,
        )
        post_tasks = PostRuntimeTask.get_tasks_from_test_task(
            task,
            1,
            self.job.test_results_path,
            None,
            status_server_uri,
            self.job.unique_id,
            config,
        )
        tasks = [*pre_tasks, task, *post_tasks]
        for task in tasks:
            if spawner == "lxc":
                task.spawner_handle = host
            elif spawner == "remote":
                task.spawner_handle = node.get_session_to_net()
        self.tasks += tasks

        # TODO: use a single state machine for all test nodes when we are able
        # to at least add requested tasks to it safely (using its locks)
        await Worker(state_machine=TaskStateMachine(tasks, self.status_repo),
                     spawner=node.worker.spawner, max_running=1,
                     task_timeout=self.job.config.get('task.timeout.running')).run()

    async def run_test_node(self, node):
        """
        Run a node once, and optionally re-run it depending on the parameters.

        :param node: test node to run
        :type node: :py:class:`TestNode`
        :returns: run status of :py:meth:`run_test_task`
        :rtype: bool
        :raises: :py:class:`AssertionError` if the ran test node contains no objects

        The retry parameters are `retry_attempts` and `retry_stop`. The first is
        the maximum number of retries, and the second indicates when to stop retrying
        in terms of encountered test status and can be a list of statuses to stop on.

        Only tests with the status of pass, warning, error or failure will be retried.
        Other statuses will be ignored and the test will run only once.

        This method also works as a convenience wrapper around :py:meth:`run_test`,
        providing some default arguments.
        """
        if node.is_objectless():
            raise AssertionError("Cannot run test nodes not using any test objects, here %s" % node)

        retry_stop = node.params.get_list("retry_stop", [])
        # ignore the retry parameters for nodes that cannot be re-run (need to run at least once)
        runs_left = 1 + node.params.get_numeric("retry_attempts", 0)
        # do not log when the user is not using the retry feature
        if runs_left > 1:
            logging.debug(f"Running test with retry_stop={', '.join(retry_stop)} and retry_attempts={runs_left}")
        if runs_left < 1:
            raise ValueError("Value of retry_attempts cannot be less than zero")
        disallowed_status = set(retry_stop).difference(set(["fail", "error", "pass", "warn", "skip"]))
        if len(disallowed_status) > 0:
            raise ValueError(f"Value of retry_stop must be a valid test status,"
                             f" found {', '.join(disallowed_status)}")

        original_prefix = node.prefix
        for r in range(runs_left):
            # appending a suffix to retries so we can tell them apart
            if r > 0:
                node.prefix = original_prefix + f"r{r}"
            uid = node.id_test.uid
            name = node.params["name"]

            await self.run_test_task(node)

            for i in range(10):
                try:
                    test_result = next((x for x in self.job.result.tests if x["name"].name == name and x["name"].uid == uid))
                    test_status = test_result["status"]
                    break
                except StopIteration:
                    await asyncio.sleep(30)
                    logging.warning(f"Test result {uid} wasn't yet found and could not be extracted")
                    test_status = "ERROR"
            else:
                logging.error(f"Test result {uid} for {name} could not be found and extracted, defaulting to ERROR")
            if test_status not in ["PASS", "WARN", "ERROR", "FAIL"]:
                # it doesn't make sense to retry with other status
                logging.info(f"Will not attempt to retry test with status {test_status}")
                break
            if test_status.lower() in retry_stop:
                logging.info(f"Stop retrying after test status {test_status.lower()}")
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

    def run_workers(self, test_suite: TestSuite or TestGraph, params: dict[str, str]) -> None:
        """
        Run all workers in parallel traversing the graph for each.

        :param test_suite: test suite to traverse as graph or a custom test graph to traverse
        :param params: runtime parameters used for extra customization
        :raises: TypeError if the provided test suite is of unknown type
        """
        if isinstance(test_suite, TestSuite):
            graph = TestGraph()
            graph.new_nodes(test_suite.tests)
            graph.parse_shared_root_from_object_roots(params)
            graph.new_workers(TestGraph.parse_workers(params))
        elif isinstance(test_suite, TestGraph):
            graph = test_suite
        else:
            raise TypeError(f"Unknown test suite type for {type(test_suite)}, must be a Cartesian graph or an Avocado test suite")

        graph.visualize(self.job.logdir)
        graph.runner = self

        for worker in graph.workers.values():
            if not worker.spawner:
                worker.spawner = SpawnerDispatcher(self.job.config, self.job)[worker.params["nets_spawner"]].obj
            if "runtime_str" in worker.params and not worker.set_up():
                raise RuntimeError(f"Failed to start environment {worker.id}")
        slot_workers = sorted([*graph.workers.values()], key=lambda x: x.params["name"])
        to_traverse = [graph.traverse_object_trees(s, params) for s in slot_workers if "runtime_str" in s.params]
        asyncio.get_event_loop().run_until_complete(asyncio.wait_for(asyncio.gather(*to_traverse),
                                                                     self.job.timeout or None))

    def run_suite(self, job: Job, test_suite: TestSuite) -> set[str]:
        """
        Run one or more tests and report with test result.

        :param job: job that includes the test suite
        :param test_suite: test suite with some tests to run
        :returns: a set with types of test failures
        """
        summary = set()

        if not test_suite.enabled:
            job.interrupted_reason = f"Suite {test_suite.name} is disabled."
            return summary

        job.result.tests_total = len(test_suite.tests)

        self.job = job
        self.test_suite = test_suite
        self.tasks = []

        self.status_repo = StatusRepo(self.job.unique_id)
        self.status_server = StatusServer(self.job.config.get('run.status_server_listen'),
                                          self.status_repo)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.status_server.create_server())
        asyncio.ensure_future(self.status_server.serve_forever())
        # TODO: this needs more customization
        asyncio.ensure_future(self._update_status())

        params = self.job.config["param_dict"]

        # TODO: we could really benefit from using an appropriate params object here
        replay_jobs = params.get("replay", "").split(" ")
        replay_status = params.get("replay_status", "fail,error,warn").split(",")
        disallowed_status = set(replay_status).difference(set(["fail", "error", "pass", "warn", "skip"]))
        if len(disallowed_status) > 0:
            raise ValueError(f"Value of replay_status must be a valid test status,"
                             f" found {', '.join(disallowed_status)}")
        for replay_job in replay_jobs:
            if not replay_job:
                continue
            replay_dir = self.job.config.get("datadir.paths.logs_dir", ".")
            replay_results = os.path.join(replay_dir, replay_job, "results.json")
            if not os.path.isfile(replay_results):
                raise RuntimeError("Cannot find replay job results file %s" % replay_results)
            with open(replay_results) as json_file:
                logging.info(f"Parsing previous results to replay {replay_results}")
                data = json.load(json_file)
                if 'tests' not in data:
                    raise RuntimeError(f"Cannot find tests to replay against in {replay_results}")
                for test_details in data["tests"]:
                    if test_details["status"].lower() not in replay_status and test_details["name"] not in self.skip_tests:
                        self.skip_tests += [test_details["name"]]

        try:
            self.run_workers(test_suite, params)
            if not self.all_tests_ok:
                # the summary is a set so only a single failed test is enough
                summary.add('FAIL')
        except (KeyboardInterrupt, asyncio.TimeoutError) as error:
            logging.info(str(error))
            self.job.interrupted_reason = str(error)
            summary.add('INTERRUPTED')

        # clean up any test node session cache
        for session in TestNode._session_cache.values():
            session.close()

        # TODO: The avocado implementation needs a workaround here:
        # Wait until all messages may have been processed by the
        # status_updater. This should be replaced by a mechanism
        # that only waits if there are missing status messages to
        # be processed, and, only for a given amount of time.
        # Tests with non received status will always show as SKIP
        # because of result reconciliation.
        time.sleep(0.05)

        self.job.result.end_tests()
        # the status server does not provide a way to verify it is fully initialized
        # so zero test runs need to access an internal attribute before closing
        if self.status_server._server_task:
            self.status_server.close()

        # Update the overall summary with found test statuses, which will
        # determine the Avocado command line exit status
        test_ids = [
            runtime_task.task.identifier
            for runtime_task in self.tasks
            if runtime_task.task.category == "test"
        ]
        summary.update(
            [
                status.upper()
                for status in self.status_repo.get_result_set_for_tasks(test_ids)
            ]
        )
        return summary
