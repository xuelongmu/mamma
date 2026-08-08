import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "prepare_sjtu_for_mamma.py"
SPEC = importlib.util.spec_from_file_location("prepare_sjtu_for_mamma", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SjtuCalibrationTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
