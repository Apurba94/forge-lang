"""Turns a checked AST into bytecode, with an optimiser at the tree and the bytecode level."""
from .syntax import ArrayLit, Assign, Binary, Bool, Break, Call, Continue, ExprStmt, FieldGet, Fn, For, ForgeError, If, Index, Let, Name, Num, Return, Str, Struct, StructLit, Unary, While
from .types import BUILTINS, Checker
from .syntax import parse

JUMPS = {"JMP", "JF", "JT"}


def wrap(n):
    """Integers are 64-bit and wrap around, as they do in compiled languages."""
    return (n + (1 << 63)) % (1 << 64) - (1 << 63)


def int_div(a, b):
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def fold(e):
    """Constant folding: evaluate what is known at compile time, without changing behaviour."""
    if isinstance(e, Unary):
        e.expr = fold(e.expr)
        if e.op == "-" and isinstance(e.expr, Num):
            n = Num(e.line, wrap(-e.expr.value) if isinstance(e.expr.value, int) else -e.expr.value)
            n.type = e.type
            return n
        if e.op == "not" and isinstance(e.expr, Bool):
            n = Bool(e.line, not e.expr.value)
            n.type = "bool"
            return n
        return e
    if isinstance(e, Binary):
        e.left, e.right = fold(e.left), fold(e.right)
        a, b = e.left, e.right
        if isinstance(a, Bool) and e.op in ("and", "or"):
            if e.op == "and":
                return b if a.value else a
            return a if a.value else b
        if isinstance(a, Num) and isinstance(b, Num):
            x, y, op = a.value, b.value, e.op
            if op in ("/", "%") and y == 0:
                return e        # keep it, so the error appears at run time
            ints = isinstance(x, int)
            if op in ("+", "-", "*", "/", "%"):
                v = {"+": lambda: x + y, "-": lambda: x - y, "*": lambda: x * y, "/": lambda: int_div(x, y) if ints else x / y, "%": lambda: x - y * int_div(x, y) if ints else 0}[op]()
                n = Num(e.line, wrap(v) if ints else v)
                n.type = e.type
                return n
            v = {"==": x == y, "!=": x != y, "<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op]
            n = Bool(e.line, v)
            n.type = "bool"
            return n
        if isinstance(a, Str) and isinstance(b, Str) and e.op == "+":
            n = Str(e.line, a.value + b.value)
            n.type = "str"
            return n
        return e
    if isinstance(e, Call):
        e.args = [fold(a) for a in e.args]
    elif isinstance(e, ArrayLit):
        e.items = [fold(a) for a in e.items]
    elif isinstance(e, Index):
        e.base, e.index = fold(e.base), fold(e.index)
    elif isinstance(e, FieldGet):
        e.base = fold(e.base)
    elif isinstance(e, StructLit):
        e.ordered = [fold(a) for a in e.ordered]
    return e


def fold_body(body):
    out = []
    for s in body:
        if isinstance(s, (Let, Assign)):
            s.value = fold(s.value)
        elif isinstance(s, ExprStmt):
            s.expr = fold(s.expr)
        elif isinstance(s, Return) and s.value is not None:
            s.value = fold(s.value)
        elif isinstance(s, If):
            s.cond = fold(s.cond)
            s.then = fold_body(s.then)
            s.other = fold_body(s.other) if s.other is not None else None
            if isinstance(s.cond, Bool):        # dead branch elimination
                chosen = s.then if s.cond.value else (s.other or [])
                if not any(isinstance(x, Let) for x in chosen):
                    out.extend(chosen)
                    continue
                s = If(s.line, Bool(s.line, True), chosen, None)
                s.cond.type = "bool"
        elif isinstance(s, While):
            s.cond = fold(s.cond)
            s.body = fold_body(s.body)
            if isinstance(s.cond, Bool) and not s.cond.value:
                continue
        elif isinstance(s, For):
            s.start, s.stop = fold(s.start), fold(s.stop)
            s.body = fold_body(s.body)
        out.append(s)
        if isinstance(s, (Return, Break, Continue)):
            break       # the rest of the block can never run
    return out


class FnCode:
    def __init__(self, name, params):
        self.name = name
        self.params = params
        self.locals = params
        self.code = []
        self.lines = []


class Compiler:
    def __init__(self, optimise=True):
        self.optimise = optimise
        self.fns = {}

    def compile(self, items):
        order = [it for it in items if isinstance(it, Fn)]
        self.index = {fn.name: i for i, fn in enumerate(order)}
        out = []
        for fn in order:
            if self.optimise:
                fn.body = fold_body(fn.body)
            out.append(self.function(fn))
        return Program(out, self.index["main"])

    def function(self, fn):
        self.f = FnCode(fn.name, len(fn.params))
        self.scopes = [{name: i for i, (name, _) in enumerate(fn.params)}]
        self.next_slot = len(fn.params)
        self.loops = []
        self.line = fn.line
        self.block(fn.body, False)
        self.emit("RET0")
        self.f.locals = self.next_slot
        if self.optimise:
            peephole(self.f)
        return self.f

    def emit(self, op, arg=None):
        self.f.code.append((op, arg))
        self.f.lines.append(self.line)
        return len(self.f.code) - 1

    def patch(self, at, target=None):
        self.f.code[at] = (self.f.code[at][0], len(self.f.code) if target is None else target)

    def declare(self, name):
        slot = self.next_slot
        self.next_slot += 1
        self.scopes[-1][name] = slot
        return slot

    def slot(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise ForgeError(f"unknown name {name}")

    def block(self, body, scope=True):
        if scope:
            self.scopes.append({})
        for s in body:
            self.line = s.line
            self.stmt(s)
        if scope:
            self.scopes.pop()

    def stmt(self, s):
        if isinstance(s, Let):
            self.expr(s.value)
            self.emit("STORE", self.declare(s.name))
        elif isinstance(s, Assign):
            t = s.target
            if isinstance(t, Name):
                self.expr(s.value)
                self.emit("STORE", self.slot(t.name))
            elif isinstance(t, Index):
                self.expr(t.base)
                self.expr(t.index)
                self.expr(s.value)
                self.emit("SETITEM")
            else:
                self.expr(t.base)
                self.expr(s.value)
                self.emit("SETFIELD", t.slot)
        elif isinstance(s, ExprStmt):
            self.expr(s.expr)
            if s.expr.type != "void":
                self.emit("POP")
        elif isinstance(s, If):
            self.expr(s.cond)
            jf = self.emit("JF")
            self.block(s.then)
            if s.other:
                j = self.emit("JMP")
                self.patch(jf)
                self.block(s.other)
                self.patch(j)
            else:
                self.patch(jf)
        elif isinstance(s, While):
            start = len(self.f.code)
            self.expr(s.cond)
            jf = self.emit("JF")
            self.loops.append(([], []))
            self.block(s.body)
            brk, cont = self.loops.pop()
            for c in cont:
                self.patch(c, start)
            self.emit("JMP", start)
            self.patch(jf)
            for b in brk:
                self.patch(b)
        elif isinstance(s, For):
            self.scopes.append({})
            i = self.declare(s.name)
            stop = self.declare(f"${i}")
            self.expr(s.start)
            self.emit("STORE", i)
            self.expr(s.stop)
            self.emit("STORE", stop)
            start = len(self.f.code)
            self.emit("LOAD", i)
            self.emit("LOAD", stop)
            self.emit("LT")
            jf = self.emit("JF")
            self.loops.append(([], []))
            self.block(s.body)
            brk, cont = self.loops.pop()
            for c in cont:
                self.patch(c)
            self.emit("INC", i)
            self.emit("JMP", start)
            self.patch(jf)
            for b in brk:
                self.patch(b)
            self.scopes.pop()
        elif isinstance(s, Return):
            if s.value is None:
                self.emit("RET0")
            else:
                self.expr(s.value)
                self.emit("RET")
        elif isinstance(s, Break):
            self.loops[-1][0].append(self.emit("JMP"))
        elif isinstance(s, Continue):
            self.loops[-1][1].append(self.emit("JMP"))

    def expr(self, e):
        self.line = e.line or self.line
        if isinstance(e, (Num, Str, Bool)):
            self.emit("CONST", e.value)
        elif isinstance(e, Name):
            self.emit("LOAD", self.slot(e.name))
        elif isinstance(e, Unary):
            self.expr(e.expr)
            self.emit("NOT" if e.op == "not" else "NEG")
        elif isinstance(e, Binary):
            if e.op in ("and", "or"):
                self.expr(e.left)
                self.emit("DUP")
                j = self.emit("JF" if e.op == "and" else "JT")
                self.emit("POP")
                self.expr(e.right)
                self.patch(j)
                return
            self.expr(e.left)
            self.expr(e.right)
            self.line = e.line
            self.emit({"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD", "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE"}[e.op])
        elif isinstance(e, Call):
            for a in e.args:
                self.expr(a)
            self.line = e.line
            if e.name in BUILTINS:
                self.emit("BUILTIN", (e.name, len(e.args)))
            else:
                self.emit("CALL", self.index[e.name])
        elif isinstance(e, ArrayLit):
            for a in e.items:
                self.expr(a)
            self.emit("ARRAY", len(e.items))
        elif isinstance(e, Index):
            self.expr(e.base)
            self.expr(e.index)
            self.line = e.line
            self.emit("GETITEM")
        elif isinstance(e, FieldGet):
            self.expr(e.base)
            self.emit("GETFIELD", e.slot)
        elif isinstance(e, StructLit):
            for a in e.ordered:
                self.expr(a)
            self.emit("ARRAY", len(e.ordered))
        else:
            raise ForgeError(f"cannot compile {type(e).__name__}", e.line)


def peephole(f):
    """Bytecode clean-ups. Removing an instruction shifts jumps, so a remap table fixes them."""
    code, lines = f.code, f.lines
    changed = True
    while changed:
        changed = False
        targets = {arg for op, arg in code if op in JUMPS}
        keep = [True] * len(code)
        new = list(code)
        i = 0
        while i < len(new) - 1:
            a, b = new[i], new[i + 1]
            if i + 1 in targets:
                i += 1
                continue
            if a[0] == "CONST" and b[0] == "POP":
                keep[i] = keep[i + 1] = False
                i += 2
                continue
            if a[0] == "STORE" and b == ("LOAD", a[1]):
                new[i] = ("DUP", None)
                new[i + 1] = a
                changed = True
            if a[0] == "CONST" and a[1] is True and b[0] == "JF":
                keep[i] = keep[i + 1] = False
                i += 2
                continue
            if a[0] == "JMP" and a[1] == i + 1:
                keep[i] = False
            i += 1
        # a jump to a jump goes straight to the final target
        for i, (op, arg) in enumerate(new):
            if op in JUMPS and arg is not None and arg < len(new) and new[arg][0] == "JMP" and new[arg][1] != arg and new[arg][1] != i:
                new[i] = (op, new[arg][1])
                changed = True
        if not all(keep):
            changed = True
            remap, pos = [], 0
            for k in keep:
                remap.append(pos)
                pos += 1 if k else 0
            remap.append(pos)
            code = [(op, remap[arg] if op in JUMPS else arg) for (op, arg), k in zip(new, keep) if k]
            lines = [l for l, k in zip(lines, keep) if k]
        else:
            code = new
    f.code, f.lines = code, lines


class Program:
    def __init__(self, fns, main):
        self.fns = fns
        self.main = main

    def size(self):
        return sum(len(f.code) for f in self.fns)

    def disassemble(self):
        out = []
        for f in self.fns:
            out.append(f"fn {f.name} (params {f.params}, locals {f.locals})")
            for i, (op, arg) in enumerate(f.code):
                out.append(f"  {i:4d}  {op:<9}{'' if arg is None else repr(arg)}")
        return "\n".join(out)


def compile_source(src, optimise=True):
    items = parse(src)
    Checker(items).check()
    return Compiler(optimise).compile(items)
