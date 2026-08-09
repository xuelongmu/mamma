from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

SCRIPT = Path(__file__).parents[1] / "prepare_depthkit_for_mamma.py"
SPEC = importlib.util.spec_from_file_location("prepare_depthkit_for_mamma", SCRIPT)
converter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = converter
SPEC.loader.exec_module(converter)


class PoseTests(unittest.TestCase):
    def test_world_pose_is_conjugated_for_handedness(self):
        pose = {"rotation": [0, 0, 0], "translation": [1, 2, 3]}
        extrinsics = {"rotation": [0, 0, 0], "translation": [0, 0, 0]}
        result = converter.color_camera_to_world(pose, extrinsics)
        np.testing.assert_allclose(
            result,
            converter.SCATTER_HANDEDNESS
            @ converter.pose_matrix(pose)
            @ converter.SCATTER_HANDEDNESS,
        )
        self.assertAlmostEqual(np.linalg.det(result[:3, :3]), 1.0)

    def test_depth_to_color_offset_is_inverted_for_color_pose(self):
        pose = {"rotation": [0, 0, 0], "translation": [0, 0, 0]}
        extrinsics = {"rotation": [0, 0, 0], "translation": [-0.03, 0, 0]}
        result = converter.color_camera_to_world(
            pose, extrinsics, direction="depth-to-color"
        )
        np.testing.assert_allclose(result[:3, 3], [0.03, 0, 0], atol=1e-12)

    def test_color_to_depth_offset_is_used_for_color_pose(self):
        pose = {"rotation": [0, 0, 0], "translation": [0, 0, 0]}
        extrinsics = {"rotation": [0, 0, 0], "translation": [-0.03, 0, 0]}
        result = converter.color_camera_to_world(
            pose, extrinsics, direction="color-to-depth"
        )
        np.testing.assert_allclose(result[:3, 3], [-0.03, 0, 0], atol=1e-12)

    def test_nonfinite_pose_is_rejected(self):
        pose = {"rotation": [0, 0, 0], "translation": [0, np.inf, 0]}
        with self.assertRaises(converter.ConversionError):
            converter.pose_matrix(pose)


class CalibrationTests(unittest.TestCase):
    def test_depthkit_coefficients_are_reordered_for_opencv(self):
        intrinsics = {
            "distortionRadial": [1, 2, 3, 0, 0, 0],
            "distortionTangential": [4, 5],
        }
        self.assertEqual(converter.distortion_coefficients(intrinsics), [1, 2, 4, 5, 3])

    def test_nonzero_rational_tail_is_rejected(self):
        intrinsics = {
            "distortionRadial": [1, 2, 3, 4, 0, 0],
            "distortionTangential": [0, 0],
        }
        with self.assertRaises(converter.ConversionError):
            converter.distortion_coefficients(intrinsics)

    def test_ccw_rotation_transforms_pixels_and_camera_model_consistently(self):
        calibration = {
            "intrinsic_matrix": [[1000, 0, 1200], [0, 900, 700], [0, 0, 1]],
            "distortions": [0.1, -0.2, 0.003, -0.004, 0.05],
            "extrinsics_matrix": [[1, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3]],
            "image_size": [2560, 1440],
        }
        rotated = converter.rotate_opencv_camera(calibration, "ccw")
        self.assertEqual(rotated["image_size"], [1440, 2560])
        np.testing.assert_allclose(
            rotated["intrinsic_matrix"],
            [[900, 0, 700], [0, 1000, 1359], [0, 0, 1]],
        )
        self.assertEqual(rotated["distortions"], [0.1, -0.2, 0.004, 0.003, 0.05])
        point = np.array([0.2, -0.1, 2.0, 1.0])
        original_projection = np.asarray(calibration["intrinsic_matrix"]) @ (
            np.asarray(calibration["extrinsics_matrix"]) @ point
        )
        original_pixel = original_projection[:2] / original_projection[2]
        rotated_projection = np.asarray(rotated["intrinsic_matrix"]) @ (
            np.asarray(rotated["extrinsics_matrix"]) @ point
        )
        rotated_pixel = rotated_projection[:2] / rotated_projection[2]
        np.testing.assert_allclose(
            rotated_pixel, [original_pixel[1], 2559 - original_pixel[0]]
        )

    def test_discovers_nested_project(self):
        with tempfile.TemporaryDirectory() as directory:
            nested = Path(directory) / "capture"
            nested.mkdir()
            (nested / "dkproject.json").write_text("{}", encoding="utf-8")
            self.assertEqual(converter.discover_project_root(Path(directory)), nested)

    def test_calibration_comparison_checks_extrinsics(self):
        reference = {
            "intrinsic_matrix": np.eye(3).tolist(),
            "distortions": [0.0] * 5,
            "extrinsics_matrix": np.eye(4)[:3].tolist(),
            "image_size": [1920, 1080],
        }
        candidate = dict(reference)
        candidate["extrinsics_matrix"] = np.asarray(
            reference["extrinsics_matrix"]
        ).copy()
        candidate["extrinsics_matrix"][0, 3] = 0.01
        candidate["extrinsics_matrix"] = candidate["extrinsics_matrix"].tolist()
        self.assertFalse(converter.calibrations_match(reference, candidate))


class PublicationTests(unittest.TestCase):
    def test_copy_overwrite_publishes_complete_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            destination = root / "destination.mp4"
            source.write_bytes(b"new video")
            destination.write_bytes(b"old video")
            camera = converter.CameraStream(
                name="cam_01",
                sensor_number=1,
                device_id="device",
                source=source,
                width=1,
                height=1,
                fps=30.0,
                frame_count=1,
                calibration={},
                world_pose={},
                stream={},
            )
            action = converter.prepare_video(
                camera,
                destination,
                mode="copy",
                target_fps=30.0,
                overwrite=True,
                rotation="none",
            )
            self.assertEqual(action, "copy")
            self.assertEqual(destination.read_bytes(), b"new video")
            self.assertFalse((root / ".destination.partial.mp4").exists())


class ArgumentTests(unittest.TestCase):
    def test_validate_only_does_not_require_output_path(self):
        with mock.patch.object(
            sys,
            "argv",
            ["prepare_depthkit_for_mamma.py", "/capture", "--validate-only"],
        ):
            arguments = converter.parse_args()
        self.assertEqual(arguments.project, Path("/capture"))
        self.assertIsNone(arguments.output)
        self.assertTrue(arguments.validate_only)


if __name__ == "__main__":
    unittest.main()
