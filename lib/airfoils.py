# -*- coding: utf-8 -*-
"""
Baked-in airfoil coordinate sets and a tiny registry.

Fusion's bundled Python cannot reliably import numpy/scipy, so we do NOT read
a .dat file at runtime and we do NOT depend on any third-party library. The
coordinates live here as plain Python literals, copied verbatim from the
companion glasair_vg_sim repo's geometry/ls413.dat (which is itself a verbatim
copy of the UIUC archive set). The numbers are the single source of truth for
every surface query the add-in makes.

LAYOUT (Lednicer, exactly as the source file stores it)
  Each surface is listed leading-edge -> trailing-edge as (x/c, y/c) pairs.
  UPPER and LOWER are kept separate here; lib/airfoil_math.assemble_selig()
  stitches them into the TE-upper -> LE -> TE-lower loop the math expects.
  The leading-edge point (0,0) appears once at the start of each surface;
  the assembler drops the duplicate so the nose is a single shared point.

To add another airfoil later: paste its UPPER/LOWER lists, wrap them in an
Airfoil entry, and register it in AIRFOILS. Nothing else has to change.
"""

# ---------------------------------------------------------------------------
#  NASA/Langley LS(1)-0413 (GA(W)-2)
#  Source: UIUC Airfoil Coordinate Database
#    https://m-selig.ae.illinois.edu/ads/coord/ls413.dat
#  45 upper + 45 lower points, blunt trailing edge
#  (upper TE y/c = -0.0016, lower TE y/c = -0.0071).
# ---------------------------------------------------------------------------
_LS413_UPPER = [
    (0.00000,  0.00000), (0.00200,  0.01040), (0.00500,  0.01590),
    (0.01250,  0.02420), (0.02500,  0.03320), (0.03750,  0.03970),
    (0.05000,  0.04480), (0.07500,  0.05260), (0.10000,  0.05860),
    (0.12500,  0.06350), (0.15000,  0.06750), (0.17500,  0.07100),
    (0.20000,  0.07400), (0.22500,  0.07650), (0.25000,  0.07860),
    (0.27500,  0.08030), (0.30000,  0.08180), (0.32500,  0.08300),
    (0.35000,  0.08380), (0.37500,  0.08430), (0.40000,  0.08460),
    (0.42500,  0.08460), (0.45000,  0.08440), (0.47500,  0.08380),
    (0.50000,  0.08290), (0.52500,  0.08170), (0.55000,  0.08020),
    (0.57500,  0.07830), (0.60000,  0.07610), (0.62500,  0.07330),
    (0.65000,  0.07020), (0.67500,  0.06670), (0.70000,  0.06290),
    (0.72500,  0.05870), (0.75000,  0.05420), (0.77500,  0.04950),
    (0.80000,  0.04450), (0.82500,  0.03930), (0.85000,  0.03400),
    (0.87500,  0.02840), (0.90000,  0.02270), (0.92500,  0.01690),
    (0.95000,  0.01100), (0.97500,  0.00480), (1.00000, -0.00160),
]

_LS413_LOWER = [
    (0.00000,  0.00000), (0.00200, -0.00500), (0.00500, -0.00940),
    (0.01250, -0.01450), (0.02500, -0.01910), (0.03750, -0.02230),
    (0.05000, -0.02500), (0.07500, -0.02940), (0.10000, -0.03280),
    (0.12500, -0.03560), (0.15000, -0.03790), (0.17500, -0.03980),
    (0.20000, -0.04140), (0.22500, -0.04270), (0.25000, -0.04370),
    (0.27500, -0.04430), (0.30000, -0.04480), (0.32500, -0.04510),
    (0.35000, -0.04520), (0.37500, -0.04500), (0.40000, -0.04470),
    (0.42500, -0.04420), (0.45000, -0.04350), (0.47500, -0.04260),
    (0.50000, -0.04140), (0.52500, -0.03990), (0.55000, -0.03810),
    (0.57500, -0.03590), (0.60000, -0.03330), (0.62500, -0.03050),
    (0.65000, -0.02740), (0.67500, -0.02420), (0.70000, -0.02100),
    (0.72500, -0.01770), (0.75000, -0.01440), (0.77500, -0.01130),
    (0.80000, -0.00830), (0.82500, -0.00570), (0.85000, -0.00350),
    (0.87500, -0.00180), (0.90000, -0.00080), (0.92500, -0.00060),
    (0.95000, -0.00130), (0.97500, -0.00340), (1.00000, -0.00710),
]


class Airfoil:
    """One named airfoil: upper + lower surfaces, each LE -> TE (x/c, y/c).

    Holding the two surfaces separately mirrors the source-file layout and
    lets airfoil_math do the Selig assembly in exactly one place. ``name`` is
    what the dialog dropdown shows.
    """

    def __init__(self, name, upper, lower):
        self.name = name
        self.upper = upper          # list[(x/c, y/c)], LE -> TE
        self.lower = lower          # list[(x/c, y/c)], LE -> TE


# The registry the dialog reads. Keys are the exact strings shown in the
# airfoil dropdown (and stored in config.DEFAULTS["airfoil"]).
AIRFOILS = {
    "LS(1)-0413 (GA(W)-2)": Airfoil(
        "LS(1)-0413 (GA(W)-2)", _LS413_UPPER, _LS413_LOWER
    ),
}


def get(name):
    """Look up an airfoil by its dropdown name; raise clearly if unknown.

    A missing key here means the dialog and the registry drifted out of sync,
    which is a programming error -- fail loudly rather than silently swapping
    in a default section the user did not pick.
    """
    if name not in AIRFOILS:
        raise KeyError(
            f"unknown airfoil {name!r}; known: {sorted(AIRFOILS)}"
        )
    return AIRFOILS[name]
