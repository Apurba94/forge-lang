"""The stack virtual machine. Every run has limits on steps and call depth."""
import math

from .compiler import int_div, wrap


class ForgeRuntimeError(Exception):
    pass


def text(v):
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, list):
        return "[" + ", ".join(text(x) for x in v) + "]"
    return str(v)


class VM:
    def __init__(self, program, output=None, max_steps=50_000_000, max_depth=2000):
        self.p = program
        self.out = output if output is not None else []
        self.max_steps = max_steps
        self.max_depth = max_depth
        self.steps = 0

    def fail(self, f, ip, message):
        line = f.lines[ip] if ip < len(f.lines) else 0
        raise ForgeRuntimeError(f"line {line} in {f.name}: {message}")

    def run(self):
        fns = self.p.fns
        f = fns[self.p.main]
        code = f.code
        slots = [None] * f.locals
        stack = []
        frames = []
        ip = 0
        steps = 0
        limit = self.max_steps
        while True:
            op, arg = code[ip]
            ip += 1
            steps += 1
            if steps > limit:
                self.steps = steps
                self.fail(f, ip - 1, f"step limit of {limit} reached")
            if op == "LOAD":
                stack.append(slots[arg])
            elif op == "CONST":
                stack.append(arg)
            elif op == "STORE":
                slots[arg] = stack.pop()
            elif op == "INC":
                slots[arg] = wrap(slots[arg] + 1)
            elif op == "ADD":
                b = stack.pop()
                a = stack.pop()
                stack.append(wrap(a + b) if isinstance(a, int) else a + b)
            elif op == "SUB":
                b = stack.pop()
                a = stack.pop()
                stack.append(wrap(a - b) if isinstance(a, int) else a - b)
            elif op == "MUL":
                b = stack.pop()
                a = stack.pop()
                stack.append(wrap(a * b) if isinstance(a, int) else a * b)
            elif op == "DIV":
                b = stack.pop()
                a = stack.pop()
                if b == 0:
                    self.fail(f, ip - 1, "division by zero")
                stack.append(wrap(int_div(a, b)) if isinstance(a, int) else a / b)
            elif op == "MOD":
                b = stack.pop()
                a = stack.pop()
                if b == 0:
                    self.fail(f, ip - 1, "division by zero")
                stack.append(a - b * int_div(a, b))
            elif op == "LT":
                b = stack.pop()
                stack.append(stack.pop() < b)
            elif op == "LE":
                b = stack.pop()
                stack.append(stack.pop() <= b)
            elif op == "GT":
                b = stack.pop()
                stack.append(stack.pop() > b)
            elif op == "GE":
                b = stack.pop()
                stack.append(stack.pop() >= b)
            elif op == "EQ":
                b = stack.pop()
                stack.append(stack.pop() == b)
            elif op == "NE":
                b = stack.pop()
                stack.append(stack.pop() != b)
            elif op == "NOT":
                stack.append(not stack.pop())
            elif op == "NEG":
                a = stack.pop()
                stack.append(wrap(-a) if isinstance(a, int) else -a)
            elif op == "JMP":
                ip = arg
            elif op == "JF":
                if not stack.pop():
                    ip = arg
            elif op == "JT":
                if stack.pop():
                    ip = arg
            elif op == "DUP":
                stack.append(stack[-1])
            elif op == "POP":
                stack.pop()
            elif op == "CALL":
                callee = fns[arg]
                if len(frames) >= self.max_depth:
                    self.fail(f, ip - 1, f"call depth limit of {self.max_depth} reached")
                frames.append((f, code, slots, ip))
                n = callee.params
                new = stack[len(stack) - n:] if n else []
                if n:
                    del stack[len(stack) - n:]
                new.extend([None] * (callee.locals - n))
                f, code, slots, ip = callee, callee.code, new, 0
            elif op == "RET" or op == "RET0":
                if not frames:
                    self.steps = steps
                    return self.out
                f, code, slots, ip = frames.pop()
            elif op == "ARRAY":
                if arg:
                    items = stack[len(stack) - arg:]
                    del stack[len(stack) - arg:]
                else:
                    items = []
                stack.append(items)
            elif op == "GETITEM":
                i = stack.pop()
                a = stack.pop()
                if not 0 <= i < len(a):
                    self.fail(f, ip - 1, f"index {i} is outside a sequence of length {len(a)}")
                stack.append(a[i])
            elif op == "SETITEM":
                v = stack.pop()
                i = stack.pop()
                a = stack.pop()
                if not 0 <= i < len(a):
                    self.fail(f, ip - 1, f"index {i} is outside a sequence of length {len(a)}")
                a[i] = v
            elif op == "GETFIELD":
                stack.append(stack.pop()[arg])
            elif op == "SETFIELD":
                v = stack.pop()
                stack.pop()[arg] = v
            elif op == "BUILTIN":
                self.builtin(arg, stack, f, ip)
            else:
                self.fail(f, ip - 1, f"bad instruction {op}")

    def builtin(self, spec, stack, f, ip):
        name, n = spec
        args = stack[len(stack) - n:]
        del stack[len(stack) - n:]
        if name == "print":
            self.out.append(text(args[0]))
        elif name == "len":
            stack.append(len(args[0]))
        elif name == "push":
            args[0].append(args[1])
        elif name == "sqrt":
            if args[0] < 0:
                self.fail(f, ip - 1, "square root of a negative number")
            stack.append(math.sqrt(args[0]))
        elif name == "floor":
            stack.append(math.floor(args[0]))
        elif name == "to_float":
            stack.append(float(args[0]))
        elif name == "to_str":
            stack.append(text(args[0]))
        elif name == "to_int":
            try:
                stack.append(int(args[0]))
            except ValueError:
                self.fail(f, ip - 1, f"not a number: {args[0]!r}")
        elif name == "substr":
            stack.append(args[0][args[1]:args[1] + args[2]])
