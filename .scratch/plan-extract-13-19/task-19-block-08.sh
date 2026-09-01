cd 99_simulator && uv run python -c "
from pathlib import Path
from uns_simulator.profiles import load_profile, read_simulator_conf
p = load_profile(read_simulator_conf(Path('../conf')), 'small')
print(p.report.per_family)
print({k: round(v, 3) for k, v in p.messages_per_second().items()})
"
