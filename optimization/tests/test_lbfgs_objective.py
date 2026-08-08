from pathlib import Path
import sys
from types import MethodType, SimpleNamespace
import unittest
from unittest import mock

import torch


OPTIMIZATION_ROOT = Path(__file__).resolve().parents[1]
if str(OPTIMIZATION_ROOT) not in sys.path:
    sys.path.insert(0, str(OPTIMIZATION_ROOT))

from utils import optimization as optimization_module  # noqa: E402


class CapturingLBFGS:
    returned_loss = None

    def __init__(self, params, **_kwargs):
        self.params = params

    def zero_grad(self):
        for param in self.params:
            param.grad = None

    def step(self, closure):
        value = closure()
        type(self).returned_loss = value.detach().item()
        return value


class LBFGSObjectiveTest(unittest.TestCase):
    def test_closure_returns_complete_objective(self):
        fitter = optimization_module.OptimizeSMPLX.__new__(
            optimization_module.OptimizeSMPLX
        )

        def parameter(width):
            return torch.zeros(
                (1, width), dtype=torch.float32, requires_grad=True
            )

        poses = {
            "global": parameter(3),
            "body": parameter(63),
            "left_hand": parameter(45),
            "right_hand": parameter(45),
            "jaw": parameter(3),
            "leye": parameter(3),
            "reye": parameter(3),
        }
        fitter.poses = {0: poses}
        fitter.smplx_betas = {0: parameter(1)}
        fitter.smplx_trans = {0: parameter(3)}
        fitter.smplx_model = {0: {"neutral": object()}}
        fitter.downsampled_verts_mat = None
        fitter.body_idx = None
        fitter.pts2d = {0: [torch.zeros((1, 1, 2))]}
        fitter.pts2d_vis_weight = {0: [torch.ones((1, 1))]}
        fitter.hand_joints2d = {0: None}
        fitter.triangulated_3d_points = {0: torch.zeros((1, 1, 3))}
        fitter.triangulated_contact = {0: None}

        def fake_forward(*_args, **_kwargs):
            points = torch.zeros((1, 1, 3), dtype=torch.float32)
            return SimpleNamespace(vertices=points, joints=points)

        def fake_process_data(
            self, pts3d_pred, joints3d_pred, *_args, **_kwargs
        ):
            return (
                [torch.zeros((1, 1, 2))],
                [torch.eye(3).unsqueeze(0)],
                [torch.eye(4).unsqueeze(0)],
                pts3d_pred,
                joints3d_pred,
                None,
                [torch.ones((1, 1))],
                torch.zeros((1, 1, 3)),
                None,
            )

        def fake_losses(self, *_args, poses, **_kwargs):
            return {
                "reproj_loss": poses["global"].sum() + 2.0,
                "shape_loss": poses["body"].sum() + 3.0,
            }

        def fake_multi_losses(self, *_args, **_kwargs):
            return {
                "intersection_loss": self.smplx_trans[0].sum() + 5.0
            }

        fitter.process_data = MethodType(fake_process_data, fitter)
        fitter.loss_functions = MethodType(fake_losses, fitter)
        fitter.loss_functions_multi_people = MethodType(
            fake_multi_losses, fitter
        )

        params = [poses["global"], poses["body"], fitter.smplx_trans[0]]
        fake_error = lambda pts2d, *_args, **_kwargs: (  # noqa: E731
            {0: torch.zeros(1)},
            pts2d,
        )
        with (
            mock.patch.object(torch.optim, "LBFGS", CapturingLBFGS),
            mock.patch.object(
                optimization_module,
                "get_smplx_forward_per_parts",
                fake_forward,
            ),
            mock.patch.object(
                optimization_module, "proj_pts_error", fake_error
            ),
        ):
            fitter.fit_smplx_to_2d_points(
                ["reproj_loss", "shape_loss", "intersection_loss"],
                params,
                num_iters=1,
                optim_verts=True,
                loss_cfg={},
            )

        self.assertAlmostEqual(CapturingLBFGS.returned_loss, 10.0)


if __name__ == "__main__":
    unittest.main()
