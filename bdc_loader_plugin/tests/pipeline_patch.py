"""Patch a name in every module of the load pipeline that reads it."""

import contextlib
import importlib
from unittest.mock import DEFAULT, MagicMock, patch

PIPELINE_MODULES = ("vrt_generator", "vrt_tasks", "vrt_layers", "vrt_overview_run", "ui_wait")


@contextlib.contextmanager
def patch_pipeline(name, new=DEFAULT, **mock_kwargs):
    """Replace ``name`` with one object in each pipeline module that has it; yields that object.

    Like patch.object: without ``new`` the replacement is a MagicMock built from
    ``mock_kwargs`` (return_value, side_effect...). Fails when no module has the name.
    """
    replacement = MagicMock(**mock_kwargs) if new is DEFAULT else new
    modules = [importlib.import_module(f"bdc_loader_plugin.core.{m}") for m in PIPELINE_MODULES]
    holders = [m for m in modules if name in vars(m)]
    if not holders:
        raise AttributeError(f"no load pipeline module has {name!r}")
    with contextlib.ExitStack() as stack:
        for module in holders:
            stack.enter_context(patch.object(module, name, replacement))
        yield replacement
