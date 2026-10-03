"""The package's public surface."""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

import gtnh_shadow_convert


def test_no_export_shadows_a_submodule() -> None:
    # A name exported from the package root replaces the submodule of the same name as an
    # attribute, so `import gtnh_shadow_convert.emit as e` once returned the emit() function
    # rather than the module. Every submodule must stay reachable by its dotted name.
    # __main__ is left out: importing it runs the command line.
    submodules = {
        info.name
        for info in pkgutil.iter_modules(gtnh_shadow_convert.__path__)
        if info.name != "__main__"
    }
    assert not submodules & set(gtnh_shadow_convert.__all__)
    for name in submodules:
        module = importlib.import_module(f"gtnh_shadow_convert.{name}")
        assert isinstance(module, ModuleType)
        assert getattr(gtnh_shadow_convert, name, module) is module


def test_the_emit_module_is_the_module() -> None:
    import gtnh_shadow_convert.emit as emit_module

    assert isinstance(emit_module, ModuleType)
    assert emit_module.version()
    assert gtnh_shadow_convert.convert is emit_module.convert
