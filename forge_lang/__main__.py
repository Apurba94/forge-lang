"""Command line: python -m forge_lang run|dis|check FILE [--no-opt]"""
import sys

from . import VM, ForgeError, ForgeRuntimeError, compile_source


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    if len(args) != 2 or args[0] not in ("run", "dis", "check"):
        print("usage: python -m forge_lang run|dis|check FILE [--no-opt]")
        return 2
    with open(args[1], encoding="utf-8") as f:
        source = f.read()
    try:
        program = compile_source(source, "--no-opt" not in argv)
        if args[0] == "dis":
            print(program.disassemble())
        elif args[0] == "check":
            print(f"ok: {len(program.fns)} functions, {program.size()} instructions")
        else:
            class Echo(list):
                def append(self, line):
                    print(line)
            VM(program, output=Echo()).run()
    except (ForgeError, ForgeRuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
