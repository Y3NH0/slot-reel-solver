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
from fractions import Fraction
from pathlib import Path

from pydantic import ValidationError

from slotmath.metrics import exact_rtp, exact_win_rate
from slotmath.spec import GameSpec, load_spec
from slotmath.verify import ReelConfig, verify


def _load_json(path: Path, stderr) -> dict:
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
    print(f"name: {spec.name}", file=out)
    print(f"grid: {spec.grid.cols}x{spec.grid.rows}", file=out)
    print(f"symbols: {len(spec.symbols)}", file=out)
    print(f"patterns: {', '.join(p.name for p in spec.patterns)}", file=out)
    print(f"combine: {spec.combine}", file=out)
    print(f"target rtp: {spec.targets.rtp}", file=out)
    print(f"min_win_rate: {spec.targets.min_win_rate}", file=out)
    print(f"payout_unit_denominator: {spec.payout_unit_denominator()}", file=out)
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
    return load_spec(spec_path), config


def _cmd_verify(args, out, err) -> int:
    spec, config = _load_pair(args, err)
    report = verify(spec, config, mc_spins=args.mc_spins, mc_seed=args.mc_seed)
    print(report.render(), file=out)
    return 0 if report.passed else 1


def _cmd_report(args, out, err) -> int:
    spec, config = _load_pair(args, err)
    m = config.metrics
    print(f"spec: {config.spec}", file=out)
    for i, reel in enumerate(config.reels):
        print(f"reel{i} (len {len(reel)}): {reel}", file=out)
    print(f"spin_count: {m.spin_count}", file=out)
    print(f"win_count: {m.win_count}  win_rate: {exact_win_rate(m)}", file=out)
    print(f"rtp: {exact_rtp(m)} = {m.rtp:.10f}", file=out)
    print(f"volatility: {m.volatility:.6f}  max_win: {m.max_win}", file=out)
    print("payout        combos   probability", file=out)
    for b in m.payout_distribution:
        prob = Fraction(b.combo_count, m.spin_count)
        print(
            f"{b.payout:>10}  {b.combo_count:>8}   {prob} = {float(prob):.6f}",
            file=out,
        )
    return 0


def _cmd_solve(args, out, err) -> int:
    from slotmath.solver import SolverOptions, solve

    data = _load_json(Path(args.path), err)
    try:
        spec = GameSpec.model_validate(data)
    except ValidationError as exc:
        print(f"{args.path}: invalid GameSpec\n{exc}", file=err)
        return 2

    config = solve(
        spec,
        SolverOptions(seed=args.seed, min_len=args.min_len, max_len=args.max_len),
    )
    if config is None:
        print("no configuration found within the search budget", file=err)
        return 1

    payload = json.loads(config.model_dump_json())
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.out}", file=out)
    else:
        print(json.dumps(payload, indent=2), file=out)
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
    p.add_argument("--out", default=None)
    p.set_defaults(func=_cmd_solve)

    try:
        args = parser.parse_args(argv)
        return args.func(args, out, err)
    except SystemExit as exc:
        return int(exc.code)


if __name__ == "__main__":
    raise SystemExit(main())
