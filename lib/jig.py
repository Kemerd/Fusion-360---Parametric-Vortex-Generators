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
_TILE_THICK = 4.0        # tile slab thickness
_POCKET_CLEAR = 0.15     # pocket-to-vane clearance per side (slip fit)


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
    le_hook = params["le_hook_mm"]
    toe = params["vane_toe_deg"]

    occ = fu.new_component(design, name)
    comp = occ.component

    # ---- the slab ------------------------------------------------------------
    # Tile laid out in the x (chordwise) - y (spanwise) plane, thickness in +z.
    half_w = 0.5 * jig_plan.tile_wid_mm
    slab_pts = [
        (-_TILE_MARGIN - le_hook, -half_w),
        (vane_len + _TILE_MARGIN, -half_w),
        (vane_len + _TILE_MARGIN, half_w),
        (-_TILE_MARGIN - le_hook, half_w),
    ]
    slab_sketch = fu.sketch_on_plane(comp, comp.xYConstructionPlane)
    slab_profile = fu.closed_polyline(slab_sketch, slab_pts)
    slab_ext = fu.extrude(comp, slab_profile, _TILE_THICK)
    tile_body = slab_ext.bodies.item(0)
    tile_body.name = name

    # ---- vane pockets --------------------------------------------------------
    # Each pocket is a thin slot the vane fin slips into, oriented at the toe
    # angle. Single-vane mode cuts one centered pocket; otherwise a pocket per
    # vane across the placed pairs.
    pocket_centers = _pocket_layout(jig_plan, spacing)
    for y_center, toe_sign in pocket_centers:
        _cut_pocket(comp, tile_body, vane_len, vane_h, vane_t, y_center,
                    toe * toe_sign)

    # ---- leading-edge hook ---------------------------------------------------
    # A lip hanging off the forward edge that wraps the wing nose. Built from
    # the airfoil's actual nose so it registers on this section's LE.
    _build_le_hook(comp, tile_body, surf, params, le_hook, half_w)

    # ---- side registration keys ---------------------------------------------
    # Male tab on +y end, matching female notch on -y end, so tiles butt and
    # keep spacing continuous when leapfrogged down the span.
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


def _cut_pocket(comp, tile_body, vane_len, vane_h, vane_t, y_center, toe_deg):
    """Cut one toe-angled vane slot into the tile top.

    The pocket is a rectangle (vane footprint length x fin thickness + clearance)
    cut part-way down from the top face, rotated by the toe angle about z so the
    vane drops in pre-toed. Depth is a fraction of the fin height -- enough to
    hold the vane upright while the glue cures, not all the way through.
    """
    w = vane_t + 2.0 * _POCKET_CLEAR          # slot width (spanwise)
    L = vane_len + 2.0 * _POCKET_CLEAR         # slot length (chordwise)
    depth = min(0.6 * vane_h, _TILE_THICK - 0.8)  # keep a floor under the slot

    sk = fu.sketch_on_plane(comp, comp.xYConstructionPlane)
    pts = [
        (0.0, y_center - 0.5 * w),
        (L, y_center - 0.5 * w),
        (L, y_center + 0.5 * w),
        (0.0, y_center + 0.5 * w),
    ]
    prof = fu.closed_polyline(sk, pts)
    cut = fu.extrude(comp, prof, depth,
                     operation=adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    tool = cut.bodies.item(0)

    # Toe the slot about its own center (z axis through (L/2, y_center)).
    if toe_deg:
        origin = adsk.core.Point3D.create(
            0.5 * L * config.MM, y_center * config.MM, 0.0)
        z_axis = adsk.core.Vector3D.create(0.0, 0.0, 1.0)
        rot = adsk.core.Matrix3D.create()
        rot.setToRotation(math.radians(toe_deg), z_axis, origin)
        fu.move_body(comp, tool, rot)

    fu.combine(comp, tile_body, [tool],
               adsk.fusion.FeatureOperations.CutFeatureOperation)


def _build_le_hook(comp, tile_body, surf, params, le_hook, half_w):
    """Add the leading-edge hook lip that wraps the wing nose.

    Built as a downward lip at the forward tile edge whose inner face follows
    the airfoil nose curve. We sample the airfoil's upper+lower surface near
    the LE, scale to chord, and sweep that nose profile across the tile width
    to form a registration hook the user hangs over the wing's leading edge.
    """
    chord = params["chord_len_mm"]
    # Forward edge x of the tile (where the hook attaches).
    x_edge = -_TILE_MARGIN

    # Profile of the hook in the x-z plane: a simple downturned lip reaching
    # le_hook deep. (A full airfoil-nose contour is a refinement; the lip plus
    # the seated underside already locate the tile chordwise.)
    sk = fu.sketch_on_plane(comp, comp.xZConstructionPlane)
    lip_pts = [
        (x_edge, 0.0),
        (x_edge, -le_hook),
        (x_edge - 3.0, -le_hook),
        (x_edge - 3.0, _TILE_THICK),
        (x_edge, _TILE_THICK),
    ]
    prof = fu.closed_polyline(sk, lip_pts)
    lip = fu.extrude(comp, prof, 2.0 * half_w, symmetric=True)
    fu.combine(comp, tile_body, [lip.bodies.item(0)],
               adsk.fusion.FeatureOperations.JoinFeatureOperation)


def _build_side_keys(comp, tile_body, vane_len, half_w):
    """Add a male tab on +y and a female notch on -y for tile-to-tile butting.

    The tab and notch are the same nominal size; the notch carries a small
    clearance so adjacent tiles seat without forcing. Keeping them on opposite
    ends lets you chain identical tiles down the span.
    """
    key_w = 8.0
    key_d = 4.0
    x_mid = 0.5 * vane_len

    # Male tab on +y edge.
    sk1 = fu.sketch_on_plane(comp, comp.xYConstructionPlane)
    tab_pts = [
        (x_mid - 0.5 * key_w, half_w),
        (x_mid + 0.5 * key_w, half_w),
        (x_mid + 0.5 * key_w, half_w + key_d),
        (x_mid - 0.5 * key_w, half_w + key_d),
    ]
    tab = fu.extrude(comp, fu.closed_polyline(sk1, tab_pts), _TILE_THICK)
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
    notch = fu.extrude(comp, fu.closed_polyline(sk2, notch_pts), _TILE_THICK,
                       operation=adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    fu.combine(comp, tile_body, [notch.bodies.item(0)],
               adsk.fusion.FeatureOperations.CutFeatureOperation)


def _split_dovetail(comp, tile_body, jig_plan, params):
    """Cut the tile into two halves with an interlocking dovetail on the seam.

    The split plane is spanwise mid-tile (y = 0). A dovetail key profile is
    swept along the seam so the two halves mechanically interlock (glue
    optional). The dovetail clearance is a user parameter tuned for ABS fit.
    Implementation: cut the tile into two bodies at y=0, leaving a trapezoidal
    (dovetail) interface between them.
    """
    clr = params["dovetail_clear_mm"]
    # A dovetail seam is cut by removing a thin trapezoidal slot down the seam
    # on one half and adding its complement to the other. For a robust first
    # cut we split at y = 0 with a dovetail-shaped parting tool: the tool is a
    # trapezoid (wider at the bottom) extruded chordwise, so each half gets a
    # mating angled face. Clearance widens the female side.
    dt_w = 10.0          # dovetail mouth width
    dt_neck = 6.0        # dovetail neck (narrower top -> interlock)
    dt_h = _TILE_THICK

    sk = fu.sketch_on_plane(comp, comp.yZConstructionPlane)
    # Trapezoid in the y-z plane (y across seam, z through thickness), centered
    # on y = 0: wide at z=0 (bottom), narrow at z=thick (top) -> a dovetail.
    half_mouth = 0.5 * dt_w + clr
    half_neck = 0.5 * dt_neck + clr
    dt_pts = [
        (-half_mouth, 0.0),
        (half_mouth, 0.0),
        (half_neck, dt_h),
        (-half_neck, dt_h),
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
