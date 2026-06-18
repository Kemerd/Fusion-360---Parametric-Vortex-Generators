# -*- coding: utf-8 -*-
"""
Build the parametric placement-jig tile, with the auto-fit fallback ladder.

THE JIG, IN ONE SENTENCE: a flat tile you register off the wing's leading edge,
that drops the delta vanes onto the chord line at the exact chord station and
spacing, which you print and leapfrog down the span.

The geometry has three jobs:
  1. LEADING-EDGE HOOK -- a lip that wraps over the wing nose so the tile
     locates from the front and cannot slide chordwise.
  2. CHORD-LINE SEAT -- the underside is tilted to the local skin so the tile
     lies flush and the vane pockets land at the right station.
  3. VG POCKETS -- negative slots that hold each delta vane at the correct
     chordwise position and toe angle while the glue sets.
  4. SIDE KEYS -- a male/female edge key so consecutive placements butt
     together and keep spacing continuous as you step down the span.

THE FALLBACK LADDER (plan_jig, pure computation -- no Fusion, unit-testable):
  Given the requested pairs, spacing, and the user's printer bed, decide what
  to actually build, degrading gracefully and NEVER silently truncating:
    1. all requested pairs fit          -> build them
    2. too long for the bed             -> build the most pairs that DO fit,
                                           and report how many were dropped
    3. not even one pair fits           -> build a single-vane tile
    4. a single-vane tile still too big -> split into dovetailed halves
  Every rung returns a human-readable note so the dialog can tell the user
  exactly what happened.
"""

import math

import adsk.core
import adsk.fusion

from .. import config
from . import fusion_util as fu


# Fixed tile proportions (mm). These are layout constants, not user knobs --
# they set how much material surrounds the pockets and the hook.
_TILE_MARGIN = 8.0       # material ahead of / behind the pocket band (chordwise)
_TILE_SIDE_MARGIN = 6.0  # material outboard of the end pockets (spanwise)
_TILE_THICK = 4.0        # legacy slab thickness (kept for the fit ladder math)
_POCKET_CLEAR = 0.15     # pocket-to-vane clearance per side (slip fit)

# Jig block sizing (mm / fraction). The block is the wing foil's bounding box
# grown by WRAP_CLEAR on every side (top, bottom, and ahead of the LE), going
# back WRAP_DEPTH_FRAC of the chord; the wing foil is then subtracted, leaving a
# square block with a foil-shaped C-channel that hooks over the leading edge.
WRAP_CLEAR = 10.0        # clearance around the foil (above, below, ahead of LE)
WRAP_DEPTH_FRAC = 0.25   # how far back the block reaches (fraction of chord)

# Vane-slot cutter span (kept generous so the straight-down cut always passes
# fully through the block regardless of local thickness).
SHELL_WALL = 16.0


class JigPlan:
    """The decided build after the fallback ladder; consumed by build_jig().

    pairs_built   -- counter-rotating pairs actually placed on this tile
    single_vane   -- True when we fell back to a one-vane tile (rung 3)
    split_halves  -- True when even that won't fit and we dovetail-split (rung 4)
    tile_len_mm   -- chordwise length of the tile as built
    tile_wid_mm   -- spanwise width of the tile as built
    note          -- human-readable explanation of what happened and why
    dropped_pairs -- requested-minus-built (for the 'run again' message)
    """

    def __init__(self, pairs_built, single_vane, split_halves,
                 tile_len_mm, tile_wid_mm, note, dropped_pairs):
        self.pairs_built = pairs_built
        self.single_vane = single_vane
        self.split_halves = split_halves
        self.tile_len_mm = tile_len_mm
        self.tile_wid_mm = tile_wid_mm
        self.note = note
        self.dropped_pairs = dropped_pairs


def _tile_span_for_pairs(pairs, spacing_mm, vane_len_mm):
    """Spanwise width a tile needs to hold `pairs` counter-rotating pairs.

    The two vanes of a pair sit half a spacing apart; pairs are one spacing
    apart center-to-center. So N pairs occupy (N-1)*spacing between pair
    centers plus the half-spacing split within the end pairs, plus the side
    margins. Spanwise width is what the bed limits (the tile is long across
    the span, short chordwise).
    """
    if pairs <= 0:
        return 0.0
    # Centers of the outermost pair vanes span (N-1)*spacing + half-spacing.
    vane_spread = (pairs - 1) * spacing_mm + 0.5 * spacing_mm
    return vane_spread + 2.0 * _TILE_SIDE_MARGIN


def _single_vane_span(vane_thick_mm):
    """Spanwise width of a ONE-VANE tile: just the vane + clearance + margins.

    A single-vane tile is genuinely narrower than a pair tile -- it holds one
    vane, with no half-spacing split between two. This is what makes the
    'fall back to a single vane' rung meaningfully smaller than 'one pair',
    so it is reachable before we resort to splitting the tile.
    """
    return vane_thick_mm + 2.0 * _POCKET_CLEAR + 2.0 * _TILE_SIDE_MARGIN


def _tile_len(vane_len_mm, le_hook_mm):
    """Chordwise tile length: pocket band + margins + the LE hook reach."""
    return vane_len_mm + 2.0 * _TILE_MARGIN + le_hook_mm


def _fits_bed(tile_len_mm, tile_wid_mm, bed_x_mm, bed_y_mm):
    """True if a tile_len x tile_wid rectangle fits the bed in EITHER orientation.

    The user can rotate the tile 90 deg on the plate, so a rectangle fits when
    its long side is within the bed's long side AND its short side within the
    bed's short side. Comparing sorted (long, short) pairs captures both
    orientations in one check -- this is the single honest fit predicate the
    whole ladder rests on.
    """
    t_long, t_short = max(tile_len_mm, tile_wid_mm), min(tile_len_mm, tile_wid_mm)
    b_long, b_short = max(bed_x_mm, bed_y_mm), min(bed_x_mm, bed_y_mm)
    return t_long <= b_long and t_short <= b_short


def plan_jig(req_pairs, spacing_mm, vane_len_mm, vane_thick_mm, le_hook_mm,
             bed_x_mm, bed_y_mm):
    """Run the fallback ladder; return a JigPlan. Pure computation.

    The tile's CHORDWISE length is fixed by the vane + hook; the SPANWISE width
    grows with the pair count. We fit the spanwise width to the larger bed axis
    (you orient the long tile along the bigger bed dimension) and the chordwise
    length to the smaller one.

    The ladder degrades in strictly decreasing tile size: all pairs -> fewer
    pairs -> a SINGLE-VANE tile (genuinely narrower than one pair, since it
    drops the half-spacing split) -> split into dovetailed halves. Each rung is
    reachable because each is smaller than the one above it.
    """
    tile_len = _tile_len(vane_len_mm, le_hook_mm)
    single_wid = _single_vane_span(vane_thick_mm)

    # Rungs 1-2: fit as many requested pairs as the bed allows (either
    # orientation). The tile width grows with pair count; the length is fixed.
    fit_pairs = req_pairs
    while fit_pairs > 0:
        wid = _tile_span_for_pairs(fit_pairs, spacing_mm, vane_len_mm)
        if _fits_bed(tile_len, wid, bed_x_mm, bed_y_mm):
            break
        fit_pairs -= 1

    if fit_pairs == req_pairs and fit_pairs >= 1:
        # Rung 1: everything fits.
        wid = _tile_span_for_pairs(fit_pairs, spacing_mm, vane_len_mm)
        return JigPlan(
            pairs_built=fit_pairs, single_vane=False, split_halves=False,
            tile_len_mm=tile_len, tile_wid_mm=wid,
            note=f"Built all {fit_pairs} requested pair(s); tile "
                 f"{tile_len:.0f} x {wid:.0f} mm fits the bed.",
            dropped_pairs=0,
        )

    if fit_pairs >= 1:
        # Rung 2: fewer pairs than asked -- report the shortfall, no silent cut.
        wid = _tile_span_for_pairs(fit_pairs, spacing_mm, vane_len_mm)
        dropped = req_pairs - fit_pairs
        return JigPlan(
            pairs_built=fit_pairs, single_vane=False, split_halves=False,
            tile_len_mm=tile_len, tile_wid_mm=wid,
            note=f"Requested {req_pairs} pairs but the bed fits {fit_pairs}; "
                 f"built {fit_pairs}. Run again to place the remaining "
                 f"{dropped} pair(s) further down the span.",
            dropped_pairs=dropped,
        )

    # Rung 3: not even one pair fits -> single-vane tile, which is narrower than
    # a pair (no half-spacing split) and so may still fit when a pair did not.
    if _fits_bed(tile_len, single_wid, bed_x_mm, bed_y_mm):
        return JigPlan(
            pairs_built=0, single_vane=True, split_halves=False,
            tile_len_mm=tile_len, tile_wid_mm=single_wid,
            note=f"A full pair won't fit the bed at {spacing_mm:.0f} mm "
                 f"spacing; built a narrower single-vane tile instead. Place "
                 f"vanes one at a time, stepping {spacing_mm:.0f} mm each move.",
            dropped_pairs=req_pairs,
        )

    # Rung 4: even the single-vane tile won't fit (its FIXED chordwise length
    # busts the bed) -> dovetail split so each half prints and clicks together.
    return JigPlan(
        pairs_built=0, single_vane=True, split_halves=True,
        tile_len_mm=tile_len, tile_wid_mm=single_wid,
        note=f"Even a single-vane tile ({tile_len:.0f} x {single_wid:.0f} mm) "
             f"won't fit the bed -- splitting into dovetailed halves that print "
             f"separately and click together.",
        dropped_pairs=req_pairs,
    )


# ===========================================================================
#  Fusion geometry
# ===========================================================================

def build_jig(design, params, seat, surf, jig_plan, name="VG Jig"):
    """Create the jig tile body per the decided JigPlan; return the body.

    :param surf: airfoil_math.UpperSurface, for the LE-hook nose profile
    :param jig_plan: the JigPlan from plan_jig()
    """
    vane_len = params["vane_len_ratio"] * params["vane_height_mm"]
    vane_h = params["vane_height_mm"]
    vane_t = params["vane_thick_mm"]
    spacing = params["jig_spacing_mm"]
    toe = params["vane_toe_deg"]
    chord = params["chord_len_mm"]
    x_frac = params["chord_pos_pct"] / 100.0

    occ = fu.new_component(design, name)
    comp = occ.component

    half_w = 0.5 * jig_plan.tile_wid_mm

    # ---- the jig block: box minus wing foil ----------------------------------
    # A square block sized to the foil's bounding box + 10 mm clearance, reaching
    # back 25% of the chord, with the wing foil subtracted -- leaving a block
    # with a foil-shaped C-channel that hooks over the leading edge. Frame:
    # x = chordwise (+x aft), z = up; station-centered so the 7%c line is x = 0.
    tile_body = _build_wrap_shell(comp, surf, params, half_w, x_frac, chord, name)

    # ---- vane slots cut straight down at the 7%c line -------------------------
    # The 7%c line is x = 0 (station-centered). Each vane slot is the flange
    # triangle, CENTERED on x = 0, toed, and cut straight DOWN through the block
    # so the vanes drop in from the top exactly on the 7% chord line.
    flange_half_w = max(vane_t, 0.6 * vane_h)
    flange_pad = max(2.0, 0.5 * vane_h)
    pocket_centers = _pocket_layout(jig_plan, spacing)
    for y_center, toe_sign in pocket_centers:
        _cut_vane_slot(comp, tile_body, vane_len, flange_half_w, flange_pad,
                       y_center, toe * toe_sign)

    # ---- side registration keys ---------------------------------------------
    _build_side_keys(comp, tile_body, vane_len, half_w)

    # ---- dovetail split (rung 4 only) ---------------------------------------
    if jig_plan.split_halves:
        _split_dovetail(comp, tile_body, jig_plan, params)

    return tile_body


def _pocket_layout(jig_plan, spacing):
    """Return [(y_center_mm, toe_sign), ...] for every vane pocket to cut.

    Pairs are centered on y = 0 and spread symmetrically; the two vanes of a
    pair sit +/- a quarter spacing from the pair center with opposite toe.
    A single-vane tile cuts exactly one centered pocket.
    """
    if jig_plan.single_vane:
        return [(0.0, +1.0)]

    centers = []
    n = jig_plan.pairs_built
    # Pair centers symmetric about 0: e.g. 2 pairs -> -spacing/2, +spacing/2.
    first = -0.5 * (n - 1) * spacing
    for p in range(n):
        pair_c = first + p * spacing
        # Two vanes a quarter-spacing apart, opposite toe (toe-out pair).
        centers.append((pair_c - 0.25 * spacing, +1.0))
        centers.append((pair_c + 0.25 * spacing, -1.0))
    return centers


def _cut_vane_slot(comp, tile_body, vane_len, flange_half_w, flange_pad,
                   y_center, toe_deg):
    """Cut one toed vane slot STRAIGHT DOWN through the shell top.

    The slot footprint is the vane's bottom flange triangle (paper-airplane:
    WIDE at the LE, tapering to a POINT aft) -- that is exactly the cross-section
    the vane presents when you push it down into the jig. We sketch that triangle
    on the z = 0 chord plane (centered at the 7%c station, toed about its own
    center) and extrude it as a tall cutter spanning the whole shell height, then
    subtract -- so the slot passes cleanly through the conformal top, giving a
    through-slot the vane drops into from above.

    Cutting straight down (global -z), not normal to the curved skin, is correct:
    the vane stands vertically off the wing, so its slot is vertical too.
    """
    hw = flange_half_w + _POCKET_CLEAR

    # Flange triangle on the chord plane (z = 0), MATCHING the vane flange and
    # CENTERED on the 7%c line (x = 0): POINT at the LE side (-x, into the flow),
    # WIDENING toward the aft side (+x). The vane footprint is vane_len long, so
    # it runs from -vane_len/2 (point) to +vane_len/2 (wide), centered on x = 0.
    x_pt = -0.5 * vane_len - flange_pad     # sharp point, LE side
    x_wide = 0.5 * vane_len + flange_pad    # wide base, aft side
    sk = fu.sketch_on_plane(comp, comp.xYConstructionPlane)
    tri_pts = [
        (x_pt, y_center),
        (x_wide, y_center - hw),
        (x_wide, y_center + hw),
    ]
    prof = fu.closed_polyline(sk, tri_pts)

    # Tall cutter spanning well above and below the block so the straight-down
    # cut always passes fully through. Symmetric about z = 0.
    cut_h = 8.0 * SHELL_WALL + 200.0
    cutter = fu.extrude(comp, prof, cut_h, symmetric=True,
                        operation=adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    tool = cutter.bodies.item(0)

    # Toe the cutter about a vertical axis through the 7%c line (x = 0).
    if toe_deg:
        origin = adsk.core.Point3D.create(0.0, y_center * config.MM, 0.0)
        z_axis = adsk.core.Vector3D.create(0.0, 0.0, 1.0)
        rot = adsk.core.Matrix3D.create()
        rot.setToRotation(math.radians(toe_deg), z_axis, origin)
        fu.move_body(comp, tool, rot)

    fu.combine(comp, tile_body, [tool],
               adsk.fusion.FeatureOperations.CutFeatureOperation)


def _build_wrap_shell(comp, surf, params, half_w, x_frac, chord, name):
    """Build the jig block: a box minus the wing foil. Return its body.

    EXACT RECIPE (the simple, correct one):
      1. Take the full wing foil section.
      2. Box HEIGHT: top = foil's highest z + CLEAR, bottom = foil's lowest z -
         CLEAR (so the box is foil_height + 2*CLEAR tall, centered on the foil).
      3. Box FORE-AFT: front edge = foil's least x (the leading edge) - CLEAR
         (hugs CLEAR mm ahead of the nose); depth = WRAP_DEPTH_FRAC of the chord
         back from there (default 25% chord).
      4. SUBTRACT the wing foil solid from the box.
    What remains is a square block with a foil-shaped C-channel cut into its
    front -- you hook it over the leading edge and it grips the nose. The VG
    slots are cut into the top afterwards (build_jig).

    Frame: x = chordwise (+x aft), z = up, station-centered so the 7%c station
    sits at x = 0, z = 0 (shared with the vane + example wing).
    """
    from . import airfoils

    af = airfoils.get(params["airfoil"])
    x_station_mm = x_frac * chord
    y_skin_station = surf.y(x_frac) * chord

    # Full foil loop in station-centered mm (x chordwise, z up).
    full_loop = [((x * chord - x_station_mm), (y * chord - y_skin_station))
                 for (x, y) in _full_airfoil_loop(af)]
    xs = [p[0] for p in full_loop]
    zs = [p[1] for p in full_loop]

    # Foil extremes.
    x_le = min(xs)                      # least x = the leading edge
    z_top = max(zs)                     # highest point of the foil
    z_bot = min(zs)                     # lowest point of the foil

    # Box per the recipe.
    bx0 = x_le - WRAP_CLEAR                       # CLEAR mm ahead of the LE
    bx1 = bx0 + WRAP_DEPTH_FRAC * chord           # back 25% of the chord
    bz0 = z_bot - WRAP_CLEAR                      # CLEAR below the lowest point
    bz1 = z_top + WRAP_CLEAR                      # CLEAR above the highest point
    box_pts = [(bx0, bz0), (bx1, bz0), (bx1, bz1), (bx0, bz1)]

    sk_b = fu.sketch_on_plane(comp, comp.xZConstructionPlane)
    prof_b = fu.closed_polyline(sk_b, box_pts)
    span = 2.0 * half_w
    box = fu.extrude(comp, prof_b, span, symmetric=True)
    cap_body = box.bodies.item(0)
    cap_body.name = name

    # Solid WING tool (full section), extruded wider than the box so the cut is
    # clean across the whole span.
    sk_w = fu.sketch_on_plane(comp, comp.xZConstructionPlane)
    prof_w = fu.closed_polyline(sk_w, full_loop)
    wing = fu.extrude(comp, prof_w, span + 20.0, symmetric=True,
                      operation=adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    wing_tool = wing.bodies.item(0)

    # Subtract the foil from the box -> block with a foil-shaped C-channel.
    fu.combine(comp, cap_body, [wing_tool],
               adsk.fusion.FeatureOperations.CutFeatureOperation)
    return cap_body


def _full_airfoil_loop(af):
    """Full closed airfoil loop (upper TE->LE then lower LE->TE) for a solid."""
    # Upper reversed (TE->LE), then lower LE->TE skipping the duplicate nose.
    return list(reversed(af.upper)) + af.lower[1:]




def _build_side_keys(comp, tile_body, vane_len, half_w):
    """Add a male tab on +y and a female notch on -y for tile-to-tile butting.

    The tab and notch are the same nominal size; the notch carries a small
    clearance so adjacent tiles seat without forcing. Keeping them on opposite
    ends lets you chain identical tiles down the span. Both are extruded as a
    TALL symmetric band about z = 0 so they fully intersect the conformal shell
    wherever it is; the boolean clips them to the actual shell body.
    """
    key_w = 8.0
    key_d = 4.0
    x_mid = 0.5 * vane_len
    tall = 4.0 * SHELL_WALL + 40.0   # spans the whole shell vertically

    # Male tab on +y edge.
    sk1 = fu.sketch_on_plane(comp, comp.xYConstructionPlane)
    tab_pts = [
        (x_mid - 0.5 * key_w, half_w),
        (x_mid + 0.5 * key_w, half_w),
        (x_mid + 0.5 * key_w, half_w + key_d),
        (x_mid - 0.5 * key_w, half_w + key_d),
    ]
    tab = fu.extrude(comp, fu.closed_polyline(sk1, tab_pts), tall, symmetric=True)
    fu.combine(comp, tile_body, [tab.bodies.item(0)],
               adsk.fusion.FeatureOperations.JoinFeatureOperation)

    # Female notch on -y edge (slightly oversized for clearance).
    clr = 0.2
    sk2 = fu.sketch_on_plane(comp, comp.xYConstructionPlane)
    notch_pts = [
        (x_mid - 0.5 * key_w - clr, -half_w),
        (x_mid + 0.5 * key_w + clr, -half_w),
        (x_mid + 0.5 * key_w + clr, -half_w + key_d + clr),
        (x_mid - 0.5 * key_w - clr, -half_w + key_d + clr),
    ]
    notch = fu.extrude(comp, fu.closed_polyline(sk2, notch_pts), tall,
                       symmetric=True,
                       operation=adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    fu.combine(comp, tile_body, [notch.bodies.item(0)],
               adsk.fusion.FeatureOperations.CutFeatureOperation)


def _split_dovetail(comp, tile_body, jig_plan, params):
    """Cut the tile into two halves with an interlocking dovetail on the seam.

    The split plane is spanwise mid-tile (y = 0). A dovetail key profile is
    swept along the seam so the two halves mechanically interlock (glue
    optional). The dovetail clearance is a user parameter tuned for ABS fit.
    The trapezoid spans a tall band about z = 0 so it keys the whole shell.
    """
    clr = params["dovetail_clear_mm"]
    # A dovetail seam is cut by removing a thin trapezoidal slot down the seam.
    # The trapezoid is wide at the top (z = +band) and narrow at the bottom
    # (z = -band) so the two halves mechanically key together; the band is tall
    # enough to cross the whole conformal shell.
    dt_w = 10.0          # dovetail mouth width
    dt_neck = 6.0        # dovetail neck (narrower -> interlock)
    band = 2.0 * SHELL_WALL + 20.0

    sk = fu.sketch_on_plane(comp, comp.yZConstructionPlane)
    half_mouth = 0.5 * dt_w + clr
    half_neck = 0.5 * dt_neck + clr
    dt_pts = [
        (-half_mouth, band),
        (half_mouth, band),
        (half_neck, -band),
        (-half_neck, -band),
    ]
    prof = fu.closed_polyline(sk, dt_pts)
    # Sweep the dovetail tool the full chordwise length of the tile.
    length = jig_plan.tile_len_mm + 10.0
    tool = fu.extrude(comp, prof, length, symmetric=True,
                      operation=adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    # Cutting the tool leaves a dovetail channel; the user prints both halves
    # and the dovetail key (printed with the tile or separately) joins them.
    fu.combine(comp, tile_body, [tool.bodies.item(0)],
               adsk.fusion.FeatureOperations.CutFeatureOperation)
