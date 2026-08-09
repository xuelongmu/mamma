from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from inference.config import materialize_run_config
from inference.steps.ma_masks import MaMasksBuilder
from inference.steps.ma_vis import MaVisBuilder
from visualization.cli import _build_parser
from visualization.pipeline import _UP_AXIS_MAP
from visualization.rerun_log import compute_floor_height


class NegativeUpAxisTests(unittest.TestCase):
    def test_builder_derives_fps_from_materialized_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preset = root / "preset.json"
            capture = root / "capture.json"
            preset.write_text(
                json.dumps(
                    {
                        "global": {"out_dir": "output"},
                        "ma_masks": {
                            "script": "run_ma_masks.py",
                            "flags": [],
                        },
                        "ma_vis": {
                            "script": "run_ma_vis.py",
                            "flags": ["--rerun-light"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            capture.write_text(
                json.dumps(
                    {
                        "cam_fps": 25.0,
                        "cams": ["cam_01"],
                        "sequences": {"000": {"name": "take"}},
                    }
                ),
                encoding="utf-8",
            )
            config = materialize_run_config(str(preset), str(capture))
            builder = MaVisBuilder(config["ma_vis"], config["global"], "tag")
            arguments = builder.python_argv("take")
            with mock.patch.dict(
                os.environ,
                {"MAMMA_YOLO_CHECKPOINT": "weights.pt"},
                clear=False,
            ):
                mask_arguments = MaMasksBuilder(
                    config["ma_masks"], config["global"], "tag"
                ).python_argv("take")
        fps_index = arguments.index("--fps")
        self.assertEqual(arguments[fps_index + 1], "25")
        preview_fps_index = mask_arguments.index("--preview_fps")
        self.assertEqual(mask_arguments[preview_fps_index + 1], "25")

    def test_pipeline_maps_negative_y_to_signed_axis(self):
        self.assertEqual(_UP_AXIS_MAP["-y"], (1, -1))
        self.assertEqual(_UP_AXIS_MAP["y-down"], (1, -1))

    def test_spaced_y_down_cli_alias_is_unambiguous(self):
        arguments = _build_parser().parse_args(
            [
                "--seq-name",
                "take",
                "--ma-3d-dir",
                "ma_3d",
                "--out-path",
                "output",
                "--up-axis",
                "y-down",
            ]
        )
        self.assertEqual(arguments.up_axis, "y-down")

    def test_y_down_floor_uses_robust_maximum_y_coordinate(self):
        vertices = np.asarray(
            [
                [[0.0, -1.0, 0.0], [0.0, 1.0, 0.0]],
                [[0.0, -0.8, 0.0], [0.0, 1.2, 0.0]],
            ]
        )
        motion = SimpleNamespace(vertices=vertices)
        floor = compute_floor_height(
            [motion],
            up_axis=1,
            up_sign=-1,
            percentile=0.0,
        )
        self.assertEqual(floor, 1.2)

    def test_floor_rejects_invalid_axis_sign(self):
        with self.assertRaisesRegex(ValueError, "up_sign"):
            compute_floor_height([], up_axis=1, up_sign=0)


if __name__ == "__main__":
    unittest.main()
