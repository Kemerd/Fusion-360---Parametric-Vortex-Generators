# -*- coding: utf-8 -*-
"""
Build the parametric delta vortex-generator vane body.

GEOMETRY (matches the CFD-winning design and the sim's physical-vane build in
gpu/fluidx3d/make_vg_wing.py):

  * A DELTA fin: a swept triangular plate standing up off the wing. Tall at the
    leading edge (full height h), sweeping back and down to a trailing point a
    distance l = ratio * h aft. Thickness t in the spanwise direction. This is
    the actual vortex-shedding surface.

  * A thin BOTTOM FLANGE: a second, wider triangle lying flat under the fin --
    the glue tab. Its thickness (~0.8 mm) is a parameter so it can be set to a
    couple of ABS perimeters; it is the part that bonds to the wing skin.

  * The whole vane is SEATED to the local wing surface at the chosen chord
    station: tilted by the footprint seat angle (~14.4 deg at 7%c, the dominant
    correction) and its underside swept on the footprint best-fit radius
    (~396 mm) so it hugs the skin instead of rocking. Both come straight from
    airfoil_math.UpperSurface.base_seat() -- no magic numbers.

  * TOE: the vane is yawed about the surface normal by the toe angle so a
    counter-rotating pair (build_pair) mirrors cleanly, +toe and -toe.

LOCAL FRAME WHILE BUILDING (before the seat move):
  x = chordwise, leading edge at x = 0, trailing tip toward +x
  y = spanwise (vane thickness direction), fin centered on y = 0
  z = up, fin height in +z, flange just below z = 0

The fin is sketched in the x-z plane and extruded in y (its thickness), so the
delta profile is drawn exactly once and the rest is parametric extrude + a
curved-base cut + the seat transform.
"""

import math

import adsk.core
import adsk.fusion

from .. import config
from . import fusion_util as fu


def build_vane(design, params, seat, toe_sign=0.0, seat_to_surface=True,
               name="VG Vane"):
    """Create one delta vane body and return it.

    :param design:  active Fusion design
    :param params:  dict of resolved dialog values (mm / deg); see config.DEFAULTS
    :param seat:    dict from UpperSurface.base_seat() -- tilt_deg, radius_mm, ...
    :param toe_sign: -1 / 0 / +1; multiplies the toe angle (pair handedness)
    :param seat_to_surface: when True, tilt+curve the vane to the wing skin;
                    when False, leave it flat at the origin (parts-at-origin mode)
    :param name:    component / body name
    :returns: the BRepBody of the finished vane
    """
    h = params["vane_height_mm"]
    ratio = params["vane_len_ratio"]
    t = params["vane_thick_mm"]
    flange_t = params["base_flange_mm"]
    toe_deg = params["vane_toe_deg"] * toe_sign

    length = ratio * h  # delta chordwise length, l = ratio * h (3h default)

    # Expose the headline dimensions as user parameters so the body stays
    # editable from Modify > Change Parameters after generation.
    fu.set_param(design, "vg_vane_height", h, "VG delta vane height")
    fu.set_param(design, "vg_vane_length", length, "VG delta vane chord length")
    fu.set_param(design, "vg_vane_thick", t, "VG vane fin thickness")
    fu.set_param(design, "vg_base_flange", flange_t, "VG base flange thickness")

    occ = fu.new_component(design, name)
    comp = occ.component

    # ---- the delta fin --------------------------------------------------------
    # Sketch the triangular side profile in the x-z plane (y is thickness).
    # Profile: base leading corner at origin, base trailing corner at +length,
    # apex at the leading edge full height. A classic swept delta: the tall
    # edge is the leading edge, sweeping down to the trailing tip.
    xz_plane = comp.xZConstructionPlane
    fin_sketch = fu.sketch_on_plane(comp, xz_plane)
    # NOTE: sketch on xZ plane has local axes (x -> sketch X, z -> sketch Y).
    fin_pts = [
        (0.0, 0.0),        # base, leading edge
        (length, 0.0),     # base, trailing edge
        (0.0, h),          # apex at the leading edge, full height
    ]
    fin_profile = fu.closed_polyline(fin_sketch, fin_pts)
    # Extrude symmetrically about the x-z plane so the fin thickness t is
    # centered on y = 0 (keeps the pair geometry symmetric).
    fin_ext = fu.extrude(comp, fin_profile, t, symmetric=True)
    fin_body = fin_ext.bodies.item(0)
    fin_body.name = "fin"

    # ---- the thin bottom flange (glue tab) -----------------------------------
    # A wider, flatter triangle under the fin. It extends a little beyond the
    # fin footprint on each side (in x) so there is real glue area, and it sits
    # just below z = 0 so it merges with the fin base.
    pad = max(2.0, 0.5 * h)            # how far the flange oversails the fin in x
    flange_sketch = fu.sketch_on_plane(comp, comp.xYConstructionPlane)
    # Flange drawn in the x-y plane (its own footprint), thickness via extrude.
    flange_half_w = max(t, 0.6 * h)    # half-width of the flange in y (spanwise)
    flange_pts = [
        (-pad, 0.0),                   # nose of the glue triangle, ahead of LE
        (length + pad, flange_half_w), # aft, one side
        (length + pad, -flange_half_w),
    ]
    flange_profile = fu.closed_polyline(flange_sketch, flange_pts)
    # Extrude DOWN from z = 0 by the flange thickness so its top face is flush
    # with the fin base (z = 0) and the glue face is the underside.
    flange_ext = fu.extrude(
        comp, flange_profile, -flange_t,
        operation=adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
    )
    flange_body = flange_ext.bodies.item(0)
    flange_body.name = "flange"

    # Weld fin + flange into one vane body.
    fu.combine(
        comp, fin_body, [flange_body],
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
    )
    vane_body = fin_body
    vane_body.name = name

    # ---- curve the underside to the skin (gentle, ~396 mm radius) ------------
    # The sagitta is ~0.1 mm at 7%c, so this is a refinement, not the main act;
    # we cut a shallow cylinder out of the flange underside so it seats on the
    # convex skin without rocking. Skip when the radius is effectively flat.
    if seat_to_surface and seat["radius_mm"] < 5.0e3:
        _curve_underside(comp, vane_body, length, pad, seat["radius_mm"], flange_t)

    # ---- seat the vane to the surface: tilt, then toe ------------------------
    if seat_to_surface:
        _apply_seat(comp, vane_body, seat["tilt_deg"], toe_deg)
    elif toe_deg:
        # Parts-at-origin still honours toe so a printed pair is handed.
        _apply_seat(comp, vane_body, 0.0, toe_deg)

    return vane_body


def build_pair(design, params, seat, name="VG Pair", seat_to_surface=True):
    """Build a counter-rotating vane pair (+toe and -toe). Returns [body, body].

    The STOLspeed-style pair toes OUT so the two vanes pump a counter-rotating
    vortex pair down between them -- exactly the arrangement the CFD used. The
    two vanes are offset half the pair spacing apart in the spanwise direction
    by the caller (jig/assembly); here they just get opposite toe.
    """
    left = build_vane(design, params, seat, toe_sign=+1.0,
                      seat_to_surface=seat_to_surface, name=f"{name} L")
    right = build_vane(design, params, seat, toe_sign=-1.0,
                       seat_to_surface=seat_to_surface, name=f"{name} R")
    return [left, right]


# ===========================================================================
#  Internal seating helpers
# ===========================================================================

def _curve_underside(comp, body, length, pad, radius_mm, flange_t):
    """Subtract a large cylinder from the flange underside to match skin curve.

    The cylinder axis runs spanwise (y), centered one radius BELOW the flange
    base, so its top surface is the wing's convex arc. Cutting it away leaves
    the flange bottom as a matching concave arc that nests on the skin. With
    radius ~396 mm and a ~19 mm footprint the removed sagitta is ~0.1 mm.
    """
    # Build the cutting cylinder as a temporary body via a sketched circle on
    # the x-z plane, extruded spanwise well past the flange width.
    sk = fu.sketch_on_plane(comp, comp.xZConstructionPlane)
    circles = sk.sketchCurves.sketchCircles
    # Center: chordwise mid-footprint, radius below the flange underside.
    cx = 0.5 * length
    cz = -flange_t - radius_mm  # one radius below the glue face
    center = adsk.core.Point3D.create(cx * config.MM, cz * config.MM, 0.0)
    circles.addByCenterRadius(center, radius_mm * config.MM)
    circ_profile = sk.profiles.item(0)
    # Extrude the disk spanwise, symmetric, wider than the flange.
    span = 4.0 * max(pad, length)
    cyl_ext = fu.extrude(comp, circ_profile, span, symmetric=True)
    cyl_body = cyl_ext.bodies.item(0)
    # The cylinder's arc sits just under the flange; cutting it removes only
    # the thin sliver where the flat flange would otherwise overhang the arc.
    fu.combine(
        comp, body, [cyl_body],
        adsk.fusion.FeatureOperations.CutFeatureOperation,
    )


def _apply_seat(comp, body, tilt_deg, toe_deg):
    """Tilt the vane to the local skin slope, then yaw it by the toe angle.

    Two rigid rotations composed into one Matrix3D:
      1. TILT about the spanwise axis (y) by the seat angle, so the vane leans
         back to lie flush on the rising skin (the dominant correction).
      2. TOE about the surface-normal axis (z) by the toe angle, giving the
         pair its handedness.
    Order matters: tilt first (in the part's own frame), then toe.
    """
    origin = adsk.core.Point3D.create(0.0, 0.0, 0.0)
    x_axis = adsk.core.Vector3D.create(1.0, 0.0, 0.0)
    y_axis = adsk.core.Vector3D.create(0.0, 1.0, 0.0)
    z_axis = adsk.core.Vector3D.create(0.0, 0.0, 1.0)

    # Tilt about +y: a positive seat angle leans the leading edge up/back to
    # match the skin rising toward the LE. Negative because the skin rises aft.
    tilt = adsk.core.Matrix3D.create()
    tilt.setToRotation(math.radians(-tilt_deg), y_axis, origin)

    # Toe about +z (the surface normal in the local frame).
    toe = adsk.core.Matrix3D.create()
    toe.setToRotation(math.radians(toe_deg), z_axis, origin)

    # Compose: apply tilt, then toe (toe * tilt in matrix terms).
    combined = adsk.core.Matrix3D.create()
    combined.setToIdentity()
    combined.transformBy(tilt)
    combined.transformBy(toe)

    fu.move_body(comp, body, combined)
