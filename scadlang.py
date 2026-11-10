"""A practical OpenSCAD subset: lexer, parser and evaluator that produce a geometry IR (not meshes).

Used by openscad_to_ckpart.py. Numbers that come out of "accessor" functions or top-level script variables are
tracked (class T) so the emitter can write them as named kernel variables / expressions.
"""
import math, re
from pathlib import Path


class Unsupported(Exception):
    pass


class T(float):
    """A number that remembers the kernel expression it came from (e = expression string over variable names)."""
    e = None

    def __new__(cls, v, e=None):
        o = float.__new__(cls, v)
        o.e = e
        return o


def ex(x):
    """Expression string of a number (tracked -> its expression, else a literal)."""
    if isinstance(x, T) and x.e:
        return x.e
    v = float(x)
    s = repr(round(v, 10))
    if s.endswith(".0"):
        s = s[:-2]
    return f"({s})" if v < 0 else s


class Undef:
    def __repr__(self):
        return "undef"
    def __bool__(self):
        return False
UNDEF = Undef()


_NAMED = {"black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000", "lime": "#00ff00", "blue": "#0000ff",
          "yellow": "#ffff00", "orange": "#ffa500", "grey": "#808080", "gray": "#808080", "silver": "#c0c0c0", "gold": "#ffd700",
          "brown": "#a52a2a", "purple": "#800080", "pink": "#ffc0cb", "cyan": "#00ffff", "magenta": "#ff00ff", "tan": "#d2b48c",
          "darkgreen": "#006400", "darkgrey": "#a9a9a9", "darkgray": "#a9a9a9", "lightgrey": "#d3d3d3", "lightgray": "#d3d3d3",
          "dimgrey": "#696969", "dimgray": "#696969", "darkred": "#8b0000", "darkblue": "#00008b", "navy": "#000080",
          "teal": "#008080", "maroon": "#800000", "olive": "#808000", "beige": "#f5f5dc", "ivory": "#fffff0", "khaki": "#f0e68c",
          "chocolate": "#d2691e", "sienna": "#a0522d", "peru": "#cd853f", "wheat": "#f5deb3", "salmon": "#fa8072", "coral": "#ff7f50",
          "darkorange": "#ff8c00", "limegreen": "#32cd32", "royalblue": "#4169e1", "skyblue": "#87ceeb", "steelblue": "#4682b4",
          "slategray": "#708090", "slategrey": "#708090", "lightblue": "#add8e6", "lightgreen": "#90ee90", "crimson": "#dc143c",
          "firebrick": "#b22222", "goldenrod": "#daa520", "saddlebrown": "#8b4513", "dodgerblue": "#1e90ff", "deepskyblue": "#00bfff"}

def color_hex(c):
    """OpenSCAD color argument -> '#rrggbb' or None (alpha ignored)"""
    if isinstance(c, str):
        t = c.strip().lower()
        if re.fullmatch(r"#[0-9a-f]{6}([0-9a-f]{2})?", t): return t[:7]
        if re.fullmatch(r"#[0-9a-f]{3}", t): return "#" + "".join(ch * 2 for ch in t[1:])
        return _NAMED.get(t)
    if isinstance(c, (list, tuple)) and len(c) >= 3 and all(isinstance(x, (int, float)) for x in c[:3]):
        return "#%02x%02x%02x" % tuple(max(0, min(255, round(float(x) * 255))) for x in c[:3])
    return None

class G:
    """Geometry IR node."""
    def __init__(self, k, **kw):
        self.k = k
        self.__dict__.update(kw)

    @property
    def dim(self):
        if self.k in ("box", "sphere", "cyl", "lext", "rext"):
            return 3
        if self.k in ("circle", "square", "poly"):
            return 2
        if self.k == "hull":
            return self.kids[0].dim if self.kids else 3
        if self.k == "xf" or self.k in ("union", "diff", "inter"):
            c = self.kids if self.k != "xf" else [self.kid]
            return c[0].dim if c else 3
        return 3


def union(nodes):
    nodes = [n for n in nodes if n is not None]
    out = []
    for n in nodes:
        if n.k == "union":
            out.extend(n.kids)
        else:
            out.append(n)
    if not out:
        return None
    return out[0] if len(out) == 1 else G("union", kids=out)


# ------------------------------------------------------------------ lexer
TOK = re.compile(r"""\s+|//[^\n]*|/\*.*?\*/|(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)|(?P<id>[$A-Za-z_][A-Za-z_0-9]*)|(?P<str>"(?:\\.|[^"\\])*")|(?P<inc><[^<>\n]*\.scad>)|(?P<op><=|>=|==|!=|&&|\|\||[-+*/%^<>=!?:;,.(){}\[\]#])""", re.S)

def lex(src):
    out, i = [], 0
    while i < len(src):
        m = TOK.match(src, i)
        if not m:
            raise SyntaxError(f"bad char {src[i]!r} at {i}")
        i = m.end()
        k = m.lastgroup
        if k is None:
            continue
        v = m.group(k)
        if k == "inc" and not (out and out[-1][1] in ("include", "use")):
            # a '<' that is not a path: re-lex as operator
            out.append(("op", "<")); i = m.start() + 1; continue
        out.append((k, v))
    out.append(("eof", ""))
    return out


# ------------------------------------------------------------------ parser
class Parser:
    def __init__(self, src):
        self.t = lex(src); self.i = 0

    def peek(self, o=0): return self.t[self.i + o]
    def nxt(self): self.i += 1; return self.t[self.i - 1]
    def is_(self, v, o=0): k, x = self.t[self.i + o]; return x == v and k in ("op", "id", "inc")
    def eat(self, v):
        if self.is_(v): self.i += 1; return True
        return False
    def need(self, v):
        if not self.eat(v): raise SyntaxError(f"expected {v!r} got {self.peek()[1]!r} at tok {self.i}")

    # statements
    def program(self):
        out = []
        while self.peek()[0] != "eof":
            s = self.stmt()
            if s: out.append(s)
        return out

    def stmt(self):
        k, v = self.peek()
        if v == ";" and k == "op": self.nxt(); return None
        if v == "{" and k == "op":
            self.nxt(); b = []
            while not self.is_("}"):
                s = self.stmt()
                if s: b.append(s)
            self.need("}"); return ("block", b)
        if k == "id" and v in ("include", "use"):
            self.nxt(); p = self.nxt()[1]; return (v, p[1:-1])
        if k == "id" and v == "module":
            self.nxt(); name = self.nxt()[1]; params = self.params()
            return ("module", name, params, self.stmt())
        if k == "id" and v == "function":
            if self.peek(1)[0] == "id":
                self.nxt(); name = self.nxt()[1]; params = self.params(); self.need("=")
                e = self.expr(); self.need(";"); return ("function", name, params, e)
        if k == "id" and self.is_("=", 1):
            name = self.nxt()[1]; self.nxt(); e = self.expr(); self.need(";"); return ("assign", name, e)
        mods = ""
        while self.peek()[0] == "op" and self.peek()[1] in "*!#%" and self.peek()[1] != "":
            mods += self.nxt()[1]
        k, v = self.peek()
        if k == "id" and v == "if":
            self.nxt(); self.need("("); c = self.expr(); self.need(")"); a = self.stmt()
            b = None
            if self.is_("else"): self.nxt(); b = self.stmt()
            return ("if", c, a, b, mods)
        if k == "id" and v in ("for", "intersection_for"):
            self.nxt(); self.need("("); asg = self.assigns(); self.need(")")
            return ("for", asg, self.stmt(), v == "intersection_for", mods)
        if k == "id" and v in ("let", "assign"):
            self.nxt(); self.need("("); asg = self.assigns(); self.need(")")
            return ("let", asg, self.stmt(), mods)
        if k == "id":
            name = self.nxt()[1]; self.need("("); args = self.args(); self.need(")")
            if self.eat(";"): kids = []
            else:
                c = self.stmt(); kids = [] if c is None else (c[1] if c[0] == "block" else [c])
            return ("inst", name, args, kids, mods)
        raise SyntaxError(f"unexpected {v!r} at tok {self.i}")

    def params(self):
        self.need("("); ps = []
        while not self.is_(")"):
            n = self.nxt()[1]; d = None
            if self.eat("="): d = self.expr()
            ps.append((n, d))
            if not self.eat(","): break
        self.need(")"); return ps

    def assigns(self):
        a = []
        while not self.is_(")"):
            n = self.nxt()[1]; self.need("="); a.append((n, self.expr()))
            if not self.eat(","): break
        return a

    def args(self):
        a = []
        while not self.is_(")"):
            if self.peek()[0] == "id" and self.is_("=", 1) and not self.is_("==", 1):
                n = self.nxt()[1]; self.nxt(); a.append((n, self.expr()))
            else:
                a.append((None, self.expr()))
            if not self.eat(","): break
        return a

    # expressions
    def expr(self):
        k, v = self.peek()
        if k == "id" and v == "let":
            self.nxt(); self.need("("); a = self.assigns(); self.need(")"); return ("let", a, self.expr())
        if k == "id" and v == "function":
            self.nxt(); ps = self.params(); return ("lambda", ps, self.expr())
        if k == "id" and v in ("echo", "assert") and self.is_("(", 1):
            self.nxt(); self.need("("); self.args(); self.need(")")
            if self.is_(";") or self.is_(")") or self.is_(",") or self.is_("]"): return ("undef",)
            return self.expr()
        c = self.binary(0)
        if self.eat("?"):
            a = self.expr(); self.need(":"); b = self.expr(); return ("tern", c, a, b)
        return c

    PREC = [("||",), ("&&",), ("==", "!="), ("<", "<=", ">", ">="), ("+", "-"), ("*", "/", "%"), ("^",)]
    def binary(self, lv):
        if lv == len(self.PREC): return self.unary()
        l = self.binary(lv + 1)
        while self.peek()[0] == "op" and self.peek()[1] in self.PREC[lv]:
            op = self.nxt()[1]; r = self.binary(lv + 1); l = ("bin", op, l, r)
        return l

    def unary(self):
        k, v = self.peek()
        if k == "op" and v in "-+!": self.nxt(); return ("un", v, self.unary())
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while True:
            if self.eat("["): i = self.expr(); self.need("]"); e = ("idx", e, i)
            elif self.is_(".") and self.peek(1)[0] == "id": self.nxt(); e = ("mem", e, self.nxt()[1])
            elif self.is_("("): self.nxt(); a = self.args(); self.need(")"); e = ("call", e, a)
            else: return e

    def primary(self):
        k, v = self.nxt()
        if k == "num": return ("num", float(v))
        if k == "str": return ("str", bytes(v[1:-1], "utf8").decode("unicode_escape"))
        if k == "id":
            if v == "true": return ("num", True)
            if v == "false": return ("num", False)
            if v == "undef": return ("undef",)
            return ("id", v)
        if v == "(":
            e = self.expr(); self.need(")"); return e
        if v == "[": return self.listlit()
        raise SyntaxError(f"unexpected {v!r} in expression at tok {self.i}")

    def listlit(self):
        if self.eat("]"): return ("list", [])
        if self.is_("for") or self.is_("if") or self.is_("each") or self.is_("let"):
            pass
        first = self.lc_or_expr()
        if self.is_(":") and not isinstance(first, tuple) or (self.is_(":") and first[0] not in ("lcfor", "lcif", "lcforc", "lceach", "lclet")):
            self.nxt(); b = self.expr()
            if self.eat(":"):
                c = self.expr(); self.need("]"); return ("range", first, b, c)  # [a:step:b]
            self.need("]"); return ("range", first, None, b)
        items = [first]
        while self.eat(","):
            if self.is_("]"): break
            items.append(self.lc_or_expr())
        self.need("]"); return ("list", items)

    def lc_or_expr(self):
        if self.is_("for"):
            self.nxt(); self.need("(")
            asg = self.assigns()
            if self.eat(";"):
                cond = self.expr(); self.need(";"); step = self.assigns(); self.need(")")
                return ("lcforc", asg, cond, step, self.lc_or_expr())
            self.need(")"); return ("lcfor", asg, self.lc_or_expr())
        if self.is_("if"):
            self.nxt(); self.need("("); c = self.expr(); self.need(")"); a = self.lc_or_expr(); b = None
            if self.eat("else"): b = self.lc_or_expr()
            return ("lcif", c, a, b)
        if self.is_("each"):
            self.nxt(); return ("lceach", self.lc_or_expr())
        if self.is_("let") and True:
            save = self.i; self.nxt(); self.need("("); a = self.assigns(); self.need(")")
            if self.is_("for") or self.is_("if") or self.is_("each") or self.is_("let"):
                return ("lclet", a, self.lc_or_expr())
            self.i = save
        return self.expr()


# ------------------------------------------------------------------ environment / interpreter
class Env:
    def __init__(self, lex=None, dyn=None):
        self.vars = {}; self.mods = {}; self.funcs = {}
        self.lex = lex; self.dyn = dyn; self.children = None; self.nchildren = 0

    def get(self, n):
        if n[0] == "$":
            e = self
            while e is not None:
                if n in e.vars: return e.vars[n]
                e = e.dyn if e.dyn is not None else None
            return UNDEF
        e = self
        while e is not None:
            if n in e.vars: return e.vars[n]
            e = e.lex
        return UNDEF

    def find(self, kind, n):
        e = self
        while e is not None:
            d = getattr(e, kind)
            if n in d: return d[n]
            e = e.lex
        return None


class Fn:  # user function value
    def __init__(self, params, body, env): self.params, self.body, self.env = params, body, env


def fmt(v):
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15: return str(int(v))
        return "%g" % v if abs(v) >= 1e-4 else repr(v)
    if isinstance(v, list): return "[" + ", ".join(fmt(x) for x in v) + "]"
    if v is UNDEF: return "undef"
    return str(v)


def isnum(v): return isinstance(v, (int, float)) and not isinstance(v, bool)


class Interp:
    def __init__(self, libpaths, track_main=True):
        self.libpaths = [Path(p) for p in libpaths]
        self.cache = {}          # path -> ast
        self.loaded = {}         # path -> Env (for use)
        self.warnings = []
        self.colors = []
        self.varvals = {}        # tracked name -> value
        self.track_main = track_main
        self.depth = 0

    # -- files
    def parse_file(self, p):
        p = str(p)
        if p not in self.cache:
            self.cache[p] = Parser(Path(p).read_text(errors="ignore")).program()
        return self.cache[p]

    def resolve(self, rel, frm):
        for base in ([Path(frm).parent] if frm else []) + self.libpaths:
            c = (base / rel).resolve()
            if c.exists(): return c
        self.warnings.append(f"missing include {rel}")
        return None

    def load_into(self, stmts, env, frm, tracked=False):
        """Define modules/functions and run assignments of a statement list into env."""
        for s in stmts:
            k = s[0]
            if k == "module": env.mods[s[1]] = (s, env)
            elif k == "function": env.funcs[s[1]] = (s, env)
        out = []
        for s in stmts:
            k = s[0]
            if k == "include":
                p = self.resolve(s[1], frm)
                if p and (str(p), id(env)) not in getattr(self, "_inc", set()):
                    self._inc = getattr(self, "_inc", set()); self._inc.add((str(p), id(env)))
                    out += self.load_into(self.parse_file(p), env, p)
            elif k == "use":
                p = self.resolve(s[1], frm)
                if p:
                    if str(p) not in self.loaded:
                        e = Env(); self.loaded[str(p)] = e
                        self.load_into(self.parse_file(p), e, p)
                    e = self.loaded[str(p)]
                    for n, v in e.mods.items(): env.mods.setdefault(n, v)
                    for n, v in e.funcs.items(): env.funcs.setdefault(n, v)
            elif k == "assign":
                v = self.ev(s[2], env)
                if tracked and isnum(v) and not isinstance(v, bool) and not s[1].startswith("$"):
                    v = self.track(s[1], v)
                env.vars[s[1]] = v
            elif k in ("module", "function"):
                pass
            else:
                out += self.exec_stmt(s, env)
        return out

    def track(self, name, v):
        n = re.sub(r"[^A-Za-z0-9_]", "_", name)
        if n.lower() in ("pi", "mm", "cm", "m", "in", "deg", "sqrt", "sin", "cos", "tan", "abs"): n += "_"
        k = n; i = 1
        while k in self.varvals and self.varvals[k] != float(v):
            i += 1; k = f"{n}_{i}"
        self.varvals[k] = float(v)
        return T(v, k)

    def run_main(self, src, name="main.scad"):
        env = Env()
        env.vars.update({"$fn": 0.0, "$fa": 12.0, "$fs": 2.0, "$t": 0.0, "$preview": False})
        stmts = Parser(src).program()
        # builtin defs
        return self.load_into(stmts, env, Path(self.libpaths[0] / name) if self.libpaths else None, tracked=self.track_main), env

    # -- expressions
    def ev(self, e, env):
        k = e[0]
        if k == "num": return e[1]
        if k == "str": return e[1]
        if k == "undef": return UNDEF
        if k == "id":
            n = e[1]
            if n == "PI": return math.pi
            v = env.get(n)
            if v is UNDEF and n[0] != "$":
                f = env.find("funcs", n)
                if f is not None: return Fn(f[0][2], f[0][3], f[1])
            return v
        if k == "list": return self.ev_list(e[1], env)
        if k == "range":
            a = self.ev(e[1], env); b = self.ev(e[3], env); s = self.ev(e[2], env) if e[2] is not None else 1.0
            return ("range", a, s, b)
        if k == "un":
            v = self.ev(e[2], env)
            if e[1] == "!": return not self.truthy(v)
            if e[1] == "-": return self.neg(v)
            return v
        if k == "bin":
            op = e[1]
            if op == "&&": return self.truthy(self.ev(e[2], env)) and self.truthy(self.ev(e[3], env))
            if op == "||": return self.truthy(self.ev(e[2], env)) or self.truthy(self.ev(e[3], env))
            return self.binop(op, self.ev(e[2], env), self.ev(e[3], env))
        if k == "tern": return self.ev(e[2] if self.truthy(self.ev(e[1], env)) else e[3], env)
        if k == "idx":
            a = self.ev(e[1], env); i = self.ev(e[2], env)
            try:
                if isinstance(a, (list, str)) and isnum(i):
                    i = int(i)
                    if 0 <= i < len(a): return a[i]
            except Exception: pass
            return UNDEF
        if k == "mem":
            a = self.ev(e[1], env)
            if isinstance(a, list) and e[2] in "xyz" and len(e[2]) == 1:
                i = "xyz".index(e[2])
                return a[i] if i < len(a) else UNDEF
            return UNDEF
        if k == "let":
            e2 = Env(env, env)
            for n, x in e[1]: e2.vars[n] = self.ev(x, e2)
            return self.ev(e[2], e2)
        if k == "lambda": return Fn(e[1], e[2], env)
        if k == "call": return self.call_fn(e, env)
        if k in ("lcfor", "lcif", "lcforc", "lceach", "lclet"): return self.ev_list([e], env)
        raise Unsupported(f"expr {k}")

    def truthy(self, v):
        if v is UNDEF or v is None: return False
        if isinstance(v, (list, str)): return len(v) > 0
        return bool(v)

    def neg(self, v):
        if isinstance(v, list): return [self.neg(x) for x in v]
        if isnum(v):
            r = -float(v)
            if isinstance(v, T) and v.e: return T(r, f"(-{v.e})" if len(v.e) < 300 else None)
            return r
        return UNDEF

    def binop(self, op, a, b):
        if op in ("==", "!="):
            eq = self.equal(a, b); return eq if op == "==" else not eq
        if op in ("<", "<=", ">", ">="):
            if isnum(a) and isnum(b): return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
            if isinstance(a, str) and isinstance(b, str): return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
            return False
        if isnum(a) and isnum(b):
            fa, fb = float(a), float(b)
            try:
                if op == "+": r = fa + fb
                elif op == "-": r = fa - fb
                elif op == "*": r = fa * fb
                elif op == "/": r = fa / fb if fb else (math.inf if fa > 0 else -math.inf if fa < 0 else math.nan)
                elif op == "%": r = math.fmod(fa, fb) if fb else math.nan
                else: r = fa ** fb
            except Exception: return UNDEF
            ea = a.e if isinstance(a, T) else None; eb = b.e if isinstance(b, T) else None
            if (ea or eb) and op in "+-*/":
                s = f"({ex(a)}{op}{ex(b)})"
                return T(r, s if len(s) < 300 else None)
            return r
        if isinstance(a, list) and isinstance(b, list) and op in "+-" and len(a) == len(b):
            return [self.binop(op, x, y) for x, y in zip(a, b)]
        if op == "*":
            if isnum(a) and isinstance(b, list): return [self.binop("*", a, x) for x in b]
            if isnum(b) and isinstance(a, list): return [self.binop("*", x, b) for x in a]
            if isinstance(a, list) and isinstance(b, list): return self.matmul(a, b)
        if op == "/" and isinstance(a, list) and isnum(b): return [self.binop("/", x, b) for x in a]
        return UNDEF

    def matmul(self, a, b):
        def isvec(x): return isinstance(x, list) and all(isnum(i) for i in x)
        try:
            if isvec(a) and isvec(b): return float(sum(float(x) * float(y) for x, y in zip(a, b)))
            if isvec(b):  # matrix * vector
                return [float(sum(float(x) * float(y) for x, y in zip(r, b))) for r in a]
            if isvec(a):  # vector * matrix
                return [float(sum(float(a[i]) * float(b[i][j]) for i in range(len(a)))) for j in range(len(b[0]))]
            return [[float(sum(float(a[i][k]) * float(b[k][j]) for k in range(len(b)))) for j in range(len(b[0]))] for i in range(len(a))]
        except Exception: return UNDEF

    def equal(self, a, b):
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(self.equal(x, y) for x, y in zip(a, b))
        if isnum(a) and isnum(b): return float(a) == float(b)
        if a is UNDEF and b is UNDEF: return True
        if type(a) != type(b): return False
        return a == b

    def iter_values(self, v):
        if isinstance(v, tuple) and v and v[0] == "range":
            _, a, s, b = v
            if not (isnum(a) and isnum(b) and isnum(s)) or s == 0: return []
            a, s, b = float(a), float(s), float(b)
            n = int(math.floor((b - a) / s + 1e-9)) + 1
            return [a + i * s for i in range(max(n, 0))] if n < 1e6 else []
        if isinstance(v, list): return v
        if isinstance(v, str): return list(v)
        return [v] if v is not UNDEF else []

    def ev_list(self, items, env):
        out = []
        for it in items:
            if it[0] in ("lcfor", "lcif", "lcforc", "lceach", "lclet"):
                self.gen(it, env, out)
            else:
                out.append(self.ev(it, env))
        return out

    def gen(self, it, env, out):
        k = it[0]
        if k == "lcfor":
            self.gen_for(it[1], 0, it[2], env, out)
        elif k == "lcforc":
            e2 = Env(env, env)
            for n, x in it[1]: e2.vars[n] = self.ev(x, e2)
            while self.truthy(self.ev(it[2], e2)):
                self.gen(it[4], e2, out) if it[4][0] in ("lcfor", "lcif", "lcforc", "lceach", "lclet") else out.append(self.ev(it[4], e2))
                nv = {n: self.ev(x, e2) for n, x in it[3]}; e2.vars.update(nv)
        elif k == "lcif":
            br = it[2] if self.truthy(self.ev(it[1], env)) else it[3]
            if br is not None:
                self.gen(br, env, out) if br[0] in ("lcfor", "lcif", "lcforc", "lceach", "lclet") else out.append(self.ev(br, env))
        elif k == "lceach":
            sub = it[1]
            if sub[0] in ("lcfor", "lcif", "lcforc", "lceach", "lclet"):
                tmp = []; self.gen(sub, env, tmp)
                for v in tmp: out.extend(self.iter_values(v))
            else: out.extend(self.iter_values(self.ev(sub, env)))
        elif k == "lclet":
            e2 = Env(env, env)
            for n, x in it[1]: e2.vars[n] = self.ev(x, e2)
            sub = it[2]
            self.gen(sub, e2, out) if sub[0] in ("lcfor", "lcif", "lcforc", "lceach", "lclet") else out.append(self.ev(sub, e2))

    def gen_for(self, asg, i, body, env, out):
        if i == len(asg):
            self.gen(body, env, out) if body[0] in ("lcfor", "lcif", "lcforc", "lceach", "lclet") else out.append(self.ev(body, env))
            return
        n, x = asg[i]
        for v in self.iter_values(self.ev(x, env)):
            e2 = Env(env, env); e2.vars[n] = v
            self.gen_for(asg, i + 1, body, e2, out)

    # -- function calls
    def bind(self, params, args, env_def, env_caller, evalenv):
        """Evaluate call arguments in env_caller and bind to params in a new env (lexical parent env_def)."""
        ne = Env(env_def, env_caller)
        pos = []; named = {}
        for n, x in args:
            v = self.ev(x, evalenv)
            if n is None: pos.append(v)
            else: named[n] = v
        names = [p[0] for p in params]
        for i, v in enumerate(pos):
            if i < len(names): ne.vars[names[i]] = v
        for n, v in named.items():
            if n in names or n[0] == "$": ne.vars[n] = v
        for n, d in params:
            if n not in ne.vars:
                ne.vars[n] = self.ev(d, ne) if d is not None else UNDEF
        return ne

    def call_fn(self, e, env):
        callee = e[1]; args = e[2]
        if callee[0] == "id":
            name = callee[1]
            f = env.find("funcs", name)
            if f is not None:
                (_, _, params, body), denv = f
                ne = self.bind(params, args, denv, env, env)
                self.depth += 1
                if self.depth > 400: raise Unsupported("recursion too deep")
                try: r = self.ev(body, ne)
                finally: self.depth -= 1
                if body[0] == "idx" and body[1][0] == "id" and body[2][0] == "num" and isnum(r) and not isinstance(r, bool):
                    return self.track(name, r)  # accessor like `f(type) = type[3]` -> named parameter
                return r
            v = env.get(name)
            if isinstance(v, Fn): return self.call_value(v, args, env)
            return self.builtin_fn(name, args, env)
        v = self.ev(callee, env)
        if isinstance(v, Fn): return self.call_value(v, args, env)
        return UNDEF

    def call_value(self, fn, args, env):
        ne = self.bind(fn.params, args, fn.env, env, env)
        return self.ev(fn.body, ne)

    def builtin_fn(self, name, args, env):
        vals = [self.ev(x, env) for n, x in args if n is None]
        kw = {n: self.ev(x, env) for n, x in args if n is not None}
        a = vals[0] if vals else UNDEF
        def num(v): return isnum(v)
        def sym1(f, name_, v):
            r = f(float(v))
            if isinstance(v, T) and v.e and name_:
                return T(r, f"{name_}({v.e})")
            return r
        try:
            if name in ("sin", "cos", "tan") and num(a): return sym1(lambda x: {"sin": math.sin, "cos": math.cos, "tan": math.tan}[name](math.radians(x)), name, a)
            if name == "sqrt" and num(a): return sym1(lambda x: math.sqrt(x) if x >= 0 else math.nan, "sqrt", a)
            if name == "abs" and num(a): return sym1(abs, "abs", a)
            if name == "asin" and num(a): return math.degrees(math.asin(max(-1, min(1, a))))
            if name == "acos" and num(a): return math.degrees(math.acos(max(-1, min(1, a))))
            if name == "atan" and num(a): return math.degrees(math.atan(a))
            if name == "atan2": return math.degrees(math.atan2(vals[0], vals[1]))
            if name == "floor" and num(a): return float(math.floor(a))
            if name == "ceil" and num(a): return float(math.ceil(a))
            if name == "round" and num(a): return float(math.floor(a + 0.5)) if a >= 0 else -float(math.floor(-a + 0.5))
            if name == "sign" and num(a): return float((a > 0) - (a < 0))
            if name == "exp": return math.exp(a)
            if name == "ln": return math.log(a)
            if name == "log": return math.log10(a) if len(vals) == 1 else math.log(vals[1]) / math.log(vals[0])
            if name == "pow": return math.pow(vals[0], vals[1])
            if name in ("min", "max"):
                v = vals[0] if len(vals) == 1 and isinstance(vals[0], list) else vals
                v = [x for x in v if num(x)]
                return (min if name == "min" else max)(v) if v else UNDEF
            if name == "norm": return math.sqrt(sum(float(x) ** 2 for x in a))
            if name == "cross":
                x, y = vals[0], vals[1]
                if len(x) == 3: return [x[1]*y[2]-x[2]*y[1], x[2]*y[0]-x[0]*y[2], x[0]*y[1]-x[1]*y[0]]
                return x[0]*y[1]-x[1]*y[0]
            if name == "len": return float(len(a)) if isinstance(a, (list, str)) else UNDEF
            if name == "concat":
                o = []
                for v in vals: o += v if isinstance(v, list) else [v]
                return o
            if name == "str": return "".join(fmt(v) if not isinstance(v, str) else v for v in vals)
            if name == "chr": return "".join(chr(int(c)) for c in (a if isinstance(a, list) else [a]))
            if name == "ord": return float(ord(a[0])) if isinstance(a, str) and a else UNDEF
            if name == "is_undef": return a is UNDEF
            if name == "is_num": return num(a)
            if name == "is_bool": return isinstance(a, bool)
            if name == "is_string": return isinstance(a, str)
            if name == "is_list": return isinstance(a, list)
            if name == "is_function": return isinstance(a, Fn)
            if name == "lookup":
                k, tab = vals[0], vals[1]
                tab = sorted(tab, key=lambda r: r[0])
                if k <= tab[0][0]: return tab[0][1]
                if k >= tab[-1][0]: return tab[-1][1]
                for p, q in zip(tab, tab[1:]):
                    if p[0] <= k <= q[0]: return p[1] + (q[1] - p[1]) * (k - p[0]) / ((q[0] - p[0]) or 1)
            if name == "search":
                tgt, hay = vals[0], vals[1]
                if isinstance(tgt, (str, float, int)): tgt = [tgt]; single = True
                else: single = False
                return [next((float(i) for i, h in enumerate(hay) if self.equal(h, t) or (isinstance(h, list) and h and self.equal(h[0], t))), []) for t in tgt]
            if name == "version": return [2021.0, 1.0, 0.0]
        except Exception as ex_:
            return UNDEF
        self.warnings.append(f"unknown function {name}")
        return UNDEF

    # -- statements
    def exec_stmts(self, stmts, env):
        out = []
        for s in stmts:
            k = s[0]
            if k == "assign": env.vars[s[1]] = self.ev(s[2], env)
            elif k in ("module", "function"):
                (env.mods if k == "module" else env.funcs)[s[1]] = (s, env)
            elif k in ("include", "use"):
                self.load_into([s], env, None)
            else:
                out += self.exec_stmt(s, env)
        return out

    def exec_scope(self, stmts, env):
        e2 = Env(env, env); e2.children = env.children; e2.nchildren = env.nchildren
        # predefine local modules/functions first
        for s in stmts:
            if s[0] == "module": e2.mods[s[1]] = (s, e2)
            elif s[0] == "function": e2.funcs[s[1]] = (s, e2)
        return self.exec_stmts(stmts, e2)

    def group(self, nodes):
        return [union(nodes)] if nodes else []

    def exec_stmt(self, s, env):
        k = s[0]
        if k == "block": return self.group(self.exec_scope(s[1], env))
        if k == "if":
            if "*" in s[4] or "%" in s[4]: return []
            br = s[2] if self.truthy(self.ev(s[1], env)) else s[3]
            return self.exec_stmt(br, env) if br is not None else []
        if k == "let":
            e2 = Env(env, env); e2.children = env.children; e2.nchildren = env.nchildren
            for n, x in s[1]: e2.vars[n] = self.ev(x, e2)
            return self.exec_stmt(s[2], e2)
        if k == "for":
            if "*" in s[4] or "%" in s[4]: return []
            res = []
            def rec(i, e):
                if i == len(s[1]):
                    res.extend(self.exec_stmt(s[2], e)); return
                n, x = s[1][i]
                for v in self.iter_values(self.ev(x, e)):
                    e2 = Env(e, e); e2.children = env.children; e2.nchildren = env.nchildren; e2.vars[n] = v
                    rec(i + 1, e2)
            rec(0, env)
            if s[3]:
                return [G("inter", kids=res)] if res else []
            return self.group(res)
        if k == "inst":
            if "*" in s[4] or "%" in s[4]: return []
            return self.inst(s, env)
        if k in ("assign", "module", "function", "include", "use"):
            return self.exec_stmts([s], env)
        raise Unsupported(f"stmt {k}")

    def eval_kids(self, kids, env):
        """children statements -> list of child nodes (each statement one node)"""
        out = []
        for s in kids:
            if s[0] == "assign": env.vars[s[1]] = self.ev(s[2], env); continue
            out += self.exec_stmt(s, env)
        return out

    def inst(self, s, env):
        _, name, args, kids, mods = s
        if name == "children":
            return self.children_call(args, env)
        m = env.find("mods", name)
        if m is not None:
            (_, _, params, body), denv = m
            ne = self.bind(params, args, denv, env, env)
            ne.children = (kids, env); ne.nchildren = len(kids)
            ne.vars["$children"] = float(len(kids))
            self.depth += 1
            if self.depth > 200: raise Unsupported("module recursion too deep")
            try: r = self.exec_stmt(body, ne) if body is not None else []
            finally: self.depth -= 1
            return self.group(r) if len(r) > 1 else r
        return self.builtin_mod(name, args, kids, env)

    def children_call(self, args, env):
        e = env
        while e is not None and e.children is None: e = e.lex
        if e is None or not e.children: return []
        kids, cenv = e.children
        if args:
            v = self.ev(args[0][1], env)
            idxs = [int(x) for x in self.iter_values(v)] if not isnum(v) else [int(v)]
            sel = [kids[i] for i in idxs if 0 <= i < len(kids)]
        else: sel = kids
        out = []
        for s in sel:
            out += self.exec_stmt(s, cenv)
        return out

    # -- builtin modules
    def builtin_mod(self, name, args, kids, env):
        pos = []; kw = {}
        for n, x in args:
            v = self.ev(x, env)
            if n is None: pos.append(v)
            else: kw[n] = v
        def P(i, n, d=UNDEF):
            if n in kw: return kw[n]
            return pos[i] if i < len(pos) else d
        def kidnodes(): return self.eval_kids(kids, env)
        fn = self.special(env, kw)

        if name == "cube":
            sz = P(0, "size", 1.0); c = self.truthy(P(1, "center", False))
            if isnum(sz): sz = [sz, sz, sz]
            if not (isinstance(sz, list) and len(sz) == 3 and all(isnum(x) for x in sz)): return []
            return [G("box", size=sz, center=c)]
        if name == "sphere":
            r = P(0, "r"); d = P(99, "d")
            if d is not UNDEF: r = d / 2 if not (isinstance(d, T) and d.e) else self.binop("/", d, 2.0)
            if r is UNDEF: r = 1.0
            return [G("sphere", r=r, fn=fn)]
        if name == "cylinder":
            h = P(0, "h", 1.0); r = P(1, "r"); r1 = P(2, "r1"); r2 = P(3, "r2"); c = self.truthy(P(4, "center", False))
            d, d1, d2 = kw.get("d", UNDEF), kw.get("d1", UNDEF), kw.get("d2", UNDEF)
            half = lambda x: self.binop("/", x, 2.0)
            if d is not UNDEF: r = half(d)
            if d1 is not UNDEF: r1 = half(d1)
            if d2 is not UNDEF: r2 = half(d2)
            if r1 is UNDEF: r1 = r if r is not UNDEF else 1.0
            if r2 is UNDEF: r2 = r if r is not UNDEF else 1.0
            return [G("cyl", h=h, r1=r1, r2=r2, center=c, fn=fn)]
        if name == "circle":
            r = P(0, "r"); d = kw.get("d", UNDEF)
            if d is not UNDEF: r = self.binop("/", d, 2.0)
            if r is UNDEF: r = 1.0
            return [G("circle", r=r, fn=fn)]
        if name == "circle4n":  # library helper: a polygon with 4n sides, taken as a true circle
            r = P(0, "r"); d = P(1, "d")
            if d is not UNDEF: r = self.binop("/", d, 2.0)
            return [G("circle", r=r, fn=0)]
        if name == "square":
            sz = P(0, "size", 1.0); c = self.truthy(P(1, "center", False))
            if isnum(sz): sz = [sz, sz]
            return [G("square", size=sz, center=c)]
        if name == "polygon":
            pts = P(0, "points"); paths = P(1, "paths", UNDEF)
            return [G("poly", pts=pts, paths=None if paths is UNDEF else paths)]
        if name in ("translate", "scale"):
            v = P(0, "v" if name == "translate" else "v")
            if isnum(v): v = [v, v, v]
            v = list(v) + [0.0 if name == "translate" else 1.0] * (3 - len(v)) if isinstance(v, list) else [0.0] * 3
            return self.wrap(("t" if name == "translate" else "s", v), kidnodes())
        if name == "rotate":
            a = P(0, "a", 0.0); v = P(1, "v", UNDEF)
            if a is UNDEF: self.warnings.append("rotate() with an undefined angle taken as 0"); a = 0.0
            if isnum(a) and v is UNDEF: return self.wrap(("r", [0.0, 0.0, a]), kidnodes())
            if isnum(a): return self.wrap(("ra", a, v), kidnodes())
            if not isinstance(a, list):
                self.warnings.append("rotate() with an undefined angle taken as 0"); a = [0.0]
            a = [x if isnum(x) else 0.0 for x in a] + [0.0] * (3 - len(a))
            return self.wrap(("r", a), kidnodes())
        if name == "mirror":
            v = P(0, "v", [1.0, 0.0, 0.0]); v = list(v) + [0.0] * (3 - len(v))
            return self.wrap(("m", v), kidnodes())
        if name == "multmatrix":
            return self.wrap(("mm", P(0, "m")), kidnodes())
        if name == "color":
            c = P(0, "c"); self.colors.append(c)
            hx = color_hex(c)
            ks = kidnodes()
            if hx:
                def tag(n):
                    if getattr(n, "col", None): return
                    n.col = hx
                    for a in ("kid",):
                        if isinstance(getattr(n, a, None), G): tag(getattr(n, a))
                    for k in (getattr(n, "kids", None) or []):
                        if isinstance(k, G): tag(k)
                for k in ks: tag(k)
            return ks
        if name in ("render", "union", "group") or name == "intersection_for":
            return self.group(kidnodes()) if name != "intersection_for" else kidnodes()
        if name == "difference":
            ks = kidnodes(); return [G("diff", kids=ks)] if ks else []
        if name == "intersection":
            ks = kidnodes(); return [G("inter", kids=ks)] if ks else []
        if name == "linear_extrude":
            ks = kidnodes(); k = union(ks)
            if k is None: return []
            return [G("lext", kid=k, h=P(0, "height", 100.0), center=self.truthy(P(1, "center", False)),
                      twist=P(99, "twist", 0.0), scale=P(99, "scale", 1.0), slices=P(99, "slices", UNDEF))]
        if name == "rotate_extrude":
            ks = kidnodes(); k = union(ks)
            if k is None: return []
            return [G("rext", kid=k, angle=P(0, "angle", 360.0))]
        if name == "hull":
            ks = kidnodes()
            if not ks: return []
            if ks[0].dim == 3: raise Unsupported("hull of 3D geometry")
            return [G("hull", kids=ks)]
        if name in ("minkowski", "polyhedron", "text", "import", "surface", "offset", "projection", "resize", "import_stl", "linear_extrude_", "roof", "fill"):
            raise Unsupported(name)
        if name in ("echo", "assert", "stl", "dxf", "svg", "vitamin", "explode_", "exploded_"):
            return []
        # unknown module: NopSCADlib BOM helpers etc. -> pass children through
        self.warnings.append(f"unknown module {name}")
        return kidnodes()

    def special(self, env, kw):
        fn = kw.get("$fn", env.get("$fn"))
        return float(fn) if isnum(fn) else 0.0

    def wrap(self, op, kids):
        k = union(kids)
        return [G("xf", op=op, kid=k)] if k is not None else []
