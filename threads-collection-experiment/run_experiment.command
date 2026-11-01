#!/bin/zsh
set -eu
experiment_root=${0:A:h}
exec /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 "$experiment_root/scripts/experiment.py" run --config "$experiment_root/config/experiment.json" "$@"
