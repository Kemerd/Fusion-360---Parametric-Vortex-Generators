# Fusion 360 — Parametric Vortex Generators

A Fusion 360 **add-in** that generates a parametric delta **vortex-generator
vane** and its **placement jig** straight from airfoil data and your
printer/aircraft numbers. Open the dialog, set the parameters (or just accept
the defaults), and it builds fully editable Fusion bodies you can tweak on the
timeline and export to STL.

The defaults are not made up — they are the **CFD-winning** configuration from
the Glasair III vortex-generator study: a **6 mm delta vane at 7 % chord,
70 mm spanwise spacing, 10° toe-out**, which pushed the section stall from
~15° to ~18° and cut stall speed by roughly **5.6 kt**. Point it at a different
airfoil/chord and every dimension recomputes from that section's geometry.

---

## What it makes

| Part | What it is |
|------|------------|
| **Delta vane** | A swept triangular fin (height *h*, length *3h*) standing off the wing, with a **thin printable base flange** (the glue tab) and an underside **tilted + gently curved** to seat flush on the wing skin at your chord station. |
| **Placement jig** | A flat tile you register off the wing **leading edge** and leapfrog down the span. It drops the vanes onto the chord line at the exact station + toe, with side keys so tiles butt together. **Auto-fits your printer bed** (see below). |

Two output modes:

- **Example assembly** — spawns a chunk of the actual wing, seats one jig on
  it at the chord station, and stands a vane beside it. Lets you *see* the fit.
  (The vane is its own body, **not** nested in the jig pocket — that avoids a
  toe/tilt rotation mismatch and reads correctly.)
- **Parts at origin** — the printable vane pair + jig, flat at (0, 0, 0),
  ready to export and arrange on the plate.

---

## The jig auto-fit ladder

Nothing is baked. You set the bed size, the requested pairs, and the spacing;
the tile **degrades gracefully** to fit your printer, and **tells you exactly
what it did** — it never silently truncates:

1. **All requested pairs fit** → builds them.
2. **Too big for the bed** → builds the most pairs that fit, and reports how
   many to place on the next run.
3. **Not even one pair fits** → builds a narrower **single-vane** tile.
4. **Even that won't fit** → **splits into dovetailed halves** (mechanical
   interlock, glue optional) that print separately and click together.

Run it again with different spacing for the root vs. outboard passes — e.g.
90 mm at the root (coarser, so the root stalls first and the ailerons keep
flying), 70 mm outboard.

---

## Install

1. In Fusion: **Utilities → Add-Ins → Scripts and Add-Ins** (or `Shift+S`).
2. On the **Add-Ins** tab, click the green **+** and select this folder
   (`Fusion 360 - Parametric Vortex Generators`).
3. Select it in the list and click **Run** (tick *Run on Startup* to keep it).
4. A **Vortex Generator + Jig** button appears on **Solid → Create**.

> The add-in is **self-contained** — no `numpy`, `scipy`, or any third-party
> package. The airfoil is baked in and all geometry math uses only the Python
> standard library, so it works on any Fusion install without pip gymnastics.

---

## Parameters

| Field | Default | Meaning |
|-------|---------|---------|
| Airfoil | LS(1)-0413 (GA(W)-2) | Section whose surface the parts seat to |
| Chord length | 902.2 mm | Physical chord (sets the seat curvature scale) |
| Chord position % | 7 % | Where the VG row sits (the 7 % stall winner) |
| Vane height | 6 mm | Delta height *h* |
| Length / height | 3.0 | Vane length = ratio × *h* (→ 18 mm) |
| Toe-out | 10° | Pair handedness (counter-rotating) |
| Fin thickness | 1.2 mm | Printable fin wall |
| Base flange thickness | 0.8 mm | Thin glue tab (~2 ABS perimeters) |
| Requested pairs | 2 | Counter-rotating pairs you want per tile |
| Spanwise spacing | 70 mm | Vane spacing (type 90 for the root pass) |
| Printer bed X / Y | 250 / 250 mm | **Your** printer — auto-fit uses these |
| LE hook depth | 12 mm | How far the hook wraps the wing nose |
| Dovetail clearance | 0.2 mm | Split-half fit (tune for ABS shrink) |
| Example wing span | 300 mm | Length of the wing chunk in assembly mode |

---

## The seat math (why the base is tilted, barely curved)

Measured from the baked-in LS(1)-0413 over the **real 18 mm vane footprint**
at 7 % chord (chord 902.2 mm):

- **Seat tilt ≈ 14.4°** — the skin climbs toward the leading edge; this is the
  **dominant** correction so the vane doesn't rock.
- **Base radius ≈ 396 mm** (best-fit circle over the footprint) — a gentle
  convex arc.
- **Sagitta ≈ 0.11 mm** — a flat base would only gap ~0.1 mm under the curve,
  i.e. below one print layer. So the curve is a refinement; the **tilt** is
  what matters.
- The skin **rises ~4.6 mm** across the base (7 % chord is forward of max
  thickness).

These come from `lib/airfoil_math.UpperSurface.base_seat()`. Verify them
without Fusion:

```
python "lib/airfoil_math.py"
```

It prints the surface metrics and asserts they match the study values.

---

## Layout

```
config.py                  parameters + DEFAULTS (the winning config)
VortexGeneratorAddin.py    add-in entry (run/stop)
VortexGeneratorAddin.manifest
commands/generate/entry.py dialog, validation, execute
lib/airfoils.py            baked-in LS(1)-0413 coordinates (UIUC, verbatim)
lib/airfoil_math.py        stdlib spline + surface slope/curvature + seat
lib/vane.py                delta vane body (fin + flange + seat)
lib/jig.py                 jig tile + the auto-fit fallback ladder
lib/assembly.py            example-assembly vs parts-at-origin orchestration
lib/fusion_util.py         thin Fusion API helpers
```
