#!/bin/bash
set -ue

# set up the sample test provider
test -d /mnt/local/tp-repo && exit 1
mkdir -p /mnt/local/tp-repo
cp -pr tp_folder /mnt/local/tp-repo

echo "Sample test suite ready"
