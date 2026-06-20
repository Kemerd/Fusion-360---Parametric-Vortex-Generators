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

    # ---- DART geometry (paper-airplane VG, per the user's step1-4 build) ------
    # A central vertical FIN plus two flat triangular WINGS (the flange) that
    # spread from the fin's base centerline out to each side, all converging to a
    # single SHARP NOSE point at the front. From the top it reads as an arrow.
    #
    # Frame (centered on x = 0, the 7%c line):
    #   NOSE  at x = x_nose (-x, the leading edge, into the flow)
    #   BACK  at x = x_back (+x); the fin's tall vertical edge lives here
    #   z = up (fin height), y = spanwise (fin thickness / wing span)
    x_nose = -0.5 * length             # sharp nose, leading edge
    x_back = 0.5 * length              # aft end (tall fin edge + wide wings)
    fin_half_t = 0.5 * t               # fin half-thickness
    wing_span = h                      # each flat wing reaches `h` out at the back

    # ---- the central fin (side profile in x-z) -------------------------------
    # Sharp & low at the nose (x_nose, 0), rising to the tall vertical edge at
    # the back. The fin height is NEGATED (-h) so that, together with the wing's
    # negated z (see _foil_loop_mm / _build_wing), the fin points UP away from
    # the now-curved-side-up wing. Base on z = 0 (the 7%c skin line, invariant).
    fin_sketch = fu.sketch_on_plane(comp, comp.xZConstructionPlane)
    # NOTE: xZ sketch local axes: x -> sketch X, z -> sketch Y.
    fin_pts = [
        (x_nose, 0.0),     # sharp nose at the LE (z = 0)
        (x_back, 0.0),     # aft base corner
        (x_back, -h),      # tall vertical edge at the back (negated z, points up)
    ]
    fin_profile = fu.closed_polyline(fin_sketch, fin_pts)
    fin_ext = fu.extrude(comp, fin_profile, t, symmetric=True)
    fin_body = fin_ext.bodies.item(0)
    fin_body.name = "fin"

    # ---- the flat flange WINGS (top footprint in x-y) ------------------------
    # An arrow/dart outline: the single sharp NOSE at (x_nose, 0), sweeping back
    # to the full span at the back -- (x_back, +wing_span) and (x_back, -wing_span).
    # This is one triangle whose tip is the shared nose, so the fin's point and
    # the wings' point coincide exactly. Thin, extruded UP (+flange_t) so it ends
    # up on the wing-contact side of the negated-z frame.
    flange_sketch = fu.sketch_on_plane(comp, comp.xYConstructionPlane)
    flange_pts = [
        (x_nose, 0.0),                 # shared sharp nose (tips coincide)
        (x_back, wing_span),           # back, one wing tip
        (x_back, -wing_span),          # back, other wing tip
    ]
    flange_profile = fu.closed_polyline(flange_sketch, flange_pts)
    flange_ext = fu.extrude(
        comp, flange_profile, flange_t,
        operation=adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
    )
    flange_body = flange_ext.bodies.item(0)
    flange_body.name = "flange"

    # Weld fin + wings into one dart body.
    fu.combine(
        comp, fin_body, [flange_body],
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
    )
    vane_body = fin_body
    vane_body.name = name

    # ---- orient: flange flat, fin up, only TOE differs -----------------------
    # All vanes sit identically -- flange flat on z = 0, fin pointing straight up
    # -- with ONLY the toe angle distinguishing them (mirrored L/R for the
    # counter-rotating pair). No surface tilt, so they are all uniform and clean
    # (the user explicitly wanted no random leaning, and the slot is cut straight
    # down to receive a vertical vane).
    if toe_deg:
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
