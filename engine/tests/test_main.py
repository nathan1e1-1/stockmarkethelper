import socket

from autotrader.main import _port_busy


def test_port_busy_true_when_something_is_listening():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert _port_busy("127.0.0.1", port) is True
    finally:
        server.close()


def test_port_busy_false_when_port_is_free():
    assert _port_busy("127.0.0.1", 0) is False