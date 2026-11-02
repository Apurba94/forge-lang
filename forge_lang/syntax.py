"""Lexer and parser for Forge. The AST is built from small dataclasses."""
import re
from dataclasses import dataclass, field


class ForgeError(Exception):
    def __init__(self, message, line=0):
        super().__init__(f"line {line}: {message}" if line else message)
        self.line = line


KEYWORDS = {"fn", "let", "mut", "if", "else", "while", "for", "in", "return", "break", "continue", "struct", "true", "false", "and", "or", "not"}
TOKEN = re.compile(r"""(?P<ws>[ \t\r]+)|(?P<nl>\n)|(?P<comment>//[^\n]*)
  |(?P<float>\d+\.\d+)|(?P<int>\d+)|(?P<str>"(?:[^"\\\n]|\\.)*")
  |(?P<id>[A-Za-z_]\w*)
  |(?P<op>->|\.\.|==|!=|<=|>=|[-+*/%=<>(){}\[\],;:.])""", re.X)
ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


@dataclass
class Tok:
    kind: str
    value: object
    line: int


def lex(src):
    out, pos, line = [], 0, 1
    while pos < len(src):
        m = TOKEN.match(src, pos)
        if not m:
            raise ForgeError(f"unexpected character {src[pos]!r}", line)
        pos = m.end()
        k, text = m.lastgroup, m.group()
        if k == "nl":
            line += 1
        elif k in ("ws", "comment"):
            pass
        elif k == "int":
            out.append(Tok("int", int(text), line))
        elif k == "float":
            out.append(Tok("float", float(text), line))
        elif k == "str":
            out.append(Tok("str", re.sub(r"\\(.)", lambda e: ESCAPES.get(e.group(1), e.group(1)), text[1:-1]), line))
        elif k == "id":
            out.append(Tok("kw" if text in KEYWORDS else "id", text, line))
        else:
            out.append(Tok("op", text, line))
    out.append(Tok("eof", None, line))
    return out


@dataclass
class Node:
    line: int = 0


@dataclass
class Num(Node):
    value: object = 0


@dataclass
class Str(Node):
    value: str = ""


@dataclass
class Bool(Node):
    value: bool = False


@dataclass
class Name(Node):
    name: str = ""


@dataclass
class Unary(Node):
    op: str = ""
    expr: Node = None


@dataclass
class Binary(Node):
    op: str = ""
    left: Node = None
    right: Node = None


@dataclass
class Call(Node):
    name: str = ""
    args: list = field(default_factory=list)


@dataclass
class ArrayLit(Node):
    items: list = field(default_factory=list)
    elem: object = None


@dataclass
class Index(Node):
    base: Node = None
    index: Node = None


@dataclass
class FieldGet(Node):
    base: Node = None
    name: str = ""
    slot: int = -1


@dataclass
class StructLit(Node):
    name: str = ""
    fields: list = field(default_factory=list)


@dataclass
class Let(Node):
    name: str = ""
    mutable: bool = False
    type: object = None
    value: Node = None


@dataclass
class Assign(Node):
    target: Node = None
    value: Node = None


@dataclass
class ExprStmt(Node):
    expr: Node = None


@dataclass
class If(Node):
    cond: Node = None
    then: list = field(default_factory=list)
    other: list = None


@dataclass
class While(Node):
    cond: Node = None
    body: list = field(default_factory=list)


@dataclass
class For(Node):
    name: str = ""
    start: Node = None
    stop: Node = None
    body: list = field(default_factory=list)


@dataclass
class Return(Node):
    value: Node = None


@dataclass
class Break(Node):
    pass


@dataclass
class Continue(Node):
    pass


@dataclass
class Fn(Node):
    name: str = ""
    params: list = field(default_factory=list)
    ret: object = "void"
    body: list = field(default_factory=list)


@dataclass
class Struct(Node):
    name: str = ""
    fields: list = field(default_factory=list)


PRECEDENCE = [["or"], ["and"], ["==", "!="], ["<", "<=", ">", ">="], ["+", "-"], ["*", "/", "%"]]


class Parser:
    def __init__(self, src):
        self.t = lex(src)
        self.i = 0

    @property
    def tok(self):
        return self.t[self.i]

    def next(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def at(self, value):
        return self.tok.value == value and self.tok.kind in ("op", "kw")

    def accept(self, value):
        if self.at(value):
            return self.next()
        return None

    def expect(self, value):
        if not self.at(value):
            raise ForgeError(f"expected '{value}' but found {self.tok.value!r}", self.tok.line)
        return self.next()

    def ident(self):
        if self.tok.kind != "id":
            raise ForgeError(f"expected a name but found {self.tok.value!r}", self.tok.line)
        return self.next().value

    def program(self):
        items = []
        while self.tok.kind != "eof":
            if self.at("fn"):
                items.append(self.function())
            elif self.at("struct"):
                items.append(self.struct())
            else:
                raise ForgeError(f"expected fn or struct but found {self.tok.value!r}", self.tok.line)
        return items

    def type_(self):
        if self.accept("["):
            inner = self.type_()
            self.expect("]")
            return ("array", inner)
        return self.ident()

    def struct(self):
        line = self.expect("struct").line
        name = self.ident()
        self.expect("{")
        fields = []
        while not self.accept("}"):
            f = self.ident()
            self.expect(":")
            fields.append((f, self.type_()))
            if not self.accept(","):
                self.expect("}")
                break
        return Struct(line, name, fields)

    def function(self):
        line = self.expect("fn").line
        name = self.ident()
        self.expect("(")
        params = []
        while not self.accept(")"):
            p = self.ident()
            self.expect(":")
            params.append((p, self.type_()))
            if not self.accept(","):
                self.expect(")")
                break
        ret = self.type_() if self.accept("->") else "void"
        return Fn(line, name, params, ret, self.block())

    def block(self):
        self.expect("{")
        body = []
        while not self.accept("}"):
            if self.tok.kind == "eof":
                raise ForgeError("missing '}'", self.tok.line)
            body.append(self.statement())
        return body

    def statement(self):
        line = self.tok.line
        if self.accept("let"):
            mutable = bool(self.accept("mut"))
            name = self.ident()
            type_ = self.type_() if self.accept(":") else None
            self.expect("=")
            value = self.expr()
            self.expect(";")
            return Let(line, name, mutable, type_, value)
        if self.accept("if"):
            return self.if_rest(line)
        if self.accept("while"):
            return While(line, self.expr(), self.block())
        if self.accept("for"):
            name = self.ident()
            self.expect("in")
            start = self.expr()
            self.expect("..")
            stop = self.expr()
            return For(line, name, start, stop, self.block())
        if self.accept("return"):
            value = None if self.at(";") else self.expr()
            self.expect(";")
            return Return(line, value)
        if self.accept("break"):
            self.expect(";")
            return Break(line)
        if self.accept("continue"):
            self.expect(";")
            return Continue(line)
        e = self.expr()
        if self.accept("="):
            if not isinstance(e, (Name, Index, FieldGet)):
                raise ForgeError("cannot assign to this expression", line)
            value = self.expr()
            self.expect(";")
            return Assign(line, e, value)
        self.expect(";")
        return ExprStmt(line, e)

    def if_rest(self, line):
        cond = self.expr()
        then = self.block()
        other = None
        if self.accept("else"):
            other = [self.if_rest(self.t[self.i - 1].line)] if self.accept("if") else self.block()
        return If(line, cond, then, other)

    def expr(self, level=0):
        if level == len(PRECEDENCE):
            return self.unary()
        e = self.expr(level + 1)
        while self.tok.kind in ("op", "kw") and self.tok.value in PRECEDENCE[level]:
            op = self.next()
            e = Binary(op.line, op.value, e, self.expr(level + 1))
        return e

    def unary(self):
        if self.at("-") or self.at("not"):
            op = self.next()
            return Unary(op.line, op.value, self.unary())
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while True:
            if self.at("["):
                line = self.next().line
                i = self.expr()
                self.expect("]")
                e = Index(line, e, i)
            elif self.at("."):
                line = self.next().line
                e = FieldGet(line, e, self.ident())
            else:
                return e

    def primary(self):
        tok = self.next()
        if tok.kind in ("int", "float"):
            return Num(tok.line, tok.value)
        if tok.kind == "str":
            return Str(tok.line, tok.value)
        if tok.value in ("true", "false") and tok.kind == "kw":
            return Bool(tok.line, tok.value == "true")
        if tok.kind == "op" and tok.value == "(":
            e = self.expr()
            self.expect(")")
            return e
        if tok.kind == "op" and tok.value == "[":
            items = []
            while not self.accept("]"):
                items.append(self.expr())
                if not self.accept(","):
                    self.expect("]")
                    break
            return ArrayLit(tok.line, items)
        if tok.kind == "id":
            if self.accept("("):
                args = []
                while not self.accept(")"):
                    args.append(self.expr())
                    if not self.accept(","):
                        self.expect(")")
                        break
                return Call(tok.line, tok.value, args)
            if self.at("{") and tok.value[0].isupper():
                self.next()
                fields = []
                while not self.accept("}"):
                    f = self.ident()
                    self.expect(":")
                    fields.append((f, self.expr()))
                    if not self.accept(","):
                        self.expect("}")
                        break
                return StructLit(tok.line, tok.value, fields)
            return Name(tok.line, tok.value)
        raise ForgeError(f"unexpected {tok.value!r}", tok.line)


def parse(src):
    return Parser(src).program()
