# -*- coding: utf-8 -*-
"""
Thin helpers over the Fusion API shared by the vane / jig / assembly builders.

These wrap the few verbose Fusion idioms we use repeatedly -- creating user
parameters, making sketches on a plane, turning point lists into closed
profiles, extruding, and combining bodies -- so the builder modules read as
geometry intent rather than API boilerplate. Nothing here is VG-specific.

All public lengths are in MILLIMETRES; conversion to Fusion's internal
centimetres happens at the API boundary via config.MM so the builders never
sprinkle 0.1 factors through their geometry code.
"""

import adsk.core
import adsk.fusion

from .. import config


def app_ui():
    """Return (app, ui) -- the two objects every builder needs to start."""
    app = adsk.core.Application.get()
    return app, app.userInterface


def active_design():
    """The active Fusion design, or a clear error if none is open.

    Every builder needs a design to add bodies to; failing here with a plain
    message beats a cryptic NoneType crash three calls deep.
    """
    app = adsk.core.Application.get()
    design = app.activeProduct
    if not isinstance(design, adsk.fusion.Design):
        raise RuntimeError(
            "No active Fusion design. Open or create a design, then run again."
        )
    return design


def set_param(design, name, value_mm, comment=""):
    """Create or update a user parameter (millimetres) and return it.

    Driving every meaningful dimension through a named user parameter is what
    makes the generated bodies editable after the fact: the user can open
    Modify > Change Parameters, tweak `vane_height`, and the timeline rebuilds.
    Reusing an existing parameter (update, not duplicate) keeps re-runs clean.
    """
    params = design.userParameters
    existing = params.itemByName(name)
    value = adsk.core.ValueInput.createByReal(value_mm * config.MM)
    if existing:
        existing.expression = f"{value_mm} mm"
        if comment:
            existing.comment = comment
        return existing
    return params.add(name, value, "mm", comment)


def new_component(design, name):
    """Add a fresh empty component to the root and return its occurrence.

    Each generated part (vane, jig, wing) lives in its own component so the
    browser tree stays tidy and parts can be moved/copied independently.
    """
    root = design.rootComponent
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    occ.component.name = name
    return occ


def sketch_on_plane(component, plane):
    """Start a sketch on a construction plane or planar face."""
    return component.sketches.add(plane)


def closed_polyline(sketch, pts_mm):
    """Draw a closed polyline through (x, y) mm points; return its profile.

    Builds the loop edge-by-edge (connecting each consecutive pair, then the
    last back to the first) so the result is a single closed profile ready to
    extrude. Points are millimetres in the sketch plane; we convert to cm here.
    """
    lines = sketch.sketchCurves.sketchLines
    n = len(pts_mm)
    pt3 = []
    for x, y in pts_mm:
        pt3.append(adsk.core.Point3D.create(x * config.MM, y * config.MM, 0.0))
    for i in range(n):
        lines.addByTwoPoints(pt3[i], pt3[(i + 1) % n])
    # A single closed loop yields exactly one profile.
    return sketch.profiles.item(0)


def extrude(component, profile, distance_mm, symmetric=False, operation=None):
    """Extrude a profile by distance_mm; return the feature.

    Defaults to a new-body join operation. ``symmetric`` extrudes both ways
    about the sketch plane (handy for centering a fin's thickness on its
    midplane). Distance is millimetres.
    """
    extrudes = component.features.extrudeFeatures
    if operation is None:
        operation = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    dist = adsk.core.ValueInput.createByReal(distance_mm * config.MM)
    inp = extrudes.createInput(profile, operation)
    if symmetric:
        extent = adsk.fusion.SymmetricExtentDefinition.create(
            adsk.core.ValueInput.createByReal(distance_mm * config.MM),
            True,  # full length is symmetric about the plane
        )
        inp.setOneSideExtent(
            extent, adsk.fusion.ExtentDirections.PositiveExtentDirection
        )
    else:
        inp.setDistanceExtent(False, dist)
    return extrudes.add(inp)


def combine(component, target_body, tool_bodies, operation):
    """Boolean target with tool bodies; operation is a FeatureOperations enum.

    Used for cutting jig pockets (Cut), welding the dovetail keys (Join), and
    splitting the tile. tool_bodies is a list; we pack it into an ObjectCollection
    which the combine feature requires.
    """
    tools = adsk.core.ObjectCollection.create()
    for b in tool_bodies:
        tools.add(b)
    combines = component.features.combineFeatures
    inp = combines.createInput(target_body, tools)
    inp.operation = operation
    inp.isKeepToolBodies = False
    return combines.add(inp)


def move_body(component, body, matrix):
    """Apply a rigid Matrix3D transform to a single body via a move feature.

    Building geometry flat and then moving it into place (tilt, toe, seat
    position) keeps the sketch math simple and the transform explicit -- the
    seat/toe orientation lives in one readable Matrix3D rather than baked into
    every sketch coordinate.
    """
    bodies = adsk.core.ObjectCollection.create()
    bodies.add(body)
    moves = component.features.moveFeatures
    inp = moves.createInput(bodies, matrix)
    return moves.add(inp)
