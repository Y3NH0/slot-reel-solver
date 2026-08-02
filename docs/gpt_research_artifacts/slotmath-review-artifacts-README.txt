Research artifacts for the slot-reel-solver technical review
=============================================================

1. homework-3x3-per-reel-symbol-coverage.json
   A concrete solution where every reel contains every declared symbol.
   Exact metrics:
     RTP = 19/20
     win rate = 37/60
     distribution = {0: 828, 20: 1152, 100: 180}

2. slotmath_coverage_analyzer.py
   Exact A/B/C-style coverage counts.  It uses full enumeration and a
   factorized theorem check; Monte Carlo is not used as a correctness gate.

3. prove_homework_ideal_coverage_bounds_15_16.py
   Bounded exhaustive proof that ideal Symbol × Pattern A/B coverage has
   no exact-RTP solution when every reel length is bounded by 16.

Example commands from repository root:

  PYTHONPATH=src python /path/to/slotmath_coverage_analyzer.py         configs/homework-3x3.json         /path/to/homework-3x3-per-reel-symbol-coverage.json

  PYTHONPATH=src python /path/to/prove_homework_ideal_coverage_bounds_15_16.py         --spec configs/homework-3x3.json
