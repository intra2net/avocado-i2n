# avocado-i2n
Plugins for avocado extending avocado-vt with automated vm state setup,
inheritance, and traversal

This file provides a brief overview of the core concepts behind the current
plugin and hopefully a compact explanation of how tests are being run.


Guiding principles
------------------
The two milestones, that determine the entire test management process are:

1) *test thoroughness* - how to test a maximum number of features with a
   minimal set of configuration parameters and code

2) *test reusability* - how to be reuse a maximum number of overlapping steps
   which offers greater performance gain with the thouroughness

The first is the code/configuration reuse, while the second is the
run/execution reuse. Combining optimally extensive testing of automatically
generated variety of scenarios with minimum setup overhead (minimal duration)
is the guiding principle for this plugin.


Background
----------
In classical test suites using the avocado-framework and the avocado-vt plugin,
most of the setup is performed at the beginning or within tests regardless of
what tests are to be performed. This has serious disadvantages since enormous
time is spent preparing for all possibilities if only a small and simple test
is desired. In order to save setup penalty, a lot of smaller actual tests
are put into larger ones. In this way the setup's benefits are artificially
extended but the tests could be simpler and better isolated. Increasing
isolation always has the cost of redundant setup. In this case, the setup that
is automatically performed before a test is minimized only to the setup (and
respectively cleanup) specific to the demands of each selected test. To
achieve the better isolation, setup is now shared among tests so that it needs
to be performed only once and then shared by all tests. The trick to do this
while keeping the tests isolated and clean is the usage of states. The
granularity of states is defined by test objects which in our case represent
virtual machines. All tests use one or more test objects and are able to
retrieve or store states of these objects. Recalling the same previously saved
state from multiple tests is then a way of saving time from all of them,
essentially running only once another test to bring the object to this state
and save it. This offers both better isolation and more reusable steps. The
test creating the state is also a test since it tests the "more basic" steps
of reaching this state. Tests using the same state are then dependent on the
first test and can be aborted if the first test fails. Test unique setup steps
should thus be integrated into the tests while setup steps that are used by
more than one test should be turned into test nodes themselves. Since some
tests use entire networks of virtual machines, they use multiple objects at
different states. And as the states are also interdependent, reusing the right
states at the right time is not a trivial task and uses a special structure
and traversing algorithm.


Cartesian trees
---------------
The interconnected states of each test object represent a tree data structure
with a single root state, the creation of the object. The basic setup thus
includes creation of the minimum required virtual machines and taking
snapshots of their respective states afterwards (non-root states). At every
step to a deeper level, another snapshot has to be taken and at going back
up it could either be removed or kept for future test runs. The latter option
has many advantages as it allows for interrupted runs to keep previous
progress and for splitting a test run into multiple shorter runs without
significant performance penalty. However, the origin of tests starts from the
Cartesian configuration.

1) *Parsing from a Cartesian configuration to create a test node*

The testing performed in a test suite is much more extensive because of the
Cartesian multiplication of the test variants. Defining just a few
alternatives for two parameters leads to a large set of possible combinations
of these alternatives and therefore tests. Therefore, for a very extensive
scenario where every step is combined in such a way, it would take far too
long to perform a setup such as installing a virtual machine every time for
every different detail. This is the reason for defining the used objects and
their state transitions as parameters directly in the Cartesian configuration.
All tests as well as the objects they use and the states they require or
create are then parsed straight from there.

2) *Connecting the test node to all test nodes it depends on and to all test
    nodes that depend on it*

Once extracted, each required object state relates to a test that provides it.
This rule is used to connect all tests based on the object trees or simply to
interconnect the trees in a directed graph. Each test node contains a set of
parents (inwards connections from other tests) and can only be run if all the
parents were run using the setup definition (of course it can also abort or
ignore the missing setup depending on a user defined policy). It then also
contains a set of children (outwards connections to other tests) where a DFS
traversal rule guarantees that the setup gain from running a child test will
not be lost but used until possible. The connection to/from another test node
might be based on one or multiple provided/required objects although the
simplified version requires that a test provides at most one object state to
others and a test using more than one virtual machines is a leaf node.

3) *Running all interconnected tests in a way that should minimize the
   precious time lost by repeating test setup*

While the structure might seem not that complex in the end, the algorithm used
to optimize the setup, i.e. traverse that structure so that the number of
repetitions of each setup tests are minimized is way more fun. Unfortunately,
it is not possible to guarantee that a setup should be performed only once
because of the sheer complexity of the dependencies but practically it should
be the case if you keep dependencies simple. A complication arises from the
fact that some states might run out of memory to store the differences from
the current object state and that some tests should play the role of setup
tests but are rather short-lived, i.e. cannot be reused if they are not
constantly retrieved. For the sake of keeping this text compact, we will avoid
giving the details but strongly recommending checking the source code of the
Cartesian graph data structure for anyone that want to have fun with forward
and backward DFS, the symmetrical pruning, and the reversing traversal path.


Offline and online states, durable and ephemeral tests
------------------------------------------------------
The basic way to implement virtual machine states is LVM. However, since LVM
requires the image to be inactive while reverting to the snapshot,
this will introduce at least shutdown-boot performance penalty between each
two tests. Actually, "live revert" is part of the future plans of LVM but
right now its extra steps while switching test nodes might be even slower.
Therefore, there is another type of states simply called here "online states"
leaving the LVM an implementation of offline states. The online states
implementation lies in the QCOW2 image format and more specifically the
QEMU-Monitor ability to take full and automatic virtual machine snapshots
which will avoid these two steps - just freeze the vm state and eventually
come back to it for another test that requires it. The QCOW2 format allows
QEMU to take live snapshots of both the virtual machine and its image without
a danger of saving image and ramdisk snapshots that are out of sync which is
the case with another implementation of online states (still available as the
"ramfile" state type). The test management and each automated vm state setup
checks for state availability once in a special "scan_dependencies" test and
uses this information for further decisions on test scheduling, order, and
skipping.

Each online state is based on an offline state. The tests that produce online
from offline states are thus ephemeral as changing the offline state would
remove all online states and the test has to be repeated. Online states are
however reusable within an offline state transition and as many branches of
online states transitions can span multiple tests without touching the offline
state. This is important in the test management as ephemeral tests provide
states that can only be reused with protective scheduling.


How to run
----------
In order to list a test set from the sample test suite, do

```
avocado list --paginator off --loaders cartesian_graph [-- "only=A no=B ..."]
```

In order to run a test set from the sample test suite, do

```
avocado run --auto --loaders cartesian_graph [-- "only=A no=B ..."]
```

In order to run a manual step in the sample test suite, do

```
avocado manu [setup=A vms=vm1 ...]
```

where any further overwriting parameters can be provided on the command line.

Currently, the plugin will only run with out own avocado(-vt) mods
(*master* branches of avocado and avocado-vt forks here).


How to install
--------------
In terms of installation, you may proceed analogically to other avocado plugins.
