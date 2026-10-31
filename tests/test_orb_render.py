# tests/test_orb_render.py
import numpy as np
import pytest

import orb_render


@pytest.fixture(scope="module")
def r():
    # Small enough to keep the suite quick, large enough that the disc has a
    # meaningful interior and edge.
    return orb_render.OrbRenderer(size=88, radius=40)


def test_frame_shape_and_type(r):
    f = r.render()
    assert f.shape == (88, 88, 4)
    assert f.dtype == np.uint8


def test_outside_the_sphere_is_fully_transparent(r):
    f = r.render()
    # The alpha channel is the *only* thing that makes the window visible. Any
    # stray alpha out here would draw a rectangle on the user's desktop.
    for corner in [(0, 0), (0, 87), (87, 0), (87, 87)]:
        assert f[corner][3] == 0
        assert tuple(f[corner][:3]) == (0, 0, 0)


def test_centre_of_the_sphere_is_opaque_and_coloured(r):
    f = r.render()
    assert f[44, 44, 3] == 255
    assert int(f[44, 44, :3].sum()) > 60


def test_colour_is_premultiplied_by_alpha(r):
    """UpdateLayeredWindow is given AC_SRC_ALPHA, which requires premultiplied
    colour. If it is not, edge pixels come out too bright and haloed."""
    f = r.render()
    a = f[..., 3].astype(np.int32)
    for ch in range(3):
        assert np.all(f[..., ch].astype(np.int32) <= a + 1)   # +1 for rounding


def test_idle_and_tinted_differ_only_when_an_amount_is_given(r):
    plain = r.render(0.0, (0.86, 0.21, 0.27), 0.0).copy()
    same = r.render(0.0, (0.20, 0.78, 0.35), 0.0).copy()
    tinted = r.render(0.0, (0.86, 0.21, 0.27), 0.78).copy()
    # amount 0 means no state colour at all, whatever the tint is — this is what
    # keeps idle an untouched replica of the reference.
    assert np.array_equal(plain, same)
    assert not np.array_equal(plain, tinted)


def test_state_colour_lands_on_the_edge_not_the_middle(r):
    plain = r.render(0.0, (0.86, 0.21, 0.27), 0.0).copy()
    tinted = r.render(0.0, (0.86, 0.21, 0.27), 0.78).copy()
    centre_shift = abs(int(tinted[44, 44, 2]) - int(plain[44, 44, 2]))
    edge_shift = abs(int(tinted[44, 7, 2]) - int(plain[44, 7, 2]))
    assert edge_shift > centre_shift


def test_angle_cache_is_reused(r):
    r._angle_cache.clear()
    r.render(0.05)
    r.render(0.05)
    r.render(0.0503)          # inside the same quantisation bucket
    assert len(r._angle_cache) == 1
    r.render(0.09)
    assert len(r._angle_cache) == 2


def test_audio_level_brightens_without_changing_the_silhouette(r):
    quiet = r.render(0.0, (0.2, 0.78, 0.35), 0.55, 0.0).copy()
    loud = r.render(0.0, (0.2, 0.78, 0.35), 0.55, 1.0).copy()
    assert np.array_equal(quiet[..., 3], loud[..., 3])        # same shape
    assert int(loud[..., :3].sum()) > int(quiet[..., :3].sum())
