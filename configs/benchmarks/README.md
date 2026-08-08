# Performance benchmark

Use the quality benchmark for changes that may affect reconstruction speed or
accuracy. It fixes the sample, cameras, and frame interval so pull request
results remain comparable:

- SJTU `badminton_full25s`
- cameras `cam_05`, `cam_00`, `cam_08`, and `cam_11`
- frames `[0, 300)` (300 frames at 25 fps)
- the repository's quality SMPL-X optimization preset

The licensed SJTU data and model assets are not part of Git. Install them
under the documented `data/` paths, then run from a clean worktree:

```bash
python -m inference run \
  --cfg configs/benchmarks/presets/quality_4v_300.yaml \
  --capture configs/benchmarks/captures/sjtu_badminton_4views.json \
  --out-tag issue-N-baseline \
  --log-tag issue-N-baseline \
  -v
```

For a solver-only A/B test, run the unchanged baseline once and reuse its
`ma_cap`, `ma_masks`, and `ma_2d` outputs for the candidate `ma_3d` run. Report
wall time, final reprojection error, MPJPE/PVE from `verts_joints_body_id-00.npz`,
and a reconstruction preview in the pull request. Keep generated outputs and
model files out of Git.
