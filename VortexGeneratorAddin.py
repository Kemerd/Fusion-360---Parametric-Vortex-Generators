# -*- coding: utf-8 -*-
"""
Add-in entry point for the Parametric Vortex Generator + Jig tool.

Fusion calls run() when the add-in is loaded (on startup, per the manifest,
or when the user toggles it in Scripts and Add-Ins) and stop() when it is
unloaded. We keep this file deliberately thin: all it does is create the
toolbar command and delegate every behaviour to commands/generate/entry.py.
Keeping the command logic out of the top-level file is the standard Fusion
add-in pattern -- it makes the command independently testable and keeps the
load/unload housekeeping in one obvious place.
"""

import traceback

import adsk.core
import adsk.fusion  # noqa: F401  (imported so the type system is initialised)

from . import config
from .commands.generate import entry as generate_cmd

# Module-level handle to the running application; populated in run() and used
# by stop() so the two halves reference the exact same UI object.
_app = None
_ui = None


def run(context):
    """Fusion add-in entry: build the command and put its button on the panel.

    Any exception here would otherwise be swallowed by Fusion and leave the
    user with a silently-missing button, so we surface the full traceback in
    a message box -- during development that is the difference between a
    five-second fix and an afternoon of guessing.
    """
    global _app, _ui
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface

        # Hand off to the command module. It owns the command definition, the
        # event handlers, and the panel button -- everything UI-facing.
        generate_cmd.start()

    except Exception:  # noqa: BLE001 -- top-level guard, must catch everything
        if _ui:
            _ui.messageBox(
                f"{config.ADDIN_NAME} failed to start:\n{traceback.format_exc()}"
            )


def stop(context):
    """Fusion add-in teardown: remove the command and its UI so a reload is clean.

    Without this, re-running the add-in during development stacks duplicate
    buttons and leaks event handlers. The command module knows exactly what it
    created, so it owns the cleanup too.
    """
    global _app, _ui
    try:
        generate_cmd.stop()

    except Exception:  # noqa: BLE001 -- teardown must not raise into Fusion
        if _ui:
            _ui.messageBox(
                f"{config.ADDIN_NAME} failed to stop:\n{traceback.format_exc()}"
            )
