"""Human-readable text builders for the CLI.

Each function here takes already-validated domain objects (a GameSpec, a
ReelConfig plus its recomputed Metrics, or a portfolio calibration dict) and
returns the exact string the CLI prints. Kept separate from
slotmath.cli.app's argument parsing and command dispatch so "what to
compute" and "how to show it" can change independently -- app.py never
builds a display string itself, only calls print() on what these functions
return.
"""

from __future__ import annotations

from fractions import Fraction

from slotmath.models.metrics import Metrics, exact_rtp, exact_win_rate
from slotmath.models.spec import GameSpec
from slotmath.verification.verify import ReelConfig


def render_spec_summary(spec: GameSpec) -> str:
    lines = [
        f"name: {spec.name}",
        f"grid: {spec.grid.cols}x{spec.grid.rows}",
        f"symbols: {len(spec.symbols)}",
        f"patterns: {', '.join(p.name for p in spec.patterns)}",
        f"combine: {spec.combine}",
        f"target rtp: {spec.targets.rtp}",
        f"min_win_rate: {spec.targets.min_win_rate}",
        f"payout_unit_denominator: {spec.payout_unit_denominator()}",
    ]
    return "\n".join(lines)


def render_payout_table(config: ReelConfig, metrics: Metrics) -> str:
    lines = [f"spec: {config.spec}"]
    for i, reel in enumerate(config.reels):
        lines.append(f"reel{i} (len {len(reel)}): {reel}")
    lines.append(f"spin_count: {metrics.spin_count}")
    lines.append(f"win_count: {metrics.win_count}  win_rate: {exact_win_rate(metrics)}")
    lines.append(f"rtp: {exact_rtp(metrics)} = {metrics.rtp:.10f}")
    lines.append(f"volatility: {metrics.volatility:.6f}  max_win: {metrics.max_win}")
    lines.append("payout        combos   probability")
    for b in metrics.payout_distribution:
        prob = Fraction(b.combo_count, metrics.spin_count)
        lines.append(f"{b.payout:>10}  {b.combo_count:>8}   {prob} = {float(prob):.6f}")
    return "\n".join(lines)


def render_calibration(
    calibration: dict, entry_count: int, label: str = "calibration derived"
) -> str:
    # Imported lazily to avoid a module-load-time dependency from
    # reporting -> solving; nothing else in this module needs it.
    from slotmath.solving.portfolio import FEATURE_NAMES

    ranges_str = ", ".join(
        f"{name}=[{lo:.4g}, {hi:.4g}]"
        for name, (lo, hi) in zip(FEATURE_NAMES, calibration["ranges"])
    )
    return (
        f"{label} from {entry_count} entries: distance={calibration['distance']:.4g}; "
        f"ranges: {ranges_str}"
    )
