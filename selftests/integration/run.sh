#!/bin/bash
set -eu

readonly test_suite="${TEST_SUITE:-/root/avocado-i2n-libs/tp_folder}"
readonly test_results="${TEST_RESULTS:-/root/avocado/job-results}"
readonly i2n_config="${I2N_CONFIG:-/etc/avocado/conf.d/i2n.conf}"

# local environment preparation
echo
echo "Configure locally the current plugin source and prepare to run"
# TODO: local installation does not play well with external pre-installations - provide custom container instead
#pip install -e .
# change default avocado settings to our preferences for an integration run
cat >/etc/avocado/avocado.conf <<EOF
[runner.output]
# Whether to display colored output in terminals that support it
colored = True
# Whether to force colored output to non-tty outputs (e.g. log files)
# Allowed values: auto, always, never
color = always

[run]
# LXC and remote spawners require manual status server address
status_server_uri = 192.168.254.254:8080
status_server_listen = 192.168.254.254:8080

[spawner.lxc]
slots = ['c101', 'c102', 'c103', 'c104', 'c105']

[spawner.remote]
slots = ['c101', 'c102', 'c103', 'c104', 'c105']
EOF
mkdir -p /etc/avocado/conf.d
# TODO: use VT's approach to register the plugin config
if [ ! -f /etc/avocado/conf.d/i2n.conf ]; then
    ln -s ~/avocado-i2n-libs/avocado_i2n/conf.d/i2n.conf "${i2n_config}"
fi
sed -i "s#suite_path = .*#suite_path = ${test_suite}#" "${i2n_config}"
rm ${HOME}/avocado_overwrite_* -fr
rm -fr /mnt/local/images/swarm/*
rm -fr /mnt/local/images/shared/vm1-* /mnt/local/images/shared/vm2-*

# minimal other dependencies for the integration run
dnf install -y python3-coverage python3-lxc

# minimal effect runs
echo
echo "Perform minimal supported manual steps (run minimal tools)"
coverage run --append --source=avocado_i2n $(which avocado) manu setup=noop
coverage run --append --source=avocado_i2n $(which avocado) manu setup=list

# TODO: The current entry points are broken and usually replaced with manual steps
#coverage run --append --source=avocado_i2n $(which avocado) list --auto "only=tutorial1"
#coverage run --append --source=avocado_i2n $(which avocado) run --auto "only=tutorial1 dry_run=yes"

# full integration run
echo
echo "Perform a full sample test suite run"
test_slots="101,102,103,104,105"
test_sets="leaves"
test_options="cartgraph_verbose_level=0 only_vm1="
coverage run --append --source=avocado_i2n $(which avocado) manu setup=run slots=$test_slots only=$test_sets $test_options

# custom checks
echo
echo "Check graph verbosity after the complete test suite run"
test -f "$test_results"/latest/cg_*.svg || (echo "Missing minimal main graph dump" && exit 1)
test -d "$test_results"/latest/graph_parse || (echo "Missing graph parsing dump directory" && exit 1)
find "$test_results"/latest/graph_parse/cg_*.svg > /dev/null || (echo "Missing graph parsing dumps" && exit 1)
test -d "$test_results"/latest/graph_traverse || (echo "Missing graph traversal dump directory" && exit 1)
find "$test_results"/latest/graph_traverse/cg_*.svg > /dev/null || (echo "Missing graph traversal dumps" && exit 1)

echo
echo "Check if all containers have identical and synced states after the run"
ims="mnt/local/images"
containers="$(printf $test_slots | sed "s/,/ /g")"
for cid in $containers; do
    diff -r /$ims/c101/rootfs/$ims /$ims/c$cid/rootfs/$ims -x el8-64* -x f33-64* -x win10-64* -x vm3 || (echo "Different states found at ${cid}" && exit 1)
done
# verify that either vm1/vm2 shared pool doesn't exit or is empty for the validity of our tests
ls -A1q /mnt/local/images/shared/vm1-* 2>/dev/null | grep -q . && (echo "Unexpected vm1 images in the shared pool" && exit 1)
ls -A1q /mnt/local/images/shared/vm2-* 2>/dev/null | grep -q . && (echo "Unexpected vm2 images in the shared pool" && exit 1)
ls -A1q /mnt/local/images/shared/vm3* | grep -q . || (echo "Missing vm3 images in the shared pool" && exit 1)

echo
echo "Check replay and overall test reruns behave as expected"
latest=$(basename $(realpath "$test_results"/latest))
test_options="replay=$latest"
coverage run --append --source=avocado_i2n $(which avocado) manu setup=run slots=$test_slots only=$test_sets $test_options
test $(ls -A1q "$test_results/latest/test-results" | grep -v by-status | wc -l) == 2 || (echo "Unexpected or missing tests replayed" && exit 1)
ls -A1q "$test_results/latest/test-results" | grep -q client_noop || (echo "The client_noop test was not rerun or cleaned from previous run" && exit 1)
ls -A1q "$test_results/latest/test-results" | grep -q explicit_noop || (echo "The explicit_noop test was not rerun or cleaned from previous run" && exit 1)
latest=$(basename $(realpath "$test_results"/latest))
test_sets="tutorial1"
test_options="replay=$latest replay_status=pass"
coverage run --append --source=avocado_i2n $(which avocado) manu setup=run slots=$test_slots only=$test_sets $test_options
test -d "$test_results"/latest/test-results || (echo "Passing tests were not replayed" && exit 1)

echo
echo "Testing a mix of shared pool and serial run"
ls -A1q /mnt/local/images/shared/vm1-* 2>/dev/null | grep -q . && (echo "Unexpected vm1 images in the shared pool found" && exit 1)
mv /mnt/local/images/swarm/vm1-* /mnt/local/images/shared/
test_options=""
coverage run --append --source=avocado_i2n $(which avocado) manu setup=run only=$test_sets $test_options
test -d "$test_results"/latest/test-results || (echo "No serial tests found" && exit 1)
ls -A1q "$test_results/latest/test-results" | grep -q install && (echo "Unwanted install test found and shared pool wasn't reused" && exit 1)
ls -A1q "$test_results/latest/test-results" | grep -q tutorial1 || (echo "The tutorial1 test wasn't run serially" && exit 1)

echo
echo "Test coverage for manual tools of all main types"
coverage run --append --source=avocado_i2n $(which avocado) manu setup=control slots=$test_slots vms=vm1,vm2 control_file=manual.control
container_array=($containers)
test $(ls -A1q "$test_results/latest/test-results" | grep -v by-status | wc -l) == ${#container_array[@]} || (echo "Incorrect total of control file runs" && exit 1)
test $(ls -A1q "$test_results/latest/test-results" | grep manage.run | wc -l) == ${#container_array[@]} || (echo "Incorrect number of control file runs" && exit 1)
coverage run --append --source=avocado_i2n $(which avocado) manu setup=get slots=$test_slots vms=vm1,vm2 get_state_images=customize
test $(ls -A1q "$test_results/latest/test-results" | grep -v by-status | wc -l) == 10 || (echo "Incorrect number of total state retrieval tests" && exit 1)
test $(ls -A1q "$test_results/latest/test-results" | grep manage.unchanged.vm1 | wc -l) == 5 || (echo "Incorrect number of vm1 state retrieval tests" && exit 1)
test $(ls -A1q "$test_results/latest/test-results" | grep manage.unchanged.vm2 | wc -l) == 5 || (echo "Incorrect number of vm2 state retrieval tests" && exit 1)
coverage run --append --source=avocado_i2n $(which avocado) manu setup=update slots=$test_slots vms=vm1,vm2 \
    from_state=customize to_state_vm1=connect remove_set=tutorial3
test $(ls -A1q "$test_results/latest/test-results" | grep -v by-status | wc -l) == 3 || (echo "Incorrect number of total tests during update" && exit 1)
test $(ls -A1q "$test_results/latest/test-results" | grep customize | wc -l) == 2 || (echo "Incorrect number of customize tests during update" && exit 1)
test $(ls -A1q "$test_results/latest/test-results" | grep connect.vm1 | wc -l) == 1 || (echo "Incorrect number of connect tests during update" && exit 1)

echo
echo "Integration tests passed successfully"
