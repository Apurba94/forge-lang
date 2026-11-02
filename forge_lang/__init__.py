"""Forge: a small statically typed language with a compiler and a virtual machine."""
from .compiler import Program, compile_source
from .syntax import ForgeError
from .vm import VM, ForgeRuntimeError


def run(source, optimise=True, **limits):
    """Compile and run a program, and return its printed lines."""
    return VM(compile_source(source, optimise), **limits).run()


__all__ = ["run", "compile_source", "Program", "VM", "ForgeError", "ForgeRuntimeError"]
