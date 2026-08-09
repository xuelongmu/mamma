# Depthkit / Scatter preprocessing

`prepare_depthkit_for_mamma.py` converts a calibrated multi-camera
Depthkit/Scatter project into MAMMA's OpenCV calibration JSON, capture
descriptor, and footage layout.

The converter reads the calibration profile selected by each RGB stream. It
converts Depthkit's left-handed camera-to-world Rodrigues pose to a proper,
right-handed MAMMA world-to-camera OpenCV transform, and records all
assumptions in `conversion_manifest.json`.

Scatter projects from this capture stack store color-profile extrinsics as
depth-to-color. That is the default; use
`--color-extrinsics-direction color-to-depth` for an exporter that uses the
opposite convention. The Xuelong conversion was independently validated with
RGB feature matches; always inspect epipolar and multi-view reprojection error
after conversion rather than relying on camera look-at direction alone.

Validate every recording whose RGB assets are present:

```bash
micromamba run -n mamma python scripts/preprocessing/depthkit/prepare_depthkit_for_mamma.py \
  /path/to/depthkit-project --validate-only
```

Prepare them under MAMMA's ignored `data/` directory:

```bash
micromamba run -n mamma python scripts/preprocessing/depthkit/prepare_depthkit_for_mamma.py \
  /path/to/depthkit-project data/my_depthkit_capture
```

`--video-mode auto` (the default) symlinks only footage whose ffprobe metadata
reports H.264/yuv420p with matching nominal and average integral frame rates
when no rotation is needed. It re-encodes all other sources. Use `copy` for a
self-contained dataset or `reencode` to force H.264/yuv420p
constant-frame-rate output. Fractional source rates are conformed to the
nearest integer; an explicit `--fps` must be a positive integer. Visualization
inherits the generated capture rate when its preset does not override it.
`--rotate ccw`, `cw`, or `180`
rotates every frame and transforms intrinsics, tangential distortion,
resolution, and extrinsics so projection geometry remains unchanged. The
capture metadata is hardware-synchronized; MAMMA still truncates each sequence
to its shortest camera stream. The adapter rejects any stream that reports
dropped capture frames because truncation cannot repair a mid-stream timeline
shift. It also rejects every nonzero distortion coefficient outside
k1/k2/p1/p2/k3 support.

Use `--recordings <name> [<name> ...]` to select takes. When changing only a
calibration-convention option after videos have already been prepared, pass
`--calibration-only --overwrite` to validate and reuse the destination videos
without re-encoding them. The requested image rotation must match the existing
conversion manifest, as must the source project, calibration hash, recordings,
cameras, source paths, device IDs, and video fingerprints.

Run a quick end-to-end solve:

```bash
MPLBACKEND=Agg \
micromamba run -n mamma python -m inference run \
  --cfg configs/experiments/depthkit-quick-first4.yaml \
  --capture data/my_depthkit_capture/capture.json \
  --out-tag my_depthkit_first4 -v
```

The quick presets sample frames 300-329. Matching full presets process every
available frame:

| Views | Quick preset | Full preset |
| ---: | --- | --- |
| 4 | `depthkit-quick-first4.yaml` | `depthkit-full-first4.yaml` |
| 6 | `depthkit-quick-6view.yaml` | `depthkit-full-6view.yaml` |
| 8 | `depthkit-quick-8view.yaml` | `depthkit-full-8view.yaml` |

The six-view set adds `cam_06` and `cam_08` to the validated first four.
The eight-view set then adds `cam_09` and `cam_10`. See the runbook for the
rig-coverage rationale and controlled-ablation caveat.

Tests:

```bash
micromamba run -n mamma python -m unittest discover \
  -s scripts/preprocessing/depthkit/tests -v
```

See [`docs/depthkit.md`](../../../docs/depthkit.md) for the full calibration
derivation, validation evidence, tested runs, and dual-perspective share-video
command.
