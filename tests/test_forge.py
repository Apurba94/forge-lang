import os
import random
import unittest

from forge_lang import ForgeError, ForgeRuntimeError, compile_source, run

HERE = os.path.dirname(os.path.abspath(__file__))


def main(body, extra=""):
    return f"{extra}\nfn main() {{\n{body}\n}}\n"


class TestPrograms(unittest.TestCase):
    def both(self, src):
        """Optimised and plain builds must always print the same thing."""
        a, b = run(src), run(src, optimise=False)
        self.assertEqual(a, b)
        return a

    def test_arithmetic_and_precedence(self):
        self.assertEqual(self.both(main("print(1 + 2 * 3); print((1 + 2) * 3); print(7 / 2); print(-7 / 2); print(7 % 3); print(-7 % 3); print(1.5 * 2.0);")), ["7", "9", "3", "-3", "1", "-1", "3.0"])

    def test_integers_wrap_at_64_bits(self):
        self.assertEqual(self.both(main("let big = 9223372036854775807; print(big + 1);")), ["-9223372036854775808"])

    def test_recursion(self):
        src = "fn fib(n: int) -> int { if n < 2 { return n; } return fib(n - 1) + fib(n - 2); }\n" + main("print(fib(15));")
        self.assertEqual(self.both(src), ["610"])

    def test_loops_break_continue(self):
        src = main("""
            let mut total = 0;
            for i in 0..10 {
                if i == 2 { continue; }
                if i == 6 { break; }
                total = total + i;
            }
            print(total);
            let mut n = 0;
            while true { n = n + 1; if n > 4 { break; } }
            print(n);
        """)
        self.assertEqual(self.both(src), ["13", "5"])

    def test_nested_loop_break_only_leaves_the_inner_loop(self):
        src = main("""
            let mut c = 0;
            for i in 0..3 { for j in 0..3 { if j == 1 { break; } c = c + 1; } }
            print(c);
        """)
        self.assertEqual(self.both(src), ["3"])

    def test_short_circuit(self):
        src = "fn boom() -> bool { print(\"boom\"); return true; }\n" + main("print(false and boom()); print(true or boom()); print(true and boom());")
        self.assertEqual(self.both(src), ["false", "true", "boom", "true"])

    def test_arrays_are_shared_references(self):
        src = "fn set(a: [int]) { a[0] = 9; }\n" + main("let a = [1, 2]; set(a); push(a, 3); print(a); print(len(a));")
        self.assertEqual(self.both(src), ["[9, 2, 3]", "3"])

    def test_structs(self):
        src = "struct P { x: int, y: int }\nfn dist(p: P) -> int { return p.x * p.x + p.y * p.y; }\n" + main("let p = P { y: 4, x: 3 }; print(dist(p)); p.x = 0; print(dist(p));")
        self.assertEqual(self.both(src), ["25", "16"])

    def test_array_of_structs(self):
        src = "struct C { n: int }\n" + main("let cs = [C { n: 1 }, C { n: 2 }]; cs[1].n = 5; print(cs[0].n + cs[1].n);")
        self.assertEqual(self.both(src), ["6"])

    def test_strings(self):
        self.assertEqual(self.both(main('let s = "abc"; print(s + "d"); print(len(s)); print(s[1]); print(substr(s, 1, 2)); print(s < "abd"); print(to_int("12") + 1);')), ["abcd", "3", "b", "bc", "true", "13"])

    def test_builtins(self):
        self.assertEqual(self.both(main("print(sqrt(16.0)); print(floor(2.7)); print(to_float(3)); print(to_str(true));")), ["4.0", "2", "3.0", "true"])

    def test_block_scope_shadowing(self):
        src = main("let x = 1; if true { let x = 2; print(x); } print(x);")
        self.assertEqual(self.both(src), ["2", "1"])

    def test_sieve_example(self):
        with open(os.path.join(HERE, "..", "examples", "sieve.fg"), encoding="utf-8") as f:
            self.assertEqual(self.both(f.read()), ["primes below 1000: 168", "largest: 997"])


class TestTypeErrors(unittest.TestCase):
    def bad(self, src, text):
        with self.assertRaises(ForgeError) as c:
            compile_source(src)
        self.assertIn(text, str(c.exception))

    def test_mismatches(self):
        self.bad(main("let x: int = 1.5;"), "expected int")
        self.bad(main('print(1 + "a");'), "matching types")
        self.bad(main("if 1 { }"), "expected bool")
        self.bad(main("let a = [1, true];"), "array item")

    def test_names(self):
        self.bad(main("print(y);"), "unknown name")
        self.bad(main("nope();"), "unknown function")
        self.bad(main("let a = 1; let a = 2;"), "already defined")

    def test_mutability(self):
        self.bad(main("let a = 1; a = 2;"), "not mutable")

    def test_functions(self):
        self.bad("fn f() -> int { }\nfn main() { }", "always return")
        self.bad("fn f(a: int) { }\n" + main("f();"), "takes 1 arguments")
        self.bad("fn f() { return 1; }\n" + main(""), "returns nothing")
        self.bad("fn f() { }", "no main")

    def test_structs(self):
        self.bad("struct P { x: int }\n" + main("let p = P { y: 1 };"), "exactly the fields")
        self.bad("struct P { x: int }\n" + main("let p = P { x: 1 }; print(p.z);"), "no field")
        self.bad("fn f(q: Q) { }\n" + main(""), "unknown type")

    def test_control(self):
        self.bad(main("break;"), "outside a loop")
        self.bad(main("let a = [];"), "array is empty")

    def test_syntax_errors_name_the_line(self):
        with self.assertRaises(ForgeError) as c:
            compile_source("fn main() {\n  let = 3;\n}")
        self.assertEqual(c.exception.line, 2)


class TestRuntimeErrors(unittest.TestCase):
    def test_runtime_failures(self):
        for body, text in [("let z = 0; print(1 / z);", "division by zero"), ("let a = [1]; print(a[3]);", "outside a sequence"), ('print(to_int("x"));', "not a number"), ("print(sqrt(-1.0));", "square root")]:
            with self.assertRaises(ForgeRuntimeError) as c:
                run(main(body))
            self.assertIn(text, str(c.exception))

    def test_folded_division_by_zero_still_fails_when_run(self):
        with self.assertRaises(ForgeRuntimeError):
            run(main("print(1 / 0);"))

    def test_runaway_programs_stop(self):
        with self.assertRaises(ForgeRuntimeError) as c:
            run(main("while true { }"), max_steps=10000)
        self.assertIn("step limit", str(c.exception))
        with self.assertRaises(ForgeRuntimeError) as c:
            run("fn f() { f(); }\n" + main("f();"), max_depth=100)
        self.assertIn("call depth", str(c.exception))

    def test_error_reports_the_line(self):
        with self.assertRaises(ForgeRuntimeError) as c:
            run("fn main() {\n  let z = 0;\n  print(1 / z);\n}")
        self.assertIn("line 3", str(c.exception))


class TestOptimiser(unittest.TestCase):
    def size(self, src, opt):
        return compile_source(src, opt).size()

    def test_constants_fold(self):
        src = main("print(2 * 3 + 4 * 5);")
        self.assertLess(self.size(src, True), self.size(src, False))
        self.assertIn("26", compile_source(src).disassemble())

    def test_dead_code_goes(self):
        src = main('if false { print("gone"); } print("kept");')
        d = compile_source(src).disassemble()
        self.assertNotIn("gone", d)
        src = "fn f() -> int { return 1; print(2); }\n" + main("print(f());")
        self.assertLess(self.size(src, True), self.size(src, False))

    def test_jump_threading_keeps_behaviour(self):
        src = main("""
            let mut n = 0;
            for i in 0..5 { if i % 2 == 0 { if i > 2 { n = n + 10; } else { n = n + 1; } } else { n = n + 100; } }
            print(n);
        """)
        self.assertEqual(run(src), run(src, optimise=False))

    def test_fewer_steps_at_run_time(self):
        from forge_lang import VM
        src = main("let mut t = 0; for i in 0..100 { t = t + 2 * 3 * 4; } print(t);")
        a, b = VM(compile_source(src, True)), VM(compile_source(src, False))
        a.run()
        b.run()
        self.assertLess(a.steps, b.steps)


class TestRandomExpressions(unittest.TestCase):
    """Generate random integer programs and compare with an independent evaluation in Python."""

    def gen(self, rng, depth):
        if depth == 0 or rng.random() < 0.25:
            return rng.choice(["a", "b", str(rng.randint(0, 50))])
        op = rng.choice(["+", "-", "*", "/", "%"])
        return f"({self.gen(rng, depth - 1)} {op} {self.gen(rng, depth - 1)})"

    @staticmethod
    def py(expr, a, b):
        def div(x, y):
            if y == 0:
                raise ZeroDivisionError
            q = abs(x) // abs(y)
            return q if (x >= 0) == (y >= 0) else -q

        class I(int):
            def __add__(s, o): return I(int(s) + int(o))
            def __sub__(s, o): return I(int(s) - int(o))
            def __mul__(s, o): return I(int(s) * int(o))
            def __truediv__(s, o): return I(div(int(s), int(o)))
            def __mod__(s, o): return I(int(s) - int(o) * div(int(s), int(o)))
            __radd__ = __add__
            def __rsub__(s, o): return I(int(o) - int(s))
            __rmul__ = __mul__
        import re
        code = re.sub(r"\b(\d+)\b", r"I(\1)", expr)
        return int(eval(code, {"I": I, "a": I(a), "b": I(b)}))

    def test_many(self):
        rng = random.Random(3)
        for _ in range(300):
            e = self.gen(rng, 4)
            a, b = rng.randint(-20, 20), rng.randint(-20, 20)
            src = main(f"let a = 0 + ({a}); let b = 0 + ({b}); print({e});")
            try:
                want = self.py(e, a, b)
            except ZeroDivisionError:
                with self.assertRaises(ForgeRuntimeError):
                    run(src)
                continue
            self.assertEqual(run(src), [str(want)], e)
            self.assertEqual(run(src, optimise=False), [str(want)], e)


if __name__ == "__main__":
    unittest.main()
