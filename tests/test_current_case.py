from starter.agent.loop import FakeProvider, run
from starter.core.gateway import Gateway, current_case
from starter.runtime.config import Settings


def test_simulate_hook_sees_the_current_case(store):
    seen = []
    gateway = Gateway(store)

    @gateway.register(simulate=lambda to, body: seen.append(current_case.get()) or {"to": to})
    def send_message(to: str, body: str) -> dict:
        """Send."""
        return {}

    case = {"id": "c1", "body": "hi"}
    run(case, gateway, Settings(), FakeProvider())
    assert seen == [case] and current_case.get() is None
