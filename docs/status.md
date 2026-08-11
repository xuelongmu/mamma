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

## 2026-08-10 - Controlled raw-distortion and Panoptic validation

- Added a controlled forward-distortion check using the same WhiteRabbit
  frames 60-89 and cameras `IOI_01, IOI_05, IOI_09, IOI_13`. Canonical source
  frames were forward-warped with matching Vicon radial-2 calibration, then
  processed as (1) canonical baseline, (2) raw pixels falsely declared
  pinhole, and (3) raw pixels correctly declared `raw_distorted`. All arms ran
  SAM2, MammaNet, and the same two-stage optimizer.
- The native-coefficient fixture displaced pixels by up to 41 px, but the
  centered subject made aggregate fit error sensitive to optimizer variance.
  A calibrated 3x stress fixture therefore repeated the same test with
  byte-identical canonical frames, 38-74 px p90 displacement by camera, and a
  49.8-55.3 dB corrected round trip. This was a stress test of the geometry
  contract, not a claim about the released camera's physical coefficients.
- On the 3x fixture, declaring raw pixels correctly reduced native epipolar
  median from 3.982 to 2.748 px and outer-region median from 19.773 to 3.554
  px. The corrected fit remained 1.531 mm PVE from the canonical-baseline fit,
  versus 5.634 mm for raw-as-pinhole. Against external MammaEval ground truth,
  root-aligned PVE improved from 18.421 to 17.201 mm and root-aligned MPJPE
  from 18.043 to 17.127 mm; the canonical baseline was 17.169/17.104 mm.
  Unaligned PVE favored the wrong arm because its global shift happened to
  cancel part of the baseline offset, so it is not used as the deciding metric.
- Independently tested CMU Panoptic `171204_pose1_sample`, frames 35-64, using
  official OpenCV Brown coefficients, synchronized HD RGB, and released
  COCO-19 3D joints. Calibration conversion was visually verified and inverted
  raw projections recovered canonical projections within 0.0013 px. The valid
  four-view set had 2.3-18.2 px p90 on-subject lens displacement.
- On that Panoptic set, pre-detection correction reduced native epipolar median
  from 2.842 to 2.666 px. Direct COCO body-15 MPJPE improved from 40.47 to
  38.75 mm, root-aligned MPJPE from 41.43 to 38.54 mm, and centroid-aligned
  MPJPE from 40.22 to 37.41 mm. Triangulation median changed from 1.329 to
  1.347 px and PA-MPJPE from 30.32 to 32.04 mm, so the real-data improvement is
  modest rather than universal.
- A second, more off-axis Panoptic camera set increased on-subject p90
  displacement to 9.9-18.2 px and cut outer-region epipolar median from 16.12
  to 7.91 px. Its final fits are excluded from accuracy claims: single-subject
  cross-view re-ID rejected two valid cameras and re-triangulated from only two
  views, producing approximately 240 mm centroid-aligned errors in both arms.
  This is a separate association failure, not evidence for or against lens
  correction.
- Conclusion: the core hypothesis is true for RGB that is actually raw
  distorted. Canonicalizing before segmentation and landmark detection repairs
  the pinhole geometry and can improve 3D accuracy. It must remain conditional
  on explicit `source_pixel_space`; already-rectified WhiteRabbit footage must
  not be remapped, and unknown Depthkit footage must fail safely rather than be
  guessed. Complete datasets, generated outputs, overlays, evaluators, and JSON
  metrics remain under ignored `tmp/core-hypothesis/`.
## 2026-08-08 - Depthkit Xuelong calibration and four-view reconstruction

- Converted the 10-camera Xuelong `dkproject.json` using the validated Scatter
  convention: conjugate the stored depth-camera-to-world pose with
  `H = diag(1, 1, -1, 1)`, then compose the inverse of the stored
  depth-to-color extrinsic before producing OpenCV world-to-camera matrices.
- The initial calibration interpretation produced roughly 85 px median
  multi-view disagreement across the first four cameras. Matched RGB evidence
  fell to 4.29 px median after the handedness and color-extrinsic correction.
- The first-four-camera full runs completed 827 frames for recording `..._02_...`
  and 1,203 frames for `..._06_...`; saved SMPL-X vertices and joints were
  finite. The corresponding 30-frame validation errors were `22, 7, 11, 15 px`
  and `10, 5, 6, 14 px` by camera.
- The 10-view aggregate calibration check was usable but less uniform: median
  camera disagreements were approximately `6.40, 4.14, 4.41, 6.41, 6.07,
  6.56, 9.86, 6.29, 4.66, 7.02 px`. Camera 07 was the clearest outlier, so the
  tested full baseline remains cameras 01-04 rather than treating all views as
  equally informative.
- The current MAMMA optimization path does not consume the retained OpenCV
  distortion coefficients. A stronger follow-up is to undistort the RGB
  footage and update intrinsics before repeating controlled camera-count
  comparisons.
- Source footage, conformed captures, reconstructions, and rendered media
  remain local generated artifacts and are not committed.

## 2026-08-08 - Depthkit nested 6/8-view extension

- Added nested six-view cameras `01, 02, 03, 04, 06, 08` and eight-view
  cameras `01, 02, 03, 04, 06, 08, 09, 10`.
- The additions fill missing horizontal rig azimuths with wide-baseline cameras.
  Camera 07 remains excluded because its 9.86 px calibration disagreement was
  the clearest 10-camera outlier; camera 05 remains outside the baseline because
  it is a closer, elevated view that does not expand horizontal coverage.
- Added quick and full presets for both camera counts. These configurations are
  materialized and validated but the six- and eight-view full reconstructions
  have not yet completed, so no comparative result is claimed.
- Standalone runs recompute upstream evidence. A controlled 4/6/8-view ablation
  must reuse compatible masks, identities, and 2D landmarks from the largest
  set and vary only the cameras used by the 3D optimizer.

## 2026-08-08 - Depthkit artifact-provenance correction

- The validated four-view full output tag is
  `xuelong_upright_4v_full_validated` for capture
  `depthkit_xuelong_10v_upright`.
- Its generated 3D artifacts are rooted at
  `output/ma_3d/xuelong_upright_4v_full_validated/depthkit_xuelong_10v_upright/`.
  The 827-frame and 1,203-frame results are in the
  `DELL_001_001_02_Xuelong_04_10_16_38_34/` and
  `DELL_001_001_06_Xuelong_04_10_18_05_51/` children, respectively.
- Matching 2D evidence is rooted at
  `output/ma_2d/xuelong_upright_4v_full_validated/depthkit_xuelong_10v_upright/`.
  These paths are generated local artifacts and remain uncommitted.

## 2026-08-09 - Depthkit 6/8-view validation-provenance correction

- The materialization-only validation used
  `data/depthkit_xuelong_10v_upright/capture.json` with
  `configs/experiments/depthkit-quick-6view.yaml`,
  `configs/experiments/depthkit-full-6view.yaml`,
  `configs/experiments/depthkit-quick-8view.yaml`, and
  `configs/experiments/depthkit-full-8view.yaml`.
- The six-view camera set was `cam_01, cam_02, cam_03, cam_04, cam_06, cam_08`;
  the eight-view set added `cam_09, cam_10`. Both capture recordings were bound
  by the materializer.
- This validation parsed, materialized, and schema-checked the presets only. It
  did not dispatch pipeline stages, assign output tags, or produce artifacts,
  so there are no 6/8-view artifact paths or reconstruction results to report.
- Next action: run the eight-view upstream evidence once under a new output tag,
  then reuse compatible masks, identities, and 2D landmarks for nested 6/4-view
  `ma_3d` runs with distinct tags. Record per-camera failures and artifact paths
  before comparing reconstruction quality.

## 2026-08-09 - Depthkit four-view next-action correction

- Preserve `xuelong_upright_4v_full_validated` and its generated 2D/3D
  artifacts as the distorted-RGB four-view reference; do not rerun or overwrite
  that tag.
- Next action: prepare a new capture with rectified RGB footage and matching
  intrinsics, run eight-view upstream evidence under a new tag, and reuse that
  evidence for nested six- and four-view `ma_3d` tags. Compare those controlled
  results with the preserved reference and record new artifact paths and
  per-camera reprojection failures in a dated entry.
