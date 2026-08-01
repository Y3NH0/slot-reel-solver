from fractions import Fraction
import pytest
from pydantic import ValidationError
import slotmath.models.spec
from slotmath.models.spec import GameSpec, load_spec


def _base():
    return {
        "name": "t",
        "grid": {"cols": 3, "rows": 3},
        "symbols": {"0": 0.25, "1": 0.55, "2": 1},
        "patterns": [{"name": "TL", "cells": [[0, 0], [0, 1], [1, 0], [1, 1]]}],
        "targets": {"rtp": 0.95, "min_win_rate": 0.55},
    }


def test_float_055_becomes_exact_eleven_twentieths():
    spec = GameSpec.model_validate(_base())
    assert spec.symbols[1] == Fraction(11, 20)


def test_string_rational_accepted():
    d = _base()
    d["symbols"]["2"] = "1/3"
    assert GameSpec.model_validate(d).symbols[2] == Fraction(1, 3)


def test_combine_defaults_to_max():
    assert GameSpec.model_validate(_base()).combine == "max"


def test_pattern_multiplier_defaults_to_one():
    spec = GameSpec.model_validate(_base())
    assert spec.patterns[0].pattern_multiplier == Fraction(1)


def test_cells_all_expands_to_every_cell():
    d = _base()
    d["patterns"] = [{"name": "FULL", "cells": "all", "pattern_multiplier": 5}]
    cells = GameSpec.model_validate(d).patterns[0].cells
    assert len(cells) == 9
    assert (2, 2) in cells and (0, 0) in cells


def test_out_of_bounds_cell_rejected():
    d = _base()
    d["patterns"] = [{"name": "X", "cells": [[3, 0]]}]
    with pytest.raises(ValidationError, match="out of bounds"):
        GameSpec.model_validate(d)


def test_duplicate_cell_rejected():
    d = _base()
    d["patterns"] = [{"name": "X", "cells": [[0, 0], [0, 0]]}]
    with pytest.raises(ValidationError, match="duplicate"):
        GameSpec.model_validate(d)


def test_payout_unit_denominator_is_lcm_of_all_payout_denominators():
    d = _base()
    d["patterns"] = [
        {"name": "TL", "cells": [[0, 0]]},
        {"name": "FULL", "cells": "all", "pattern_multiplier": 5},
    ]
    # payouts: 0.25,0.55,1 and x5 -> denominators 4,20,1 -> lcm 20
    assert GameSpec.model_validate(d).payout_unit_denominator() == 20


def test_payout_units_is_integer():
    spec = GameSpec.model_validate(_base())
    p = spec.patterns[0]
    assert spec.payout_units(1, p) == 11    # 0.55 * 20
    assert spec.payout_units(0, p) == 5     # 0.25 * 20


def test_payout_unit_denominator_is_cached(monkeypatch):
    spec = GameSpec.model_validate(_base())

    calls = {"n": 0}
    real_lcm = slotmath.models.spec.lcm

    def counting_lcm(*args):
        calls["n"] += 1
        return real_lcm(*args)

    monkeypatch.setattr(slotmath.models.spec, "lcm", counting_lcm)

    first = spec.payout_unit_denominator()
    second = spec.payout_unit_denominator()

    assert first == second == 20
    assert calls["n"] == 1, "payout_unit_denominator() recomputed lcm instead of using the cache"


def test_homework_config_loads():
    spec = load_spec("configs/homework-3x3.json")
    assert spec.grid.cols == 3 and spec.grid.rows == 3
    assert len(spec.patterns) == 5
    assert spec.targets.rtp == Fraction(19, 20)
    assert spec.targets.min_win_rate == Fraction(11, 20)
    assert spec.payout_unit_denominator() == 20
