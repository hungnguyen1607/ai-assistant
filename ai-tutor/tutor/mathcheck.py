"""SymPy-backed math verification exposed as tools to the tutor model."""

import multiprocessing as mp
import re
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from concurrent.futures.process import BrokenProcessPool

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)
TIMEOUT_S = 25


def _parse(text: str, func: str = "y", var: str = "x") -> sp.Expr:
    """Parse '2*x*y + y' = 0', 'dy/dx = e^(3x+2y)', 'y = C*x^4' into a SymPy expression (lhs - rhs)."""
    if "__" in text or "import" in text or "lambda" in text:
        raise ValueError("unsupported input")
    s = text.replace("−", "-").replace("·", "*").replace("π", "pi").replace("′", "'")
    # ln|u| has the same derivative as ln(u); other |u| become Abs(u)
    s = re.sub(r"\b(ln|log)\s*\|([^|]+)\|", r"log(\2)", s)
    s = re.sub(r"\|([^|]+)\|", r"Abs(\1)", s)
    s = re.sub(rf"d\^?2\s*{func}\s*/\s*d{var}\s*\^?2", " _D2_ ", s)
    s = re.sub(rf"d{var}\s*/\s*d{func}", " (1/_D1_) ", s)
    s = re.sub(rf"d{func}\s*/\s*d{var}", " _D1_ ", s)
    s = re.sub(rf"\b{func}''", " _D2_ ", s)
    s = re.sub(rf"\b{func}'", " _D1_ ", s)
    s = re.sub(rf"\b{func}\s*\(\s*{var}\s*\)", f" {func} ", s)
    s = re.sub(r"\bln\b", "log", s)
    s = re.sub(r"\be\^", "E^", s)
    v, f = sp.Symbol(var), sp.Symbol(func)
    local = {var: v, func: f, "_D1_": sp.Symbol("_D1_"), "_D2_": sp.Symbol("_D2_"), "E": sp.E, "e": sp.E}
    for name in ("C", "C1", "C2", "C3", "c", "c1", "c2", "k"):
        local.setdefault(name, sp.Symbol(name))
    sides = s.split("=")
    if len(sides) > 2:
        raise ValueError("more than one '=' sign")
    exprs = [parse_expr(side, local_dict=local, transformations=TRANSFORMS) for side in sides]
    expr = exprs[0] - exprs[1] if len(exprs) == 2 else exprs[0]
    F = sp.Function(func)(v)
    return expr.subs({sp.Symbol("_D2_"): F.diff(v, 2), sp.Symbol("_D1_"): F.diff(v), f: F})


def _solution_eq(text: str, func: str, var: str) -> sp.Eq:
    F = sp.Function(func)(sp.Symbol(var))
    if "=" in text:
        lhs, rhs = text.split("=", 1)
        if lhs.strip() in (func, f"{func}({var})"):
            return sp.Eq(F, _parse(rhs, func, var))
    return sp.Eq(_parse(text, func, var), 0)


def _numeric_slope_check(eq: sp.Expr, sol: sp.Eq, func: str, var: str) -> bool | None:
    """Check y' from the (possibly implicit) solution against the ODE at random points.

    Returns True/False, or None if the check couldn't be carried out.
    """
    import random

    x, Y, P = sp.Symbol(var), sp.Symbol("_Y_"), sp.Symbol("_P_")
    F = sp.Function(func)(x)
    G = (sol.lhs - sol.rhs).subs(F, Y)
    slope = -sp.diff(G, x) / sp.diff(G, Y)
    ode_slopes = sp.solve(eq.subs(F.diff(x), P).subs(F, Y), P)
    if not ode_slopes:
        return None
    consts = sorted((G.free_symbols | slope.free_symbols) - {x, Y}, key=str)
    rng, tested = random.Random(0), 0
    for _ in range(40):
        point = {x: rng.uniform(0.2, 1.8), Y: rng.uniform(0.2, 1.8)}
        if consts:
            # pick the constant so the solution curve passes through this point
            c_vals = sp.solve(G.subs(point), consts[0])
            if not c_vals:
                continue
            point[consts[0]] = c_vals[0]
            for c in consts[1:]:
                point[c] = rng.uniform(0.5, 1.5)
        try:
            want = complex(slope.subs(point).evalf())
            if abs(want.imag) > 1e-9:
                continue
            if not any(abs(complex(s.subs(point).evalf()) - want) <= 1e-6 * max(1, abs(want)) for s in ode_slopes):
                return False
            tested += 1
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if tested >= 5:
            return True
    return None


def _check_ode(ode: str, solution: str, func: str, var: str) -> str:
    eq = _parse(ode, func, var)
    sol = _solution_eq(solution, func, var)
    F = sp.Function(func)(sp.Symbol(var))
    residual = None
    if sol.lhs == F:  # explicit; checkodesol would try (and often fail) to solve implicit ones for y
        try:
            ok, residual = sp.checkodesol(eq, sol, func=F)
            if ok:
                return f"VERIFIED: {sp.sstr(sol)} satisfies {sp.sstr(eq)} = 0"
        except NotImplementedError:
            pass
    numeric = _numeric_slope_check(eq, sol, func, var)
    if numeric:
        return f"VERIFIED (slope matches the ODE at 5 random points): {sp.sstr(sol)}"
    if numeric is False:
        return f"NOT VERIFIED: the slope from {sp.sstr(sol)} doesn't match the ODE at a test point."
    if residual is not None:
        return f"NOT VERIFIED. Residual after substituting: {sp.sstr(sp.simplify(residual))}"
    return "INCONCLUSIVE: couldn't evaluate this solution numerically; check it by hand."


def _dsolve(ode: str, ics: str, func: str, var: str) -> str:
    v = sp.Symbol(var)
    F = sp.Function(func)
    eq = _parse(ode, func, var)
    ic_map = {}
    for part in filter(None, (p.strip() for p in (ics or "").split(","))):
        lhs, rhs = part.split("=")
        m = re.fullmatch(rf"{func}('*)\((.+)\)", lhs.strip())
        if not m:
            raise ValueError(f"can't read initial condition '{part}', use y(0)=1 or y'(0)=2")
        order, at = len(m.group(1)), sp.sympify(m.group(2))
        key = F(at) if order == 0 else F(v).diff(v, order).subs(v, at)
        ic_map[key] = sp.sympify(rhs)
    sol = sp.dsolve(eq, F(v), ics=ic_map or None)
    sols = sol if isinstance(sol, list) else [sol]
    return "\n".join(f"{sp.sstr(s)}    (LaTeX: {sp.latex(s)})" for s in sols)


def _compute(op: str, expr: str, var: str, other: str) -> str:
    v = sp.Symbol(var)
    e = _parse(expr, "_nofunc_", var)
    if op == "simplify":
        r = sp.simplify(e)
    elif op == "factor":
        r = sp.factor(e)
    elif op == "expand":
        r = sp.expand(e)
    elif op == "partial_fractions":
        r = sp.apart(e, v)
    elif op == "integrate":
        r = sp.integrate(e, v) if not other else sp.integrate(e, (v, *[sp.sympify(b) for b in other.split(",")]))
    elif op == "diff":
        r = sp.diff(e, v, int(other or 1))
    elif op == "solve":
        r = sp.solve(e, v)
    elif op == "limit":
        r = sp.limit(e, v, sp.sympify(other or "oo"))
    elif op == "equal":
        diff = sp.simplify(e - _parse(other, "_nofunc_", var))
        if diff == 0:
            return "EQUAL"
        if diff.is_number and abs(sp.N(diff)) < 1e-6:
            return "EQUAL (up to rounding)"
        return f"NOT EQUAL (difference simplifies to {sp.sstr(diff)})"
    elif op == "numeric":
        r = sp.N(e, 10)
    else:
        raise ValueError(f"unknown op '{op}'")
    return f"{sp.sstr(r)}    (LaTeX: {sp.latex(r)})"


def _safe(fn, args) -> str:
    try:
        return fn(*args)
    except Exception as exc:  # report parse/math errors back to the model so it can retry
        return f"ERROR: {type(exc).__name__}: {exc}"


_pool: ProcessPoolExecutor | None = None
_pool_lock = threading.Lock()


def _get_pool() -> ProcessPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            # forkserver, not fork: forking a multi-threaded web server can deadlock the child
            ctx = mp.get_context("forkserver")
            ctx.set_forkserver_preload(["sympy", "tutor.mathcheck"])
            _pool = ProcessPoolExecutor(max_workers=2, mp_context=ctx)
        return _pool


def _kill_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            for proc in list(_pool._processes.values()):
                proc.kill()
            _pool.shutdown(wait=False, cancel_futures=True)
            _pool = None


def _run(fn, *args) -> str:
    future = _get_pool().submit(_safe, fn, args)
    try:
        return future.result(timeout=TIMEOUT_S)
    except FuturesTimeout:
        _kill_pool()
        return f"ERROR: SymPy took longer than {TIMEOUT_S}s; verify this step by hand or simplify the input."
    except BrokenProcessPool:
        _kill_pool()
        return "ERROR: the SymPy worker crashed; try again or simplify the input."


def check_ode(ode: str, solution: str, func: str = "y", var: str = "x") -> str:
    return _run(_check_ode, ode, solution, func, var)


def dsolve(ode: str, ics: str = "", func: str = "y", var: str = "x") -> str:
    return _run(_dsolve, ode, ics, func, var)


def compute(op: str, expr: str, var: str = "x", other: str = "") -> str:
    return _run(_compute, op, expr, var, other)
