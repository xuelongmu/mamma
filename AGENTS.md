# Agent guidance

This checkout is configured and tested under WSL at `/home/xuelong/mamma`.
Before changing the environment or continuing an experiment, read:

1. [`docs/status.md`](docs/status.md) for the dated research log and current state.
2. [`docs/local-runbook.md`](docs/local-runbook.md) for operational commands.
3. [`docs/viewer.md`](docs/viewer.md) before serving or sharing a Rerun scene.
4. [`docs/sjtu-sports.md`](docs/sjtu-sports.md) for the SJTU sports workflow.

## Research log and changelog

- Append a dated entry to `docs/status.md` after a meaningful run, failure,
  decision, or result. Record inputs, camera set, output tag, observations,
  artifact paths, and the next action. Do not rewrite older entries to make a
  later result look cleaner; add a correction with a new date.
- Update the `Unreleased` section of `CHANGELOG.md` for repository-visible
  changes to code, configuration, documentation, or behavior.
- Keep generated outputs, model assets, downloaded footage, credentials, and
  machine-local process state out of both files and out of version control.

## Contribution workflow

- Never commit directly to `main`. Create a focused branch and propose the
  change as a pull request.
- Use one ordinary PR for a cohesive change. Do not create a stack merely to
  separate documentation, tests, scripts, or arbitrary implementation phases.
- Use stacked PRs only when later changes functionally depend on earlier ones
  and each layer can be reviewed and merged independently.
- GitHub's stacked-PR tooling is a public preview. With GitHub CLI 2.90+ and
  Git 2.20+, the standard workflow is:

  ```bash
  gh extension install github/gh-stack
  gh stack init
  gh stack add <dependent-branch>
  gh stack submit
  gh stack view
  ```

- In a stack, the first PR targets the trunk and each subsequent PR targets the
  branch directly below it. Explain the dependency and intended merge order in
  every PR description.
- Never open a pull request or issue against the upstream MAMMA repository.
  Before creating either, verify that the target owner and repository are this
  fork. Treat an upstream remote as read-only.
- Do not push, open a PR, merge, or modify remote state unless the user asks.

## Working environment

- Use the micromamba environment named `mamma`.
- Run repository commands from `/home/xuelong/mamma`.
- Run `micromamba run -n mamma python -m inference doctor` before a long job.
- The working installation uses Python 3.11, PyTorch 2.5.1 + CUDA 12.4, and has
  been tested on an RTX 4090.
- Check `nvidia-smi` before a GPU-heavy stage. Do not terminate an unrelated
  process to free memory without explicit authorization.
- Pass MAMMA/SMPL-X credentials through `MAMMA_USERNAME` and `MAMMA_PASSWORD`
  only when an authenticated download needs them. Never print or commit them.

## Pipeline and recovery

- The stage order is `ma_cap -> ma_masks -> ma_2d -> ma_3d -> ma_vis`.
- Pipeline stages resume from `DONE` markers. Reuse an output tag to continue
  an interrupted run; use a new tag for a clean comparison.
- Do not delete outputs or `DONE` markers without explicit authorization.
- For camera-count ablations, reuse identical masks, identities, and 2D
  landmarks when the experiment is meant to isolate only the 3D camera set.
- More cameras are not automatically better. Record missing-landmark ratios,
  uncertainty, reprojection outliers, and identity failures.
- Under `use_gt=False`, `gt_joints` and `gt_vertices` may duplicate predictions
  for visualization compatibility. Verify provenance before reporting MPJPE or
  PVE.

## Headless visualization and world orientation

Set these variables for commands that use EGL or reach `ma_vis`:

```bash
export LD_LIBRARY_PATH=/home/xuelong/micromamba/envs/mamma/lib
export __EGL_VENDOR_LIBRARY_DIRS=/home/xuelong/micromamba/envs/mamma/share/glvnd/egl_vendor.d
export MPLBACKEND=Agg
```

The WSL setup may warn about `/dev/dri/renderD128` and fall back to
`kms_swrast`; that is acceptable when rendering continues.

SJTU sports calibration uses world X-up. Pass `--up-axis x`, log
`ViewCoordinates.RIGHT_HAND_X_UP` at the Rerun world root, and visually verify
that people stand upright before sharing a URL or video.

The browser URL must retain its complete recording query. A bare web-viewer
address opens the Rerun homepage rather than the recording. See
[`docs/viewer.md`](docs/viewer.md) for exact commands and URLs.

## Repository hygiene

- Preserve unrelated and user-authored changes.
- Use the repository-root `tmp/` directory for scratch files, temporary media,
  manifests, logs, and other disposable intermediates. `tmp/` is gitignored;
  do not force-add or upload anything from it.
- Prefer repository-relative paths and explicit CLI arguments in reusable
  scripts. Keep `/home/<user>`, `/mnt/<drive>`, PIDs, and fixed ports in local
  examples rather than implementation defaults.
- Never commit or upload media assets through the repository host, including
  PR or issue attachments and release assets. Source footage, extracted
  frames, images, audio, videos, rendered previews, and `.rrd` recordings may
  exist locally only under the gitignored `tmp/` directory. Any storage or
  transfer beyond that local scratch directory must be handled outside the
  repository host. Record only non-sensitive metadata and external handling
  instructions in the research log.
- Do not commit licensed SMPL-X model files, weights, generated outputs, or
  credentials.
- Run `git diff --check`, relevant tests, and shell/Python syntax checks before
  handing work off.
