# Depthkit / Scatter reconstruction

This runbook covers calibrated multi-camera RGB recordings exported in a
Depthkit/Scatter project. It records the calibration conversion validated on
the 10-camera Xuelong capture, the four-view reconstruction methodology, and
the commands needed to reproduce the result without committing source footage.

## Source layout

Pass either the project directory or its `dkproject.json` to the adapter. A
project can contain multiple recordings; each usable recording must have an RGB
asset for every participating device.

```text
<project>/
├── dkproject.json
└── .../Sensor01-...mp4
```

Keep the source project outside the repository. Write converted captures under
the ignored `data/` directory.

## Calibration convention

The Scatter project used for this work stores:

- `worldExtrinsics.world` as a depth-camera-to-world pose;
- that world pose in a left-handed coordinate system; and
- each color calibration's extrinsics as depth-camera-to-color-camera.

With `H = diag(1, 1, -1, 1)`, the validated conversion is:

```text
world_from_depth = H @ stored_world @ H
world_from_color = world_from_depth @ inverse(stored_color_extrinsic)
color_from_world = inverse(world_from_color)
```

The final 3x4 `color_from_world` matrix is the OpenCV world-to-camera
extrinsic consumed by MAMMA. The adapter also reorders Depthkit distortion
coefficients to OpenCV's `[k1, k2, p1, p2, k3]` order. It rejects non-zero
rational-model `k4`, `k5`, or `k6` terms because MAMMA's JSON loader does not
represent them.

Do not infer correctness from camera look directions alone. On the Xuelong
capture, an earlier convention produced roughly 85 px median disagreement in
the first four views; the conversion above reduced it to 4.29 px on matched
RGB evidence.

## Validate and conform the project

From WSL, validate the available recordings and calibration before writing
anything:

```bash
micromamba run -n mamma python \
  scripts/preprocessing/depthkit/prepare_depthkit_for_mamma.py \
  /mnt/d/dynamic-splat/test_data/Xuelong /tmp/unused --validate-only
```

The source Xuelong videos are sideways. Rotate every stream counter-clockwise
and transform its intrinsics, tangential distortion, dimensions, and camera
extrinsics in the same operation:

```bash
micromamba run -n mamma python \
  scripts/preprocessing/depthkit/prepare_depthkit_for_mamma.py \
  /mnt/d/dynamic-splat/test_data/Xuelong data/xuelong_depthkit \
  --rotate ccw --video-mode reencode
```

The adapter writes `calibration.json`, `capture.json`, and an auditable
`conversion_manifest.json`. With `--video-mode auto`, it links same-rate video
when no rotation is needed and otherwise re-encodes constant-frame-rate
H.264/yuv420p footage. Use `copy` for a self-contained capture. If only a
calibration convention changes after videos are prepared, use
`--calibration-only --overwrite` to verify and reuse those videos.

## Validate before MAMMA

For every selected camera, verify:

1. identical frame rate and synchronized action frames;
2. dimensions matching the converted calibration;
3. positive depth for points in the capture volume;
4. a proper, orthonormal camera rotation;
5. low epipolar disagreement on matched RGB features; and
6. usable subject coverage throughout the requested interval.

The converter preserves the Brown-Conrady distortion coefficients, but the
current MAMMA optimization path does not consume them. For a rigorous result,
undistort every RGB stream first and write the corresponding rectified
intrinsics. The Xuelong result below used the distorted RGB frames directly;
that limitation should remain attached to comparisons.

## Run the four-view reconstruction

The first four cameras were more stable than the initial 10-view solve. Start
with the tested 30-frame interval:

```bash
LD_LIBRARY_PATH=/home/xuelong/micromamba/envs/mamma/lib \
__EGL_VENDOR_LIBRARY_DIRS=/home/xuelong/micromamba/envs/mamma/share/glvnd/egl_vendor.d \
MPLBACKEND=Agg \
micromamba run -n mamma python -m inference run \
  --cfg configs/experiments/depthkit-quick-first4.yaml \
  --capture data/xuelong_depthkit/capture.json \
  --out-tag xuelong_depthkit_quick_first4 -v
```

After masks, identities, 2D landmarks, reprojections, scale, and orientation
look plausible, process every frame:

```bash
LD_LIBRARY_PATH=/home/xuelong/micromamba/envs/mamma/lib \
__EGL_VENDOR_LIBRARY_DIRS=/home/xuelong/micromamba/envs/mamma/share/glvnd/egl_vendor.d \
MPLBACKEND=Agg \
micromamba run -n mamma python -m inference run \
  --cfg configs/experiments/depthkit-full-first4.yaml \
  --capture data/xuelong_depthkit/capture.json \
  --out-tag xuelong_depthkit_full_first4 -v
```

The tested full runs completed 827 frames for the `..._02_...` recording and
1,203 frames for the `..._06_...` recording with finite saved SMPL-X vertices.
In the short validation interval, per-camera reprojection errors were
`22, 7, 11, 15 px` and `10, 5, 6, 14 px`, respectively.

## Render both 3D perspectives with the source views

Depthkit's converted world is Y-down. The established share renderer converts
it to a right-handed Y-up display when passed `--up-axis=-y`. A second azimuth
places the opposite side of the performer beside the first 3D view, while the
four synchronized source cameras remain in the bottom filmstrip:

```bash
PYOPENGL_PLATFORM=egl \
LD_LIBRARY_PATH=/home/xuelong/micromamba/envs/mamma/lib \
__EGL_VENDOR_LIBRARY_DIRS=/home/xuelong/micromamba/envs/mamma/share/glvnd/egl_vendor.d \
micromamba run -n mamma python scripts/render_share_video.py \
  --ma-3d-dir output/ma_3d/<tag>/<capture>/<sequence> \
  --ma-2d-dir output/ma_2d/<tag>/<capture>/<sequence> \
  --videos-dir data/xuelong_depthkit/<sequence>/videos \
  --cams cam_01 cam_02 cam_03 cam_04 \
  --up-axis=-y \
  --azimuth-degrees 45 \
  --secondary-azimuth-degrees 225 \
  --fps 30 \
  --output output/share/<tag>.mp4 \
  --title "Xuelong reconstruction - four views"
```

Supplying `--ma-2d-dir` hides the SMPL-X mesh on frames where fewer than two
selected cameras contain useful landmark visibility. It preserves the full
timeline and filmstrip, avoiding unconstrained entrance/exit poses without
trimming the clip.

Use [`viewer.md`](viewer.md) for source-frame offsets, deliverable validation,
and interactive Rerun handoff. Keep generated footage, reconstructions, and
`.rrd` files out of git.
