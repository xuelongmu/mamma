# SJTU sports reconstruction

This runbook covers the SJTU Free Viewpoint RGB-D sports samples used for the
badminton and basketball experiments in [`status.md`](status.md). It documents
the conversion assumptions, validation gates, camera-count methodology, and
commands needed to reproduce the work without committing source footage.

## Source layout

The downloaded sample is expected to contain:

```text
<source>/
├── RGB/
│   ├── 0.mp4
│   ├── 1.mp4
│   └── ...
└── paras.txt
```

The tested samples have 12 synchronized 1920x1080 streams at 25 fps. The
badminton take has 628 frames (25.12 seconds); the basketball take has 955
frames (38.2 seconds).

Keep source archives outside the repository. Put conformed captures below the
ignored `data/` directory.

## Calibration convention

SJTU describes a camera as:

```text
Xc = R * (Xw - C)
```

`C` is the camera center in world coordinates, not a world-to-camera
translation vector. MAMMA's 3x4 world-to-camera extrinsic is therefore:

```text
[R | -R*C_metres]
```

The supplied camera centers are in rig units. For these samples, the adapter
estimates metric scale from the documented 0.46 m spacing between adjacent
cameras. The observed median separation is 7.9028077 rig units, giving:

```text
0.058207161 metres per rig unit
```

This is a dataset-specific inference. Record the scale in the generated
conformance manifest and validate projected scene points before a costly solve.

SJTU's world X axis is vertical. Use X-up and 25 fps for every Rerun export.

## Conform a sequence

The reusable adapter writes constant-frame-rate MP4s, `calibration.json`,
`capture.json`, and `conformance.json`:

```bash
micromamba run -n mamma python \
  scripts/preprocessing/sjtu/prepare_sjtu_for_mamma.py \
  /path/to/sjtu-badminton \
  data/sjtu_badminton \
  badminton_full25s \
  --camera-ids 5 0 2 3 7 8 10 11 \
  --start-seconds 0 \
  --duration 25.12 \
  --fps 25
```

The camera order is intentional: camera 05 was the strongest automatic
initialization view for the two-player badminton take.

For all 12 cameras:

```text
--camera-ids 5 0 1 2 3 4 6 7 8 9 10 11
```

The adapter reuses completed conformed videos when resuming. Each new encode is
written atomically so an interrupted ffmpeg process cannot leave a partial
final-path MP4. Pass `--overwrite` to intentionally recompute every selected
camera. Resume is rejected when the existing conformance manifest disagrees
with the source root, interval, frame rate, or camera-spacing assumption.

## Validate before MAMMA

For every selected camera, verify:

1. identical frame count and frame rate;
2. dimensions matching calibration;
3. a positive-depth projection of known world points;
4. rotation determinant near 1 and negligible orthogonality error;
5. corresponding action frames are synchronized; and
6. both people retain usable coverage in the selected views.

Example stream check:

```bash
for video in data/sjtu_badminton/badminton_full25s/videos/*.mp4; do
  ffprobe -v error -select_streams v:0 \
    -show_entries stream=width,height,r_frame_rate,nb_frames \
    -of csv=p=0 "$video"
done
```

## Run the full pipeline

Use the X-up preset added for these captures:

```bash
LD_LIBRARY_PATH=/home/xuelong/micromamba/envs/mamma/lib \
__EGL_VENDOR_LIBRARY_DIRS=/home/xuelong/micromamba/envs/mamma/share/glvnd/egl_vendor.d \
MPLBACKEND=Agg \
micromamba run -n mamma python -m inference run \
  --cfg configs/experiments/sjtu-sports-full.yaml \
  --capture data/sjtu_badminton/badminton_full25s/capture.json \
  --out-tag sjtu_badminton_full25s_8v -v
```

Run a short frame slice first when testing a new source. Do not extend to the
full clip until masks, identity matching, 2D landmarks, reprojections, body
scale, and orientation are plausible.

## Camera-count ablations

The tested badminton subsets were:

| Views | Cameras |
| ---: | --- |
| 4 | `cam_05 cam_00 cam_08 cam_11` |
| 6 | `cam_05 cam_00 cam_02 cam_07 cam_10 cam_11` |
| 8 | `cam_05 cam_00 cam_02 cam_03 cam_07 cam_08 cam_10 cam_11` |

The tested basketball plan is:

| Views | Cameras |
| ---: | --- |
| 4 | `cam_05 cam_00 cam_08 cam_11` |
| 6 | `cam_05 cam_00 cam_02 cam_07 cam_09 cam_11` |
| 12 | `cam_05 cam_00 cam_01 cam_02 cam_03 cam_04 cam_06 cam_07 cam_08 cam_09 cam_10 cam_11` |

For a camera-count ablation, run masks, identity matching, and MammaNet once on
the largest set. Reuse those artifacts and change only `--cam_names` supplied
to `run_ma_3d.py`. Otherwise, differences in segmentation or identity
initialization confound the camera-count comparison.

Use distinct 3D output tags. Never point two concurrent jobs at the same output
directory.

## Incrementally add cameras

The 12-view badminton run adds cameras `01, 04, 06, 09` to the completed
8-view baseline. Existing camera mask directories and per-camera MammaNet NPZs
can be reused only when all of the following match:

- source frames and encoding timeline;
- calibration;
- frame interval;
- subject IDs;
- mask/MammaNet configuration; and
- body numbering.

Prefer symlinks or an explicit cache manifest over copying large generated
directories. Do not create a stage-level `DONE` marker until every requested
camera has completed. Record exactly which cameras were reused in
[`status.md`](status.md).

## Assessment

Inspect both the 3D scene and camera-space evidence:

- per-camera reprojection error;
- missing-landmark ratio;
- effective uncertainty and optimizer weight;
- identity swaps or absent bodies;
- per-frame body vertical extent;
- floor contact and obvious scale collapse; and
- beginning, middle, and end of the full clip.

A camera with an isolated high residual may hurt a larger set. Report the
outlier rather than tuning it away after seeing the ablation result.

Do not compute accuracy against `gt_joints` or `gt_vertices` unless real ground
truth provenance is established. Under `use_gt=False`, those arrays can be
prediction duplicates used for visualization compatibility.

## Outputs

The primary products are:

```text
output/ma_3d/<tag>/<capture>/<sequence>/
output/ma_vis/<tag>/<capture>/<sequence>/scene.rrd
```

Use [`viewer.md`](viewer.md) for interactive serving and portable video
rendering. Keep generated outputs and source footage out of git.
