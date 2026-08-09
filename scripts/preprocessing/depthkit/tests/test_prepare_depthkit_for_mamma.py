from __future__ import annotations

import importlib.util
import json
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


def camera_stream(
    source: Path,
    *,
    name: str = "cam_01",
    device_id: str = "device",
) -> converter.CameraStream:
    return converter.CameraStream(
        name=name,
        sensor_number=1,
        device_id=device_id,
        source=source,
        width=1,
        height=1,
        fps=30.0,
        frame_count=1,
        calibration={},
        world_pose={},
        stream={},
    )


def source_identity_manifest(
    project: Path,
    takes: dict[str, list[converter.CameraStream]],
    *,
    rotation: str = "ccw",
) -> dict:
    calibration = project / "dkproject.json"
    return {
        "rotation": rotation,
        "source_project": str(project),
        "source_calibration_sha256": converter.sha256_file(calibration),
        "recordings": {
            name: [
                {
                    "camera": camera.name,
                    "device_id": camera.device_id,
                    "source": str(camera.source),
                    "source_fingerprint": converter.source_fingerprint(camera),
                }
                for camera in cameras
            ]
            for name, cameras in takes.items()
        },
    }


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

    def test_coincident_camera_centers_are_rejected(self):
        pose = {"rotation": [0, 0, 0], "translation": [0, 0, 0]}
        extrinsics = {"rotation": [0, 0, 0], "translation": [0, 0, 0]}
        cameras = []
        for index in (1, 2):
            camera = camera_stream(Path("unused"), name=f"cam_{index:02d}")
            cameras.append(
                converter.CameraStream(
                    **{
                        **camera.__dict__,
                        "calibration": {"extrinsics": extrinsics},
                        "world_pose": pose,
                    }
                )
            )
        with self.assertRaisesRegex(converter.ConversionError, "distinct"):
            converter.camera_look_at_score(cameras, "depth-to-color")


class CalibrationTests(unittest.TestCase):
    def test_depthkit_coefficients_are_reordered_for_opencv(self):
        intrinsics = {
            "distortionRadial": [1, 2, 3, 0, 0, 0],
            "distortionTangential": [4, 5],
        }
        self.assertEqual(converter.distortion_coefficients(intrinsics), [1, 2, 4, 5, 3])

    def test_nonzero_rational_tail_is_rejected(self):
        unsupported = (
            {
                "distortionRadial": [1, 2, 3, 4, 0, 0],
                "distortionTangential": [0, 0],
            },
            {
                "distortionRadial": [1, 2, 3, 0, 0, 0, 4],
                "distortionTangential": [0, 0],
            },
            {
                "distortionRadial": [1, 2, 3],
                "distortionTangential": [0, 0, 4],
            },
        )
        for intrinsics in unsupported:
            with self.subTest(intrinsics=intrinsics):
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
    def test_recording_with_dropped_frames_is_rejected(self):
        camera = camera_stream(Path("unused"))
        dropped_camera = converter.CameraStream(
            **{
                **camera.__dict__,
                "stream": {"numDroppedFrames": 1},
            }
        )
        with self.assertRaisesRegex(converter.ConversionError, "dropped capture"):
            converter.validate_synchronized_streams({"take": [dropped_camera]})

    def test_copy_overwrite_publishes_complete_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            destination = root / "destination.mp4"
            source.write_bytes(b"new video")
            destination.write_bytes(b"old video")
            camera = camera_stream(source)
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

    def test_copy_mode_replaces_matching_source_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            destination = root / "destination.mp4"
            source.write_bytes(b"video")
            destination.symlink_to(source)
            action = converter.prepare_video(
                camera_stream(source),
                destination,
                mode="copy",
                target_fps=30,
                overwrite=True,
                rotation="none",
            )
            self.assertEqual(action, "copy")
            self.assertFalse(destination.is_symlink())
            self.assertEqual(destination.read_bytes(), b"video")

    def test_symlink_mode_reuses_matching_source_symlink_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            destination = root / "destination.mp4"
            source.write_bytes(b"video")
            destination.symlink_to(source)
            action = converter.prepare_video(
                camera_stream(source),
                destination,
                mode="symlink",
                target_fps=30,
                overwrite=False,
                rotation="none",
            )
            self.assertEqual(action, "symlink")
            self.assertTrue(destination.is_symlink())

    def test_auto_symlink_requires_conformant_stream_metadata(self):
        stream_data = {
            "streams": [
                {
                    "codec_name": "h264",
                    "pix_fmt": "yuv420p",
                    "r_frame_rate": "30/1",
                    "avg_frame_rate": "30/1",
                }
            ]
        }
        with mock.patch.object(
            converter.subprocess,
            "run",
            return_value=mock.Mock(stdout=json.dumps(stream_data)),
        ):
            self.assertTrue(
                converter.video_is_conformant_for_symlink(Path("video.mp4"), 30)
            )

        stream_data["streams"][0]["avg_frame_rate"] = "30000/1001"
        with mock.patch.object(
            converter.subprocess,
            "run",
            return_value=mock.Mock(stdout=json.dumps(stream_data)),
        ):
            self.assertFalse(
                converter.video_is_conformant_for_symlink(Path("video.mp4"), 30)
            )

    def test_calibration_only_rejects_rotation_change(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            project = output / "project"
            project.mkdir()
            (project / "dkproject.json").write_text("{}", encoding="utf-8")
            source = project / "video.mp4"
            source.write_bytes(b"video")
            takes = {"take": [camera_stream(source)]}
            (output / "conversion_manifest.json").write_text(
                json.dumps(source_identity_manifest(project, takes)),
                encoding="utf-8",
            )
            converter.validate_calibration_only_manifest(
                output,
                "ccw",
                project,
                takes,
            )
            with self.assertRaisesRegex(converter.ConversionError, "rotation"):
                converter.validate_calibration_only_manifest(
                    output,
                    "cw",
                    project,
                    takes,
                )

    def test_calibration_only_rejects_changed_source_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            project = output / "project"
            project.mkdir()
            (project / "dkproject.json").write_text("{}", encoding="utf-8")
            source = project / "video.mp4"
            source.write_bytes(b"original video")
            takes = {"take": [camera_stream(source)]}
            (output / "conversion_manifest.json").write_text(
                json.dumps(source_identity_manifest(project, takes)),
                encoding="utf-8",
            )
            source.write_bytes(b"replacement video with a different size")
            with self.assertRaisesRegex(converter.ConversionError, "source changed"):
                converter.validate_calibration_only_manifest(
                    output,
                    "ccw",
                    project,
                    takes,
                )

    def test_overwrite_invalidation_removes_all_published_descriptors(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            names = (
                "calibration.json",
                "capture.json",
                "conversion_manifest.json",
            )
            for name in names:
                (output / name).write_text("{}", encoding="utf-8")
            converter.invalidate_capture_descriptors(output)
            self.assertTrue(all(not (output / name).exists() for name in names))


class ArgumentTests(unittest.TestCase):
    def test_recording_names_must_be_unique_safe_path_components(self):
        converter.validate_recording_names(["safe_take"])
        invalid_names = (
            ["duplicate", "duplicate"],
            ["../escape"],
            ["/absolute"],
            ["nested/take"],
            [r"nested\take"],
            ["."],
            [".."],
            ["C:drive-qualified"],
        )
        for names in invalid_names:
            with self.subTest(names=names):
                with self.assertRaises(converter.ConversionError):
                    converter.validate_recording_names(names)

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

    def test_recording_selection_uses_explicit_option(self):
        with mock.patch.object(
            sys,
            "argv",
            [
                "prepare_depthkit_for_mamma.py",
                "/capture",
                "--recordings",
                "take_a",
                "take_b",
                "--validate-only",
            ],
        ):
            arguments = converter.parse_args()
        self.assertIsNone(arguments.output)
        self.assertEqual(arguments.recordings, ["take_a", "take_b"])

    def test_fractional_output_fps_is_rejected(self):
        with mock.patch.object(
            sys,
            "argv",
            [
                "prepare_depthkit_for_mamma.py",
                "/capture",
                "--fps",
                "29.97",
                "--validate-only",
            ],
        ):
            with self.assertRaises(SystemExit):
                converter.parse_args()

    def test_validate_only_builds_converted_camera_models(self):
        arguments = mock.Mock(
            project=Path("/capture"),
            output=None,
            recordings=["take"],
            fps=30,
            video_mode="auto",
            rotate="none",
            color_extrinsics_direction="depth-to-color",
            overwrite=False,
            calibration_only=False,
            validate_only=True,
        )
        cameras = [
            camera_stream(Path("unused"), name="cam_01", device_id="device_1"),
            camera_stream(Path("unused"), name="cam_02", device_id="device_2"),
        ]
        with (
            mock.patch.object(converter, "parse_args", return_value=arguments),
            mock.patch.object(
                converter,
                "discover_project_root",
                return_value=Path("/capture"),
            ),
            mock.patch.object(
                converter,
                "load_json",
                return_value={"recordings": {"take": {}}},
            ),
            mock.patch.object(
                converter,
                "gather_recording",
                return_value=cameras,
            ),
            mock.patch.object(
                converter,
                "camera_look_at_score",
                return_value=1.0,
            ),
            mock.patch.object(
                converter,
                "mamma_camera",
                side_effect=converter.ConversionError("invalid camera model"),
            ),
        ):
            with self.assertRaisesRegex(converter.ConversionError, "camera model"):
                converter.main()


if __name__ == "__main__":
    unittest.main()
