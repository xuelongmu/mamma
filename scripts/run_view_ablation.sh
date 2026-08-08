#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Mask visualization uses matplotlib from worker threads. The GUI Tk backend
# can abort on larger camera sets, so force the normal headless backend.
export MPLBACKEND=Agg

for views in 4 6 8; do
    micromamba run -n mamma python -m inference run \
        --cfg configs/ablations/presets/quick_2d.yaml \
        --capture "configs/ablations/captures/mamma_eval_catchball_${views}views.json" \
        --out-tag "ablate_${views}v" \
        -v
done
