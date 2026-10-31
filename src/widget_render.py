# widget_render.py
"""
The compact ring widget: a small amber halo with a label, meant to float over
your work and be dragged wherever you want it.

Drawn with PIL rather than numpy like the orb. The orb is a smooth field where
every pixel is a formula, which numpy suits; this is strokes, dots and a word,
which is drawing — and PIL is already a dependency for the tray icon. Everything
is rendered at SUPERSAMPLE times the final size and shrunk down, because arcs a
pixel and a half wide alias badly otherwise.

Output is premultiplied BGRA, the same contract as orb_render, so the layered
window in orb_ui can push either without caring which drew it.
"""
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SUPERSAMPLE = 3

# Amber, as in the reference. State colours ride on top of this rather than
# replacing it, so the widget still reads as itself when it is listening.
BASE = (240, 165, 40)
CORE = (10, 10, 13)

# Arc segments: (radius fraction, start angle, sweep, width, brightness).
# Deliberately uneven — a complete circle reads as a loading spinner, and the
# gaps are what make it look like an instrument.
ARCS = [
    (0.98, -95, 150, 2.0, 1.00),
    (0.98, 95, 120, 2.0, 0.55),
    (0.86, 40, 95, 1.4, 0.75),
    (0.86, 210, 70, 1.4, 0.45),
    (1.10, 150, 60, 2.6, 0.90),
]

# Glowing beads sitting on the ring, at (angle, radius fraction, size fraction).
DOTS = [(-88, 0.98, 0.055), (18, 0.98, 0.04), (96, 1.10, 0.05),
        (168, 0.86, 0.035), (232, 0.98, 0.045)]

_FONT_CANDIDATES = [
    # Nirmala carries Devanagari, so a label like "ब्रह्म" renders rather than
    # coming out as boxes. Latin falls through to the others.
    r"C:\Windows\Fonts\NirmalaS.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\consola.ttf",
]


def _font(px):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _tint(colour, tint, amount):
    """Slides the amber toward a state colour without losing its warmth."""
    if amount <= 0:
        return colour
    return tuple(int(round(c + (t * 255 - c) * amount)) for c, t in zip(colour, tint))


class RingWidget:
    """Renders the floating widget. Same call shape as OrbRenderer."""

    def __init__(self, size, label="TRON"):
        self.size = int(size)
        self.label = label
        self._s = self.size * SUPERSAMPLE
        self._font = _font(int(self._s * 0.135))
        self._cache = {}

    # geometry helpers work in the supersampled space
    def _box(self, draw_radius):
        c = self._s / 2
        return [c - draw_radius, c - draw_radius, c + draw_radius, c + draw_radius]

    def _render(self, angle_deg, colour, level):
        s = self._s
        base_r = s * 0.30                      # ring radius; the rest is glow headroom
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d, dg = ImageDraw.Draw(img), ImageDraw.Draw(glow)

        # Dark core, so the label stays readable over a busy desktop.
        core_r = base_r * 0.80
        d.ellipse(self._box(core_r), fill=CORE + (200,))

        bright = 1.0 + 0.35 * level            # the voice pushes the ring brighter
        for rf, start, sweep, width, strength in ARCS:
            r = base_r * rf
            a0 = start + angle_deg
            col = tuple(min(255, int(c * strength * bright)) for c in colour)
            d.arc(self._box(r), a0, a0 + sweep, fill=col + (255,),
                  width=max(1, int(width * SUPERSAMPLE)))
            dg.arc(self._box(r), a0, a0 + sweep, fill=col + (170,),
                   width=max(1, int(width * SUPERSAMPLE * 2.2)))

        for a, rf, sf in DOTS:
            rad = base_r * rf
            import math
            th = math.radians(a + angle_deg)
            cx = s / 2 + rad * math.cos(th)
            cy = s / 2 + rad * math.sin(th)
            dot = s * sf * 0.5
            col = tuple(min(255, int(c * bright)) for c in colour)
            d.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill=col + (255,))
            dg.ellipse([cx - dot * 2.4, cy - dot * 2.4, cx + dot * 2.4, cy + dot * 2.4],
                       fill=col + (150,))

        label_col = tuple(min(255, int(c * 0.55 + 255 * 0.45)) for c in colour)
        d.text((s / 2, s / 2), self.label, font=self._font, fill=label_col + (255,),
               anchor="mm")

        glow = glow.filter(ImageFilter.GaussianBlur(radius=s * 0.022))
        out = Image.alpha_composite(glow, img)
        return out.resize((self.size, self.size), Image.LANCZOS)

    def render(self, angle=0.0, tint=(0.0, 0.0, 0.0), amount=0.0, level=0.0):
        """Premultiplied BGRA for UpdateLayeredWindow.

        Cached on the rounded inputs: the ring turns slowly, so most frames are
        a repeat of one already drawn, and PIL redrawing at 3x is far too
        expensive to do 30 times a second for no visible change."""
        import math
        deg = math.degrees(angle) % 360.0
        key = (round(deg / 3.0), tuple(round(c, 2) for c in tint),
               round(amount, 2), round(level, 1))
        hit = self._cache.get(key)
        if hit is None:
            colour = _tint(BASE, tint, amount * 0.7)
            hit = self._to_bgra(self._render(key[0] * 3.0, colour, level))
            if len(self._cache) > 400:         # a full turn at this quantisation
                self._cache.clear()
            self._cache[key] = hit
        return hit

    @staticmethod
    def _to_bgra(rgba):
        import numpy as np
        arr = np.asarray(rgba, dtype=np.uint16)
        a = arr[..., 3]
        out = np.empty(arr.shape, np.uint8)
        # Premultiply: AC_SRC_ALPHA blending expects it, and skipping this makes
        # every soft edge glow far too hot.
        out[..., 0] = (arr[..., 2] * a // 255).astype(np.uint8)   # B
        out[..., 1] = (arr[..., 1] * a // 255).astype(np.uint8)   # G
        out[..., 2] = (arr[..., 0] * a // 255).astype(np.uint8)   # R
        out[..., 3] = a.astype(np.uint8)
        return out
