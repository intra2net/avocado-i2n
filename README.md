# avocado-i2n
*Plugins for avocado extending avocado-vt with automated vm state setup,
inheritance, and traversal*

[![GH Actions](https://github.com/intra2net/avocado-i2n/actions/workflows/ci.yml/badge.svg)](https://github.com/intra2net/avocado-i2n/actions/workflows/ci.yml) [![Documentation Status](https://readthedocs.org/projects/avocado-i2n/badge/?version=latest)](https://avocado-i2n.readthedocs.io/en/latest/?badge=latest) [![CodeQL](https://github.com/intra2net/avocado-i2n/actions/workflows/codeql.yml/badge.svg)](https://github.com/intra2net/avocado-i2n/actions/workflows/codeql.yml) [![codecov](https://codecov.io/gh/intra2net/avocado-i2n/branch/master/graph/badge.svg)](https://codecov.io/gh/intra2net/avocado-i2n)

This file provides a brief overview of the core concepts behind the current
plugin and hopefully a compact explanation of how tests are being run.

## Motivation and background
The two milestones and guiding principles for a test running process are:

1) *test thoroughness* - how to test a maximum number of features with a
   minimal set of configuration parameters and code

2) *test reusability* - how to be reuse a maximum number of overlapping steps
   which offers greater performance gain with the thoroughness

The first is the code/configuration reuse, while the second is the
run/execution reuse. Combining optimally extensive testing of automatically
generated variety of scenarios with minimum setup overhead (minimal duration)
is the guiding principle for large scale testing. The first of these is well
handled by Cartesian configuration - producing a large number of scenarios and
configurations from a minimal, compact, and easy to read set of definitions,
also allowing to reuse test code for multiple variants and thus use cases. The
second guiding principle is the reason for the development of this plugin.

In classical test suites using the avocado-framework and the avocado-vt plugin,
most of the setup is performed at the beginning or within tests regardless of
what tests are to be performed. This has serious disadvantages since enormous
time is spent preparing for all possibilities if only a small and simple test
is desired. In order to save setup penalty, a lot of smaller actual tests
are put into larger ones (e.g. test for feature B while testing for feature A
because the setup of feature A is available and/or very similar to that of B).
In this way the setup's benefits are available but are also artificially
extended as the tests could be simpler and better isolated. Increasing
isolation always has the cost of redundant setup. In this case, the setup that
is automatically performed before a test is minimized only to the setup (and
respectively cleanup) specific to the demands of each selected test. To
achieve the better isolation, setup is now shared among tests so that it needs
to be performed only once and then shared by all tests. The trick to do this
while keeping the tests isolated and clean is the usage of states.

The granularity of states follows test objects which in our case represent
virtual machines. All tests use one or more test objects and are able to
retrieve or store states of these objects. Recalling the same previously saved
state from multiple tests is then a way of saving time from all of them,
essentially running another test only once to bring the object to this state
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

### Cartesian trees
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
of these alternatives and therefore tests. As a result, for a very extensive
scenario where every step is combined in such a way, it would take far too
long to perform setup such as installing a virtual machine every time for
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
might be based on one or multiple provided/required objects.

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

### Image, VM, and network states; normal and permanent vms
The sample test suite supports three types of stateful objects, i.e. test
objects with reusable state setup: images, vms, and networks. The image states
can be managed using different state backends like QCOW2, LVM, among others and
esentially can store and retrieve previous states of one or more VM images. The
VM states contain the image as well as RAM states and are thus states of an
entire running VM and all its images managed by backends like QCOW2VT (Qemu
monitor usage through Avocado VT) and Ramfile. Finally, the network states are
currently only managed by the VMNet state backend relying on the general VMNet
subpackage and all the networking management it provides.

For some comparison between VM and image states: the VM states are faster since
they involve running VM-s without an extra boot or shutdown but image states are
more granular and more appropriate for VMs using RAID1 or other multi-image
setup. For comparison among state backends, QCOW2 snapshots are easier to manage
and share since they involve simple transfer of QCOW2 files while LVM is more
rigid and not perfectly isolated for containerization (this eventually harder to
parallelize) but could be even faster if managed on top of RAM for maximum
speedup. LVM could also have more difficult to debug errors on unclean process
interruptions. QCOW2VT might not support some cases of states like ones using
pflash drives while the Ramfile backend is generally unstable. In the end all
state backends have different limitations with the major ones outlined so far.

A final additional concept to consider for test running is that of permanent
vms. For a test requiring vms with highly sophisticated preparation sequences
that sometimes might be only semi-automatable or requiring strictly human input
it might be more preferable to add an external vm that could for instance only
be manipulated via states derived from a single starting state (thus without
interfering with the original setup) or a few manually created starting states.
Such a permanent vm might just be brought from outside to participate in the
test suite orchestration or it could be at least partially prepared in-house
using the test suite toolset through an extra tool development. More information
about it can be found in the test development documentation.

## How to install
In terms of installation, you may proceed analogically to other avocado
plugins. One quick way is using PyPI:

```
pip install avocado-framework-plugin-i2n
```

## How to run
In order to list a test set from the sample test suite, do

```
avocado list --loaders cartesian_graph[ -- "K1=V1[ K2=V2[ ...]]"]
avocado list --loaders cartesian_graph -- "only=tutorial2 no=files"
```

In order to run a test set from the sample test suite, do

```
avocado run --auto --loaders cartesian_graph[ -- "K1=V1[ K2=V2[ ...]]"]
avocado run --auto --loaders cartesian_graph -- "only=tutorial1 file_contents=testing"
```

In order to run a manual step in the sample test suite, do

```
avocado manu[ "K1=V1[ K2=V2[ ...]]"]
avocado manu setup=full,update vms=vm1
```

where any further overwriting parameters can be provided on the command line. In
order to initate dry runs for instance you can use *dry_run=yes*.

### Tool options
The auto plugin is a an instance of a manual run step from the manu plugin
where the following statements are equivalent

```
avocado run --auto --loaders cartesian_graph -- "only=tutorial1 file_contents=testing"
avocado manu setup=run only=tutorial1 file_contents=testing
avocado manu only=tutorial1 file_contents=testing
```

but using the manu plugin is preferable because of its simpler syntax as well
generalization to many other tools implemented as manual steps. Thus, from here
on we will only look at the manu plugin with default option *setup=run* unless
explicitly stated at the command line.

 **Note**:  Any call will use the default settings in `objects.cfg` for the
available vms and `sets.cfg` for the tests which should be present in any test
suite using the plugin (see sample test suite for details). The main parameters
of interest there and on the command line are *setup* for manual test steps,
*only_vmX* for vm/object restrictions, and *only* for test/node restrictions.

```
OPTIONS:
[setup=setupchain]
[only_vmX=vmvariant]
[only=all|normal|minimal|...]
[get|set|unset_mode=XX]
```

The *setup* parameter will be used in the case of tool mode (manu plugin)
and the *get/set/unset_mode* parameter is mostly used in the case of test mode
(auto plugin). The choice of types of setup (manual steps) is the following:

 - *noop* - Simply load all plugins and do nothing (good for probing)
 - *create* - Create any predefined image for each virtual machine
 - *collect* - Collect the vm root state from a pool if available
 - *install* - Prepare step files and install virtual machines
 - *deploy* - Simply deploy changes on top of current state (will be lost
   after reverting to snapshot)
 - *internal* - Run a custom setup node without any automated setup
 - *boot* - Simply boot the registered virtual machines and run selected
   controls if any
 - *list* - List selected tests
 - *run* - Run selected tests
 - *download* - Download a set of files from the vm to the test results folder
 - *upload* - Upload a set of files to the vm's temporary folder
 - *unittest* - Run all unit tests available for the test suite utilities
 - *update* - Redeploy tests on a vm, removing all descending states
 - *shutdown* - Shutdown gracefully or kill living vms
 - *clean* - Remove the logical volumes of all installed vms
 - *full* - Create lvm image, install product, deploy tests and take a clean
   snapshot
 - *check* - Check whether a given state (snapshot of saved setup) exists
 - *get* - Get a given state, i.e. revert to it keeping it for further reuse
 - *set* - Set a given state, keeping it for further reuse
 - *unset* - Unset a given state, making it unavailable for further reuse but
   freeing space
 - *push* - Same like setting a given state
 - *pop* - Pop a given state, i.e. revert to it but making it unavailable for
   further reuse
 - *\<tool>* - Run any custom compatible tool, located in the tools test suite
   folder

You can define a chain of setup steps, e.g.

```
avocado manu setup=install,boot,deploy,run only=all
```

If you want to run tests at some point, you must include the *run* step
somewhere in the chain. Each setup performed after the *run* plays the role of
cleanup. You can run the tests multiple times with different setup steps in
between by adding multiple *run* steps throughout the setup chain. As all
other parameters, setup is not obligatory. If you don't use it on the command
line a default value from your configs will be selected. The additional but
rarely used get, set, or unset mode governs setup availability and defines the
overall existing (first char position) and missing (second char position)
setup policy. The value consists of two lowercase letters, each dot is one
of 'f' (force), 'i' (ignore), 'r' (reuse), 'a' (abort) and carries a special
meaning according to its position - the first position determines the action
of choice if the setup is present and the second if the setup is missing. Here
is a brief description of each possible policies and action combinations:

    ----------------------------------------
    -            - existing - non-existing -
    ----------------------------------------
    - get_mode   - ari      - ai           -
    ----------------------------------------
    - set_mode   - arf      - af           -
    ----------------------------------------
    - unset_mode - rf       - ai           -
    ----------------------------------------

 - get_mode:
   - *a.* - Abort if a setup is present (get_state)
   - *r.* - Reuse the present setup (get_state)
   - *i.* - Ignore all existing setup (run without the get_state)
   - *.a* - Abort if a setup is missing (get_state)
   - *.i* - Ignore all missing setup (run without any setup although it might
            be required)

 - set_mode:
   - *a.* - Abort if the set_state is already present (to avoid overwriting
            previous setup)
   - *r.* - Reuse the present set_state (ignore the results from the test that
            was run)
   - *f.* - Overwrite (recreate and save) all existing setup for children
            (set_state)
   - *.a* - Abort if the set_state is missing (if for example the purpose was
            overwriting)
   - *.f* - Create and save all missing setup for children (set_state)

 - unset_mode:
   - *r.* - Reuse the present unset_state for further test runs (don't cleanup
            the state here called "old")
   - *f.* - Remove the present unset_state (will be unavailable for children
            in the next runs)
   - *.a* - Abort if the state for cleanup is missing (cannot be removed since
            not there)
   - *.i* - Ignore if the state for cleanup is missing (cannot be removed
            since not there)

A combination of defaults for all three policies would reuse all setup left
from previous runs determined by the set of tests you want to run. Automatic setup
can only be performed if and where you have defined *run* for the manual setup.
Since the default manual setup is *run*, simply omitting the setup parameter at
the command line will suffice for performing the automatic setup for most cases.
A scenario to appreciate automated setup steps is the following:

```
avocado manu setup=full vms=vm1,vm2
avocado manu only=tutorial2..files
avocado manu setup=clean vms=vm1
avocado manu only=tutorial2..files
```

Assuming that line one and two will create two vms and then simply reuse the
first one which is a dependency for the given tutorial test. The third line
will then eliminate the existing setup for vm1 (and vm1 entirely). The final
line would then still require vm1 although only vm2 is available. The setup for
this test will start by bringing vm1 to the state which is required for the
tutorial test ignoring and not modifying in any way the setup of vm2. If for
instance the dependency of tutorial2 is 'vm1_ready' (defined as the parameter
'get_state=vm1_ready' in the config for this subset), scanning for this state
and its dependencies will detect that all dependencies are missing, i.e. the
vm1 doesn't have the state and doesn't exist at all (also missing root state).
The test traversal would then look for the tests based on the state names since
simple setup is used. Since vm1 doesn't exist, it will create it and bring it
to that state automatically, also determining the *setup* steps automatically.

In the end with all but the minimum necessary vms and setup steps, the tests
will run. For this reason, it is important to point out that the list of vms
defined on the command line is used mainly for manual setup steps but could
also play the role of a restriction of the tests to include in run steps and is
otherwise automatically determined during automatic setup and thus not needed
if you don't want to restrict tests via vms they use. You can distinguish among
manual and automated steps by looking at test prefixes. The first contain "m"
in their identifiers while automated steps contain "a". Cleanup tests contain
"c" and are also automated depending on the unset mode you use. Finally, "b" is
used for additional test variants based on multiple variants of the vms they use
and "d" is reserved for duplicate tests due to multiple variants of test vms'
setup. If you include only one *run* the tests executed within the run step
will not contain any letters but if you include multiple *run* steps, in order
to guarantee we can distinguish among the tests, they will contain "n" (with
"t" for the terminal test nodes for each test object vm's image). The typical
approach to do this test tagging is compound and specifically in order of test
discovery, i.e. 0m1n1a2 stands for the test which is the second automated setup
of the test which is the first test in a run step m1 and first run n1. These
prefixes are also used in all graphical descriptions of the Cartesian graph and
for resolving all test dependencies.

 **Note**: The order of regular (run/main) tests is not always guaranteed.
Also, missing test numbers represent excluded tests due to guest variant
restrictions (some tests run only on some OS, hardware, or vms in general).

More details regarding the configuration necessary for creating the graph is
available in the test development documentation but the essential ones are the
*check*, *get*, *set*, and *unset* routines with additional parameters like

- *\*_state{_vms|_images}* - A vm or image state to perform the routine on
- *\*_mode* - Behaviors in case of present/absent setup defined above
- *\*_opts* - Secondary options, important only within the implementation

An *only* argument can have any number of ".", "..", and "," in between variant
names where the first stands for *immediately followed by*, the second for AND
and the third for OR operations on test variants. Using multiple only arguments
is equivalent to using AND among the different only values. In this sense,

```
avocado manu only=aaa only=bbb
```

is analogical to

```
avocado manu only=aaa..bbb
```

You can also use "no=aaa" to exclude variant "aaa" for which there is no
shortcut alternative, but you can also stack multiple *no* arguments similarly
to the multiple *only* arguments. The *only* and *no* arguments together with
the inline symbols above help run only a selection of one or more tests. Most
importantly

```
avocado manu [only=all|normal|minimal|...] only=TESTSUBVARIANT
```

 is the same as using the *only* clause in the Cartesian configs. Ultimately,
all *only* parameters have the same effect but the "all", "normal", "minimal"
and other variants specified in the *main_restrictions* base config parameter
are treated in a special way where they have an overridable default value. What
this means is that compared to all standard variants, we will only end up with
just one (default if not overrriden) variant (e.g. 'only=normal') and not a
Cartesian product of all of them. The following are examples of test selections

```
avocado manu only=minimal only=quicktest
avocado manu only=normal only=tutorial1
avocado manu only=normal..tutorial2 only=names,files
avocado manu only=tutorial2..names,quicktest.tutorial2.files
```

 For more details on the possible test subvariants once again check the
`groups.cfg` or `sets.cfg` config files, the first one of which emphasizes on
the current available test groups and the second on test sets, i.e. selections
of these groups.

Similarly to the test restrictions, you can restrict the variants of vms that
are defined in `objects.cfg`. The only difference is the way you specify this,
namely by using *only_vmX* instead of *only* where vmX is the suffix of the vm
that you want to restrict. The following are examples of vm selection

```
avocado manu only_vm2=Win10
avocado manu only_vm1=CentOS only=tutorial1
avocado manu only_vm2=
```

If we allow for multiple hardware or software variants of vm2, the third line
would simply run all tests compatible with all vm2 variants.

Any other parameter used by the tests can also be given like an optional
argument. For example the parameter `vms` can be used to perform setup only on
a single virtual machine. Thus, if you want to perform a full vm cleanup but
you want to affect only virtual machine with the name 'vm2' you can simply type

```
avocado manu setup=clean vms=vm2
```

 **Note**: Be careful with the vm parameter generator, i.e. if you want to
define some parameters for a single virtual machine which should not be
generated make sure to do so. Making any parameter specific is easy - you only
have to append a `_vmname` suffix to it, e.g. `nic_vm2` identically to the vm
restriction.

### Test debugging
Whenever you run a single test and it fails, the vms will be left running
afterwards and completely accessible for any type of debugging. The philosophy
of this is that a vm state is cleaned up only when a new test is run and needs
the particular test object (vm). As a result, all cleanups are removed and
merged with all setups which is the only thing we have to worry about
throughout any test run or development. An exception of this, i.e. a vm which
is not left running could be either if the vm is an ephemeral client or if it
was forced to shut down by a *kill_vm* parameter or when setting an image state
(after automated clean shutdown) in the scope of the given test being run. If
more than one test is being run and the error occurred at an early test, the
vm's state can be saved as 'last_error' and can later on be accessed via

```
avocado manu setup=get get_state=last_error vms=vm1
```

 for the vms that were involved in the test (e.g. vm1) but you have to use a
special `set_state_on_error=last_error` parameter as by default we rather cancel
saving the originally specified states via `set_state_on_error=`.

If more than one tests failed, in order to avoid running out of space, the
state of the last error will be saved on top of the previous error. This means
that you will only be able to quickly debug the last encountered error. A
second limitation in the state debugging is that it doesn't support more
complicated tests, i.e. tests with more complex network topologies, hence also
our choice of default above.

 **Note**: There is a large set of dumped data, including logs, files of
importance for the particular tests, hardware info, etc. for every test in the
test results. If the test involves work with the vm's GUI, some backends also
provide additional image logging (see backend documentation for more info). You
can make use of all these things in addition to any possible states at the
time of the error. Graphical representation of the entire Cartesian graph of
tests is also available for each step of the test running and parsing and can
be optionally enabled for job-related debugging.

### Unit testing
Even though a test suite usually has the sole purpose of testing software,
many of the tests make heavy use of utilities. The fact that the code of such
test utilities is reused so many times and for so many tests might be a good
motivation for testing these utilities separately and developing their own unit
tests. This is strongly advised for more complex utilities.

Therefore, to run all available unit tests (for all utilities) use the *unit
test* tool or manual step

```
avocado manu setup=unittest
```

 This will validate all utilities or at least the ones that are more complex.

To run only a subset of the unit tests (or even just one), you can make use
of UNIX shell style pattern matching:

```
avocado manu setup=unittest ut_filter=*_helper_unittest.py
```

 This will run only the unit tests that end with '_helper_unittest.py'.

If you are developing your own unit test for a utility, you only need to
follow the guide about unit testing in python and put your own test module
next to the utility with the name `<my-utility>_unittest.py` and it will be
automatically discovered when you run the "unittest" manual step.

### Single node running
If you want to run a test without automated setup from a complete graph, i.e.
an internal (variant) test node, you can use the *internal* tool or manual step

```
avocado manu setup=internal node=set_provider vms=vm1
```

 This will run an internal test (used by the Cartesian graph for automated
setup) completely manually, i.e. without performing any automated setup or
requiring any present state as well as setting any state. This implies that you
can escape any automated setup/cleanup steps but are responsible for any
setup/cleanup that is required by the test you are running (the test node). Use
with care as this is mostly used for manual and semi-manual tests. All variants
in the configuration can be parsed from the command line and the ones that are
inaccessible will not be traversed as described in:

https://github.com/intra2net/avocado-i2n/blob/master/doc/test_traversal_algorithm.pdf

What this means is that all nodes we typically parse with *only leaves* will
usually represent actual use cases of the product under QA connected to a root
traversal entry point through *nonleaves* and thus ultimately traversed. The
most standard set *only normal* is an even smaller set of such nodes while the
*only all* restriction will parse the complete graph but traverse only the part
reachable from the shared root node skip the rest. Any internal tests that are
not directly used remain disconnected and as such will not be run. They are then
typically called only from (manual step) tools. Reading the graph from the
config is thus mostly WYSIWYG and does not require any extra knowledge of the
code parsing it.

## How to develop
While some users might only run a test suite for their own product QA, others
are probably going to be writing tests to expand its coverage. This document
concentrates only on the running part and the developing part is covered in
multiple tutorials in the project wiki. Feel free to check it out.
