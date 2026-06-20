# -*- coding: utf-8 -*-
"""
Top-level orchestration: turn resolved dialog values into Fusion bodies.

Two output modes (the dialog's radio):

  EXAMPLE ASSEMBLY -- spawn a short chunk of the actual wing from the airfoil
      data, then seat ONE jig tile on its upper surface at the chord station,
      and stand the vane(s) as their own separate bodies. This lets the user
      SEE the whole thing fits before printing. The vane is deliberately NOT
      nested inside the jig pocket -- threading the vane's curve + tilt + toe
      into the pocket invites a rotation mismatch and reads wrong; a free-
      standing vane body is clearer and correct.

  PARTS AT ORIGIN -- the printable parts (vane pair + jig) generated flat at
      the origin, no wing, ready to export STL and arrange on the plate.

This module owns the high-level sequence; the geometry lives in vane.py /
jig.py and the surface math in airfoil_math.py. Keeping orchestration separate
means the dialog handler just gathers values and calls run().
"""

import math

import adsk.core
import adsk.fusion

from .. import config
from . import airfoils
from . import airfoil_math
from . import fusion_util as fu
from . import vane as vane_mod
from . import jig as jig_mod


def run(design, params, output_mode):
    """Build everything for the chosen output mode. Returns a status string.

    :param design:      active Fusion design
    :param params:      resolved dialog values (mm / deg)
    :param output_mode: config.OutputMode.ASSEMBLY or .ORIGIN
    :returns: a human-readable summary (the jig note plus what was built),
              shown to the user after the command runs
    """
    # Surface query for the chosen airfoil + chord station -- the single source
    # of the seat geometry both the vane and the jig consume.
    surf = airfoil_math.UpperSurface(airfoils.get(params["airfoil"]))
    x_frac = params["chord_pos_pct"] / 100.0
    vane_len = params["vane_len_ratio"] * params["vane_height_mm"]
    seat = surf.base_seat(x_frac, vane_len, params["chord_len_mm"])

    # Decide the jig build up front (the fallback ladder) so its note can be
    # reported regardless of mode.
    jig_plan = jig_mod.plan_jig(
        req_pairs=int(params["jig_pairs"]),
        spacing_mm=params["jig_spacing_mm"],
        vane_len_mm=vane_len,
        vane_thick_mm=params["vane_thick_mm"],
        le_hook_mm=params["le_hook_mm"],
        bed_x_mm=params["bed_x_mm"],
        bed_y_mm=params["bed_y_mm"],
    )

    if output_mode == config.OutputMode.ASSEMBLY:
        summary = _build_assembly(design, params, seat, surf, jig_plan)
    else:
        summary = _build_at_origin(design, params, seat, surf, jig_plan)

    # Always surface the seat numbers + the jig ladder outcome; this is the
    # honest report of what the tool actually did and why.
    seat_line = (
        f"Seat @ {params['chord_pos_pct']:.1f}%c: tilt {seat['tilt_deg']:.1f} deg, "
        f"base R {seat['radius_mm']:.0f} mm (sagitta {seat['sagitta_mm']:.2f} mm)."
    )
    return f"{summary}\n\n{seat_line}\n\nJig: {jig_plan.note}"


# ===========================================================================
#  Mode builders
# ===========================================================================

def _build_at_origin(design, params, seat, surf, jig_plan):
    """Printable parts flat at the origin: a vane pair + the jig tile.

    Vane pair is seated (tilt+curve) so the printed parts already have the
    correct base, but positioned at the origin rather than on a wing. The jig
    is built per the fallback-ladder plan.
    """
    vane_mod.build_pair(design, params, seat, name="VG Vane",
                        seat_to_surface=True)
    jig_mod.build_jig(design, params, seat, surf, jig_plan, name="VG Jig")
    pair_word = "1 vane" if jig_plan.single_vane else "1 vane pair"
    return f"Parts at origin: {pair_word} + jig tile ({jig_plan.pairs_built} pair pockets)."


def _build_assembly(design, params, seat, surf, jig_plan):
    """Example assembly: wing chunk + one seated jig + a free-standing vane.

    The wing is a short spanwise extrusion of the airfoil section at the user's
    chord. The jig is seated on the upper surface at the chord station (tilted
    to the local slope and lifted to the skin height). The vane stands as its
    own body beside the station -- intentionally not inside the jig pocket.
    """
    chord = params["chord_len_mm"]
    span = params["wing_span_mm"]

    # All three parts are built in the SAME station-centered frame (x = 0 at the
    # chord station, z = 0 at the skin there), so they coincide at the origin
    # with no per-part transform -- this is what fixes the jig/vane/wing
    # alignment. The wing is built station-centered, the jig carves its
    # underside in that frame, and the vane seats at z = 0 on that skin.

    # ---- wing body (station-centered, jig/vane frame) ------------------------
    _build_wing(design, surf, params, chord, span)

    # ---- jig, already seated on the wing at the origin -----------------------
    jig_mod.build_jig(design, params, seat, surf, jig_plan, name="VG Jig")

    # ---- a real VG resting INSIDE each jig slot ------------------------------
    # Build a vane at every slot position (same layout the jig cut), seated and
    # toed identically, and drop it into the slot at the y of that pocket -- so
    # the assembly shows exactly how the vanes sit in the jig.
    spacing = params["jig_spacing_mm"]
    slots = jig_mod._pocket_layout(jig_plan, spacing)
    n = 0
    for (y_center, toe_sign) in slots:
        vane_body = vane_mod.build_vane(design, params, seat, toe_sign=toe_sign,
                                        seat_to_surface=True,
                                        name=f"VG Vane {n + 1}")
        # Vanes are built centered on x = 0 (the 7%c line) and z = 0 (the skin),
        # so the only move is spanwise to this slot's y.
        _translate_body(design, vane_body, 0.0, 0.0, y_center)
        n += 1

    # ---- a print-ready VG, parked off to the side ----------------------------
    # A single FLAT vane (no seat tilt/curve) laid flange-down on z = 0, parked
    # well clear of the wing so it sits ready to export / arrange on the plate.
    _build_print_vane(design, params, seat, span)

    return (
        f"Example assembly: wing ({chord:.0f} mm chord x {span:.0f} mm span) "
        f"+ jig + {n} vanes in their slots + 1 print-ready vane off to the side."
    )


def _build_print_vane(design, params, seat, span_mm):
    """Build one FLAT vane parked off to the side, oriented for printing.

    seat_to_surface=False keeps it flat (no tilt/curve) and flange-down on the
    z = 0 plane -- exactly how it should sit on a print bed. It is parked a wing
    span away in -x and out in +y so it never overlaps the assembly.
    """
    vane = vane_mod.build_vane(design, params, seat, toe_sign=0.0,
                               seat_to_surface=False, name="VG Vane (print)")
    chord = params["chord_len_mm"]
    park_x = -0.6 * chord                 # well ahead of the wing nose
    park_y = 0.5 * span_mm + 60.0         # clear of the spanwise extent
    _translate_body(design, vane, park_x, 0.0, park_y)


# ===========================================================================
#  Wing + seating helpers
# ===========================================================================

def _build_wing(design, surf, params, chord_mm, span_mm):
    """Extrude a chunk of the airfoil section into a solid wing body.

    CRITICAL FRAME NOTE: the wing is built in the SAME frame the jig and vane
    use -- x = chordwise, y = spanwise, z = up (surface normal). So the airfoil
    profile is sketched in the x-z plane (x chordwise, z thickness/up) and
    extruded along y (spanwise). This matches the jig (which carves its wing
    underside in x-z and extrudes the tile in -z) so seating is a pure
    translation with no axis swap -- the reason the jig and vane now align on
    the wing instead of sitting in rotated frames.

    The section is shifted so the chord station x_frac lands at x = 0 and the
    upper skin at that station sits at z = 0, exactly like _carve_wing builds
    its tool -- so the jig's carved underside mates the wing perfectly.
    """
    occ = fu.new_component(design, "Wing (example)")
    comp = occ.component

    af = airfoils.get(params["airfoil"])
    loop = airfoil_math.assemble_selig(af.upper, af.lower)

    x_frac = params["chord_pos_pct"] / 100.0
    x_station_mm = x_frac * chord_mm
    y_skin_station = surf.y(x_frac) * chord_mm

    # Profile in the x-z plane, station-centered. z is NEGATED so the curved
    # suction surface faces UP (right side up) -- the same flip the jig applies
    # in _foil_loop_mm, so the wing and the jig stay matched. x is untouched so
    # the 7%c / chord-% measurement is unaffected.
    pts = []
    for (xc, yc) in loop:
        x_mm = xc * chord_mm - x_station_mm
        z_mm = -(yc * chord_mm - y_skin_station)
        pts.append((x_mm, z_mm))

    sk = fu.sketch_on_plane(comp, comp.xZConstructionPlane)
    prof = fu.closed_polyline(sk, pts)
    ext = fu.extrude(comp, prof, span_mm, symmetric=True)
    body = ext.bodies.item(0)
    body.name = "Wing"
    return body


def _translate_body(design, body, dx_mm, dy_mm, dz_mm):
    """Rigidly translate a body by (dx, dy, dz) millimetres.

    Used only to park the free-standing example vane spanwise beside the jig;
    all parts already share the station-centered origin, so no rotation or
    skin-height offset is needed.
    """
    comp = design.rootComponent
    move = adsk.core.Matrix3D.create()
    move.translation = adsk.core.Vector3D.create(
        dx_mm * config.MM, dy_mm * config.MM, dz_mm * config.MM,
    )
    bodies = adsk.core.ObjectCollection.create()
    bodies.add(body)
    moves = comp.features.moveFeatures
    inp = moves.createInput(bodies, move)
    moves.add(inp)
