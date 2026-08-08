import importlib.util
import argparse
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "prepare_sjtu_for_mamma.py"
SPEC = importlib.util.spec_from_file_location("prepare_sjtu_for_mamma", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SjtuCalibrationTest(unittest.TestCase):
    def test_fps_must_be_a_positive_integer(self):
        self.assertEqual(MODULE.positive_integer("25"), 25)
        with self.assertRaises(argparse.ArgumentTypeError):
            MODULE.positive_integer("29.97")
        with self.assertRaises(argparse.ArgumentTypeError):
            MODULE.positive_integer("0")

    def test_physical_spacing_must_be_finite_and_positive(self):
        self.assertEqual(MODULE.positive_finite_float("0.46"), 0.46)
        for value in ("0", "-1", "nan", "inf"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    MODULE.positive_finite_float(value)

    def test_parses_five_line_camera_blocks(self):
        content = "\n".join([
            "camera 3",
            "size 1920 1080",
            "intrinsic 1000 1001 960 540",
            "rotation 1 0 0 0 1 0 0 0 1",
            "center 1 2 3",
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paras.txt"
            path.write_text(content)
            cameras = MODULE.parse_calibration(path)

        self.assertEqual([cameras[3]["width"], cameras[3]["height"]], [1920, 1080])
        self.assertEqual(cameras[3]["intrinsic"][0], [1000.0, 0.0, 960.0])

    def test_metric_extrinsic_uses_negative_rotated_camera_center(self):
        camera = {
            "width": 10,
            "height": 20,
            "intrinsic": [[1.0, 0.0, 2.0], [0.0, 1.0, 3.0], [0.0, 0.0, 1.0]],
            "rotation": [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
            "center_units": [1.0, 2.0, 3.0],
        }
        calibration = MODULE.metric_calibration(camera, 0.5)
        self.assertEqual(calibration["extrinsics_matrix"], [
            [0.0, -1.0, 0.0, 1.0],
            [1.0, 0.0, 0.0, -0.5],
            [0.0, 0.0, 1.0, -1.5],
        ])

    def test_preflight_reports_all_camera_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "RGB").mkdir()
            videos = root / "conformed"
            videos.mkdir()
            for camera_id in (0, 1):
                (root / "RGB" / f"{camera_id}.mp4").touch()
            (videos / "cam_01.mp4").touch()

            jobs = MODULE.preflight_video_jobs(root, videos, [0, 1])
            self.assertEqual([job[1] for job in jobs], ["cam_00", "cam_01"])
            self.assertFalse((videos / "cam_00.mp4").exists())

    def test_encode_video_atomically_commits_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            output = root / "cam_00.mp4"
            source.touch()

            def successful_run(command, check):
                self.assertTrue(check)
                Path(command[-1]).write_bytes(b"complete")

            with mock.patch.object(MODULE.subprocess, "run", successful_run):
                MODULE.encode_video(source, output, "fps=25")

            self.assertEqual(output.read_bytes(), b"complete")
            self.assertFalse((root / ".cam_00.partial.mp4").exists())

    def test_encode_video_cleans_failed_temporary_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            output = root / "cam_00.mp4"
            source.touch()

            def failed_run(command, check):
                Path(command[-1]).write_bytes(b"partial")
                raise subprocess.CalledProcessError(1, command)

            with mock.patch.object(MODULE.subprocess, "run", failed_run):
                with self.assertRaises(subprocess.CalledProcessError):
                    MODULE.encode_video(source, output, "fps=25")

            self.assertFalse(output.exists())
            self.assertFalse((root / ".cam_00.partial.mp4").exists())

    def test_capture_descriptor_uses_session_relative_paths(self):
        capture = MODULE.build_capture_descriptor("take", 25, ["cam_00"])
        self.assertEqual(capture["capture_root"], "..")
        self.assertEqual(capture["calib"], "calibration.json")

    def test_resume_manifest_rejects_changed_encode_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conformance.json"
            expected = MODULE.build_resume_signature(
                Path("/source"), 0.0, 5.0, 25, 0.46
            )
            path.write_text(json.dumps(expected))

            completed = MODULE.validate_resume_manifest(path, expected, True, False)
            self.assertEqual(completed, set())
            changed = {**expected, "start_seconds": 1.0}
            with self.assertRaises(RuntimeError):
                MODULE.validate_resume_manifest(path, changed, True, False)

    def test_resume_manifest_is_required_for_existing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conformance.json"
            expected = MODULE.build_resume_signature(
                Path("/source"), 0.0, None, 25, 0.46
            )
            with self.assertRaises(RuntimeError):
                MODULE.validate_resume_manifest(path, expected, True, False)

    def test_reuse_requires_completion_for_current_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_complete = root / "cam_00.mp4"
            stale_from_interrupted_overwrite = root / "cam_01.mp4"
            old_complete.touch()
            stale_from_interrupted_overwrite.touch()
            completed = {"cam_00"}

            self.assertTrue(
                MODULE.should_reuse_output(
                    old_complete, "cam_00", completed, overwrite=False
                )
            )
            self.assertFalse(
                MODULE.should_reuse_output(
                    stale_from_interrupted_overwrite,
                    "cam_01",
                    completed,
                    overwrite=False,
                )
            )


if __name__ == "__main__":
    unittest.main()
