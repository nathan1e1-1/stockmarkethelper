import socket
import threading
import time

from autotrader.main import _port_busy, _wait_port_free


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


def test_port_busy_ignores_time_wait_from_closed_connection():
    # A freshly closed connection leaves a TIME_WAIT socket on the listener port.
    # Nothing is listening, so the probe must report the port as free (SO_REUSEADDR),
    # not misread the leftover TIME_WAIT as "busy".
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    connection, _ = server.accept()
    client.close()
    connection.close()
    server.close()
    assert _port_busy("127.0.0.1", port) is False


def test_wait_port_free_returns_false_when_still_busy():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert _wait_port_free("127.0.0.1", port, attempts=1, interval=0.01) is False
    finally:
        server.close()


def test_wait_port_free_returns_true_when_freed_within_attempts():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def release():
        time.sleep(0.2)
        server.close()

    releaser = threading.Thread(target=release)
    releaser.start()
    try:
        assert _wait_port_free("127.0.0.1", port, attempts=20, interval=0.05) is True
    finally:
        releaser.join(timeout=2)
        try:
            server.close()
        except OSError:
            pass