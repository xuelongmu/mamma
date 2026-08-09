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
- Before resuming, recheck GPU availability with `nvidia-smi`. Do not terminate
  unrelated processes without authorization.

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

## 2026-08-08 - MammaEval 4/6/8-view quantitative check

- Evaluated `230929_WhiteRabbit_CatchBall_50048_1`, source frames 60-89, with
  the same calibration, locked-head SMPL-X model, 16-beta configuration, and
  `configs/examples/presets/quick.yaml` optimization settings.
- Four views: `IOI_01, IOI_05, IOI_09, IOI_13`; output tag `ablate_4v`.
- Six views: `IOI_01, IOI_03, IOI_05, IOI_09, IOI_11, IOI_13`; output tag
  `ablate_6v`.
- Eight views: `IOI_01, IOI_03, IOI_05, IOI_07, IOI_09, IOI_11, IOI_13,
  IOI_15`; output tag `ablate_8v`.

| Views | PVE | MPJPE (127) | MPJPE (body 22) | Hand-region PVE | PA-PVE |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 15.015 mm | 15.433 mm | 16.181 mm | 12.539 mm | 11.980 mm |
| 6 | 14.858 mm | 15.372 mm | 15.712 mm | 12.514 mm | 11.883 mm |
| 8 | 15.938 mm | 18.051 mm | 15.434 mm | 16.068 mm | 12.234 mm |

- Six views were the best balanced result. Four views were effectively tied
  for this short single-person interval. Eight views slightly improved the 22
  principal body joints but degraded hands, auxiliary joints, and total
  surface accuracy.
- The eight-view regression was consistent with camera diagnostics: `IOI_07`
  had a 22.72% missing-landmark ratio and 24.08 px effective uncertainty, while
  `IOI_15` had 22.72 px effective uncertainty. The six-view set had no missing
  landmarks in this interval.
- The optimization ran with `use_gt=False`, so its saved `gt_*` arrays were
  prediction duplicates. Metrics above were computed separately by
  regenerating frames 60-89 from the original MammaEval `gt/global.npz` with
  the matching subject template, model variant, beta count, and world frame.
  They are local measurements, not an official evaluator export.
- Primary local artifacts remain under
  `output/ma_3d/ablate_{4,6,8}v/` and
  `output/ma_vis/ablate_{4,6,8}v/`; generated media and `.rrd` files are not
  committed.
- Next action for a stronger conclusion: repeat the comparison on longer,
  higher-motion and multi-person intervals while holding masks, identities,
  and 2D landmarks fixed.

## 2026-08-08 - Correction to MammaEval camera-count interpretation

- The `ablate_4v`, `ablate_6v`, and `ablate_8v` runs used separate pipeline
  tags, so masks, identity assignment, and 2D landmarks were recomputed rather
  than reused from the largest camera set.
- The table above is therefore an uncontrolled exploratory comparison, not an
  isolated 3D camera-count ablation. Do not attribute the differences solely
  to view count.
- A controlled rerun must reuse the same compatible upstream evidence and vary
  only the cameras supplied to the 3D fit.

## 2026-08-08 - Badminton baseline next action correction

- The next action for the completed eight-view badminton baseline is to inspect
  reprojections at the beginning, middle, and end, then reuse its compatible
  masks and 2D landmarks for the pending 12-view fit and any controlled
  camera-count comparison.

## 2026-08-08 - Share-video next action correction

- Validate synchronization and framing at the beginning, middle, and end of
  every 4-, 6-, and 8-view share video, then prepare the approved files for
  external handoff without committing or uploading the generated media through
  repository hosting.

## 2026-08-08 - Badminton ablation handoff correction

- Inspect the 4-, 6-, and 8-view reconstruction results under
  `output/ma_3d/sjtu_badminton_full25s_{4,6,8}v/` and their interactive scenes
  under `output/ma_vis/sjtu_badminton_full25s_{4,6,8}v/`. These local generated
  artifacts are not committed.
- Next action: inspect beginning, middle, and end reprojections for both bodies,
  quantify per-camera residuals with particular attention to body 1 and camera
  05 in the 6-view solve, then compare those diagnostics with the pending true
  12-view reconstruction.

## 2026-08-08 - Basketball artifact-location correction

- The conformed basketball capture uses session tag `basketball_full38s` and is
  rooted at `data/sjtu_basketball/basketball_full38s/`; its descriptor is
  `data/sjtu_basketball/basketball_full38s/capture.json` and its 12 synchronized
  camera streams are under the sibling `videos/` directory.
- The completed SAM2 stage uses output tag `sjtu_basketball_full38s_12v`; masks,
  reports, and per-camera visualizations are rooted at
  `output/ma_masks/sjtu_basketball_full38s_12v/basketball_full38s/basketball_full38s/`.
  These generated local artifacts are not committed.

## 2026-08-08 - Share-renderer smoke-test handoff correction

- The one-frame renderer smoke test used badminton cameras `cam_05`, `cam_00`,
  `cam_08`, and `cam_11` at local mesh and source frame 0.
- Its ephemeral local artifact is `/tmp/mamma_share_renderer_smoke.mp4` on the
  handoff WSL instance: one 1920x1080 frame encoded at 25 fps. It is not
  committed or uploaded.
- Next action: rerun this frame-0 check into the repository's gitignored `tmp/`
  directory after renderer changes, add middle/end frame checks for framing and
  synchronization, and only then render a full share video.

## 2026-08-09 - Source pixel-space contract and distortion A/B

- Evaluated whether lens metadata alone justifies undistorting delivered RGB
  before detection. It does not: calibration coefficients describe the lens
  model, while an exporter may already have rectified the video. The pipeline
  now requires an independent `source_pixel_space` declaration and keeps the
  pinhole-only optimizer behind a canonical-geometry guard.
- MammaEval input: `230929_WhiteRabbit_CatchBall_50048_1`, frames 60-89,
  cameras `IOI_01, IOI_05, IOI_09, IOI_13`. Both arms ran SAM2, MammaNet, and
  the same optimizer settings. Preserving the declared pinhole footage beat a
  forced second remap: PVE 15.015 vs 15.616 mm, MPJPE 15.433 vs 16.164 mm, and
  observed epipolar median 1.823 vs 2.322 px. The forced remap increased outer
  radial reprojection error from 4.729 to 7.080 px. This capture is therefore
  declared `pinhole_undistorted`.
- Depthkit inputs: recordings
  `DELL_001_001_02_Xuelong_04_10_16_38_34` and
  `DELL_001_001_06_Xuelong_04_10_18_05_51`, frames 300-329, using corrected
  color-to-depth extrinsics. Nested camera sets were `cam_01`-`cam_04` (4),
  plus `cam_06, cam_08` (6), plus `cam_09, cam_10` (8). The remap arm reran
  masks and landmarks; both arms completed all 12 two-stage 3D fits.
- Depthkit did not show a repeatable improvement. Recording two was nearly
  unchanged: 8-view epipolar medians were 129.304 px preserved and 129.873 px
  remapped. Recording one degraded at 6/8 views after several remapped-view
  detections diverged; its 8-view triangulation median rose from 125.188 to
  177.622 px. The very large residuals in both arms show that calibration/pose
  convention and cross-view detection quality dominate any lens correction.
  Depthkit has no external 3D ground truth here, so saved duplicate `gt_*`
  arrays were not used as evaluation targets.
- Disposable artifacts and complete JSON metrics are under
  `tmp/issue3-expanded/` and `tmp/issue3-depthkit/`; they remain ignored and
  are not uploaded. Validation passed 105 focused tests, 33 smoke checks with
  zero failures, compile-all, CLI help checks, and the real-data runs above.
- Decision: do not let the Depthkit adapter guess `raw_distorted`; leave its
  source space unknown until a reprojection gate and exporter provenance
  establish it. Next, fix the dominant Depthkit calibration/detection issue,
  then repeat the same distortion A/B with external 3D ground truth or a
  calibrated target before changing that declaration.
