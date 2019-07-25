#!/bin/bash

set -euxo pipefail

THISDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BASEDIR="$( dirname "$( dirname "${THISDIR}" )" )"

# shellcheck source=/dev/null
source "${BASEDIR}/ci/in_docker/prepare.sh"

cd "${BASEDIR}"
find . -iname \*.sh -print0 | xargs -0 shellcheck
# Version independant checks
PYVER=3.7
# Run pyspelling in root to check docs
"python${PYVER}" -m pyspelling
cd "${BASEDIR}/app"
# Version dependant checks
for PYVER in ${PYTHONVERS} ; do
  "python${PYVER}" -m flake8 "${MODULES[@]}"
  "python${PYVER}" -m isort -rc -c --diff "${MODULES[@]}"
  "python${PYVER}" -m bandit -r "${MODULES[@]}"
  find "${MODULES[@]}" -iname \*.py -print0 | xargs -0 -n 1 "${BASEDIR}/ci/in_docker/pylint.sh" "python${PYVER}"
  "python${PYVER}" -m pytest -n auto --cov-config=.coveragerc --cov-fail-under=0 "--cov=${MAIN_MODULE}" --cov-report=xml:test-cov.xml --cov-report=html
done
# validate doco
"${BASEDIR}/ci/in_docker/doco.sh"
echo 'Testing Complete'
