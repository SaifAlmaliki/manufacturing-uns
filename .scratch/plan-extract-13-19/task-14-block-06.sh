cd 99_simulator && uv run pytest -v && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/devices.py 99_simulator/test/test_devices.py
git commit -m "feat(simulator): add SignalDevice publishing declarative signals on cadence tiers"
