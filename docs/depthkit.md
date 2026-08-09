# Depthkit / Scatter reconstruction

This runbook covers calibrated multi-camera RGB recordings exported in a
Depthkit/Scatter project. It records the calibration conversion validated on
the 10-camera Xuelong capture, the 4/6/8-view reconstruction methodology, and
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

## Run the 4/6/8-view reconstructions

The camera sets are nested so every larger solve preserves the smaller set:

| Views | Cameras | Selection rationale |
| ---: | --- | --- |
| 4 | `cam_01 cam_02 cam_03 cam_04` | Validated full-clip baseline |
| 6 | add `cam_06 cam_08` | Fill the 44-degree and 90-degree rig azimuths with wide-baseline cameras |
| 8 | add `cam_09 cam_10` | Fill the 227-degree and 0-degree gaps while retaining wide baselines |

This selection excludes camera 07, whose 9.86 px calibration disagreement was
the clearest outlier in the 10-camera check. Cameras 05 and 07 are both closer
to the capture-volume centroid than the selected additions; they remain useful
follow-up candidates for studying elevated viewpoints, not part of this nested
baseline.

Start each camera count with its 30-frame interval:

```bash
LD_LIBRARY_PATH=/home/xuelong/micromamba/envs/mamma/lib \
__EGL_VENDOR_LIBRARY_DIRS=/home/xuelong/micromamba/envs/mamma/share/glvnd/egl_vendor.d \
MPLBACKEND=Agg \
micromamba run -n mamma python -m inference run \
  --cfg configs/experiments/depthkit-quick-<subset>.yaml \
  --capture data/xuelong_depthkit/capture.json \
  --out-tag xuelong_depthkit_quick_<views>v -v
```

Use `first4`, `6view`, or `8view` for `<subset>`, and `4`, `6`, or
`8` for `<views>`.

After masks, identities, 2D landmarks, reprojections, scale, and orientation
look plausible, process every frame with the matching full preset:

```bash
LD_LIBRARY_PATH=/home/xuelong/micromamba/envs/mamma/lib \
__EGL_VENDOR_LIBRARY_DIRS=/home/xuelong/micromamba/envs/mamma/share/glvnd/egl_vendor.d \
MPLBACKEND=Agg \
micromamba run -n mamma python -m inference run \
  --cfg configs/experiments/depthkit-full-<subset>.yaml \
  --capture data/xuelong_depthkit/capture.json \
  --out-tag xuelong_depthkit_full_<views>v -v
```

Only the four-view full baseline has completed validation so far. It processed
827 frames for the `..._02_...` recording and
1,203 frames for the `..._06_...` recording with finite saved SMPL-X vertices.
In the short validation interval, per-camera reprojection errors were
`22, 7, 11, 15 px` and `10, 5, 6, 14 px`, respectively.

The standalone presets are useful for producing each deliverable, but their
upstream masks, identities, and 2D landmarks are recomputed. For a controlled
camera-count ablation, run the eight-view upstream stages once, reuse compatible
evidence for the common cameras, and vary only the camera list passed to
`run_ma_3d.py`. Use distinct 3D output tags and report any per-camera outlier
instead of attributing every difference to view count.

## Render both 3D perspectives with the source views

Depthkit's converted world is Y-down. The established share renderer converts
it to a right-handed Y-up display when passed `--up-axis=-y`. A second azimuth
places the opposite side of the performer beside the first 3D view, while the
selected synchronized source cameras remain in the bottom filmstrip:

```bash
PYOPENGL_PLATFORM=egl \
LD_LIBRARY_PATH=/home/xuelong/micromamba/envs/mamma/lib \
__EGL_VENDOR_LIBRARY_DIRS=/home/xuelong/micromamba/envs/mamma/share/glvnd/egl_vendor.d \
micromamba run -n mamma python scripts/render_share_video.py \
  --ma-3d-dir output/ma_3d/<tag>/<capture>/<sequence> \
  --ma-2d-dir output/ma_2d/<tag>/<capture>/<sequence> \
  --videos-dir data/xuelong_depthkit/<sequence>/videos \
  --cams cam_01 cam_02 cam_03 cam_04 cam_06 cam_08 cam_09 cam_10 \
  --up-axis=-y \
  --azimuth-degrees 45 \
  --secondary-azimuth-degrees 225 \
  --fps 30 \
  --output output/share/<tag>.mp4 \
  --title "Xuelong reconstruction - eight views"
```

Supplying `--ma-2d-dir` hides the SMPL-X mesh on frames where fewer than two
selected cameras contain useful landmark visibility. Pass the exact camera set
used by the corresponding 4-, 6-, or 8-view solve. The renderer preserves the
full timeline and filmstrip, avoiding unconstrained entrance/exit poses without
trimming the clip.

Use [`viewer.md`](viewer.md) for source-frame offsets, deliverable validation,
and interactive Rerun handoff. Keep generated footage, reconstructions, and
`.rrd` files out of git.
