import pytest
from recoverhand_host.desktop.virtual_hand import normalize_pose


def test_virtual_hand_accepts_scalar_or_five_finger_pose() -> None:
    assert normalize_pose(0.4) == (0.4,) * 5
    assert normalize_pose([0.1, 0.2, 0.3, 0.4, 0.5]) == (0.1, 0.2, 0.3, 0.4, 0.5)


def test_virtual_hand_clamps_pose_and_rejects_wrong_shape() -> None:
    assert normalize_pose([-1.0, 0.0, 0.5, 1.0, 2.0]) == (0.0, 0.0, 0.5, 1.0, 1.0)
    with pytest.raises(ValueError, match="五指"):
        normalize_pose([0.0, 1.0])
