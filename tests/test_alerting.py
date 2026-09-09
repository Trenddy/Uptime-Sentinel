from uptime_sentinel.alerting import AlertManager


class RecordingBackend:
    def __init__(self):
        self.events = []

    def send(self, event):
        self.events.append(event)


def test_no_alert_on_first_check_seen():
    backend = RecordingBackend()
    mgr = AlertManager([backend])
    mgr.process("api", ok=True, detail="fine", timestamp=1.0)
    assert backend.events == []


def test_alert_fires_only_on_up_to_down_transition():
    backend = RecordingBackend()
    mgr = AlertManager([backend])
    mgr.process("api", ok=True, detail="fine", timestamp=1.0)
    mgr.process("api", ok=True, detail="fine", timestamp=2.0)  # no transition
    mgr.process("api", ok=False, detail="timeout", timestamp=3.0)  # down transition

    assert len(backend.events) == 1
    assert backend.events[0].kind == "down"


def test_alert_fires_on_recovery_transition():
    backend = RecordingBackend()
    mgr = AlertManager([backend])
    mgr.process("api", ok=True, detail="fine", timestamp=1.0)
    mgr.process("api", ok=False, detail="timeout", timestamp=2.0)
    mgr.process("api", ok=True, detail="fine", timestamp=3.0)

    kinds = [e.kind for e in backend.events]
    assert kinds == ["down", "recovered"]


def test_sla_breach_fires_regardless_of_state():
    backend = RecordingBackend()
    mgr = AlertManager([backend])
    mgr.sla_breach("api", "uptime 98.0% below target 99.9%", timestamp=1.0)
    assert len(backend.events) == 1
    assert backend.events[0].kind == "sla_breach"


def test_multiple_backends_all_receive_events():
    b1, b2 = RecordingBackend(), RecordingBackend()
    mgr = AlertManager([b1, b2])
    mgr.process("api", ok=True, detail="fine", timestamp=1.0)
    mgr.process("api", ok=False, detail="timeout", timestamp=2.0)
    assert len(b1.events) == 1
    assert len(b2.events) == 1
