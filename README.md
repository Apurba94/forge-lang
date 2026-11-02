# Forge

A small statically typed programming language with a complete pipeline, written in pure Python: lexer, parser, type checker, optimiser, bytecode compiler and stack virtual machine.

```
struct Point { x: int, y: int }

fn norm(p: Point) -> int {
    return p.x * p.x + p.y * p.y;
}

fn main() {
    let points = [Point { x: 3, y: 4 }, Point { x: 1, y: 1 }];
    let mut total = 0;
    for i in 0..len(points) {
        total = total + norm(points[i]);
    }
    print(total);
}
```

## Run it

```
python -m forge_lang run examples/sieve.fg
python -m forge_lang dis examples/sieve.fg
python -m forge_lang check examples/sieve.fg
```

`dis` prints the bytecode, which is the best way to see what the compiler does. Add `--no-opt` to compare it with the unoptimised output.

## The language

- Types: `int` (64-bit, wrapping), `float`, `bool`, `str`, arrays such as `[int]`, and structs
- `let` is immutable unless you write `let mut`, and local types are inferred
- `if`, `while`, `for i in a..b`, `break`, `continue`, functions and recursion
- Built-ins: `print`, `len`, `push`, `sqrt`, `floor`, `to_float`, `to_str`, `to_int`, `substr`

## The pipeline

| Stage | File | What it does |
|---|---|---|
| Lexer and parser | `syntax.py` | Source text to a typed tree, with line numbers in every error |
| Type checker | `types.py` | Types, mutability, scope and "does every path return?" |
| Optimiser | `compiler.py` | Constant folding, dead-branch and unreachable-code removal, then bytecode peephole passes and jump threading |
| Compiler | `compiler.py` | Tree to stack bytecode |
| Virtual machine | `vm.py` | Runs bytecode, with bounds checks and limits on steps and call depth |

## How it is tested

Every program in the behaviour tests runs with and without the optimiser, and both must print the same. A further test generates 300 random integer programs and compares the results with an independent evaluation in Python, including division by zero.

## Limits

Forge has no closures, generics or modules, and the virtual machine is interpreted in Python, so it is much slower than a native language. It exists to show how a compiler works.

MIT licence.
