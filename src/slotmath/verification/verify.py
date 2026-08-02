"""Three-layer verification.

Layer 1 reads the artifact and checks it against itself -- zero computation,
because the integer counts make contradictions visible on their own.
Layer 2 recomputes with both engines and requires exact Fraction agreement
between naive, engine and the file.
Layer 3 simulates along an independent path (montecarlo.py).

Failures in layer 2 must distinguish "the engines disagree with each other"
(a program bug) from "the engines agree but the file does not" (a stale or
edited artifact). Reporting both as "verification failed" is the same as not
reporting.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Literal

from pydantic import BaseModel

from slotmath.evaluation import engine, montecarlo, naive
from slotmath.evaluation.coverage import (
    cross_check_coverage,
    missing_symbols_per_reel,
)
from slotmath.evaluation.engine import SignatureBudgetExceeded
from slotmath.models.metrics import (
    BoardTooLargeError,
    Metrics,
    build_metrics,
    check_board_budget,
    exact_rtp,
    exact_win_rate,
)
from slotmath.models.spec import GameSpec

# Layer 1 float checks compare *display* floats (rtp/win_rate/volatility/
# max_win) against values derived from the integer counts. These floats
# round-trip through JSON via repr(), which is exact for the shortest decimal
# but can still differ in the last bit or two after arithmetic (sqrt for
# volatility in particular). A tight relative tolerance catches a forged or
# stale float without flagging harmless round-trip noise. This tolerance is
# strictly for these display checks -- the RTP-vs-target comparison a few
# lines down remains exact Fraction equality with no tolerance at all.
_FLOAT_RTOL = 1e-9


class ReelConfig(BaseModel):
    spec: str
    reels: list[list[int]]
    metrics: Metrics
    solver: dict | None = None


class Gate(BaseModel):
    name: str
    passed: bool
    severity: Literal["fail", "warn"]
    detail: str


class VerifyReport(BaseModel):
    gates: list[Gate]
    passed: bool

    def render(self) -> str:
        lines = []
        for gate in self.gates:
            mark = "PASS" if gate.passed else gate.severity.upper()
            lines.append(f"[{mark:4}] {gate.name}: {gate.detail}")
        lines.append(f"verdict: {'PASS' if self.passed else 'FAIL'}")
        return "\n".join(lines)


def _distribution(metrics: Metrics) -> dict[int, int]:
    return {b.payout_units: b.combo_count for b in metrics.payout_distribution}


def verify(
    spec: GameSpec,
    config: ReelConfig,
    mc_spins: int = 2_000_000,
    mc_seed: int = 20260731,
    sigma_limit: float = 5.0,
) -> VerifyReport:
    gates: list[Gate] = []

    def add(name, passed, detail, severity="fail"):
        gates.append(Gate(name=name, passed=passed, severity=severity, detail=detail))

    # ---- symbols declared -------------------------------------------------
    used_symbols = {s for reel in config.reels for s in reel}
    unknown = sorted(used_symbols - set(spec.symbols))
    add(
        "symbols_declared",
        not unknown,
        "all reel symbols are declared" if not unknown
        else f"reels contain undeclared symbols: {unknown}",
    )
    if unknown:
        return VerifyReport(gates=gates, passed=False)

    # ---- every declared symbol is used -------------------------------------
    # The converse of symbols_declared: a symbol nobody's reels ever land on
    # is dead weight in the paytable -- legal under the letter of most specs,
    # but not a reasonable output. Not short-circuited like symbols_declared:
    # an undeclared symbol makes payout computation itself suspect, but a
    # missing declared symbol doesn't stop Layers 1-3 from computing
    # correctly, so they still run and report their own status independently.
    missing = sorted(set(spec.symbols) - used_symbols)
    add(
        "all_symbols_used",
        not missing,
        "every declared symbol appears in at least one reel" if not missing
        else f"declared symbols never appear in any reel: {missing}",
    )

    # ---- optional: every reel carries every symbol -------------------------
    # Strictly stronger than all_symbols_used above, and only checked when the
    # spec asks for it, so specs written before this constraint existed are
    # unaffected. Named per reel and per symbol: "coverage failed" tells an
    # author nothing about which strip to edit.
    if spec.coverage.each_reel_all_symbols:
        per_reel = missing_symbols_per_reel(spec, config.reels)
        faults = [
            f"reel {index} is missing declared symbol {symbol}"
            for index, absent in enumerate(per_reel)
            for symbol in absent
        ]
        add(
            "per_reel_symbol_coverage",
            not faults,
            "every reel contains every declared symbol" if not faults
            else "; ".join(faults),
        )

    # ---- Layer 1: file internal consistency -------------------------------
    m = config.metrics
    dist = _distribution(m)
    problems: list[str] = []

    expected_spins = 1
    for reel in config.reels:
        expected_spins *= len(reel)
    if m.spin_count != expected_spins:
        problems.append(
            f"spin_count {m.spin_count} != product of reel lengths {expected_spins}"
        )
    if sum(dist.values()) != m.spin_count:
        problems.append(
            f"combo_count sum {sum(dist.values())} != spin_count {m.spin_count}"
        )
    units = sum(u * c for u, c in dist.items())
    if units != m.total_payout_units:
        problems.append(
            f"sum(payout_units x combo_count) {units} != total_payout_units "
            f"{m.total_payout_units}"
        )
    if m.win_count != m.spin_count - dist.get(0, 0):
        problems.append(f"win_count {m.win_count} disagrees with the zero bucket")
    for bucket in m.payout_distribution:
        if bucket.payout_units / m.payout_unit_denominator != bucket.payout:
            problems.append(f"bucket {bucket.payout_units} payout float is inconsistent")

    # The four derived floats below are documented as checked here (see module
    # docstring); they were previously read straight from the file and never
    # compared against anything, so a forged rtp/win_rate/volatility/max_win
    # sailed through Layer 1. Compare each against a value derived from the
    # integer counts that are the actual source of truth, with the tolerance
    # explained at _FLOAT_RTOL above.
    if m.spin_count:
        expected_win_rate = m.win_count / m.spin_count
        if not math.isclose(m.win_rate, expected_win_rate, rel_tol=_FLOAT_RTOL):
            problems.append(
                f"win_rate {m.win_rate} != win_count/spin_count "
                f"{expected_win_rate}"
            )

        expected_rtp = m.total_payout_units / (m.payout_unit_denominator * m.spin_count)
        if not math.isclose(m.rtp, expected_rtp, rel_tol=_FLOAT_RTOL):
            problems.append(
                f"rtp {m.rtp} != total_payout_units/(payout_unit_denominator * "
                f"spin_count) {expected_rtp}"
            )

        expected_max_win = (max(dist) / m.payout_unit_denominator) if dist else 0.0
        if not math.isclose(m.max_win, expected_max_win, rel_tol=_FLOAT_RTOL):
            problems.append(
                f"max_win {m.max_win} != max(payout_units)/payout_unit_denominator "
                f"{expected_max_win}"
            )

        mean = Fraction(m.total_payout_units, m.payout_unit_denominator * m.spin_count)
        variance = sum(
            count * (Fraction(units, m.payout_unit_denominator) - mean) ** 2
            for units, count in dist.items()
        ) / m.spin_count
        expected_volatility = math.sqrt(float(variance))
        if not math.isclose(m.volatility, expected_volatility, rel_tol=_FLOAT_RTOL):
            problems.append(
                f"volatility {m.volatility} != sqrt(variance of payout_units / "
                f"payout_unit_denominator) {expected_volatility}"
            )

    add(
        "file_consistency",
        not problems,
        "artifact is internally consistent" if not problems else "; ".join(problems),
    )
    if problems:
        return VerifyReport(gates=gates, passed=False)

    # ---- Layer 2: engine vs naive vs file ---------------------------------
    # naive.evaluate is unbounded (prod(reel lengths)), so its cost is
    # checked directly, before it is ever called -- see
    # metrics.check_board_budget / metrics.NAIVE_BUDGET. Shared with
    # slotmath.cli.app's `report` command, which recomputes the same way
    # (see finding 2 / the report-command regression note in the fix report).
    try:
        check_board_budget(config.reels)
    except BoardTooLargeError as exc:
        add("engine_matches_naive", False, str(exc))
        return VerifyReport(gates=gates, passed=False)

    # engine.evaluate is also called FIRST, ahead of naive: it raises
    # SignatureBudgetExceeded before doing any enumeration work once its own
    # (much smaller, signature-space) budget is exceeded. With the
    # board_size check above already bounding naive's cost, this mostly
    # covers pathological signature layouts within an otherwise-small board.
    try:
        engine_dist = engine.evaluate(spec, config.reels)
    except SignatureBudgetExceeded as exc:
        add(
            "engine_matches_naive",
            False,
            f"signature space too large to evaluate safely: {exc}",
        )
        return VerifyReport(gates=gates, passed=False)
    naive_dist = naive.evaluate(spec, config.reels)

    engines_agree = naive_dist == engine_dist
    add(
        "engine_matches_naive",
        engines_agree,
        "signature engine agrees with full enumeration" if engines_agree
        else "ENGINES DISAGREE -- this is a program bug, not a bad artifact. "
             f"naive={naive_dist} engine={engine_dist}",
    )
    if not engines_agree:
        return VerifyReport(gates=gates, passed=False)

    file_agrees = naive_dist == dist
    add(
        "file_matches_recompute",
        file_agrees,
        "artifact metrics match recomputation" if file_agrees
        else "both engines agree with each other but not with the file -- the "
             "artifact is stale or was edited. Re-run the solver.",
    )
    if not file_agrees:
        return VerifyReport(gates=gates, passed=False)

    recomputed = build_metrics(spec, naive_dist)

    # ---- targets ----------------------------------------------------------
    actual_rtp = exact_rtp(recomputed)
    on_target = actual_rtp == spec.targets.rtp
    add(
        "rtp_exact",
        on_target,
        f"RTP is exactly {actual_rtp}" if on_target
        else f"RTP is {actual_rtp} ({float(actual_rtp):.10f}), target is "
             f"{spec.targets.rtp}. There is no tolerance band.",
    )

    actual_win_rate = exact_win_rate(recomputed)
    meets = actual_win_rate >= spec.targets.min_win_rate
    add(
        "min_win_rate",
        meets,
        f"win_rate {actual_win_rate} >= {spec.targets.min_win_rate}" if meets
        else f"win_rate {actual_win_rate} is below {spec.targets.min_win_rate}",
    )

    # ---- optional: symbol x pattern coverage -------------------------------
    # Exact and structural: computed by two independent analyzers that must
    # agree, never by the Monte Carlo below. A simulation cannot distinguish
    # "this pair is impossible" from "this pair is rare", so it has no vote
    # here. cross_check_coverage raises on analyzer disagreement rather than
    # returning a failed gate -- that would be a program bug, not a verdict
    # on the artifact, and the two must never be confused.
    if spec.coverage.symbol_pattern != "none":
        kind = spec.coverage.symbol_pattern
        coverage_report = cross_check_coverage(spec, config.reels)
        uncovered = coverage_report.uncovered(kind)
        detail = (
            f"every (symbol, pattern) pair reaches {kind} coverage"
            if not uncovered
            else "; ".join(
                f"symbol {e.symbol} never reaches {kind} coverage under "
                f"{e.pattern}"
                + (f" ({e.reasons[0].describe()})" if e.reasons else "")
                for e in uncovered
            )
        )
        add("symbol_pattern_coverage", not uncovered, detail)

    # ---- Layer 3: independent Monte Carlo ---------------------------------
    sim = montecarlo.simulate(spec, config.reels, spins=mc_spins, seed=mc_seed)
    sigma = montecarlo.sigma_deviation(spec, config.reels, sim, naive_dist)
    within = abs(sigma) < sigma_limit
    add(
        "monte_carlo",
        within,
        f"simulated RTP is {sigma:+.2f} sigma from exact "
        f"({mc_spins} spins, seed {mc_seed})",
    )

    # ---- warnings ---------------------------------------------------------
    never_loses = actual_win_rate == 1
    add(
        "win_rate_not_degenerate",
        not never_loses,
        "win_rate is below 1" if not never_loses
        else "win_rate is exactly 1: the player never comes up empty. Legal "
             "under the rules but commercially unusual.",
        severity="warn",
    )

    passed = all(g.passed for g in gates if g.severity == "fail")
    return VerifyReport(gates=gates, passed=passed)
