cd 99_simulator && uv run ruff check . && uv run ruff format .
git add 99_simulator/src/uns_simulator/devices.py 99_simulator/test/test_devices.py
git commit -m "fix(simulator): reuse one MQTT connection per device with backoff and unique client ids"
