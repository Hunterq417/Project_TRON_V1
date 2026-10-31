# orb_render.py
"""
Draws the orb into an RGBA image on the CPU.

This is a numpy port of the fragment shader the orb used to run in a WebView2
window. It moved to the CPU so the window can be a real per-pixel-alpha layered
window: a browser cannot composite against the desktop, which forced the old
approach of painting a copy of the wallpaper behind the orb — and that broke the
moment the wallpaper changed. Rendering here means the orb has genuine
transparency and adapts to whatever is behind it, wallpaper or not.

PARAMS was fitted numerically against a frame of the Spline "Voice AI Assistant"
scene (mean absolute error 4.6/255 over a 6720-point polar grid). Hand-editing
those numbers pulls the orb off the reference; refit rather than nudge.
"""
import numpy as np

# Fitted against the reference frame — see the module docstring.
PARAMS = {
    "lobes": [
        #   dx        dy       pow       amp         r         g         b
        [-0.7195, -0.6227,  4.7881,  3.1543,  0.0597,  0.0753,  0.4302],
        [-0.4341, -0.6303,  2.2670,  1.3190,  1.0371,  0.5388,  0.0268],
        [-0.3188,  0.2283, 13.3488,  0.6386,  0.7704,  0.0000,  0.5391],
        [-0.8311,  0.2854, 14.9136,  4.0000,  0.4416,  0.0000,  0.3089],
        [ 0.4825,  0.3125,  4.4639,  1.0617,  0.2460,  0.8690,  1.6399],
        [ 0.4375,  0.7913,  5.2567,  4.0000,  0.1547,  0.0809,  0.3392],
        [ 0.8764, -0.3644,  3.1274,  4.0000,  0.1339,  0.0000,  0.3029],
        [-0.0794,  0.7207,  4.8124,  1.0587,  0.0000,  0.1178,  0.0000],
        [-0.0094,  0.8667,  0.6000,  0.0499,  1.2876,  0.0000,  1.1924],
    ],
    "rim":     [2.2641, 2.9337, 0.0, 1.0807],   # strength, pow, bias, gain
    "rimCol":  [1.4343, 1.4561, 1.6785],
    "rimCol2": [-0.6839, -0.9776, 0.1418],      # iridescent boost along rimAxis
    "rimAxis": [1.8617, 6.0011],                # angle, power
    "rim2":    [0.3768, 12.9318],               # thin glass ring: strength, pow
    "rim2Col": [1.5348, 0.9921, 0.7888],
    "spec":    [-0.671, -0.438, 5.8231, 0.4533],
}

# [edge-highlight hue swing, edge band strength, edge band width]. Width is a
# falloff exponent: lower reaches further in from the rim. All scale with the
# per-state amount, which is 0 at idle, so at rest the orb is the pure replica.
STATE_RIM = (1.0, 1.15, 2.0)

# Angle quantisation for the field cache. Callers reuse this to tell whether a
# new angle would even produce a different frame — at idle the wobble is slow
# enough that it crosses a bucket only a few times a second, which is what keeps
# an always-visible orb almost free.
ANGLE_STEP = 0.01

_LUMA = np.array([0.299, 0.587, 0.114], np.float32)
_THIRD = np.float32(1.0 / 3.0)


def _swirl(angle):
    """Rotation about a tilted axis, so the gradient tumbles rather than
    spinning flat. Identity at angle 0, which is the fitted pose."""
    ax = np.array([0.22, 0.94, 0.26], np.float32)
    ax /= np.linalg.norm(ax)
    x, y, z = ax
    c, s = np.cos(angle), np.sin(angle)
    ic = 1.0 - c
    return np.array([
        [c + x * x * ic,     x * y * ic - z * s, x * z * ic + y * s],
        [y * x * ic + z * s, c + y * y * ic,     y * z * ic - x * s],
        [z * x * ic - y * s, z * y * ic + x * s, c + z * z * ic],
    ], np.float32)


class OrbRenderer:
    """Renders the orb at a fixed pixel radius.

    Everything that depends only on geometry — the sphere normals, the disc
    coverage, both fresnel falloffs, the specular — is computed once here. Only
    the lobe field actually varies frame to frame, which is what keeps this fast
    enough to animate on the CPU.
    """

    def __init__(self, size, radius):
        self.size = int(size)
        self.radius = float(radius)
        n = self.size
        cy = cx = (n - 1) * 0.5
        yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
        px = (xx - cx) / self.radius
        py = (yy - cy) / self.radius
        r = np.hypot(px, py)
        safe_r = np.maximum(r, 1e-5)

        # Alpha is the disc, feathered by about a pixel so the silhouette is not
        # a staircase. This is the *only* thing that makes the window visible;
        # everywhere it is 0 the desktop shows through untouched.
        self.alpha = np.clip((1.0 - r) * self.radius * 1.5, 0.0, 1.0).astype(np.float32)
        self.mask = self.alpha > 0.0

        rc = np.minimum(r, 1.0)
        z = np.sqrt(np.maximum(0.0, 1.0 - rc * rc))
        k = rc / safe_r
        self._n = np.stack([px * k, py * k, z], axis=-1).astype(np.float32)

        one_minus_z = (1.0 - z).astype(np.float32)
        P = PARAMS

        # Broad fresnel rim, with its iridescent axis.
        sdir = np.stack([px / safe_r, py / safe_r], axis=-1)
        axis = np.array([np.cos(P["rimAxis"][0]), np.sin(P["rimAxis"][0])], np.float32)
        ax = sdir @ axis
        irid = np.power(ax * ax, P["rimAxis"][1]).astype(np.float32)
        rim_tint = (np.array(P["rimCol"], np.float32)
                    + np.array(P["rimCol2"], np.float32) * irid[..., None])
        rim_broad = (np.power(one_minus_z, P["rim"][1]) * P["rim"][0])[..., None] * rim_tint

        # Thin glass ring. Its colour is state-dependent, so only the falloff is
        # baked here.
        ring_mask = (np.power(one_minus_z, P["rim2"][1]) * P["rim2"][0]).astype(np.float32)

        # State band: how far the state colour reaches in from the edge.
        band = np.power(one_minus_z, STATE_RIM[2]).astype(np.float32)

        # Specular — the light direction is fixed, so this is constant.
        lx, ly = P["spec"][0], P["spec"][1]
        lz = np.sqrt(max(0.0, 1.0 - lx * lx - ly * ly))
        dl = np.clip(self._n @ np.array([lx, ly, lz], np.float32), 0.0, None)
        spec = (np.power(dl, P["spec"][2]) * P["spec"][3])[..., None] \
            * np.array([1.0, 0.96, 1.0], np.float32)

        self._lobe_dirs = np.array(
            [[l[0], l[1], np.sqrt(max(0.0, 1.0 - l[0] ** 2 - l[1] ** 2))] for l in P["lobes"]],
            np.float32)
        self._lobe_pow = np.array([l[2] for l in P["lobes"]], np.float32)
        self._lobe_amp = np.array([l[3] for l in P["lobes"]], np.float32)
        self._lobe_col = np.array([[l[4], l[5], l[6]] for l in P["lobes"]], np.float32)

        # Work on the disc's pixels only — outside it every term is multiplied
        # away by alpha, so computing it would be wasted. Every static term is
        # flattened to that same set of pixels now, because re-applying a boolean
        # mask each frame allocates and copies, and that cost dominated the
        # render before it was hoisted here.
        m = self.mask
        self._flat_n = self._n[m]
        self._rim_broad = rim_broad[m]
        self._ring_mask = ring_mask[m][:, None]
        self._band = band[m]
        self._spec = spec[m]
        self._alpha_m = self.alpha[m][:, None]
        self._deterministic_noise = (
            (np.random.default_rng(7).random(self._flat_n.shape[0]).astype(np.float32) - 0.5)
            / 255.0)[:, None]

        # The output buffer is reused, and its alpha channel is written once:
        # the silhouette never changes, only the colour inside it.
        self._angle_cache = {}
        self._buf = np.zeros((n, n, 4), np.uint8)
        self._buf[..., 3] = (self.alpha * 255.0).astype(np.uint8)

    def _field_cached(self, angle):
        """The lobe field for this angle, memoised.

        The field is by far the most expensive part of a frame and the only part
        that depends on the angle — and the angle only ever oscillates back and
        forth through a small bounded range, so after one cycle every value it
        takes has already been computed. Quantising to ~0.6 degrees is well below
        what is visible on a gradient this smooth. Stored as float16 to keep the
        whole cache to a few MB.
        """
        key = int(round(angle / ANGLE_STEP))
        hit = self._angle_cache.get(key)
        if hit is None:
            hit = self._field(_swirl(key * ANGLE_STEP)).astype(np.float16)
            self._angle_cache[key] = hit
        return hit.astype(np.float32)

    def _field(self, rot):
        """Normalised blend of the angular lobes, over the disc's pixels."""
        dirs = self._lobe_dirs @ rot.T                       # rotate the lobes, not the sphere
        dt = self._flat_n @ dirs.T                           # (px, 9)
        np.clip(dt, 1e-8, None, out=dt)
        # exp(p*log(x)) rather than power(x, p): measurably faster here, and the
        # clip above keeps log away from zero.
        np.log(dt, out=dt)
        dt *= self._lobe_pow
        np.exp(dt, out=dt)
        w = dt * self._lobe_amp
        wsum = w.sum(axis=1) + 1e-5
        return (w @ self._lobe_col) / wsum[:, None]

    def render(self, angle=0.0, tint=(0.0, 0.0, 0.0), amount=0.0, level=0.0):
        """Premultiplied BGRA, ready for UpdateLayeredWindow.

        The returned buffer is reused between calls — copy it if you need to keep
        a frame. UpdateLayeredWindow consumes it immediately, so this is safe for
        the only caller.
        """
        P = PARAMS
        body = self._field_cached(angle) * P["rim"][3]

        surf = body + self._rim_broad * (
            P["rim"][2] + (1.0 - P["rim"][2]) * (body @ np.full(3, _THIRD, np.float32))[:, None])

        # Hold the tint's energy constant: blending straight to a dark state
        # colour would dim the sphere's edge instead of colouring it.
        tint = np.asarray(tint, np.float32)
        lit = tint * (0.8 / max(float(tint @ _LUMA), 0.05))

        ring_col = (np.array(P["rim2Col"], np.float32)
                    + (lit - np.array(P["rim2Col"], np.float32))
                    * min(max(amount * STATE_RIM[0], 0.0), 1.0))
        surf += self._ring_mask * ring_col

        # A hue blend, not added light: adding to the thin ring alone is far too
        # subtle to read against the body's own saturated gradient.
        t = np.clip(amount * STATE_RIM[1] * self._band, 0.0, 1.0)[:, None]
        target = lit * (0.45 + 0.85 * (surf @ np.full(3, _THIRD, np.float32))[:, None])
        surf += (target - surf) * t

        surf += self._spec
        # Voice level breathes the orb's brightness. It used to scale the
        # sphere, but the geometry here is precomputed for one radius and
        # rebuilding it per frame costs more than the whole render — brightness
        # carries the same beat for free.
        if level > 0.0:
            surf *= 1.0 + 0.22 * float(level)
        # One-LSB dither: these gradients are smooth enough that 8-bit
        # quantisation otherwise draws visible contour rings.
        surf += self._deterministic_noise
        np.clip(surf, 0.0, 1.0, out=surf)

        surf *= self._alpha_m * 255.0               # premultiplied alpha
        self._buf[self.mask, :3] = surf[:, ::-1].astype(np.uint8)   # RGB -> BGR
        return self._buf
