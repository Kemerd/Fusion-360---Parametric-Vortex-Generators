# -*- coding: utf-8 -*-
"""
The 'Generate' command: dialog, live validation, and execution.

This module owns everything UI-facing for the single command the add-in
exposes. It follows the standard Fusion command lifecycle:

  start()            -- create the command definition + panel button (once,
                        at add-in load)
  command_created    -- build the dialog inputs every time the user opens it
  input_changed      -- live preview of the fallback-ladder outcome as the
                        user edits pairs / spacing / bed
  validate_inputs    -- gray out OK on impossible input (non-positive sizes)
  command_execute    -- gather values and hand off to lib/assembly.run()
  stop()             -- tear the button + command down (at add-in unload)

Event handlers are kept as module-level globals in a list so Python does not
garbage-collect them while Fusion still holds the C++ side -- a classic Fusion
add-in gotcha that silently kills callbacks if the handlers go out of scope.
"""

import traceback

import adsk.core
import adsk.fusion

from ... import config
from ...lib import airfoils
from ...lib import airfoil_math
from ...lib import jig as jig_mod
from ...lib import assembly

# Keep references to handlers alive (see module docstring).
_handlers = []


# ===========================================================================
#  Lifecycle: start / stop
# ===========================================================================

def start():
    """Create the command definition and drop its button on the panel."""
    app = adsk.core.Application.get()
    ui = app.userInterface

    # Reuse an existing definition if a prior session left one (clean reloads).
    cmd_def = ui.commandDefinitions.itemById(config.CMD_ID)
    if not cmd_def:
        cmd_def = ui.commandDefinitions.addButtonDefinition(
            config.CMD_ID, config.CMD_NAME, config.CMD_DESCRIPTION
        )

    # Wire the 'created' event -- this fires each time the user clicks the button.
    on_created = _CommandCreatedHandler()
    cmd_def.commandCreated.add(on_created)
    _handlers.append(on_created)

    # Place the button on the Solid > Create panel.
    panel = ui.allToolbarPanels.itemById(config.PANEL_ID)
    if panel:
        control = panel.controls.itemById(config.CMD_ID)
        if not control:
            control = panel.controls.addCommand(cmd_def)
            control.isPromoted = config.IS_PROMOTED


def stop():
    """Remove the panel button and the command definition for a clean unload."""
    app = adsk.core.Application.get()
    ui = app.userInterface

    panel = ui.allToolbarPanels.itemById(config.PANEL_ID)
    if panel:
        control = panel.controls.itemById(config.CMD_ID)
        if control:
            control.deleteMe()

    cmd_def = ui.commandDefinitions.itemById(config.CMD_ID)
    if cmd_def:
        cmd_def.deleteMe()

    _handlers.clear()


# ===========================================================================
#  Dialog construction
# ===========================================================================

class _CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    """Builds the dialog inputs and wires the per-command event handlers."""

    def notify(self, args):
        try:
            cmd = args.command
            inputs = cmd.commandInputs
            d = config.DEFAULTS
            I = config.Inputs

            # -- airfoil + plan, in millimetres -----------------------------
            af_dd = inputs.addDropDownCommandInput(
                I.AIRFOIL, "Airfoil",
                adsk.core.DropDownStyles.TextListDropDownStyle,
            )
            for name in airfoils.AIRFOILS:
                af_dd.listItems.add(name, name == d["airfoil"], "")

            _mm(inputs, I.CHORD_LEN, "Chord length", d["chord_len_mm"])
            inputs.addValueInput(
                I.CHORD_POS, "Chord position (%)", "",
                adsk.core.ValueInput.createByReal(d["chord_pos_pct"]),
            )

            # -- vane group -------------------------------------------------
            vg = inputs.addGroupCommandInput(I.VANE_GROUP, "Vane (delta)")
            vci = vg.children
            _mm(vci, I.VANE_HEIGHT, "Height", d["vane_height_mm"])
            vci.addValueInput(
                I.VANE_LEN_RATIO, "Length / height", "",
                adsk.core.ValueInput.createByReal(d["vane_len_ratio"]),
            )
            vci.addValueInput(
                I.VANE_TOE, "Toe-out (deg)", "",
                adsk.core.ValueInput.createByReal(d["vane_toe_deg"]),
            )
            _mm(vci, I.VANE_THICK, "Fin thickness", d["vane_thick_mm"])
            _mm(vci, I.BASE_FLANGE, "Base flange thickness", d["base_flange_mm"])

            # -- jig group --------------------------------------------------
            jg = inputs.addGroupCommandInput(I.JIG_GROUP, "Jig (placement tile)")
            jci = jg.children
            jci.addValueInput(
                I.JIG_PAIRS, "Requested pairs", "",
                adsk.core.ValueInput.createByReal(d["jig_pairs"]),
            )
            _mm(jci, I.JIG_SPACING, "Spanwise spacing", d["jig_spacing_mm"])
            _mm(jci, I.BED_X, "Printer bed X", d["bed_x_mm"])
            _mm(jci, I.BED_Y, "Printer bed Y", d["bed_y_mm"])
            _mm(jci, I.LE_HOOK, "LE hook depth", d["le_hook_mm"])
            _mm(jci, I.DOVETAIL_CLEAR, "Dovetail clearance", d["dovetail_clear_mm"])

            # A read-only text box that previews the fallback-ladder outcome.
            preview = jci.addTextBoxCommandInput(
                "jig_preview", "Jig result", "", 3, True
            )
            preview.isFullWidth = True

            # -- output mode + example-wing span ----------------------------
            om = inputs.addRadioButtonGroupCommandInput(
                I.OUTPUT_MODE, "Output"
            )
            om.listItems.add(config.OutputMode.ASSEMBLY, True, "")
            om.listItems.add(config.OutputMode.ORIGIN, False, "")
            _mm(inputs, I.WING_SPAN, "Example wing span", d["wing_span_mm"])

            # -- per-command handlers ---------------------------------------
            on_exec = _ExecuteHandler()
            cmd.execute.add(on_exec)
            _handlers.append(on_exec)

            on_change = _InputChangedHandler()
            cmd.inputChanged.add(on_change)
            _handlers.append(on_change)

            on_validate = _ValidateHandler()
            cmd.validateInputs.add(on_validate)
            _handlers.append(on_validate)

            # Seed the preview once on open.
            _refresh_preview(inputs)

        except Exception:  # noqa: BLE001
            app = adsk.core.Application.get()
            app.userInterface.messageBox(
                f"Dialog build failed:\n{traceback.format_exc()}"
            )


def _mm(inputs, input_id, label, default_mm):
    """Add a millimetre value input (Fusion shows it in the doc's units).

    Centralizes the verbose ValueInput dance and keeps every length field
    consistent. Fusion stores lengths internally in cm, so we convert.
    """
    return inputs.addValueInput(
        input_id, label, "mm",
        adsk.core.ValueInput.createByReal(default_mm * config.MM),
    )


# ===========================================================================
#  Value gathering
# ===========================================================================

def _read_params(inputs):
    """Pull every dialog value into a plain dict in mm / deg (assembly's input).

    Length inputs come back in Fusion's internal cm, so we convert to mm via
    config.MM. Plain-number inputs (ratios, angles, counts) are taken as-is.
    """
    I = config.Inputs

    def length_mm(iid):
        return inputs.itemById(iid).value / config.MM

    def number(iid):
        return inputs.itemById(iid).value

    af = inputs.itemById(I.AIRFOIL).selectedItem.name

    return {
        "airfoil": af,
        "chord_len_mm": length_mm(I.CHORD_LEN),
        "chord_pos_pct": number(I.CHORD_POS),
        "vane_height_mm": length_mm(I.VANE_HEIGHT),
        "vane_len_ratio": number(I.VANE_LEN_RATIO),
        "vane_toe_deg": number(I.VANE_TOE),
        "vane_thick_mm": length_mm(I.VANE_THICK),
        "base_flange_mm": length_mm(I.BASE_FLANGE),
        "jig_pairs": number(I.JIG_PAIRS),
        "jig_spacing_mm": length_mm(I.JIG_SPACING),
        "bed_x_mm": length_mm(I.BED_X),
        "bed_y_mm": length_mm(I.BED_Y),
        "le_hook_mm": length_mm(I.LE_HOOK),
        "dovetail_clear_mm": length_mm(I.DOVETAIL_CLEAR),
        "wing_span_mm": length_mm(I.WING_SPAN),
    }


def _refresh_preview(inputs):
    """Recompute the fallback-ladder note and show it in the preview box.

    Pure pre-compute (plan_jig + base_seat) so the user sees what will be built
    -- including any auto-fit fallback -- BEFORE committing. No bodies created.
    """
    try:
        p = _read_params(inputs)
        vane_len = p["vane_len_ratio"] * p["vane_height_mm"]
        plan = jig_mod.plan_jig(
            req_pairs=int(p["jig_pairs"]),
            spacing_mm=p["jig_spacing_mm"],
            vane_len_mm=vane_len,
            vane_thick_mm=p["vane_thick_mm"],
            le_hook_mm=p["le_hook_mm"],
            bed_x_mm=p["bed_x_mm"],
            bed_y_mm=p["bed_y_mm"],
        )
        surf = airfoil_math.UpperSurface(airfoils.get(p["airfoil"]))
        seat = surf.base_seat(p["chord_pos_pct"] / 100.0, vane_len, p["chord_len_mm"])
        text = (
            f"Seat: tilt {seat['tilt_deg']:.1f} deg, base R {seat['radius_mm']:.0f} mm.\n"
            f"{plan.note}"
        )
        box = inputs.itemById("jig_preview")
        if box:
            box.text = text
    except Exception:  # noqa: BLE001 -- preview must never break the dialog
        box = inputs.itemById("jig_preview")
        if box:
            box.text = "(adjust inputs)"


# ===========================================================================
#  Per-command event handlers
# ===========================================================================

class _InputChangedHandler(adsk.core.InputChangedEventHandler):
    """Refresh the ladder preview whenever a relevant field changes."""

    def notify(self, args):
        try:
            _refresh_preview(args.inputs)
        except Exception:  # noqa: BLE001
            pass


class _ValidateHandler(adsk.core.ValidateInputsEventHandler):
    """Disable OK on physically impossible input (non-positive dimensions)."""

    def notify(self, args):
        try:
            inputs = args.inputs
            I = config.Inputs
            # Every length must be positive; pairs must be >= 1; bed positive.
            checks = [
                inputs.itemById(I.CHORD_LEN).value > 0,
                inputs.itemById(I.VANE_HEIGHT).value > 0,
                inputs.itemById(I.VANE_THICK).value > 0,
                inputs.itemById(I.BASE_FLANGE).value > 0,
                inputs.itemById(I.BED_X).value > 0,
                inputs.itemById(I.BED_Y).value > 0,
                inputs.itemById(I.JIG_PAIRS).value >= 1,
                0 < inputs.itemById(I.CHORD_POS).value < 100,
            ]
            args.areInputsValid = all(checks)
        except Exception:  # noqa: BLE001
            args.areInputsValid = False


class _ExecuteHandler(adsk.core.CommandEventHandler):
    """Gather values and build the bodies via lib/assembly.run()."""

    def notify(self, args):
        app = adsk.core.Application.get()
        ui = app.userInterface
        try:
            design = app.activeProduct
            if not isinstance(design, adsk.fusion.Design):
                ui.messageBox("Open or create a Fusion design first.")
                return

            inputs = args.command.commandInputs
            params = _read_params(inputs)
            mode = inputs.itemById(config.Inputs.OUTPUT_MODE).selectedItem.name

            summary = assembly.run(design, params, mode)
            ui.messageBox(summary, config.CMD_NAME)

        except Exception:  # noqa: BLE001
            ui.messageBox(f"Generation failed:\n{traceback.format_exc()}")
