#!/bin/bash
set -eu

# must prepare locally
echo
echo "Configure locally the current plugin source and prepare to run"
# TODO: local installation does not play well with external pre-installations - provide custom container instead
#pip install -e .
readonly test_suite="${TEST_SUITE:-/root/avocado-i2n-libs/tp_folder}"
readonly i2n_config="${I2N_CONFIG:-/etc/avocado/conf.d/i2n.conf}"
rm ${HOME}/avocado_overwrite_* -fr
sed -i "s#suite_path = .*#suite_path = ${test_suite}#" "${i2n_config}"
rm -fr /mnt/local/images/swarm/*
rm -fr /mnt/local/images/shared/vm1/* /mnt/local/images/shared/vm2/*

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
test -f /mnt/local/results/latest/cg_*.svg
test -d /mnt/local/results/latest/graph_parse
find /mnt/local/results/latest/graph_parse/cg_*.svg > /dev/null
test -d /mnt/local/results/latest/graph_traverse
find /mnt/local/results/latest/graph_traverse/cg_*.svg > /dev/null

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
latest=$(basename $(realpath /mnt/local/results/latest))
test_options="replay=$latest"
coverage run --append --source=avocado_i2n $(which avocado) manu setup=run slots=$test_slots only=$test_sets $test_options
test $(ls -A1q /mnt/local/results/latest/test-results | grep -v by-status | wc -l) == 2
ls -A1q /mnt/local/results/latest/test-results | grep -q client_noop || exit 1
ls -A1q /mnt/local/results/latest/test-results | grep -q explicit_noop || exit 1
latest=$(basename $(realpath /mnt/local/results/latest))
test_sets="tutorial1"
test_options="replay=$latest replay_status=pass"
coverage run --append --source=avocado_i2n $(which avocado) manu setup=run slots=$test_slots only=$test_sets $test_options
test -d /mnt/local/results/latest/test-results


echo
echo "Integration tests passed successfully"
