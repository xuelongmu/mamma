from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

SCRIPT = Path(__file__).parents[3] / "render_share_video.py"
SPEC = importlib.util.spec_from_file_location("render_share_video", SCRIPT)
renderer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = renderer
SPEC.loader.exec_module(renderer)


class WorldAxisTests(unittest.TestCase):
    def test_supported_world_axes_become_right_handed_y_up(self):
        world_up_vectors = {
            "x": [1.0, 0.0, 0.0],
            "y": [0.0, 1.0, 0.0],
            "-y": [0.0, -1.0, 0.0],
            "z": [0.0, 0.0, 1.0],
            "-z": [0.0, 0.0, -1.0],
        }
        for axis, world_up in world_up_vectors.items():
            with self.subTest(axis=axis):
                basis = renderer.world_to_display(np.eye(3), axis)
                converted_up = renderer.world_to_display(np.asarray(world_up), axis)
                np.testing.assert_allclose(converted_up, [0.0, 1.0, 0.0])
                self.assertAlmostEqual(float(np.linalg.det(basis)), 1.0)


class VisibilityTests(unittest.TestCase):
    def test_mesh_gate_requires_two_visible_selected_cameras(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values = {
                "cam_01": [1.0, 1.0, 0.0],
                "cam_02": [1.0, 0.0, 0.0],
                "cam_03": [0.0, 0.0, 1.0],
                "cam_04": [0.0, 0.0, 1.0],
            }
            for camera, visibility in values.items():
                np.savez(
                    root / f"{camera}.npz",
                    visibilities=np.asarray(visibility)[:, None],
                )
            active = renderer.landmark_active_frames(
                root,
                list(values),
                frame_count=3,
                min_visible_cameras=2,
                mean_visibility_threshold=0.05,
            )
            np.testing.assert_array_equal(active, [True, False, True])

    def test_mesh_gate_rejects_short_landmark_timeline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            np.savez(root / "cam_01.npz", visibilities=np.ones((1, 2)))
            with self.assertRaisesRegex(ValueError, "reconstruction has 2"):
                renderer.landmark_active_frames(
                    root,
                    ["cam_01"],
                    frame_count=2,
                    min_visible_cameras=1,
                    mean_visibility_threshold=0.05,
                )


if __name__ == "__main__":
    unittest.main()
