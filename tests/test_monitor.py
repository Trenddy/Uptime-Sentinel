from uptime_sentinel.monitor import check_tcp, run_check


def test_tcp_check_succeeds_against_local_listener():
    import socket
    import threading

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def accept_once():
        try:
            conn, _ = server.accept()
            conn.close()
        except OSError:
            pass

    t = threading.Thread(target=accept_once, daemon=True)
    t.start()

    result = check_tcp("local", "127.0.0.1", port, timeout_seconds=2)
    server.close()

    assert result.ok is True
    assert result.check_type == "tcp"
    assert result.error is None


def test_tcp_check_fails_against_closed_port():
    # Port 1 is a reserved/unlikely-to-be-listening port on localhost.
    result = check_tcp("local", "127.0.0.1", 1, timeout_seconds=1)
    assert result.ok is False
    assert result.error is not None


def test_run_check_dispatches_by_type():
    cfg = {"name": "local", "type": "tcp", "host": "127.0.0.1", "port": 1, "timeout_seconds": 1}
    result = run_check(cfg)
    assert result.service == "local"
    assert result.check_type == "tcp"


def test_run_check_raises_on_unknown_type():
    import pytest

    with pytest.raises(ValueError):
        run_check({"name": "bad", "type": "carrier-pigeon"})
