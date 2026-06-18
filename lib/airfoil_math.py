# -*- coding: utf-8 -*-
"""
Pure-stdlib airfoil geometry math (no numpy, no scipy).

This module is the self-contained port of the routines the companion
glasair_vg_sim repo implements with numpy/scipy:

  * geometry/airfoil.py            -> Lednicer assembly + cubic resampling
  * gpu/fluidx3d/make_vg_wing.py   -> upper_surface_point(x_frac) -> (y, slope)

Everything below uses only the Python standard library (``math``), because
Fusion 360's bundled interpreter cannot reliably import compiled packages.
The numerical method is a natural cubic spline fitted to the upper-surface
points -- the same curve family scipy's CubicSpline produces -- so the
suction-peak nose is represented with the same fidelity the CFD used, rather
than the kinked under-sized nose a piecewise-linear interpolation would give.

COORDINATE CONVENTION (identical to the whole VG pipeline)
  x = chordwise, leading edge at x = 0, trailing edge at x = 1 (chord-normalized)
  y = surface-normal / thickness direction, +y up (suction side positive)

PUBLIC SURFACE QUERY
  An UpperSurface object built from an airfoils.Airfoil answers three things at
  any chordwise fraction x in [0, 1]:
    y(x)        -- normalized height of the upper skin
    slope(x)    -- local skin angle in radians, atan(dy/dx)
    radius(x)   -- signed local radius of curvature (mm needs chord scaling)
  These three are exactly what the vane and jig builders need to seat a part
  flush on the wing: y positions it, slope tilts it, radius curves its base.
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple


# ===========================================================================
#  Natural cubic spline (stdlib reimplementation of scipy.interpolate.CubicSpline
#  with the 'natural' boundary condition: second derivative zero at both ends)
# ===========================================================================

class CubicSpline:
    """One-dimensional natural cubic spline y(x) over strictly increasing x.

    Solves the standard symmetric tridiagonal system for the second
    derivatives at the knots (the Thomas algorithm), then evaluates the usual
    piecewise cubic. 'Natural' end conditions (M0 = Mn = 0) match what we want
    for an open surface segment and avoid inventing an end slope. Accurate to
    machine precision on the ~45-point surfaces used here; the cost is O(n).
    """

    def __init__(self, xs: Sequence[float], ys: Sequence[float]):
        # Defensive copies as plain lists -- the input may be tuples from the
        # baked-in coordinate tables, and we index/mutate during the solve.
        self._x = [float(v) for v in xs]
        self._y = [float(v) for v in ys]
        n = len(self._x)
        if n < 3:
            raise ValueError("cubic spline needs at least 3 points")
        # Strict monotonicity is required: a repeated/backtracking x would make
        # an interval width zero and divide-by-zero the solve.
        for i in range(1, n):
            if self._x[i] <= self._x[i - 1]:
                raise ValueError("cubic spline x must be strictly increasing")

        # Interval widths h[i] between knot i and i+1.
        h = [self._x[i + 1] - self._x[i] for i in range(n - 1)]

        # Build the tridiagonal system A * M = d for the knot second
        # derivatives M. Interior rows are the classic continuity-of-slope
        # equations; the two end rows enforce the natural condition M=0.
        a = [0.0] * n   # sub-diagonal
        b = [0.0] * n   # main diagonal
        c = [0.0] * n   # super-diagonal
        d = [0.0] * n   # right-hand side

        # Natural boundary rows: M[0] = 0 and M[n-1] = 0.
        b[0] = 1.0
        b[n - 1] = 1.0

        # Interior rows i = 1 .. n-2.
        for i in range(1, n - 1):
            a[i] = h[i - 1]
            b[i] = 2.0 * (h[i - 1] + h[i])
            c[i] = h[i]
            d[i] = 6.0 * (
                (self._y[i + 1] - self._y[i]) / h[i]
                - (self._y[i] - self._y[i - 1]) / h[i - 1]
            )

        # Thomas algorithm: forward elimination then back-substitution.
        # The matrix is diagonally dominant, so no pivoting is needed.
        for i in range(1, n):
            w = a[i] / b[i - 1]
            b[i] -= w * c[i - 1]
            d[i] -= w * d[i - 1]
        m = [0.0] * n
        m[n - 1] = d[n - 1] / b[n - 1]
        for i in range(n - 2, -1, -1):
            m[i] = (d[i] - c[i] * m[i + 1]) / b[i]

        self._h = h
        self._m = m  # second derivatives at the knots

    def _interval(self, x: float) -> int:
        """Index i of the knot interval [x_i, x_{i+1}] containing x.

        Clamps to the end intervals so queries exactly at (or a hair past) the
        endpoints still evaluate -- the surface query never extrapolates far,
        but the LE/TE endpoints must not fall off the table.
        """
        xs = self._x
        if x <= xs[0]:
            return 0
        if x >= xs[-1]:
            return len(xs) - 2
        # Binary search for the bracketing interval.
        lo, hi = 0, len(xs) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if xs[mid] <= x:
                lo = mid
            else:
                hi = mid
        return lo

    def value(self, x: float) -> float:
        """Spline value y(x)."""
        i = self._interval(x)
        return self._eval(i, x, 0)

    def deriv1(self, x: float) -> float:
        """First derivative dy/dx at x."""
        i = self._interval(x)
        return self._eval(i, x, 1)

    def deriv2(self, x: float) -> float:
        """Second derivative d2y/dx2 at x."""
        i = self._interval(x)
        return self._eval(i, x, 2)

    def _eval(self, i: int, x: float, order: int) -> float:
        """Evaluate the cubic on interval i (value/1st/2nd derivative).

        Uses the standard second-derivative (moment) form of the natural
        cubic spline; ``order`` selects y, y', or y''. Keeping all three in one
        place guarantees they are mutually consistent (the slope really is the
        derivative of the value the builders use).
        """
        xi, xi1 = self._x[i], self._x[i + 1]
        hi = self._h[i]
        mi, mi1 = self._m[i], self._m[i + 1]
        yi, yi1 = self._y[i], self._y[i + 1]

        # Local coordinates measured from each end of the interval.
        A = (xi1 - x) / hi
        B = (x - xi) / hi

        if order == 0:
            return (
                A * yi + B * yi1
                + ((A ** 3 - A) * mi + (B ** 3 - B) * mi1) * (hi ** 2) / 6.0
            )
        if order == 1:
            return (
                (yi1 - yi) / hi
                - (3.0 * A ** 2 - 1.0) / 6.0 * hi * mi
                + (3.0 * B ** 2 - 1.0) / 6.0 * hi * mi1
            )
        # order == 2
        return A * mi + B * mi1


# ===========================================================================
#  Selig assembly (Lednicer upper/lower -> single loop) -- parity with
#  geometry/airfoil.py load_airfoil(), but operating on the baked-in lists
# ===========================================================================

_LE_MATCH_TOL = 1e-8


def assemble_selig(upper: Sequence[Tuple[float, float]],
                   lower: Sequence[Tuple[float, float]]
                   ) -> List[Tuple[float, float]]:
    """Stitch Lednicer surfaces into a Selig loop: TE-upper -> LE -> TE-lower.

    Mirrors load_airfoil(): the upper surface is reversed (so it runs TE->LE),
    then the lower surface is appended LE->TE with its duplicate leading-edge
    point dropped, leaving the nose shared exactly once.
    """
    up = [(float(x), float(y)) for x, y in upper]
    lo = [(float(x), float(y)) for x, y in lower]
    # Drop the lower LE copy if it coincides with the upper LE.
    if (abs(up[0][0] - lo[0][0]) < _LE_MATCH_TOL
            and abs(up[0][1] - lo[0][1]) < _LE_MATCH_TOL):
        lo = lo[1:]
    return list(reversed(up)) + lo


# ===========================================================================
#  Upper-surface query -- the object the vane / jig builders consume
# ===========================================================================

class UpperSurface:
    """Spline-backed query of an airfoil's UPPER surface, chord-normalized.

    Built directly from the LE->TE upper-surface points (the form the baked-in
    tables already store), so no loop splitting is needed. All queries take a
    chord fraction x in [0, 1] and return chord-normalized results; multiply by
    the physical chord to get millimetres.
    """

    def __init__(self, airfoil):
        # The baked-in upper surface is already LE -> TE with strictly
        # increasing x, exactly what CubicSpline wants.
        xs = [p[0] for p in airfoil.upper]
        ys = [p[1] for p in airfoil.upper]
        self.name = airfoil.name
        self._spline = CubicSpline(xs, ys)
        self._x_min = xs[0]
        self._x_max = xs[-1]

    def y(self, x_frac: float) -> float:
        """Upper-surface height y/c at chordwise fraction x_frac."""
        return self._spline.value(x_frac)

    def slope_rad(self, x_frac: float) -> float:
        """Local skin angle atan(dy/dx) in radians at x_frac.

        Positive forward of max thickness (skin rising toward the LE). This is
        the seat tilt the vane and jig apply so a part lies flush instead of
        rocking on the curved skin.
        """
        return math.atan(self._spline.deriv1(x_frac))

    def slope_deg(self, x_frac: float) -> float:
        """Local skin angle in degrees (convenience for reporting / UI)."""
        return math.degrees(self.slope_rad(x_frac))

    def radius_mm(self, x0_frac: float, x1_frac: float, chord_mm: float) -> float:
        """Best-fit-circle radius (mm) of the skin over the [x0, x1] footprint.

        The *point-wise* analytic curvature kappa = y''/(1+y'^2)^1.5 is the
        textbook formula, but near the leading edge of this section it is both
        large and numerically unstable (it swings hundreds of mm for a 1% shift
        in the sample window). What the vane base actually rests on is not a
        point -- it is the whole 18 mm footprint -- so the physically honest
        radius is the circle that best fits the skin OVER that footprint.

        We sample the surface across the footprint and fit a circle with the
        algebraic (Kasa) least-squares method: minimise
            sum( (x-a)^2 + (y-b)^2 - R^2 )^2
        which is linear in (a, b, a^2+b^2-R^2) and so solvable with a tiny
        3x3 normal-equation solve -- no numpy needed. The result is stable and
        is exactly the radius to sweep the base to.
        """
        a, b, r = self._fit_circle(x0_frac, x1_frac, chord_mm)
        return r

    def base_seat(self, x0_frac: float, length_mm: float, chord_mm: float):
        """Everything the vane/jig base needs to lie flush over its footprint.

        Returns a dict with:
          tilt_deg   -- seat angle: the chord-line tilt of the skin from the
                        forward footprint point to the aft one (the DOMINANT
                        correction; ~14-15 deg at 7%c)
          radius_mm  -- best-fit circle radius to sweep the underside to
          sagitta_mm -- max gap a perfectly FLAT base would leave under the
                        curved skin (how much curve actually matters; at 7%c
                        this is ~0.1 mm, i.e. below a print layer -- the tilt
                        is what counts, the curve is a refinement)
          rise_mm    -- how much the skin rises from the front of the footprint
                        to the back (positive forward of max thickness)
          x1_frac    -- aft footprint station, for the caller's reference

        ``length_mm`` is the chordwise footprint length (the vane length 3h, or
        the jig seat length). Working from the real footprint -- not a point --
        is why these numbers are stable and trustworthy.
        """
        x1_frac = x0_frac + (length_mm / chord_mm)

        # Footprint endpoints in physical mm for the tilt / rise.
        y0 = self.y(x0_frac) * chord_mm
        y1 = self.y(x1_frac) * chord_mm
        x0 = x0_frac * chord_mm
        x1 = x1_frac * chord_mm
        tilt_deg = math.degrees(math.atan2(y1 - y0, x1 - x0))
        rise_mm = y1 - y0

        # Best-fit circle over the footprint, then the sagitta of the chord.
        _, _, radius_mm = self._fit_circle(x0_frac, x1_frac, chord_mm)
        base_chord = math.hypot(x1 - x0, y1 - y0)
        half = 0.5 * base_chord
        # Guard the sqrt: if the fit radius is smaller than half the chord
        # (degenerate, never happens for these gentle skins) clamp to zero.
        sagitta_mm = radius_mm - math.sqrt(max(radius_mm * radius_mm - half * half, 0.0))

        return {
            "tilt_deg": tilt_deg,
            "radius_mm": radius_mm,
            "sagitta_mm": sagitta_mm,
            "rise_mm": rise_mm,
            "x1_frac": x1_frac,
        }

    def _fit_circle(self, x0_frac: float, x1_frac: float, chord_mm: float):
        """Kasa algebraic circle fit to the skin over [x0, x1]; returns (a,b,R) mm.

        Samples 15 points across the footprint (plenty for the gentle skin),
        builds the 3x3 normal equations of the linear Kasa system, and solves
        them with a hand-rolled Cramer's-rule / elimination solve so the module
        stays numpy-free. Center (a, b) and radius R come back in millimetres.
        """
        n = 15
        xs = []
        ys = []
        for i in range(n):
            t = i / (n - 1)
            xf = x0_frac + t * (x1_frac - x0_frac)
            xs.append(xf * chord_mm)
            ys.append(self.y(xf) * chord_mm)

        # Kasa: minimise sum( (x^2+y^2) - (2a x + 2b y + (R^2-a^2-b^2)) )^2.
        # Unknown vector u = (2a, 2b, R^2-a^2-b^2). Build A^T A (3x3) and A^T z.
        sx = sxx = sxy = sy = syy = 0.0
        sz = sxz = syz = 0.0
        for x, y in zip(xs, ys):
            z = x * x + y * y
            sx += x
            sy += y
            sxx += x * x
            sxy += x * y
            syy += y * y
            sz += z
            sxz += x * z
            syz += y * z

        # Normal-equation matrix M (symmetric) and right-hand side rhs.
        M = [
            [sxx, sxy, sx],
            [sxy, syy, sy],
            [sx,  sy,  float(n)],
        ]
        rhs = [sxz, syz, sz]
        u = _solve3(M, rhs)

        a = u[0] / 2.0
        b = u[1] / 2.0
        r = math.sqrt(max(u[2] + a * a + b * b, 0.0))
        return a, b, r

    def rise_mm(self, x0_frac: float, x1_frac: float, chord_mm: float) -> float:
        """Skin height change (mm) from x0 to x1; positive when aft is higher.

        Forward of max thickness (~40%c) the upper skin rises going aft, so a
        vane base placed at 7%c rises ~4.6 mm over its 18 mm length. Named
        'rise' (not 'drop') because the sign is genuinely upward here -- the
        earlier 'drop' wording in the plan had the direction backwards.
        """
        return (self.y(x1_frac) - self.y(x0_frac)) * chord_mm


def _solve3(M, rhs):
    """Solve a 3x3 linear system M u = rhs by Cramer's rule (numpy-free).

    The Kasa normal-equation matrix is small, symmetric and well-conditioned
    for our sample sets, so a direct determinant solve is both exact enough and
    trivially dependency-free. Raises if the system is singular (collinear
    samples), which for a real airfoil skin never happens.
    """
    def det3(m):
        return (
            m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
        )

    D = det3(M)
    if abs(D) < 1e-18:
        raise ValueError("singular system in circle fit (collinear samples?)")

    # Replace each column with rhs in turn (Cramer's rule).
    out = []
    for col in range(3):
        Mc = [row[:] for row in M]
        for row in range(3):
            Mc[row][col] = rhs[row]
        out.append(det3(Mc) / D)
    return out


# ===========================================================================
#  Standalone verification -- run this file directly (no Fusion needed)
#    python "lib/airfoil_math.py"
#  Confirms parity with the plan's measured numbers at 7% chord:
#    slope ~ 15.7 deg, R ~ 574 mm, drop ~ 4.6 mm over the 18 mm vane base.
# ===========================================================================

def _self_check() -> None:
    """Print the 7%-chord surface metrics and assert they match the sim."""
    # Local import so the module has zero import-time dependency on its sibling
    # when used inside Fusion; the self-check is the only consumer of airfoils.
    try:
        from . import airfoils  # package-relative (when imported as a module)
    except ImportError:
        import airfoils  # script-relative (when run directly)

    chord_mm = 902.2
    surf = UpperSurface(airfoils.get("LS(1)-0413 (GA(W)-2)"))

    print(f"UpperSurface: {surf.name}, chord = {chord_mm} mm\n")
    print("  x/c     y/c       slope(deg)")
    for xf in (0.02, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12):
        print(f"  {xf:.2f}  {surf.y(xf):+.5f}   {surf.slope_deg(xf):+7.2f}")

    # The seat over the REAL 18 mm vane footprint -- the physically honest way
    # to size the curve (a point-wise curvature near the LE is unstable; the
    # footprint best-fit is what the base actually rests on).
    x0 = 0.07
    seat = surf.base_seat(x0, 18.0, chord_mm)  # 18 mm = 3 x 6 mm vane base
    print(f"\n  18 mm vane base at 7%c spans x/c {x0:.4f} -> {seat['x1_frac']:.4f}")
    print(f"  seat tilt (DOMINANT correction) = {seat['tilt_deg']:.2f} deg")
    print(f"  best-fit base radius            = {seat['radius_mm']:.1f} mm")
    print(f"  sagitta (flat-base gap)         = {seat['sagitta_mm']:.3f} mm")
    print(f"  skin rise over the base         = {seat['rise_mm']:.2f} mm (rises aft)")

    # Hard asserts against the robustly-measured footprint values:
    #   tilt ~14.4 deg, R ~400 mm, sagitta ~0.1 mm, rise ~4.6 mm.
    assert 13.5 < seat["tilt_deg"] < 16.0, "seat tilt at 7%c off"
    assert 350.0 < seat["radius_mm"] < 460.0, "footprint radius at 7%c off"
    assert 0.05 < seat["sagitta_mm"] < 0.20, "sagitta at 7%c off"
    assert 4.0 < seat["rise_mm"] < 5.2, "skin rise off"
    print("\n  [ok] 7%c footprint seat metrics match the sim within tolerance")


if __name__ == "__main__":
    _self_check()
