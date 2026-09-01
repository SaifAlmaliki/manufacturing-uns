docker build -t uns/simulator:local --build-arg GIT_HASH=local -f 99_simulator/Dockerfile .
docker run --rm --name uns_sim_smoke uns/simulator:local
