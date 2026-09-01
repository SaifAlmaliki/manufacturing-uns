cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/simulator.py 99_simulator/test/test_simulator.py
git commit -m "feat(simulator): run the plant clock and schedule publishing per cadence tier"
