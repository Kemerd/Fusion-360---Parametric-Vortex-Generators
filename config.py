# -*- coding: utf-8 -*-
"""
Central configuration for the Parametric Vortex Generator add-in.

Everything that the rest of the add-in references by name lives here: the
Fusion command / panel identifiers (so the UI hooks are defined in exactly
one place), and the DEFAULTS dictionary that seeds every dialog field.

The DEFAULTS are not arbitrary -- they are the *winning* configuration from
the Glasair III CFD study (gpu/rapidcfd/06-17-26_results.md in the companion
glasair_vg_sim repo): a 6 mm delta vane at 7% chord, 70 mm spanwise spacing,
10 deg toe-out. Anyone who just opens the dialog and hits OK gets that exact
design; every value is overridable for the next airfoil or aircraft.
"""

# ---------------------------------------------------------------------------
#  Add-in identity
# ---------------------------------------------------------------------------
# A human-readable name shown in Fusion's "Scripts and Add-Ins" list and used
# as a prefix for every command id so our ids never collide with another
# add-in's. Fusion command ids must be globally unique within a session.
ADDIN_NAME = "VortexGeneratorAddin"
COMPANY_NAME = "GlasairVG"

# ---------------------------------------------------------------------------
#  Command + UI identifiers
# ---------------------------------------------------------------------------
# The single "Generate" command. Folder layout under commands/ leaves room for
# more commands later (e.g. an "import .dat" command) without renaming things.
CMD_ID = f"{ADDIN_NAME}_generate"
CMD_NAME = "Vortex Generator + Jig"
CMD_DESCRIPTION = (
    "Generate a parametric delta vortex-generator vane and its placement jig "
    "from airfoil data and printer/aircraft parameters."
)

# Where the button lives. We drop it on the SOLID tab's CREATE panel, which is
# where users expect a body-creating tool to be.
WORKSPACE_ID = "FusionSolidEnvironment"
TAB_ID = "SolidTab"
PANEL_ID = "SolidCreatePanel"
# Place our button after the existing controls rather than hijacking the front.
COMMAND_BESIDE_ID = ""

# Run the command palette on the right; not a promoted (pinned) button.
IS_PROMOTED = True

# ---------------------------------------------------------------------------
#  Per-input identifiers (referenced by entry.py when reading the dialog)
# ---------------------------------------------------------------------------
# Centralizing the input ids keeps the dialog-builder and the value-reader in
# perfect sync; a typo here fails loudly in both places at once instead of
# silently returning a default.
class Inputs:
    AIRFOIL = "airfoil"
    CHORD_LEN = "chord_len_mm"
    CHORD_POS = "chord_pos_pct"

    VANE_GROUP = "vane_group"
    VANE_HEIGHT = "vane_height_mm"
    VANE_LEN_RATIO = "vane_len_ratio"
    VANE_TOE = "vane_toe_deg"
    VANE_THICK = "vane_thick_mm"
    BASE_FLANGE = "base_flange_mm"

    JIG_GROUP = "jig_group"
    JIG_PAIRS = "jig_pairs"
    JIG_SPACING = "jig_spacing_mm"
    BED_X = "bed_x_mm"
    BED_Y = "bed_y_mm"
    LE_HOOK = "le_hook_mm"
    DOVETAIL_CLEAR = "dovetail_clear_mm"

    OUTPUT_MODE = "output_mode"
    WING_SPAN = "wing_span_mm"


# Output-mode radio choices (kept as constants so entry.py and assembly.py
# agree on the exact strings).
class OutputMode:
    ASSEMBLY = "Example assembly (wing + jig)"
    ORIGIN = "Parts at origin (for printing)"


# ---------------------------------------------------------------------------
#  DEFAULTS -- the winning Glasair III config (all lengths in mm, angles deg)
# ---------------------------------------------------------------------------
DEFAULTS = {
    # -- airfoil / planform ------------------------------------------------
    # 0.9022 m aileron-station chord from aircraft.yaml (DXF-measured).
    "airfoil": "LS(1)-0413 (GA(W)-2)",
    "chord_len_mm": 902.2,
    "chord_pos_pct": 7.0,          # VG leading edge at 7% chord [IMP74]

    # -- vane --------------------------------------------------------------
    # 6 mm delta is the stall winner; l = 3h matches vane_length_per_height.
    "vane_height_mm": 6.0,
    "vane_len_ratio": 3.0,         # length = 3 x height -> 18 mm
    "vane_toe_deg": 10.0,          # 10 deg toe-out (counter-rotating pair)
    "vane_thick_mm": 1.2,          # printable fin wall (ABS); not aero-critical
    "base_flange_mm": 0.8,         # thin glue tab, ~2 ABS perimeters

    # -- jig ---------------------------------------------------------------
    "jig_pairs": 2,                # requested counter-rotating pairs per tile
    "jig_spacing_mm": 70.0,        # 70 mm winner; type 90 for the root pass
    "bed_x_mm": 250.0,             # user's printer bed -- adjust to taste
    "bed_y_mm": 250.0,
    "le_hook_mm": 12.0,            # how far the LE hook wraps over the nose
    "dovetail_clear_mm": 0.2,      # split-half dovetail fit clearance (ABS)

    # -- output ------------------------------------------------------------
    "wing_span_mm": 300.0,         # example-assembly wing chunk length
}

# ---------------------------------------------------------------------------
#  Hard geometric guards (not user-facing, but referenced by the builders)
# ---------------------------------------------------------------------------
# Fusion works internally in centimeters; every length we hand the API must be
# converted mm -> cm. One constant, used everywhere, so the factor is never
# fat-fingered inline.
MM = 0.1  # 1 mm = 0.1 cm (Fusion internal unit)
