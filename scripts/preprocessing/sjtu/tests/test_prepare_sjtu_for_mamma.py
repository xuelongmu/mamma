import importlib.util
import argparse
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

    def test_preflight_reuses_existing_complete_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "RGB").mkdir()
            videos = root / "conformed"
            videos.mkdir()
            for camera_id in (0, 1):
                (root / "RGB" / f"{camera_id}.mp4").touch()
            (videos / "cam_01.mp4").touch()

            jobs = MODULE.preflight_video_jobs(root, videos, [0, 1], False)
            self.assertFalse(jobs[0][-1])
            self.assertTrue(jobs[1][-1])
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


if __name__ == "__main__":
    unittest.main()
