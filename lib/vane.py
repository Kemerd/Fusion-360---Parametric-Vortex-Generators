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
    # CENTERED on x = 0 (the 7%c line) so it drops into the centered jig slot.
    # The TALL edge is at the LEADING edge (-x, into the flow) at full height,
    # sweeping down to a trailing point at +x. Runs -length/2 .. +length/2.
    xz_plane = comp.xZConstructionPlane
    fin_sketch = fu.sketch_on_plane(comp, xz_plane)
    # NOTE: sketch on xZ plane has local axes (x -> sketch X, z -> sketch Y).
    x_le = -0.5 * length      # leading edge, tall
    x_te = 0.5 * length       # trailing edge, point
    fin_pts = [
        (x_le, 0.0),       # base, leading edge
        (x_te, 0.0),       # base, trailing edge
        (x_le, h),         # apex at the leading edge, full height
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
    # Flange (paper-airplane footprint), CENTERED on x = 0 to match the fin and
    # the jig slot. SHARP point at the LE side (-x, into the flow), WIDENING aft
    # (+x). Runs -length/2 - pad .. +length/2 + pad. FLAT (no curve -- the user
    # chose a flat, printable vane; the ~0.14 mm surface bend is negligible).
    x_pt = -0.5 * length - pad         # sharp point, LE side
    x_wide = 0.5 * length + pad        # wide base, aft side
    flange_half_w = max(t, 0.6 * h)    # half-width of the flange in y (spanwise)
    flange_pts = [
        (x_pt, 0.0),                   # LE point (sharp, into the flow)
        (x_wide, flange_half_w),       # aft, wide -- one side
        (x_wide, -flange_half_w),      # aft, wide -- other side
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

    # ---- seat the vane to the surface: tilt, then toe ------------------------
    # FLAT vane (no base curve, per the user's choice -- easier to print). Only
    # the tilt + toe are applied so the vane sits at the local surface angle.
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
