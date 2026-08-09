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
  /path/to/depthkit-project /tmp/unused --validate-only
```

Prepare them under MAMMA's ignored `data/` directory:

```bash
micromamba run -n mamma python scripts/preprocessing/depthkit/prepare_depthkit_for_mamma.py \
  /path/to/depthkit-project data/my_depthkit_capture
```

`--video-mode auto` (the default) symlinks same-rate footage when no rotation
is needed and re-encodes when its frame rate differs or `--rotate` is
requested. Use `copy` for a self-contained dataset or `reencode` to force
H.264/yuv420p constant-frame-rate output. `--rotate ccw`, `cw`, or `180`
rotates every frame and transforms intrinsics, tangential distortion,
resolution, and extrinsics so projection geometry remains unchanged. The
capture metadata is hardware-synchronized; MAMMA still truncates each sequence
to its shortest camera stream.

When changing only a calibration-convention option after videos have already
been prepared, pass `--calibration-only --overwrite` to validate and reuse the
destination videos without re-encoding them.

Run a quick end-to-end solve:

```bash
LD_LIBRARY_PATH=/home/xuelong/micromamba/envs/mamma/lib \
__EGL_VENDOR_LIBRARY_DIRS=/home/xuelong/micromamba/envs/mamma/share/glvnd/egl_vendor.d \
MPLBACKEND=Agg \
micromamba run -n mamma python -m inference run \
  --cfg configs/experiments/depthkit-quick-first4.yaml \
  --capture data/my_depthkit_capture/capture.json \
  --out-tag my_depthkit_first4 -v
```

The quick preset samples frames 300-329 and uses `cam_01` through `cam_04`.
`configs/experiments/depthkit-full-first4.yaml` processes the same camera set
for every available frame.

Tests:

```bash
micromamba run -n mamma python -m unittest discover \
  -s scripts/preprocessing/depthkit/tests -v
```

See [`docs/depthkit.md`](../../../docs/depthkit.md) for the full calibration
derivation, validation evidence, tested runs, and dual-perspective share-video
command.
