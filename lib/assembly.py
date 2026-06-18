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
    x_frac = params["chord_pos_pct"] / 100.0

    # ---- wing body -----------------------------------------------------------
    wing_body = _build_wing(design, surf, params, chord, span)

    # Surface anchor: where the jig/vane sit on the skin (mm, wing frame).
    x_station = x_frac * chord
    y_surface = surf.y(x_frac) * chord  # skin height at the station

    # ---- jig, seated on the wing --------------------------------------------
    jig_body = jig_mod.build_jig(design, params, seat, surf, jig_plan,
                                 name="VG Jig")
    _seat_body_on_wing(design, jig_body, x_station, y_surface,
                       seat["tilt_deg"], lift_mm=0.0)

    # ---- a free-standing vane (NOT in the pocket) ---------------------------
    # One representative vane, seated, parked just outboard of the jig so it is
    # visible next to the assembly rather than hidden in a slot.
    vane_body = vane_mod.build_vane(design, params, seat, toe_sign=+1.0,
                                    seat_to_surface=True, name="VG Vane")
    park_y = 0.5 * jig_plan.tile_wid_mm + 15.0  # spanwise, beside the tile
    _seat_body_on_wing(design, vane_body, x_station, y_surface,
                       seat["tilt_deg"], lift_mm=0.0, span_offset_mm=park_y)

    return (
        f"Example assembly: wing ({chord:.0f} mm chord x {span:.0f} mm span) "
        f"+ seated jig ({jig_plan.pairs_built} pair pockets) + 1 free-standing vane."
    )


# ===========================================================================
#  Wing + seating helpers
# ===========================================================================

def _build_wing(design, surf, params, chord_mm, span_mm):
    """Extrude a chunk of the airfoil section into a solid wing body.

    Samples the full airfoil loop (upper TE->LE->TE lower) from the baked-in
    coordinates, scales to the physical chord, draws it as a closed profile in
    the chordwise-normal (x-y) plane, and extrudes it spanwise (z) by span_mm.
    This is the visual context the jig seats onto.
    """
    occ = fu.new_component(design, "Wing (example)")
    comp = occ.component

    af = airfoils.get(params["airfoil"])
    loop = airfoil_math.assemble_selig(af.upper, af.lower)

    # Closed airfoil profile in mm (x chordwise, y thickness).
    pts = [(x * chord_mm, y * chord_mm) for (x, y) in loop]
    sk = fu.sketch_on_plane(comp, comp.xYConstructionPlane)
    prof = fu.closed_polyline(sk, pts)
    ext = fu.extrude(comp, prof, span_mm, symmetric=True)
    body = ext.bodies.item(0)
    body.name = "Wing"
    return body


def _seat_body_on_wing(design, body, x_station_mm, y_surface_mm, tilt_deg,
                       lift_mm=0.0, span_offset_mm=0.0):
    """Move an already-seated part onto the wing skin at the chord station.

    The vane/jig are built seated (tilted) at the local origin; this places
    them at the right chordwise station and skin height on the wing body. The
    part's own tilt already matches the slope, so here we only TRANSLATE (plus
    an optional spanwise park offset for the free-standing vane).
    """
    comp = design.rootComponent
    move = adsk.core.Matrix3D.create()
    move.translation = adsk.core.Vector3D.create(
        x_station_mm * config.MM,
        (y_surface_mm + lift_mm) * config.MM,
        span_offset_mm * config.MM,
    )
    bodies = adsk.core.ObjectCollection.create()
    bodies.add(body)
    moves = comp.features.moveFeatures
    inp = moves.createInput(bodies, move)
    moves.add(inp)
