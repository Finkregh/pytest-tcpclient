"""Tests for the pytest-tcpclient plugin functionality."""

import pytest


def assert_failure(
    result: pytest.RunResult,
    message: str,
    server_variable_name: str = "tcpserver",
) -> None:
    """Assert that a test failed with a specific error message.

    Args:
        result: The pytest result object
        message: Expected failure message
        server_variable_name: Name of the server variable in the test (default: "tcpserver")

    """
    __tracebackhide__ = True
    result.assert_outcomes(failed=1)
    lines = result.stdout.get_lines_after(
        f">       await {server_variable_name}.join()",
    )
    assert lines[0] == f"E       Failed: {message}"


def test_expect_connect_passes_1(pytester: pytest.Pytester) -> None:
    """Test that expect_connect passes when client connects properly (variant 1)."""
    pytester.copy_example("test_expect_connect_passes_1.py")
    pytester.runpytest().assert_outcomes(passed=1)


def test_expect_connect_passes_2(pytester: pytest.Pytester) -> None:
    """Test that expect_connect passes when client connects properly (variant 2)."""
    pytester.copy_example("test_expect_connect_passes_2.py")
    pytester.runpytest().assert_outcomes(passed=1)


def test_expect_connect_minimal(pytester: pytest.Pytester) -> None:
    """Test minimal expect_connect functionality."""
    pytester.copy_example("test_expect_connect_minimal.py")
    pytester.runpytest().assert_outcomes(passed=1)


def test_second_connection_causes_failure(pytester: pytest.Pytester) -> None:
    """Test that a second connection attempt causes failure."""
    pytester.copy_example("test_second_connection_causes_failure.py")
    result: pytest.RunResult = pytester.runpytest()
    print(result.outlines)
    assert_failure(
        result,
        "While waiting for client to disconnect a second connection was attempted.",
    )


def test_expect_connect_times_out(pytester: pytest.Pytester) -> None:
    """Test that expect_connect times out when no client connects."""
    pytester.copy_example("test_expect_connect_times_out.py")
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    assert_failure(result, "Timed out waiting for client to connect.")


def test_expect_disconnect_close_not_called(pytester: pytest.Pytester) -> None:
    """Test failure when client doesn't call writer.close()."""
    pytester.copy_example("test_expect_disconnect_close_not_called.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "Timed out waiting for client to disconnect. Remember to call `writer.close()`.",
    )


def test_expect_disconnect_wait_closed_not_called(pytester: pytest.Pytester) -> None:
    """Test failure when client doesn't call await writer.wait_closed()."""
    pytester.copy_example("test_expect_disconnect_wait_closed_not_called.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "Timed out waiting for client to call `await writer.wait_closed()`.",
    )


def test_expect_disconnect_receives_unexpected_bytes(pytester: pytest.Pytester) -> None:
    """Test failure when server receives unexpected bytes during disconnect."""
    pytester.copy_example("test_expect_disconnect_receives_unexpected_bytes.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "Received unexpected data while waiting for client to disconnect. Data is b'Hello'.",
    )


def test_expect_bytes_success(pytester: pytest.Pytester) -> None:
    """Test successful expect_bytes operation."""
    pytester.copy_example("test_expect_bytes_success.py")
    pytester.runpytest().assert_outcomes(passed=1)


def test_expect_bytes_times_out(pytester: pytest.Pytester) -> None:
    """Test expect_bytes timeout when client doesn't send expected data."""
    pytester.copy_example("test_expect_bytes_times_out.py")
    result = pytester.runpytest()
    assert_failure(result, "Timed out waiting for b'Hello, world!'")


def test_expect_bytes_connection_closed(pytester: pytest.Pytester) -> None:
    """Test expect_bytes failure when connection is closed prematurely."""
    pytester.copy_example("test_expect_bytes_connection_closed.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "Expected to read b'Hello, world' but only read b'' before the connection was closed.",
    )


def test_expect_bytes_wrong_bytes_sent(pytester: pytest.Pytester) -> None:
    """Test expect_bytes failure when client sends wrong data."""
    pytester.copy_example("test_expect_bytes_wrong_bytes_sent.py")
    result = pytester.runpytest()
    assert_failure(result, "Expected to read b'Bonjour' but actually read b'Goodbye'")


def test_send_bytes(pytester: pytest.Pytester) -> None:
    """Test successful send_bytes operation."""
    pytester.copy_example("test_send_bytes.py")
    pytester.runpytest().assert_outcomes(passed=1)


def test_sent_data_not_read(pytester: pytest.Pytester) -> None:
    """Test failure when server sends data that client doesn't read."""
    pytester.copy_example("test_sent_data_not_read.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "There is data sent by server that was not read by client: unread_bytes=b'Hola!'.",
    )


def test_readuntil(pytester: pytest.Pytester) -> None:
    """Test readuntil with unread data detection."""
    pytester.copy_example("test_readuntil.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "There is data sent by server that was not read by client: unread_bytes=b'BBB'.",
    )


def test_readline(pytester: pytest.Pytester) -> None:
    """Test readline with unread data detection."""
    pytester.copy_example("test_readline.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "There is data sent by server that was not read by client: unread_bytes=b'Two\\n'.",
    )


def test_readexactly(pytester: pytest.Pytester) -> None:
    """Test readexactly with unread data detection."""
    pytester.copy_example("test_readexactly.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "There is data sent by server that was not read by client: unread_bytes=b'Two'.",
    )


def test_connection_reset_error(pytester: pytest.Pytester) -> None:
    """Test handling of connection reset errors."""
    pytester.copy_example("test_connection_reset_error.py")
    result = pytester.runpytest()
    # This test can produce different error messages depending on the platform and Python version
    # On Linux/GitHub Actions: "Connection was reset. Did client close writer prematurely?"
    # On macOS: "There is data sent by server that was not read by client: unread_bytes=b'Adios!Amigo!'."
    result.assert_outcomes(failed=1)
    lines = result.stdout.get_lines_after(">       await tcpserver.join()")
    error_message = lines[0]

    # Accept either error message as both are valid depending on platform/timing
    expected_messages = [
        "E       Failed: Connection was reset. Did client close writer prematurely?",
        "E       Failed: There is data sent by server that was not read by client: unread_bytes=b'Adios!Amigo!'.",
    ]

    assert (
        error_message in expected_messages
    ), f"Got unexpected error message: {error_message}"


def test_delayed_join(pytester: pytest.Pytester) -> None:
    """Test delayed join operation."""
    pytester.copy_example("test_delayed_join.py")
    pytester.runpytest().assert_outcomes(passed=1)


def test_expect_connect_is_absent(pytester: pytest.Pytester) -> None:
    """Test failure when expect_connect is missing before expect_bytes."""
    pytester.copy_example("test_expect_connect_is_absent.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "Missing `expect_connect()` before `expect_bytes(b'Hello, world')`",
    )


def test_early_error_doesnt_hang_test(pytester: pytest.Pytester) -> None:
    """Test that early errors don't cause test to hang."""
    pytester.copy_example("test_early_error_doesnt_hang_test.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "Expected to read b'Hello' but actually read b'Adios'",
    )


def test_ordering_error(pytester: pytest.Pytester) -> None:
    """Test ordering error handling."""
    pytester.copy_example("test_ordering_error.py")
    pytester.runpytest().assert_outcomes(passed=1)


def test_expect_frame_success(pytester: pytest.Pytester) -> None:
    """Test successful expect_frame operation."""
    pytester.copy_example("test_expect_frame_success.py")
    pytester.runpytest().assert_outcomes(passed=1)


def test_expect_frame_times_out(pytester: pytest.Pytester) -> None:
    """Test expect_frame timeout when client doesn't send expected frame."""
    pytester.copy_example("test_expect_frame_times_out.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "Timed out waiting for frame b'Goodbye, world'",
    )


def test_expect_frame_wrong_bytes_sent(pytester: pytest.Pytester) -> None:
    """Test expect_frame failure when client sends wrong frame data."""
    pytester.copy_example("test_expect_frame_wrong_bytes_sent.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "Expected to get frame b'Bonjour' but actually got frame b'Goodbye, world'",
    )


def test_send_frame_success(pytester: pytest.Pytester) -> None:
    """Test successful send_frame operation."""
    pytester.copy_example("test_send_frame_success.py")
    pytester.runpytest().assert_outcomes(passed=1)


def test_sent_frame_not_read(pytester: pytest.Pytester) -> None:
    """Test failure when server sends frame that client doesn't read."""
    pytester.copy_example("test_sent_frame_not_read.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "There is data sent by server that was not read by client: "
        "unread_bytes=b'\\x00\\x00\\x00\\x05Hello'.",
    )


def test_server_disconnect(pytester: pytest.Pytester) -> None:
    """Test server-initiated disconnect."""
    pytester.copy_example("test_server_disconnect.py")
    pytester.runpytest().assert_outcomes(passed=1)


def test_readexactly_incomplete(pytester: pytest.Pytester) -> None:
    """Test readexactly with incomplete data."""
    pytester.copy_example("test_readexactly_incomplete.py")
    pytester.runpytest().assert_outcomes(passed=1)


def test_tcpserver_factory_success(pytester: pytest.Pytester) -> None:
    """Test successful tcpserver_factory operation."""
    pytester.copy_example("test_tcpserver_factory_success.py")
    pytester.runpytest().assert_outcomes(passed=1)


def test_tcpserver_factory_second_connection_causes_failure(
    pytester: pytest.Pytester,
) -> None:
    """Test tcpserver_factory failure when second connection is attempted."""
    pytester.copy_example("test_tcpserver_factory_second_connection_causes_failure.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "While waiting for client to disconnect a second connection was attempted.",
        server_variable_name="server",
    )


def test_tcpserver_factory_two_servers_one_fails(pytester: pytest.Pytester) -> None:
    """Test tcpserver_factory with two servers where one fails."""
    pytester.copy_example("test_tcpserver_factory_two_servers_one_fails.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "Expected to get frame b'Client hello 2' but actually got frame b''",
        server_variable_name="server_2",
    )


def test_hello(pytester: pytest.Pytester) -> None:
    """Test basic hello world functionality."""
    pytester.copy_example("test_hello.py")
    pytester.runpytest().assert_outcomes(passed=1)


def test_expect_disconnect_no_connection(pytester: pytest.Pytester) -> None:
    """Test expect_disconnect failure when client is not connected."""
    pytester.copy_example("test_expect_disconnect_no_connection.py")
    result = pytester.runpytest()
    assert_failure(
        result,
        "Client is not connected. Did you forget to call `asyncio.open_connection`?",
    )


def test_tcpserver_factory_two_servers_fail(pytester: pytest.Pytester) -> None:
    """Test tcpserver_factory with two servers that both fail."""
    pytester.copy_example("test_tcpserver_factory_two_servers_fail.py")
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    lines = result.stdout.get_lines_after(">       await tcpserver_factory.stop()")
    assert (
        lines[0]
        == "E       Failed: Expected to read b'Hello_1' but actually read b'Hello_2'"
    )
