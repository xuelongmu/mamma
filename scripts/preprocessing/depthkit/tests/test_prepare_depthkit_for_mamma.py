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

    def test_low_parallel_rig_score_is_a_warning_not_an_error(self):
        warning = converter.look_at_score_warning(0.0)
        self.assertIsNotNone(warning)
        self.assertIn("parallel", warning)
        self.assertIsNone(converter.look_at_score_warning(0.9))


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

    def test_explicit_recording_rejects_device_without_color_stream(self):
        project = {
            "recordings": {
                "take": {
                    "streams": {
                        "device_1": [{"type": "depth"}],
                    }
                }
            }
        }
        with self.assertRaisesRegex(converter.ConversionError, "lacks a color"):
            converter.gather_recording(Path("unused"), project, "take")

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
    def test_preflight_rejects_recording_symlink_outside_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"video")
            for preflight in (
                converter.preflight_non_overwrite,
                converter.preflight_overwrite,
            ):
                with self.subTest(preflight=preflight.__name__):
                    output = root / preflight.__name__
                    external = root / f"external_{preflight.__name__}"
                    output.mkdir()
                    external.mkdir()
                    (output / "take").symlink_to(external, target_is_directory=True)
                    with self.assertRaisesRegex(
                        converter.ConversionError, "escapes the output"
                    ):
                        preflight(
                            output,
                            {"take": [camera_stream(source)]},
                            mode="copy",
                            target_fps=30,
                            rotation="none",
                        )
                    self.assertFalse((external / "videos").exists())

    def test_overwrite_preflight_preserves_descriptors_on_invalid_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            names = (
                "calibration.json",
                "capture.json",
                "conversion_manifest.json",
            )
            for name in names:
                (output / name).write_text("old", encoding="utf-8")
            source = output / "source.mp4"
            source.write_bytes(b"video")
            with self.assertRaisesRegex(converter.ConversionError, "cannot apply"):
                converter.preflight_overwrite(
                    output,
                    {"take": [camera_stream(source)]},
                    mode="copy",
                    target_fps=30,
                    rotation="ccw",
                )
            self.assertTrue(all((output / name).is_file() for name in names))

    def test_overwrite_preflight_preserves_descriptors_on_fps_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            names = (
                "calibration.json",
                "capture.json",
                "conversion_manifest.json",
            )
            for name in names:
                (output / name).write_text("old", encoding="utf-8")
            source = output / "source.mp4"
            source.write_bytes(b"video")
            for mode in ("copy", "symlink"):
                with self.subTest(mode=mode):
                    with self.assertRaisesRegex(
                        converter.ConversionError, "cannot change"
                    ):
                        converter.preflight_overwrite(
                            output,
                            {"take": [camera_stream(source)]},
                            mode=mode,
                            target_fps=25,
                            rotation="none",
                        )
                    self.assertTrue(all((output / name).is_file() for name in names))

    def test_calibration_only_rejects_changed_prepared_video(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "prepared.mp4"
            destination.write_bytes(b"prepared video")
            prior = {
                "prepared": str(destination),
                "prepared_frames": 10,
                "prepared_fingerprint": converter.file_fingerprint(destination),
            }
            converter.validate_prepared_video_identity(prior, destination, 10)
            destination.write_bytes(b"replaced prepared video")
            with self.assertRaisesRegex(converter.ConversionError, "changed"):
                converter.validate_prepared_video_identity(prior, destination, 10)

    def test_non_overwrite_preflight_prevents_partial_video_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            videos = output / "take" / "videos"
            videos.mkdir(parents=True)
            source_1 = root / "source_1.mp4"
            source_2 = root / "source_2.mp4"
            source_1.write_bytes(b"one")
            source_2.write_bytes(b"two")
            cameras = [
                camera_stream(source_1, name="cam_01", device_id="device_1"),
                camera_stream(source_2, name="cam_02", device_id="device_2"),
            ]
            (videos / "cam_02.mp4").write_bytes(b"existing")
            with self.assertRaisesRegex(converter.ConversionError, "overwrite"):
                converter.preflight_non_overwrite(
                    output,
                    {"take": cameras},
                    mode="copy",
                    target_fps=30,
                    rotation="none",
                )
            self.assertFalse((videos / "cam_01.mp4").exists())

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

    def test_mismatched_stream_sync_offsets_are_rejected(self):
        first = camera_stream(Path("first"), name="cam_01", device_id="device_1")
        second = camera_stream(Path("second"), name="cam_02", device_id="device_2")
        first = converter.CameraStream(
            **{
                **first.__dict__,
                "stream": {
                    "syncOffset": {"negative": False, "ticks": 0, "timebase": 1}
                },
            }
        )
        second = converter.CameraStream(
            **{
                **second.__dict__,
                "stream": {
                    "syncOffset": {"negative": False, "ticks": 1, "timebase": 30}
                },
            }
        )
        with self.assertRaisesRegex(converter.ConversionError, "mismatched"):
            converter.validate_synchronized_streams({"take": [first, second]})

    def test_mismatched_source_camera_rates_are_rejected(self):
        first = camera_stream(Path("first"), name="cam_01", device_id="device_1")
        second = camera_stream(Path("second"), name="cam_02", device_id="device_2")
        second = converter.CameraStream(
            **{
                **second.__dict__,
                "fps": 25.0,
            }
        )
        with self.assertRaisesRegex(converter.ConversionError, "not synchronized"):
            converter.validate_common_source_fps({"take": [first, second]})

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

    def test_calibration_only_publication_invalidates_before_first_write(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            names = (
                "calibration.json",
                "capture.json",
                "conversion_manifest.json",
            )
            for name in names:
                (output / name).write_text("old", encoding="utf-8")

            def fail_first_write(*_args, **_kwargs):
                self.assertTrue(all(not (output / name).exists() for name in names))
                raise OSError("simulated full disk")

            with mock.patch.object(
                converter,
                "write_json",
                side_effect=fail_first_write,
            ):
                with self.assertRaisesRegex(OSError, "full disk"):
                    converter.publish_capture_descriptors(
                        output,
                        {},
                        {},
                        {},
                        overwrite=True,
                        invalidate_existing=True,
                    )
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
