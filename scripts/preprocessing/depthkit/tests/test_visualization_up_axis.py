from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from visualization.cli import _build_parser
from visualization.pipeline import _UP_AXIS_MAP
from visualization.rerun_log import compute_floor_height


class NegativeUpAxisTests(unittest.TestCase):
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
