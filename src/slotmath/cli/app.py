"""Command line entry point.

Exit codes are part of the contract, because the hook depends on them:
  0  everything passed
  1  verification did not pass
  2  the tool itself could not run (missing file, malformed JSON, bad schema)
Conflating 1 and 2 would make "the verifier crashed" read as "the solution
is wrong".
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from slotmath.evaluation import naive
from slotmath.models.metrics import build_metrics, check_board_budget
from slotmath.models.spec import GameSpec, load_spec
from slotmath.reporting.render import (
    render_calibration,
    render_coverage_report,
    render_payout_table,
    render_spec_summary,
)
from slotmath.verification.verify import ReelConfig, verify


def _load_json(path: Path, stderr) -> dict:
    # scripts/hooks/verify_on_write.py carries its own copy of this
    # read-and-parse guard. The duplication is deliberate: the hook's fast
    # path must not import the evaluation stack (slotmath.evaluation /
    # slotmath.verification), so it cannot import this function. Keep both
    # in sync by hand.
    if not path.exists():
        print(f"{path}: not found", file=stderr)
        raise SystemExit(2)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"{path}: cannot read file: {exc.strerror or exc}", file=stderr)
        raise SystemExit(2)
    except UnicodeDecodeError as exc:
        print(f"{path}: cannot read file: {exc}", file=stderr)
        raise SystemExit(2)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"{path}: invalid JSON at line {exc.lineno}: {exc.msg}", file=stderr)
        raise SystemExit(2)


def _cmd_spec(args, out, err) -> int:
    data = _load_json(Path(args.path), err)
    try:
        spec = GameSpec.model_validate(data)
    except ValidationError as exc:
        print(f"{args.path}: invalid GameSpec\n{exc}", file=err)
        return 2
    print(render_spec_summary(spec), file=out)
    return 0


def _load_pair(args, err) -> tuple[GameSpec, ReelConfig]:
    data = _load_json(Path(args.path), err)
    try:
        config = ReelConfig.model_validate(data)
    except ValidationError as exc:
        print(f"{args.path}: invalid ReelConfig\n{exc}", file=err)
        raise SystemExit(2)
    spec_path = Path(config.spec)
    if not spec_path.exists():
        print(f"{config.spec}: referenced spec not found", file=err)
        raise SystemExit(2)
    try:
        spec = load_spec(spec_path)
    except json.JSONDecodeError as exc:
        print(f"{config.spec}: invalid JSON at line {exc.lineno}: {exc.msg}", file=err)
        raise SystemExit(2)
    except ValidationError as exc:
        print(f"{config.spec}: invalid GameSpec\n{exc}", file=err)
        raise SystemExit(2)
    return spec, config


def _cmd_verify(args, out, err) -> int:
    spec, config = _load_pair(args, err)
    report = verify(spec, config, mc_spins=args.mc_spins, mc_seed=args.mc_seed)
    print(report.render(), file=out)
    return 0 if report.passed else 1


def _cmd_report(args, out, err) -> int:
    spec, config = _load_pair(args, err)
    # Render from a fresh recomputation, never from config.metrics: the file
    # is untrusted input (see finding 2 -- Layer 1 forgot to check the very
    # floats this command used to print verbatim), so build the table from
    # naive.evaluate's distribution and build_metrics(), which can only ever
    # report what the reels actually produce. naive.evaluate is an
    # unbounded full enumeration, so check_board_budget guards it here the
    # same way verify.py's Layer 2 does -- otherwise a command that used to
    # do zero computation would happily grind for minutes on an oversized
    # artifact. BoardTooLargeError is a ValueError subclass, so it is caught
    # by the same except clause as any other reel-shape problem.
    try:
        check_board_budget(config.reels)
        distribution = naive.evaluate(spec, config.reels)
    except ValueError as exc:
        print(f"{args.path}: cannot evaluate reels: {exc}", file=err)
        return 2
    m = build_metrics(spec, distribution)
    print(render_payout_table(config, m), file=out)
    return 0


def _cmd_coverage(args, out, err) -> int:
    from slotmath.evaluation.coverage import cross_check_coverage

    spec_data = _load_json(Path(args.spec), err)
    try:
        spec = GameSpec.model_validate(spec_data)
    except ValidationError as exc:
        print(f"{args.spec}: invalid GameSpec\n{exc}", file=err)
        return 2

    data = _load_json(Path(args.solution), err)
    reels = data.get("reels")
    if not isinstance(reels, list):
        print(f"{args.solution}: no reels array", file=err)
        return 2

    try:
        check_board_budget(reels)
        report = cross_check_coverage(spec, reels)
    except ValueError as exc:
        print(f"{args.solution}: cannot analyse reels: {exc}", file=err)
        return 2

    if args.json:
        print(json.dumps(report.to_dict(), indent=2), file=out)
    else:
        print(render_coverage_report(report, spec), file=out)
    tier = args.require or spec.coverage.symbol_pattern
    if tier != "none" and not report.fully_covers(tier):
        return 1
    return 0


def _cmd_feasibility(args, out, err) -> int:
    from slotmath.solving.feasibility import (
        SolveStatus,
        precheck,
        prove_bounded_coverage_infeasible,
    )

    data = _load_json(Path(args.path), err)
    try:
        spec = GameSpec.model_validate(data)
    except ValidationError as exc:
        print(f"{args.path}: invalid GameSpec\n{exc}", file=err)
        return 2

    low = max(args.min_len, spec.grid.rows)
    finding = precheck(spec, low, args.max_len)
    print(f"precheck: {finding.status.value}", file=out)
    for diagnostic in finding.diagnostics:
        print(f"  {diagnostic}", file=out)

    if spec.coverage.symbol_pattern == "none":
        print(
            "no symbol_pattern coverage constraint: bounded enumeration not "
            "applicable",
            file=out,
        )
        return 0 if not finding.proved() else 1

    result = prove_bounded_coverage_infeasible(spec, low, args.max_len)
    print(f"bounded enumeration: {result.status.value}", file=out)
    print(f"  lengths considered: {list(result.lengths_considered)}", file=out)
    print(f"  strips enumerated: {result.strips_enumerated}", file=out)
    print(f"  histogram combinations: {result.histogram_combinations}", file=out)
    if result.best_win_rate_at_exact_rtp is not None:
        print(
            f"  best win rate at exact RTP: "
            f"{result.best_win_rate_at_exact_rtp}",
            file=out,
        )
    print(f"  {result.detail}", file=out)
    if result.witness:
        print(f"  witness: {[list(w) for w in result.witness]}", file=out)
    return 0 if result.status is SolveStatus.PROVEN_FEASIBLE else 1


def _cmd_solve(args, out, err) -> int:
    from slotmath.solving.solver import SolverOptions, solve_with_status

    data = _load_json(Path(args.path), err)
    try:
        spec = GameSpec.model_validate(data)
    except ValidationError as exc:
        print(f"{args.path}: invalid GameSpec\n{exc}", file=err)
        return 2

    outcome = solve_with_status(
        spec,
        SolverOptions(
            seed=args.seed,
            min_len=args.min_len,
            max_len=args.max_len,
            max_seeds=args.max_seeds,
            max_candidates=args.max_candidates,
            spec_path=args.path,
        ),
    )
    config = outcome.config
    if config is None:
        # Never collapse these into one message: "no solution exists" and "the
        # budget ran out" call for completely different next steps.
        print(f"no configuration returned ({outcome.status.value})", file=err)
        for diagnostic in outcome.diagnostics:
            print(f"  {diagnostic}", file=err)
        return 1

    payload = json.loads(config.model_dump_json())
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.out}", file=out)
    else:
        print(json.dumps(payload, indent=2), file=out)
    return 0


def _cmd_explore(args, out, err) -> int:
    from slotmath.solving.portfolio import (
        Portfolio,
        maybe_calibrate,
        recalibrate,
        should_admit,
    )
    from slotmath.solving.solver import SolverOptions, solve_with_status

    data = _load_json(Path(args.path), err)
    try:
        spec = GameSpec.model_validate(data)
    except ValidationError as exc:
        print(f"{args.path}: invalid GameSpec\n{exc}", file=err)
        return 2

    store = Path(args.portfolio)
    if store.exists():
        portfolio_data = _load_json(store, err)
        try:
            portfolio = Portfolio.model_validate(portfolio_data)
        except ValidationError as exc:
            print(f"{store}: invalid Portfolio\n{exc}", file=err)
            return 2
    else:
        portfolio = Portfolio(entries=[], calibration=None)

    if args.recalibrate:
        if recalibrate(portfolio):
            print(
                render_calibration(
                    portfolio.calibration, len(portfolio.entries), label="recalibrated"
                ),
                file=out,
            )
        else:
            print("recalibrate requested but the portfolio is empty; nothing to calibrate from", file=out)

    admitted = 0
    for round_index in range(args.rounds):
        outcome = solve_with_status(
            spec, SolverOptions(seed=args.seed + round_index, spec_path=args.path)
        )
        config = outcome.config
        if config is None:
            print(
                f"round {round_index}: no config found ({outcome.status.value})",
                file=out,
            )
            continue

        if portfolio.calibration is None:
            admit = True  # still collecting the unfiltered calibration sample
        else:
            threshold = (
                args.distance
                if args.distance is not None
                else portfolio.calibration.get("distance", 0.25)
            )
            admit = should_admit(portfolio, config.metrics, threshold)

        if not admit:
            print(f"round {round_index}: rejected as too similar", file=out)
            continue

        portfolio.entries.append(config)
        admitted += 1

        if portfolio.calibration is None:
            print(
                f"round {round_index}: admitted (calibrating, "
                f"{len(portfolio.entries)}/{args.calibration_size})",
                file=out,
            )
            if maybe_calibrate(portfolio, args.calibration_size):
                print(
                    render_calibration(portfolio.calibration, len(portfolio.entries)),
                    file=out,
                )
        else:
            print(f"round {round_index}: admitted (portfolio now {len(portfolio.entries)})", file=out)

    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(portfolio.model_dump_json(indent=2), encoding="utf-8")
    print(f"admitted {admitted} of {args.rounds}; wrote {store}", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    import sys

    out, err = sys.stdout, sys.stderr
    parser = argparse.ArgumentParser(prog="slotmath")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("spec", help="validate and summarise a GameSpec")
    p.add_argument("path")
    p.set_defaults(func=_cmd_spec)

    p = sub.add_parser("verify", help="run all gates against a ReelConfig")
    p.add_argument("path")
    p.add_argument("--mc-spins", type=int, default=2_000_000)
    p.add_argument("--mc-seed", type=int, default=20260731)
    p.set_defaults(func=_cmd_verify)

    p = sub.add_parser("report", help="print a human readable payout table")
    p.add_argument("path")
    p.set_defaults(func=_cmd_report)

    p = sub.add_parser("solve", help="search for a reel config meeting the targets")
    p.add_argument("path")
    p.add_argument("--seed", type=int, default=20260731)
    p.add_argument("--min-len", type=int, default=3)
    p.add_argument("--max-len", type=int, default=16)
    p.add_argument("--max-seeds", type=int, default=400)
    p.add_argument("--max-candidates", type=int, default=40_000)
    p.add_argument("--out", default=None)
    p.set_defaults(func=_cmd_solve)

    p = sub.add_parser(
        "coverage", help="exact symbol x pattern coverage report for a solution"
    )
    p.add_argument("spec")
    p.add_argument("solution")
    p.add_argument("--json", action="store_true", help="emit the full report as JSON")
    p.add_argument(
        "--require",
        choices=["none", "raw", "winning", "max_eligible", "unique_credit"],
        default=None,
        help=(
            "exit 1 unless every (symbol, pattern) pair reaches this tier "
            "(default: whatever the spec's coverage block asks for)"
        ),
    )
    p.set_defaults(func=_cmd_coverage)

    p = sub.add_parser(
        "feasibility",
        help="report whether the targets are provably unreachable, or merely unfound",
    )
    p.add_argument("path")
    p.add_argument("--min-len", type=int, default=3)
    p.add_argument("--max-len", type=int, default=16)
    p.set_defaults(func=_cmd_feasibility)

    p = sub.add_parser("explore", help="collect diverse valid configs")
    p.add_argument("path")
    p.add_argument("--portfolio", default="solutions/portfolio.json")
    p.add_argument("--seed", type=int, default=20260731)
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--distance", type=float, default=None)
    p.add_argument(
        "--calibration-size",
        type=int,
        default=6,
        help=(
            "entries to collect with no diversity filter before deriving "
            "ranges and a distance threshold from their observed spread "
            "(default 6 -- a solve takes roughly a minute, so this keeps a "
            "fresh run's calibration phase in the single-digit minutes)"
        ),
    )
    p.add_argument(
        "--recalibrate",
        action="store_true",
        help="discard any existing calibration and derive a fresh one from the current entries",
    )
    p.set_defaults(func=_cmd_explore)

    try:
        args = parser.parse_args(argv)
        return args.func(args, out, err)
    except SystemExit as exc:
        return int(exc.code)


if __name__ == "__main__":
    raise SystemExit(main())
