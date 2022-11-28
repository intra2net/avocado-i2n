#!/bin/bash
set -eu

# minimal effect runs
coverage run --append --source=avocado_i2n $(which avocado) manu setup=noop
coverage run --append --source=avocado_i2n $(which avocado) manu setup=list

# TODO: The current entry points are broken and usually replaced with manual steps
#coverage run --append --source=avocado_i2n $(which avocado) list --auto "only=tutorial1"
#coverage run --append --source=avocado_i2n $(which avocado) run --auto "only=tutorial1 dry_run=yes"

# full integration run
test_slots="c101,c102,c103,c104,c105"
test_sets="leaves"
test_options="cartgraph_verbose_level=0"
coverage run --append --source=avocado_i2n $(which avocado) manu setup=run slots=$test_slots only=$test_sets $test_options

# custom checks
# check graph verbosity after the complete test suite run
test -f /mnt/local/results/latest/cg_*.svg
test -d /mnt/local/results/latest/graph_parse
find /mnt/local/results/latest/graph_parse/cg_*.svg > /dev/null
test -d /mnt/local/results/latest/graph_traverse
find /mnt/local/results/latest/graph_traverse/cg_*.svg > /dev/null
# TODO: check if all containers have the same states with identical hash sums
# TODO: further custom hooks

echo "Integration tests passed successfully"
