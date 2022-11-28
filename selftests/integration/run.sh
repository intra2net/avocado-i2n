#!/bin/bash
set -eu

# minimal effect runs
coverage run --append --source=avocado_i2n $(which avocado) manu setup=noop
coverage run --append --source=avocado_i2n $(which avocado) manu setup=list

# TODO: The current entry points are broken and usually replaced with manual steps
#coverage run --append --source=avocado_i2n $(which avocado) list --auto "only=tutorial1"
#coverage run --append --source=avocado_i2n $(which avocado) run --auto "only=tutorial1 dry_run=yes"

# full integration run
coverage run --append --source=avocado_i2n $(which avocado) manu setup=run slots=c101,c102,c103,c104,c105 only=leaves
