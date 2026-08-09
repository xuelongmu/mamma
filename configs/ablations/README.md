# MammaEval view-count smoke test

These captures use frames 60–89 of
`230929_WhiteRabbit_CatchBall_50048_1` from MammaEval-Singles. The camera
sets are nested so results can be compared without changing the common views:

- 4 views: `IOI_01 IOI_05 IOI_09 IOI_13`
- 6 views: add `IOI_03 IOI_11`
- 8 views: add `IOI_07 IOI_15`

Run all three from the repository checkout. The helper enters the `mamma`
environment for each invocation:

```bash
bash scripts/run_view_ablation.sh
```

The included `quick_2d.yaml` stops after MammaNet inference. It validates
capture loading, SAM 2 masks, and the released MammaNet checkpoint without
requiring the separately gated SMPL-X locked-head model. A meaningful
view-count accuracy ablation requires enabling `ma_3d` after installing that
model; the released repository currently marks its quantitative benchmark
evaluator as forthcoming.
