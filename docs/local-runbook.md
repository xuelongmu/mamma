# Local MAMMA runbook

This document covers operational details that are intentionally more specific
than the upstream installation and input-format documentation. Read
[`status.md`](status.md) first for current experiments and pending work.

## Known-good environment

- Repository: `/home/xuelong/mamma` under WSL
- Environment: micromamba environment `mamma`
- Python: 3.11
- PyTorch: 2.5.1 + CUDA 12.4
- Tested GPU: NVIDIA RTX 4090
- Verified Rerun SDK: 0.23.1

Required local body assets:

```text
data/body_models/smplx_locked_head/smplx/SMPLX_FEMALE.npz
data/body_models/smplx_locked_head/smplx/SMPLX_MALE.npz
data/body_models/smplx_locked_head/smplx/SMPLX_NEUTRAL.npz
data/body_models/downsampled_verts/verts_512.pkl
```

These assets are licensed separately and must not be committed.

Before a long run:

```bash
cd /home/xuelong/mamma
micromamba run -n mamma python -m inference doctor
nvidia-smi
```

Do not terminate an unfamiliar GPU process. If there is insufficient memory,
queue the work or ask the owner to release it.

## Headless rendering

Commands that can reach `ma_vis`, `pyrender`, or matplotlib should use:

```bash
export LD_LIBRARY_PATH=/home/xuelong/micromamba/envs/mamma/lib
export __EGL_VENDOR_LIBRARY_DIRS=/home/xuelong/micromamba/envs/mamma/share/glvnd/egl_vendor.d
export MPLBACKEND=Agg
```

Renderer smoke test:

```bash
PYOPENGL_PLATFORM=egl \
LD_LIBRARY_PATH=/home/xuelong/micromamba/envs/mamma/lib \
__EGL_VENDOR_LIBRARY_DIRS=/home/xuelong/micromamba/envs/mamma/share/glvnd/egl_vendor.d \
micromamba run -n mamma python -c \
  'import pyrender; r=pyrender.OffscreenRenderer(64,64); print("EGL OK"); r.delete()'
```

`Invalid device ID (0)` generally indicates the EGL vendor variable is absent.
The current WSL installation may warn about `/dev/dri/renderD128` and fall back
to `kms_swrast`; that is acceptable when rendering proceeds.

## Pipeline lifecycle

The stage order is:

```text
ma_cap -> ma_masks -> ma_2d -> ma_3d -> ma_vis
```

Run from the repository root:

```bash
micromamba run -n mamma python -m inference run \
  --cfg configs/examples/presets/quick.yaml \
  --capture <capture.json> \
  --out-tag <tag> -v
```

Use `configs/examples/presets/quick.yaml` for an end-to-end frame slice and
`configs/examples/presets/full.yaml` for a full sequence. A preset that disables
`ma_3d` is a preprocessing test, not a reconstruction.

Outputs are namespaced by tag:

```text
output/ma_cap/<tag>/
output/ma_masks/<tag>/
output/ma_2d/<tag>/
output/ma_3d/<tag>/
output/ma_vis/<tag>/
output/logs/jobs/<user>/<tag>/
```

Each completed stage writes a `DONE` marker. If a job is interrupted:

1. identify the first stage without `DONE`;
2. inspect both its `.out` and `.err` logs;
3. fix the cause without deleting valid upstream artifacts; and
4. rerun the identical command and output tag.

Use `--force` only when intentionally recomputing completed stages. Use a new
tag when a comparison must not inherit caches.

## Long-running jobs

Prefer one logged launcher per experiment. Record its command, tag, cameras,
and output log in [`status.md`](status.md). A detached process should redirect
stdin and both output streams:

```bash
mkdir -p output/logs/local
nohup bash scripts/<runner>.sh \
  > output/logs/local/<tag>.log 2>&1 < /dev/null &
```

Verify the process and log immediately. Do not assume that printing a PID means
the child survived initialization.

For GPU queues, check actual memory usage rather than only process names. Leave
headroom for model initialization; MammaNet and its detector can require more
memory at startup than during steady-state frame inference.

## Camera-count experiments

For a genuine camera-count ablation:

1. preprocess the largest camera set once;
2. keep masks, identity assignments, and 2D landmarks fixed;
3. use nested, spatially distributed camera subsets;
4. change only the camera list passed to `ma_3d`;
5. use a distinct 3D/visualization tag for each subset; and
6. inspect per-camera diagnostics rather than assuming more views are better.

The included MammaEval smoke-test captures are:

| Views | Cameras | Capture descriptor |
| ---: | --- | --- |
| 4 | `IOI_01 IOI_05 IOI_09 IOI_13` | `configs/ablations/captures/mamma_eval_catchball_4views.json` |
| 6 | `IOI_01 IOI_03 IOI_05 IOI_09 IOI_11 IOI_13` | `configs/ablations/captures/mamma_eval_catchball_6views.json` |
| 8 | `IOI_01 IOI_03 IOI_05 IOI_07 IOI_09 IOI_11 IOI_13 IOI_15` | `configs/ablations/captures/mamma_eval_catchball_8views.json` |

Run their preprocessing smoke test with:

```bash
bash scripts/run_view_ablation.sh
```

`configs/ablations/presets/quick_2d.yaml` intentionally stops before SMPL-X
optimization. Use an end-to-end preset when evaluating reconstructed bodies.

For SJTU-specific subsets and cache reuse, see
[`sjtu-sports.md`](sjtu-sports.md).

## Visual validation

A successful exit code is necessary but insufficient. Inspect:

- selected subject count and identity continuity;
- masks and dense landmarks in every requested camera;
- front, side, rear, and elevated reprojections;
- high-error or missing-landmark cameras;
- body scale and floor contact over the full timeline;
- world up-axis and ground orientation; and
- frames near the start, middle, and end.

The default visualizer may limit the number of overlay cameras in its preview.
An abbreviated collage does not mean the 3D optimizer used only those views.
Pass every requested overlay camera explicitly when the collage itself is an
experimental artifact.

For example, after a six-view 3D solve, rerun the visualization stage with the
complete list rather than accepting the four-camera default:

```bash
LD_LIBRARY_PATH=/home/xuelong/micromamba/envs/mamma/lib \
__EGL_VENDOR_LIBRARY_DIRS=/home/xuelong/micromamba/envs/mamma/share/glvnd/egl_vendor.d \
MPLBACKEND=Agg \
micromamba run -n mamma python visualization/run_ma_vis.py \
  --ma_2d_dir output/ma_2d/<tag>/<capture> \
  --ma_3d_dir output/ma_3d/<tag>/<capture> \
  --ma_cap_dir output/ma_cap/<tag>/<capture> \
  --seq_name <sequence> \
  --out_path output/ma_vis/<tag>/<capture> \
  --cam_names_overlay IOI_01 IOI_03 IOI_05 IOI_09 IOI_11 IOI_13 \
  --max_preview_cams 6 -v
```

Confirm the resulting log says `overlay rendered: 6/6` and inspect the labeled
collage. Use the corresponding complete camera list and preview limit for any
other subset.

Use [`viewer.md`](viewer.md) to serve the `.rrd` recording. Always keep the
complete `?url=rerun%2Bhttp...` query in the browser URL.

## Metrics caveat

When `run_ma_3d.py` uses `use_gt=False`, the `gt_joints` and `gt_vertices`
arrays in `verts_joints_body_id-XX.npz` may duplicate predictions for
visualization compatibility. They are not evaluation targets. The absence of
the evaluator's ground-truth files is another warning sign.

Before reporting MPJPE, PVE, or any zero-valued error, document the source of
ground truth, model variant, template, beta count, frame alignment, coordinate
convention, and joint subset.

## Bringing new footage

The complete schemas live in [`YOUR-DATA.md`](YOUR-DATA.md). Operational gates:

1. synchronize corresponding frame numbers;
2. use constant-frame-rate video;
3. keep each camera fixed after calibration;
4. match recorded resolution to intrinsics;
5. solve all extrinsics in one metric world frame;
6. verify reprojections before masks or optimization; and
7. select a short interval with overlapping subject coverage for the first run.

MAMMA consumes calibration; it does not estimate a camera rig or temporal
offsets.

## Troubleshooting checklist

1. Run `python -m inference doctor` in the `mamma` environment.
2. Verify the capture descriptor's data root, calibration, cameras, and sequence.
3. Confirm every requested camera has a video and calibration entry.
4. Confirm frame counts, frame rates, and synchronization.
5. Inspect the first missing `DONE` marker and both stage logs.
6. Check GPU memory ownership before retrying an OOM or killed process.
7. For `ma_vis`, verify EGL variables and world up-axis.
8. For a viewer homepage, restore the recording query parameter.
9. For a comparison, verify that caches and changed variables match the stated
   methodology.
10. Append the failure and resolution to [`status.md`](status.md).
