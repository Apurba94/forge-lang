"""The type checker. It also records what the compiler needs, such as struct field slots."""
from .syntax import ArrayLit, Assign, Binary, Bool, Break, Call, Continue, ExprStmt, FieldGet, Fn, For, ForgeError, If, Index, Let, Name, Num, Return, Str, Struct, StructLit, Unary, While

BASE = {"int", "float", "bool", "str", "void"}
BUILTINS = {"print": (None, "void"), "len": (None, "int"), "push": (None, "void"), "sqrt": (["float"], "float"), "floor": (["float"], "int"),
            "to_float": (["int"], "float"), "to_str": (None, "str"), "to_int": (["str"], "int"), "substr": (["str", "int", "int"], "str")}


def show(t):
    return f"[{show(t[1])}]" if isinstance(t, tuple) else str(t)


class Checker:
    def __init__(self, items):
        self.items = items
        self.structs = {}
        self.fns = {}
        self.scopes = []
        self.ret = None
        self.loops = 0

    def check(self):
        for it in self.items:
            if isinstance(it, Struct):
                if it.name in self.structs:
                    raise ForgeError(f"struct {it.name} is defined twice", it.line)
                self.structs[it.name] = it
        for it in self.items:
            if isinstance(it, Struct):
                for name, t in it.fields:
                    self.known(t, it.line)
            else:
                if it.name in self.fns or it.name in BUILTINS:
                    raise ForgeError(f"function {it.name} is defined twice", it.line)
                self.fns[it.name] = it
                for _, t in it.params:
                    self.known(t, it.line)
                self.known(it.ret, it.line)
        if "main" not in self.fns:
            raise ForgeError("the program has no main function")
        if self.fns["main"].params or self.fns["main"].ret != "void":
            raise ForgeError("main takes no parameters and returns nothing", self.fns["main"].line)
        for it in self.items:
            if isinstance(it, Fn):
                self.function(it)
        return self

    def known(self, t, line):
        if isinstance(t, tuple):
            return self.known(t[1], line)
        if t not in BASE and t not in self.structs:
            raise ForgeError(f"unknown type {t}", line)

    def function(self, fn):
        self.scopes = [{}]
        self.ret = fn.ret
        for name, t in fn.params:
            if name in self.scopes[0]:
                raise ForgeError(f"parameter {name} appears twice", fn.line)
            self.scopes[0][name] = (t, False)
        self.block(fn.body, new_scope=False)
        if fn.ret != "void" and not self.always_returns(fn.body):
            raise ForgeError(f"function {fn.name} does not always return a value", fn.line)

    def always_returns(self, body):
        for s in body:
            if isinstance(s, Return):
                return True
            if isinstance(s, If) and s.other is not None and self.always_returns(s.then) and self.always_returns(s.other):
                return True
        return False

    def block(self, body, new_scope=True):
        if new_scope:
            self.scopes.append({})
        for s in body:
            self.stmt(s)
        if new_scope:
            self.scopes.pop()

    def lookup(self, name, line):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise ForgeError(f"unknown name {name}", line)

    def stmt(self, s):
        if isinstance(s, Let):
            t = self.expr(s.value, s.type)
            if s.type is not None:
                self.known(s.type, s.line)
                self.same(s.type, t, s.line, f"let {s.name}")
                t = s.type
            if t == "void":
                raise ForgeError("cannot store a void value", s.line)
            if t == ("array", None):
                raise ForgeError(f"give {s.name} a type: its array is empty", s.line)
            if s.name in self.scopes[-1]:
                raise ForgeError(f"{s.name} is already defined in this block", s.line)
            self.scopes[-1][s.name] = (t, s.mutable)
        elif isinstance(s, Assign):
            if isinstance(s.target, Name):
                t, mutable = self.lookup(s.target.name, s.line)
                if not mutable:
                    raise ForgeError(f"{s.target.name} is not mutable: declare it with let mut", s.line)
            else:
                t = self.expr(s.target)     # arrays and structs are references, so their contents can change
            self.same(t, self.expr(s.value, t), s.line, "assignment")
        elif isinstance(s, ExprStmt):
            self.expr(s.expr)
        elif isinstance(s, If):
            self.cond(s.cond)
            self.block(s.then)
            if s.other is not None:
                self.block(s.other)
        elif isinstance(s, While):
            self.cond(s.cond)
            self.loops += 1
            self.block(s.body)
            self.loops -= 1
        elif isinstance(s, For):
            self.same("int", self.expr(s.start), s.line, "for start")
            self.same("int", self.expr(s.stop), s.line, "for stop")
            self.scopes.append({s.name: ("int", False)})
            self.loops += 1
            self.block(s.body)
            self.loops -= 1
            self.scopes.pop()
        elif isinstance(s, Return):
            if s.value is None:
                if self.ret != "void":
                    raise ForgeError(f"expected a {show(self.ret)} return value", s.line)
            else:
                if self.ret == "void":
                    raise ForgeError("this function returns nothing", s.line)
                self.same(self.ret, self.expr(s.value, self.ret), s.line, "return")
        elif isinstance(s, (Break, Continue)):
            if not self.loops:
                raise ForgeError("break or continue outside a loop", s.line)

    def cond(self, e):
        self.same("bool", self.expr(e), e.line, "condition")

    def same(self, want, got, line, what):
        if want != got and not (isinstance(want, tuple) and got == ("array", None)):
            raise ForgeError(f"{what}: expected {show(want)} but got {show(got)}", line)

    def expr(self, e, hint=None):
        t = self.infer(e, hint)
        e.type = t
        return t

    def infer(self, e, hint):
        if isinstance(e, Num):
            return "int" if isinstance(e.value, int) else "float"
        if isinstance(e, Str):
            return "str"
        if isinstance(e, Bool):
            return "bool"
        if isinstance(e, Name):
            return self.lookup(e.name, e.line)[0]
        if isinstance(e, Unary):
            t = self.expr(e.expr)
            if e.op == "not":
                self.same("bool", t, e.line, "not")
                return "bool"
            if t not in ("int", "float"):
                raise ForgeError(f"cannot negate {show(t)}", e.line)
            return t
        if isinstance(e, Binary):
            a, b = self.expr(e.left), self.expr(e.right)
            if e.op in ("and", "or"):
                self.same("bool", a, e.line, e.op)
                self.same("bool", b, e.line, e.op)
                return "bool"
            if a != b:
                raise ForgeError(f"'{e.op}' needs matching types, got {show(a)} and {show(b)}", e.line)
            if e.op in ("==", "!="):
                if a in ("void",) or isinstance(a, tuple) or a in self.structs:
                    raise ForgeError(f"cannot compare {show(a)}", e.line)
                return "bool"
            if e.op in ("<", "<=", ">", ">="):
                if a not in ("int", "float", "str"):
                    raise ForgeError(f"cannot order {show(a)}", e.line)
                return "bool"
            if e.op == "+" and a == "str":
                return "str"
            if e.op == "%" and a != "int":
                raise ForgeError("% needs integers", e.line)
            if a not in ("int", "float"):
                raise ForgeError(f"'{e.op}' cannot use {show(a)}", e.line)
            return a
        if isinstance(e, Call):
            return self.call(e)
        if isinstance(e, ArrayLit):
            if not e.items:
                return hint if isinstance(hint, tuple) else ("array", None)
            t = self.expr(e.items[0], hint[1] if isinstance(hint, tuple) else None)
            for item in e.items[1:]:
                self.same(t, self.expr(item), item.line, "array item")
            return ("array", t)
        if isinstance(e, Index):
            base = self.expr(e.base)
            self.same("int", self.expr(e.index), e.line, "index")
            if base == "str":
                return "str"
            if not isinstance(base, tuple):
                raise ForgeError(f"cannot index {show(base)}", e.line)
            return base[1]
        if isinstance(e, FieldGet):
            base = self.expr(e.base)
            if base not in self.structs:
                raise ForgeError(f"{show(base)} has no fields", e.line)
            for i, (name, t) in enumerate(self.structs[base].fields):
                if name == e.name:
                    e.slot = i
                    return t
            raise ForgeError(f"{base} has no field {e.name}", e.line)
        if isinstance(e, StructLit):
            if e.name not in self.structs:
                raise ForgeError(f"unknown struct {e.name}", e.line)
            want = self.structs[e.name].fields
            got = dict(e.fields)
            if len(got) != len(e.fields) or set(got) != {n for n, _ in want}:
                raise ForgeError(f"{e.name} needs exactly the fields {', '.join(n for n, _ in want)}", e.line)
            e.ordered = []
            for name, t in want:
                self.same(t, self.expr(got[name], t), e.line, f"field {name}")
                e.ordered.append(got[name])
            return e.name
        raise ForgeError(f"cannot type {type(e).__name__}", e.line)

    def call(self, e):
        if e.name in BUILTINS:
            params, ret = BUILTINS[e.name]
            args = [self.expr(a) for a in e.args]
            if e.name == "print":
                if len(args) != 1 or args[0] == "void":
                    raise ForgeError("print takes one value", e.line)
            elif e.name == "len":
                if len(args) != 1 or not (args[0] == "str" or isinstance(args[0], tuple)):
                    raise ForgeError("len takes a string or an array", e.line)
            elif e.name == "push":
                if len(args) != 2 or not isinstance(args[0], tuple):
                    raise ForgeError("push takes an array and a value", e.line)
                if args[0][1] is not None:
                    self.same(args[0][1], args[1], e.line, "push")
            elif e.name == "to_str":
                if len(args) != 1:
                    raise ForgeError("to_str takes one value", e.line)
            else:
                if len(args) != len(params):
                    raise ForgeError(f"{e.name} takes {len(params)} arguments", e.line)
                for w, g in zip(params, args):
                    self.same(w, g, e.line, e.name)
            return ret
        fn = self.fns.get(e.name)
        if fn is None:
            raise ForgeError(f"unknown function {e.name}", e.line)
        if len(e.args) != len(fn.params):
            raise ForgeError(f"{e.name} takes {len(fn.params)} arguments, got {len(e.args)}", e.line)
        for (name, want), arg in zip(fn.params, e.args):
            self.same(want, self.expr(arg, want), e.line, f"argument {name}")
        return fn.ret
