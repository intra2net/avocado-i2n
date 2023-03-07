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
rm -fr /mnt/local/images/shared/vm1/* /mnt/local/images/shared/vm2/*

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
test_options="cartgraph_verbose_level=0"
coverage run --append --source=avocado_i2n $(which avocado) manu setup=run slots=$test_slots only=$test_sets $test_options

# custom checks
echo
echo "Check graph verbosity after the complete test suite run"
test -f "$test_results"/latest/cg_*.svg
test -d "$test_results"/latest/graph_parse
find "$test_results"/latest/graph_parse/cg_*.svg > /dev/null
test -d "$test_results"/latest/graph_traverse
find "$test_results"/latest/graph_traverse/cg_*.svg > /dev/null

echo
echo "Check if all containers have identical and synced states after the run"
ims="mnt/local/images"
containers="$(printf $test_slots | sed "s/,/ /g")"
for cid in $containers; do
    diff -r /$ims/c101/rootfs/$ims /$ims/c$cid/rootfs/$ims -x el8-64* -x win10-64* -x vm3
done
ls -A1q /mnt/local/images/shared/vm1 | grep -q . && exit 1
ls -A1q /mnt/local/images/shared/vm2 | grep -q . && exit 1
ls -A1q /mnt/local/images/shared/vm3 | grep -q . || exit 1

echo
echo "Check replay and overall test reruns behave as expected"
latest=$(basename $(realpath "$test_results"/latest))
test_options="replay=$latest"
coverage run --append --source=avocado_i2n $(which avocado) manu setup=run slots=$test_slots only=$test_sets $test_options
test $(ls -A1q "$test_results/latest/test-results" | grep -v by-status | wc -l) == 2
ls -A1q "$test_results/latest/test-results" | grep -q client_noop || exit 1
ls -A1q "$test_results/latest/test-results" | grep -q explicit_noop || exit 1
latest=$(basename $(realpath "$test_results"/latest))
test_sets="tutorial1"
test_options="replay=$latest replay_status=pass"
coverage run --append --source=avocado_i2n $(which avocado) manu setup=run slots=$test_slots only=$test_sets $test_options
test -d "$test_results"/latest/test-results

echo
echo "Testing a mix of shared pool and serial run"
ls -A1q /mnt/local/images/shared/vm1 | grep -q . && exit 1
mv /mnt/local/images/swarm/vm1/* /mnt/local/images/shared/vm1
test_options=""
coverage run --append --source=avocado_i2n $(which avocado) manu setup=run only=$test_sets $test_options
test -d "$test_results"/latest/test-results
ls -A1q "$test_results/latest/test-results" | grep -q install && exit 1
ls -A1q "$test_results/latest/test-results" | grep -q tutorial1 || exit 1

echo
echo "Integration tests passed successfully"
