"""Every module in this package is a vertical. The factory mounts each one's `router`, calls its
`seed(store)` in local mode, and the gateway calls its `register_tools(gateway)`; all optional."""

import importlib
import pkgutil
from collections.abc import Iterator
from types import ModuleType


def modules() -> Iterator[ModuleType]:
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        yield importlib.import_module(f"{__name__}.{info.name}")
