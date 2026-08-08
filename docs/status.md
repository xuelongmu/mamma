# Research status

This is the append-only research log for local reconstruction work. Add a new
dated entry after meaningful experiments, failures, decisions, or corrections.
Repository changes belong in [`../CHANGELOG.md`](../CHANGELOG.md).

Each entry should include, where applicable:

- objective and input sequence;
- camera names and frame interval;
- preset, output tag, and cache-reuse strategy;
- quantitative and visual observations;
- artifact paths and current state;
- failures or caveats; and
- the next concrete action.

Do not edit old entries to hide superseded results. Add a dated correction.

## 2026-08-08 - SJTU badminton calibration and full-clip baseline

- Conformed the 25.12-second SJTU badminton take at 25 fps using cameras
  `05, 00, 02, 03, 07, 08, 10, 11`.
- Converted camera centers from SJTU rig units using a median adjacent-camera
  scale of `0.058207161` metres per rig unit and wrote world-to-camera
  extrinsics as `[R | -R*C]`.
- Confirmed that the SJTU world coordinate system is X-up. Visualization must
  use `--up-axis x` and record `RIGHT_HAND_X_UP` at the Rerun world root.
- Output tag: `sjtu_badminton_full25s_8v`.
- MAMMA retained two identities for all 628 frames. Cross-view re-identification
  required zero label swaps.
- Median X-axis body extents were approximately 1.667 m and 1.480 m.
- Interactive artifact:
  `output/ma_vis/sjtu_badminton_full25s_8v/badminton_full25s/badminton_full25s/scene.rrd`.

## 2026-08-08 - Badminton camera-count ablation

- Reused the 8-view masks, identities, and 2D landmarks so only the cameras
  supplied to `ma_3d` changed.
- Four views: `05, 00, 08, 11`; output tag
  `sjtu_badminton_full25s_4v`.
- Six views: `05, 00, 02, 07, 10, 11`; output tag
  `sjtu_badminton_full25s_6v`.
- Eight views: `05, 00, 02, 03, 07, 08, 10, 11`.

| Views | Body 0 median X extent | Body 1 median X extent |
| ---: | ---: | ---: |
| 4 | 1.661 m | 1.345 m |
| 6 | 1.667 m | 1.452 m |
| 8 | 1.667 m | 1.480 m |

The first player remained stable. The second player collapsed in the 4-view
solve and progressively recovered with 6 and 8 views. In the 6-view solve,
camera 05 remained an isolated high-error view for the second body.

## 2026-08-08 - Share-video rendering correction

- Rendered 1920x1080, 25 fps, 628-frame videos with the reconstructed 3D scene
  above a synchronized source-camera filmstrip.
- The first white-background perspective exports were geometrically correct
  but visually inferior to Rerun: low contrast and perspective shrinkage made
  the distant player look smaller.
- Added a corrected presentation using a dark scene, saturated people,
  shadows, X-up-to-Y-up conversion, and stabilized orthographic framing.
- Preferred local artifacts are:
  `share/videos/badminton_4v_rerun_style.mp4`,
  `share/videos/badminton_6v_rerun_style.mp4`, and
  `share/videos/badminton_8v_rerun_style.mp4` in the handoff workspace. These
  generated videos are not committed.

## 2026-08-08 - Basketball and 12-view badminton pending work

- Conformed the complete 38.2-second SJTU basketball take: 12 cameras, 955
  frames, 1920x1080, 25 fps.
- Completed SAM2 masks for all 11,460 basketball camera-frames with one
  continuous identity. The 2D, 12-view 3D, 4-view 3D, and 6-view 3D stages are
  pending GPU availability.
- Conformed a true 12-camera badminton input: 628 frames per camera. The
  intended run reuses the existing eight camera masks and 2D landmarks and
  computes only cameras `01, 04, 06, 09` before the 12-view fit.
- At the last check, an unrelated `viewer_4c4d.py` process held enough GPU
  memory to prevent safe MAMMA landmark inference. Do not terminate it without
  authorization. Recheck `nvidia-smi`, then resume the queued work.

## 2026-08-08 - Handoff documentation

- Consolidating agent guidance, operational commands, viewer instructions,
  SJTU methodology, reusable preprocessing, and rendering utilities on branch
  `docs/research-handoff`.
- This is one cohesive contribution and should be proposed as one ordinary PR.
  Use a PR stack only for later sets of functionally dependent changes.
- Verified the reusable SJTU calibration parser and metric-extrinsic conversion
  with unit tests, materialized the SJTU full preset successfully, and passed
  the repository environment doctor.
- Smoke-rendered one badminton frame with four source views at 1920x1080 and
  25 fps using the repository-relative share renderer. EGL fell back to
  `kms_swrast` after the expected WSL `/dev/dri/renderD128` warning.
- Contribution policy clarification: treat the upstream repository as
  read-only. Never open issues or pull requests there; verify that any proposed
  remote contribution targets this fork.
- Repository handling policy: use the gitignored root `tmp/` directory for
  disposable local intermediates, including media. Media assets must never be
  committed or uploaded through repository hosting; external storage and
  transfer are handled outside the repository host.
