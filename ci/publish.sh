#!/bin/bash

set -euxo pipefail

THISDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BASEDIR="$( dirname "${THISDIR}" )"

# shellcheck source=/dev/null
source "${BASEDIR}/ci/shared/_docker_helper.sh"

docker_compose_run "app" "/workspace/ci/in_docker/publish.sh" "$@"
