# in 99_simulator/test/test_devices.py, extend the existing DummyClient
class DummyClient:
    def __init__(self, *args, **kwargs):  # noqa: ARG002
        self.published: list[tuple[str, dict]] = []
        self.enter_count = 0
        self.fail_on_enter = 0
        self.fail_on_publish = False

    async def __aenter__(self):
        self.enter_count += 1
        if self.fail_on_enter > 0:
            self.fail_on_enter -= 1
            raise OSError("broker refused the connection")
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False

    async def publish(self, topic, payload, **kwargs):  # noqa: ARG002
        if self.fail_on_publish:
            raise OSError("broker went away")
        self.published.append((topic, json.loads(payload)))
