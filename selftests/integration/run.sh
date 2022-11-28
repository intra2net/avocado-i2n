#!/bin/bash
set -eu

coverage run --append --source=avocado_i2n $(which avocado) manu setup=noop
coverage run --append --source=avocado_i2n $(which avocado) manu setup=list

# TODO: The current entry points are broken and usually replaced with manual steps
#coverage run --append --source=avocado_i2n $(which avocado) list --auto "only=tutorial1"
#coverage run --append --source=avocado_i2n $(which avocado) run --auto "only=tutorial1 dry_run=yes"

