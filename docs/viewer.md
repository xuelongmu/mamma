# Rerun viewer and share-video guide

MAMMA's `ma_vis` stage writes an interactive `scene.rrd`. The recording embeds
the reconstructed meshes, camera rig, camera frames, projected landmarks,
ground, and timeline. A recipient needs a compatible Rerun viewer but does not
need MAMMA, a GPU, or licensed SMPL-X model files merely to inspect the scene.

The local scenes in this research log were verified with:

```text
rerun-sdk==0.23.1
```

## Open a recording in the browser

From the repository root, assign one port to Rerun's recording server and a
different port to its HTTP web viewer:

```bash
micromamba run -n mamma rerun \
  output/ma_vis/<tag>/<capture>/<sequence>/scene.rrd \
  --web-viewer \
  --bind 0.0.0.0 \
  --port 9880 \
  --web-viewer-port 9098
```

Open the complete URL:

```text
http://localhost:9098/?url=rerun%2Bhttp%3A%2F%2Flocalhost%3A9880%2Fproxy
```

The query decodes to `rerun+http://localhost:9880/proxy`. It connects the web
viewer to the recording server. Opening only `http://localhost:9098/` shows the
generic Rerun homepage and examples; it does not select the recording.

When a browser or chat application renders the URL as a link, preserve the
entire `?url=...` query:

```markdown
[Open the reconstruction](http://localhost:9098/?url=rerun%2Bhttp%3A%2F%2Flocalhost%3A9880%2Fproxy)
```

The server process must remain alive while the scene is open.

## Serve multiple scenes

Every process needs a unique gRPC/recording port and HTTP port. For example:

| Scene | Recording port | HTTP port | URL |
| --- | ---: | ---: | --- |
| baseline | 9880 | 9098 | `http://localhost:9098/?url=rerun%2Bhttp%3A%2F%2Flocalhost%3A9880%2Fproxy` |
| four views | 9882 | 9100 | `http://localhost:9100/?url=rerun%2Bhttp%3A%2F%2Flocalhost%3A9882%2Fproxy` |
| six views | 9884 | 9102 | `http://localhost:9102/?url=rerun%2Bhttp%3A%2F%2Flocalhost%3A9884%2Fproxy` |

Before replacing a server, inspect the exact process command. Do not kill a
port owner merely because its purpose is unclear.

## Headless environment

Set the EGL and matplotlib environment for visualization commands under WSL:

```bash
export LD_LIBRARY_PATH=/home/xuelong/micromamba/envs/mamma/lib
export __EGL_VENDOR_LIBRARY_DIRS=/home/xuelong/micromamba/envs/mamma/share/glvnd/egl_vendor.d
export MPLBACKEND=Agg
```

`Invalid device ID (0)` generally means the EGL vendor directory is missing.
A warning about `/dev/dri/renderD128`, followed by `kms_swrast`, is acceptable
when the render continues.

## World orientation

Rerun defaults are not a substitute for dataset coordinate metadata. Pass the
correct visualizer option and log the matching `ViewCoordinates` archetype at
the `world` root:

| Dataset world | CLI | Rerun coordinates |
| --- | --- | --- |
| X-up | `--up-axis x` | `RIGHT_HAND_X_UP` |
| Y-up | `--up-axis y` | `RIGHT_HAND_Y_UP` |
| Z-up | `--up-axis z` | `RIGHT_HAND_Z_UP` |

SJTU sports footage is X-up. Verify that people stand upright and that the
ground is horizontal before sharing either the `.rrd` or a rendered video.

## Interactive scene versus share video

Use `.rrd` for inspection and debugging. It keeps the camera rig, timeline,
individual streams, landmarks, and selectable meshes interactive.

Use `scripts/render_share_video.py` for a portable MP4. It produces a stabilized
3D reconstruction in the main panel and synchronized camera views in a bottom
filmstrip. Example:

```bash
PYOPENGL_PLATFORM=egl \
LD_LIBRARY_PATH=/home/xuelong/micromamba/envs/mamma/lib \
__EGL_VENDOR_LIBRARY_DIRS=/home/xuelong/micromamba/envs/mamma/share/glvnd/egl_vendor.d \
micromamba run -n mamma python scripts/render_share_video.py \
  --ma-3d-dir output/ma_3d/<tag>/<capture>/<sequence> \
  --videos-dir data/<capture>/<sequence>/videos \
  --cams cam_05 cam_00 cam_02 cam_03 cam_07 cam_08 cam_10 cam_11 \
  --output output/share/<tag>.mp4 \
  --title "Badminton reconstruction - 8 views"
```

The share renderer converts SJTU X-up vertices to a conventional Y-up display
space. Do not apply a second rotation to already-converted vertices.

Validate a deliverable before sharing:

```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,avg_frame_rate,nb_frames \
  -show_entries format=duration \
  -of default=noprint_wrappers=1 output/share/<tag>.mp4
```

Inspect frames near the beginning, middle, and end. A successful encode does
not prove that framing, orientation, identity, or source-camera timing is good.

## Sharing and licensing

- `.rrd` files embed dataset-derived camera frames. Confirm the dataset's
  redistribution terms before external sharing.
- Raw SMPL-X parameter files do not include the body model, but regenerating
  vertices requires separately licensed compatible assets.
- Never bundle `SMPLX_MALE.npz`, `SMPLX_FEMALE.npz`, `SMPLX_NEUTRAL.npz`,
  credentials, or model weights unless the relevant license explicitly allows
  the distribution.
