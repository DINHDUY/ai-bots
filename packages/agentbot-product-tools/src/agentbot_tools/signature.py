"""Build a typed async function from a validated parameter list."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

IDENT = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def bind_parameters(name, description, parameters, optional, call):
    """Return an async function whose signature is the tool's parameter list.

    Names are identifiers validated by the caller. The description is assigned
    after construction so it cannot change the function body.
    """
    if not IDENT.fullmatch(name) or any(not IDENT.fullmatch(param) for param in parameters):
        raise RuntimeError(f"Invalid tool function name: {name}")
    parts = [f"{param}: str = ''" if param in optional else f"{param}: str" for param in parameters]
    arguments = ", ".join(f"{param}={param}" for param in parameters)
    source = f"async def {name}({', '.join(parts)}) -> str:\n    return await _call({arguments})\n"
    namespace: dict[str, Callable[..., Awaitable[str]]] = {"_call": call}
    exec(source, namespace)  # noqa: S102 - parameter names are checked identifiers
    function = namespace[name]
    function.__doc__ = description
    return function
