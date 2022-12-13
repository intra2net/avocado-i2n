#!/bin/bash
set -eu

# must install locally
echo
echo "Install locally the current plugin source"
pip install -e .

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
test_slots="c101,c102,c103,c104,c105"
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
    diff -r /$ims/c101/rootfs/$ims /$ims/$cid/rootfs/$ims -x el8-64* -x win10-64* -x vm3
done

echo
echo "Integration tests passed successfully"
