"""Pytest plugin for testing TCP clients with mock servers."""

# ruff: noqa: EM101, TRY003, ANN401, ERA001, E501

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio

from .framing import read_frame, write_frame

if TYPE_CHECKING:
    from asyncio import Event, Queue, Server, StreamReader, StreamWriter, Task

    from pytest_mock import MockerFixture


@dataclass
class ServerActionEvent:
    """Base class for server action events."""


@dataclass
class ClientConnectedEvent(ServerActionEvent):
    """Event indicating a client has connected."""


@dataclass
class ClientNotConnectedEvent(ServerActionEvent):
    """Event indicating no client is connected."""


@dataclass
class SecondClientConnectionAttempted(ServerActionEvent):
    """Event indicating a second client connection was attempted."""


@dataclass
class ReadZeroBytes(ServerActionEvent):
    """Event indicating zero bytes were read (connection closed)."""


@dataclass
class ClientCalledWriterClose(ServerActionEvent):
    """Event indicating client called writer.close()."""


@dataclass
class ClientCalledWriterWaitClosed(ServerActionEvent):
    """Event indicating client called await writer.wait_closed()."""


@dataclass
class NoRemainingSentData(ServerActionEvent):
    """Event indicating all sent data has been read by client."""


@dataclass
class ExceptionEvent(ServerActionEvent):
    """Event indicating an exception occurred."""

    exception: Exception


@dataclass
class BytesReadEvent(ServerActionEvent):
    """Event indicating bytes were read from client."""

    bytes_read: bytes


@dataclass
class FrameReadEvent(ServerActionEvent):
    """Event indicating a frame was read from client."""

    payload: bytes


@dataclass
class TimeoutEvent(ServerActionEvent):
    """Event indicating a timeout occurred."""


@dataclass
class IncompleteReadEvent(ServerActionEvent):
    """Event indicating an incomplete read occurred."""

    partial: bytes


@dataclass
class UnreadSentBytes(ServerActionEvent):
    """Event indicating there are unread bytes sent by server."""

    def __init__(self, unread_bytes: bytes) -> None:
        """Initialize with unread bytes.

        Args:
            unread_bytes: The bytes that were sent but not read

        """
        self.unread_bytes = unread_bytes


class UnexpectedEventError(Exception):
    """Exception raised when an unexpected event occurs."""

    def __init__(
        self,
        expected_event: ServerActionEvent,
        actual_event: ServerActionEvent,
    ) -> None:
        """Initialize with expected and actual events.

        Args:
            expected_event: The event that was expected
            actual_event: The event that actually occurred

        """
        super().__init__(
            f"UnexpectedEventError(expected_event={expected_event}, actual_event={actual_event}",
        )
        self.expected_event = expected_event
        self.actual_event = actual_event


class ExpectConnect:
    """Expectation that a client will connect to the server."""

    def __init__(self, server: "MockTcpServer", timeout: float) -> None:
        """Initialize the expectation.

        Args:
            server: The mock TCP server
            timeout: Timeout in seconds for the connection

        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.server = server
        self.timeout = timeout

    async def server_action(self) -> None:
        """Perform server-side action (none needed for connection expectation)."""
        # See `MockTcpServer.start` for why this method cannot itself generate
        # the `ClientConnectedEvent`

    async def evaluate(self) -> None:
        """Evaluate whether the expectation was met."""
        # Since `server_action` does nothing, it cannot generate an error event in the
        # case of a timeout. We have to do that here.

        try:
            self.logger.debug("Expecting connection from client.")
            next_event = await asyncio.wait_for(
                self.server.server_event_queue.get(),
                timeout=self.timeout,
            )
        except TimeoutError:
            self.logger.debug("Timed out waiting for client to connect.")
            next_event = TimeoutEvent()

        if not isinstance(next_event, ClientConnectedEvent):
            raise UnexpectedEventError(ClientConnectedEvent(), next_event)

        self.logger.debug("Client connected")


class ExpectIsConnected:
    """Expectation that a client is already connected."""

    def __init__(self, server: "MockTcpServer") -> None:
        """Initialize the expectation.

        Args:
            server: The mock TCP server

        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.server = server

    async def server_action(self) -> None:
        """Perform server-side action (none needed for connection check)."""

    async def evaluate(self) -> None:
        """Evaluate whether the client is connected."""
        # Since `server_action` does nothing, it cannot generate an error event in the
        # case of a timeout. We have to do that here.

        self.logger.debug("Expecting client to already be connected")
        if not self.server.connected:
            raise UnexpectedEventError(
                ClientConnectedEvent(),
                ClientNotConnectedEvent(),
            )

        self.logger.debug("Client connected")


class ExpectClientCalledWriterClose:
    """Expectation that client will call writer.close()."""

    def __init__(self, server: "MockTcpServer", timeout: float) -> None:
        """Initialize the expectation.

        Args:
            server: The mock TCP server
            timeout: Timeout in seconds

        """
        self.server = server
        self.timeout = timeout

    async def server_action(self) -> ClientCalledWriterClose | TimeoutEvent:
        """Wait for client to call writer.close()."""
        try:
            await asyncio.wait_for(
                self.server.client_called_writer_close.wait(),
                timeout=self.timeout,
            )
            return ClientCalledWriterClose()
        except TimeoutError:
            return TimeoutEvent()

    async def evaluate(self) -> None:
        """Evaluate whether the expectation was met."""
        next_event = await self.server.server_event_queue.get()
        if not isinstance(next_event, ClientCalledWriterClose):
            raise UnexpectedEventError(ClientCalledWriterClose(), next_event)


class ExpectClientCalledWriterWaitClosed:
    """Expectation that client will call await writer.wait_closed()."""

    def __init__(self, server: "MockTcpServer", timeout: float) -> None:
        """Initialize the expectation.

        Args:
            server: The mock TCP server
            timeout: Timeout in seconds

        """
        self.server = server
        self.timeout = timeout

    async def server_action(self) -> ClientCalledWriterWaitClosed | TimeoutEvent:
        """Wait for client to call await writer.wait_closed()."""
        try:
            await asyncio.wait_for(
                self.server.client_called_writer_waited_closed.wait(),
                timeout=self.timeout,
            )
            return ClientCalledWriterWaitClosed()
        except TimeoutError:
            return TimeoutEvent()

    async def evaluate(self) -> None:
        """Evaluate whether the expectation was met."""
        next_event = await self.server.server_event_queue.get()
        if not isinstance(next_event, ClientCalledWriterWaitClosed):
            raise UnexpectedEventError(ClientCalledWriterWaitClosed(), next_event)


class ExpectBytes:
    """Expectation that client will send specific bytes."""

    def __init__(
        self,
        server: "MockTcpServer",
        expected_bytes: bytes,
        timeout: float,
    ) -> None:
        """Initialize the expectation.

        Args:
            server: The mock TCP server
            expected_bytes: The bytes expected from client
            timeout: Timeout in seconds

        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.server = server
        self.expected_bytes = expected_bytes
        self.timeout = timeout

    async def server_action(
        self,
    ) -> BytesReadEvent | TimeoutEvent | IncompleteReadEvent:
        """Read bytes from client."""
        try:
            self.logger.debug("Expecting to read bytes: %s", self.expected_bytes)
            received = await asyncio.wait_for(
                self.server.reader.readexactly(len(self.expected_bytes)),
                timeout=self.timeout,
            )
            self.logger.debug("Bytes read: %s", received)
            return BytesReadEvent(received)
        except TimeoutError:
            self.logger.debug("Timed out waiting to read bytes %s", self.expected_bytes)
            return TimeoutEvent()
        except asyncio.IncompleteReadError as e:
            self.logger.debug(
                "Incomplete read while trying to read bytes %s",
                self.expected_bytes,
            )
            return IncompleteReadEvent(e.partial)

    async def evaluate(self) -> None:
        """Evaluate whether the expected bytes were received."""
        next_event = await self.server.server_event_queue.get()
        if not isinstance(next_event, BytesReadEvent):
            raise UnexpectedEventError(BytesReadEvent(self.expected_bytes), next_event)
        if next_event.bytes_read != self.expected_bytes:
            raise UnexpectedEventError(BytesReadEvent(self.expected_bytes), next_event)
        self.logger.debug("Expected bytes were received: %s", self.expected_bytes)


class ExpectFrame:
    """Expectation that client will send a specific frame."""

    def __init__(
        self,
        server: "MockTcpServer",
        expected_payload: bytes,
        timeout: float,
    ) -> None:
        """Initialize the expectation.

        Args:
            server: The mock TCP server
            expected_payload: The frame payload expected from client
            timeout: Timeout in seconds

        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.server = server
        self.expected_payload = expected_payload
        self.timeout = timeout

    async def server_action(self) -> FrameReadEvent | TimeoutEvent:
        """Read frame from client."""
        try:
            self.logger.debug("Expecting to read frame: %s", self.expected_payload)
            payload = await asyncio.wait_for(
                read_frame(self.server.reader),
                timeout=self.timeout,
            )
            self.logger.debug("Payload read: %s", payload)
            return FrameReadEvent(payload)
        except TimeoutError:
            self.logger.debug(
                "Timed out waiting to read frame %s",
                self.expected_payload,
            )
            return TimeoutEvent()

    async def evaluate(self) -> None:
        """Evaluate whether the expected frame was received."""
        next_event = await self.server.server_event_queue.get()
        if not isinstance(next_event, FrameReadEvent):
            raise UnexpectedEventError(
                FrameReadEvent(self.expected_payload),
                next_event,
            )
        if next_event.payload != self.expected_payload:
            raise UnexpectedEventError(
                FrameReadEvent(self.expected_payload),
                next_event,
            )
        self.logger.debug("Expected frame was received: %s", self.expected_payload)


class ExpectReadZeroBytes:
    """Expectation that reading will return zero bytes (connection closed)."""

    def __init__(self, server: "MockTcpServer", timeout: float) -> None:
        """Initialize the expectation.

        Args:
            server: The mock TCP server
            timeout: Timeout in seconds

        """
        self.server = server
        self.timeout = timeout

    async def server_action(self) -> ReadZeroBytes | BytesReadEvent:
        """Attempt to read bytes, expecting zero bytes (connection closed)."""
        try:
            received = await asyncio.wait_for(
                self.server.reader.read(),
                timeout=self.timeout,
            )
            if len(received) == 0:
                return ReadZeroBytes()
            return BytesReadEvent(received)
        except ConnectionResetError:
            return ReadZeroBytes()

    async def evaluate(self) -> None:
        """Evaluate whether zero bytes were read."""
        next_event = await self.server.server_event_queue.get()
        if not isinstance(next_event, ReadZeroBytes):
            raise UnexpectedEventError(ReadZeroBytes(), next_event)


class ExpectClientReadAllSentBytes:
    """Expectation that client has read all bytes sent by server."""

    def __init__(self, server: "MockTcpServer", timeout: float) -> None:
        """Initialize the expectation.

        Args:
            server: The mock TCP server
            timeout: Timeout in seconds

        """
        self.server = server
        self.timeout = timeout

    async def server_action(self) -> NoRemainingSentData | UnreadSentBytes:
        """Check if client has read all sent data."""
        sent_bytes = self.server.data_sent_from_server
        read_bytes = self.server.data_read_by_client
        if read_bytes == sent_bytes:
            return NoRemainingSentData()
        if not sent_bytes.startswith(read_bytes):
            msg = (
                "sent_bytes does not start with read_bytes: "
                f"{sent_bytes=}, {read_bytes=}"
            )
            raise ValueError(msg)
        return UnreadSentBytes(sent_bytes[len(read_bytes) :])

    async def evaluate(self) -> None:
        """Evaluate whether all sent data was read."""
        next_event = await self.server.server_event_queue.get()
        if not isinstance(next_event, NoRemainingSentData):
            raise UnexpectedEventError(NoRemainingSentData(), next_event)


class SendBytes:
    """Action to send bytes from server to client."""

    def __init__(self, server: "MockTcpServer", data: bytes) -> None:
        """Initialize the action.

        Args:
            server: The mock TCP server
            data: The bytes to send

        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.server = server
        self.data = data

    async def server_action(self) -> None:
        """Send bytes to client."""
        self.logger.debug("Sending bytes %s", self.data)
        self.server.writer.write(self.data)
        await self.server.writer.drain()

    async def evaluate(self) -> None:
        """No evaluation needed for send action."""


class SendFrame:
    """Action to send a frame from server to client."""

    def __init__(self, server: "MockTcpServer", payload: bytes) -> None:
        """Initialize the action.

        Args:
            server: The mock TCP server
            payload: The frame payload to send

        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.server = server
        self.payload = payload

    async def server_action(self) -> None:
        """Send frame to client."""
        self.logger.debug("Send frame %s", self.payload)
        write_frame(self.server.writer, self.payload)
        await self.server.writer.drain()

    async def evaluate(self) -> None:
        """No evaluation needed for send action."""


class Disconnect:
    """Action to disconnect server from client."""

    def __init__(self, server: "MockTcpServer") -> None:
        """Initialize the action.

        Args:
            server: The mock TCP server

        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.server = server

    async def server_action(self) -> None:
        """Disconnect from client."""
        self.logger.debug("Server disconnecting")
        self.server.writer.close()
        await self.server.writer.wait_closed()

    async def evaluate(self) -> None:
        """No evaluation needed for disconnect action."""


def interpret_error(exception: Exception) -> str:  # noqa: C901, PLR0911, PLR0912
    """Interpret an UnexpectedEventError and return a human-readable message.

    Args:
        exception: The exception to interpret

    Returns:
        A human-readable error message

    """
    if not isinstance(exception, UnexpectedEventError):  # pragma: no cover
        return f"Cannot interpret {exception}, {type(exception)=}"

    expected_event = exception.expected_event
    actual_event = exception.actual_event

    if isinstance(expected_event, ReadZeroBytes):
        if isinstance(actual_event, BytesReadEvent):
            return (
                "Received unexpected data while waiting for client to disconnect. "
                f"Data is {actual_event.bytes_read!r}."
            )
    elif isinstance(expected_event, ClientCalledWriterClose):
        if isinstance(actual_event, SecondClientConnectionAttempted):
            return (
                "While waiting for client to disconnect a "
                "second connection was attempted."
            )
        if isinstance(actual_event, TimeoutEvent):
            return (
                "Timed out waiting for client to disconnect. "
                "Remember to call `writer.close()`."
            )
        if isinstance(actual_event, ExceptionEvent) and isinstance(
            actual_event.exception,
            ConnectionResetError,
        ):
            return "Connection was reset. Did client close writer prematurely?"
    elif isinstance(expected_event, ClientConnectedEvent):
        if isinstance(actual_event, TimeoutEvent):
            return "Timed out waiting for client to connect."
        if isinstance(actual_event, ClientNotConnectedEvent):
            return (
                "Client is not connected. "
                "Did you forget to call `asyncio.open_connection`?"
            )
    elif isinstance(expected_event, BytesReadEvent):
        if isinstance(actual_event, TimeoutEvent):
            return f"Timed out waiting for {expected_event.bytes_read!r}"
        if isinstance(actual_event, ClientConnectedEvent):
            return (
                "Missing `expect_connect()` before "
                f"`expect_bytes({expected_event.bytes_read!r})`"
            )
        if isinstance(actual_event, BytesReadEvent):
            return (
                f"Expected to read {expected_event.bytes_read!r} "
                f"but actually read {actual_event.bytes_read!r}"
            )
        if isinstance(actual_event, IncompleteReadEvent) and not actual_event.partial:
            return (
                f"Expected to read {expected_event.bytes_read!r} "
                f"but only read {actual_event.partial} "
                "before the connection was closed."
            )
    elif isinstance(expected_event, FrameReadEvent):
        if isinstance(actual_event, TimeoutEvent):
            return f"Timed out waiting for frame {expected_event.payload!r}"
        # elif isinstance(actual_event, ClientConnectedEvent):
        #     return "Missing `expect_connect()` before " + \
        #             f"`expect_bytes({expected_event.bytes_read})`"
        if isinstance(actual_event, FrameReadEvent):
            return (
                f"Expected to get frame {expected_event.payload!r} "
                f"but actually got frame {actual_event.payload!r}"
            )
    elif isinstance(expected_event, ClientCalledWriterWaitClosed):
        if isinstance(actual_event, TimeoutEvent):
            return "Timed out waiting for client to call `await writer.wait_closed()`."
    elif isinstance(expected_event, NoRemainingSentData) and isinstance(
        actual_event,
        UnreadSentBytes,
    ):
        return (
            "There is data sent by server that was not read by client: "
            f"unread_bytes={actual_event.unread_bytes!r}."
        )

    return f"Cannot interpret {exception}, {type(exception)=}"  # pragma: no cover


class InterceptorProtocol:
    """Protocol interceptor for capturing connection events."""

    def __init__(self, server: "MockTcpServer", original_protocol: Any) -> None:
        """Initialize the interceptor.

        Args:
            server: The mock TCP server
            original_protocol: The original protocol to wrap

        """
        self.server = server
        self.original_protocol = original_protocol

    def connection_made(self, transport: Any) -> None:
        """Handle connection made event."""
        self.original_protocol.connection_made(transport)

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle connection lost event."""
        self.original_protocol.connection_lost(exc)

    def pause_writing(self) -> None:  # pragma: no cover
        """Handle pause writing event."""
        self.original_protocol.pause_writing()

    def resume_writing(self) -> None:  # pragma: no cover
        """Handle resume writing event."""
        self.original_protocol.resume_writing()

    def data_received(self, data: bytes) -> None:
        """Handle data received event."""
        self.original_protocol.data_received(data)

    def eof_received(self) -> None:
        """Handle EOF received event."""
        self.original_protocol.eof_received()


class MockTcpServer:
    """Mock TCP server for testing TCP clients."""

    def __init__(self, service_port: int, mocker: "MockerFixture") -> None:
        """Initialize the mock server.

        Args:
            service_port: Port number for the server
            mocker: Pytest mocker fixture

        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.service_port = service_port
        self.mocker = mocker
        self.connected = False
        self.errors: list[Exception] = []
        self.join_already_failed = False
        self.stopped = False
        self.instructions: list[Any] = []
        self.server_event_queue: Queue[ServerActionEvent] = asyncio.Queue()
        self.server_actions: Queue[Callable[[], Any]] = asyncio.Queue()
        self.expecations_queue: Queue[Any] = asyncio.Queue()

        self.evaluator_task: Task[None] | None = None
        self.server: Server | None = None
        self.reader: StreamReader | None = None
        self.writer: StreamWriter | None = None
        self.client_reader: StreamReader | None = None
        self.client_writer: StreamWriter | None = None

        self.client_called_writer_close: Event = asyncio.Event()
        self.client_called_writer_waited_closed: Event = asyncio.Event()
        self.data_read_by_client = b""
        self.data_sent_from_server = b""

        # Add type annotations for dynamically assigned attributes
        self.original_writer_write: Callable[[bytes], None] | None = None
        self.original_client_writer_close: Callable[[], None] | None = None
        self.original_client_writer_wait_closed: Callable[[], Any] | None = None
        self.original_client_reader_read: Callable[..., Any] | None = None
        self.original_client_reader_readexactly: Callable[..., Any] | None = None
        self.original_client_reader_readuntil: Callable[..., Any] | None = None
        self.server_action_task: Task[None] | None = None

    def protocol_factory(self, original_protocol: Any) -> InterceptorProtocol:
        """Create an interceptor protocol wrapping the original protocol.

        Args:
            original_protocol: The original protocol to wrap

        Returns:
            InterceptorProtocol instance

        """
        return InterceptorProtocol(self, original_protocol)

    def register_client_streams(
        self,
        client_reader: "StreamReader",
        client_writer: "StreamWriter",
    ) -> None:
        """Register client streams and set up monitoring/patching.

        Args:
            client_reader: The client's StreamReader
            client_writer: The client's StreamWriter

        """
        if self.client_reader is not None:
            return

        self.client_reader = client_reader
        self.client_writer = client_writer

        self.original_client_writer_close = self.client_writer.close
        self.mocker.patch.object(self.client_writer, "close", self.client_writer_close)

        self.original_client_writer_wait_closed = self.client_writer.wait_closed
        self.mocker.patch.object(
            self.client_writer,
            "wait_closed",
            self.client_writer_wait_closed,
        )

        self.original_client_reader_read = self.client_reader.read
        self.mocker.patch.object(self.client_reader, "read", self.client_read)

        # No need to patch `readline` because it is implemented with `readuntil`
        # self.original_client_reader_readline = self.client_reader.readline
        # self.mocker.patch.object(self.client_reader, "readline", self.client_readline)

        self.original_client_reader_readexactly = self.client_reader.readexactly
        self.mocker.patch.object(
            self.client_reader,
            "readexactly",
            self.client_readexactly,
        )

        self.original_client_reader_readuntil = self.client_reader.readuntil
        self.mocker.patch.object(self.client_reader, "readuntil", self.client_readuntil)

    async def client_read(self, *args: Any, **kwargs: Any) -> bytes:
        """Intercept client read method and track data read.

        Args:
            *args: Arguments passed to original read method
            **kwargs: Keyword arguments passed to original read method

        Returns:
            Data read from the stream

        """
        if self.original_client_reader_read is None:
            raise RuntimeError("Original client reader read method is not available")
        data = await self.original_client_reader_read(*args, **kwargs)
        self.data_read_by_client += data
        return data

    # async def client_readline(self, *args, **kwargs):
    #     data = await self.original_client_reader_readline(*args, **kwargs)
    #     self.data_read_by_client += data
    #     return data

    async def client_readexactly(self, *args: Any, **kwargs: Any) -> bytes:
        """Intercept client readexactly method and track data read.

        Args:
            *args: Arguments passed to original readexactly method
            **kwargs: Keyword arguments passed to original readexactly method

        Returns:
            Data read from the stream

        """
        try:
            data = await self.original_client_reader_readexactly(*args, **kwargs)
            self.data_read_by_client += data
            return data
        except asyncio.IncompleteReadError as e:
            # Have to record the bytes we did read so that we don't wrongly accuse client
            # of not reading them.
            self.data_read_by_client += e.partial
            raise

    async def client_readuntil(self, *args: Any, **kwargs: Any) -> bytes:
        """Intercept client readuntil method and track data read.

        Args:
            *args: Arguments passed to original readuntil method
            **kwargs: Keyword arguments passed to original readuntil method

        Returns:
            Data read from the stream

        """
        if self.original_client_reader_readuntil is None:
            raise RuntimeError(
                "Original client reader readuntil method is not available",
            )
        data = await self.original_client_reader_readuntil(*args, **kwargs)
        self.data_read_by_client += data
        return data

    def client_writer_close(self) -> None:
        """Intercept client writer close method and set event flag."""
        self.client_called_writer_close.set()
        self.original_client_writer_close()

    async def client_writer_wait_closed(self) -> None:
        """Intercept client writer wait_closed method and set event flag."""
        self.client_called_writer_waited_closed.set()
        await self.original_client_writer_wait_closed()

    async def start(self) -> None:
        """Start the mock TCP server and begin accepting connections."""
        self.evaluator_task = asyncio.create_task(self.evaluate_expectations())
        self.server_action_task = asyncio.create_task(self.execute_server_actions())

        # I thought it would be neater to have `ExpectConnect.server_action`
        # method call `start_accepting_connections` but then there's a race
        # between the server starting to accept connections and the test client
        # actually making the connection. If the client wins, there's no server
        # waiting on the port and connection attempt fails. I tried it and the client
        # usually wins.
        #
        # In fact, there is no guarantee that the client will call
        # `expect_connect` _before_ actually attempting the connection. It may
        # try the connection and then call `expect_connect`. We want that to
        # work. So we have to guarantee that the server is already accepting
        # connections by the time the test is invoked with the `tcpserver`
        # fixture.
        await self.start_accepting_connections()

    async def start_accepting_connections(self) -> None:
        """Start accepting client connections on the configured port."""

        def handle_client_connection(
            reader: "StreamReader",
            writer: "StreamWriter",
        ) -> None:
            self.logger.debug("client connection established")
            if self.connected:
                self.server_event_queue.put_nowait(SecondClientConnectionAttempted())
                return
            self.connected = True
            self.reader = reader

            self.writer = writer

            # Capture all data sent from the server by patching `write` method of
            # the writer
            self.original_writer_write = self.writer.write
            self.mocker.patch.object(self.writer, "write", self.intercept_sent_data)

            self.server_event_queue.put_nowait(ClientConnectedEvent())

        self.server = await asyncio.start_server(
            handle_client_connection,
            port=self.service_port,
            start_serving=True,
        )

    def intercept_sent_data(self, data: bytes) -> None:
        """Intercept data sent from server to client for tracking.

        Args:
            data: The data being sent

        """
        self.data_sent_from_server += data
        self.original_writer_write(data)

    async def evaluate_expectations(self) -> None:
        """Continuously evaluate expectations from the queue."""
        try:
            while True:
                # If there are already errors, there's no point evaluating the expectation.
                # However, we do still have to call `task_done` on the queue to
                # signal that the expectation has been processed.

                expectation = await self.expecations_queue.get()
                self.logger.debug("evaluating expectation: %s", expectation)
                if not self.errors:
                    # Asynchronously, we want to generate the server event that corresponds to
                    # this expectation. We have to do it asynchronously because there may already
                    # be other actions from previous expectations. If everything goes well, the
                    # call to `evaluate` will match up with the event generated by the server
                    # action.
                    self.server_actions.put_nowait(expectation.server_action)
                    try:
                        await expectation.evaluate()
                    except Exception as e:  # noqa: BLE001
                        self.error(e)
                self.expecations_queue.task_done()
        except asyncio.CancelledError:
            # Handle cancellation gracefully
            self.logger.debug("evaluate_expectations task cancelled")
            raise

    async def execute_server_actions(self) -> None:
        """Continuously execute server actions from the queue."""
        try:
            while True:
                server_action = await self.server_actions.get()
                self.logger.debug("performing server action: %s", server_action)
                if self.errors:
                    # Just drop the server action. It's irrelevant now
                    continue
                try:
                    server_event = await server_action()
                except Exception as e:  # noqa: BLE001
                    server_event = ExceptionEvent(e)
                if server_event is not None:
                    self.server_event_queue.put_nowait(server_event)
        except asyncio.CancelledError:
            # Handle cancellation gracefully
            self.logger.debug("execute_server_actions task cancelled")
            raise

    def error(self, exception: Exception) -> None:
        """Record an error that occurred during server operation.

        Args:
            exception: The exception that occurred

        """
        self.errors.append(exception)

    async def stop(self) -> None:  # noqa: C901, PLR0912
        """Stop the mock TCP server and clean up resources."""
        __tracebackhide__ = True
        try:
            # Only try to join if we haven't already failed and stopped
            if not self.join_already_failed and not self.stopped:
                await self.join()
        except Exception as e:
            self.logger.debug("Error during join: %s", e)
        finally:
            self.stopped = True

            # Cancel all tasks aggressively
            tasks_to_cancel = []
            if self.evaluator_task is not None:
                tasks_to_cancel.append(self.evaluator_task)
            if (
                hasattr(self, "server_action_task")
                and self.server_action_task is not None
            ):
                tasks_to_cancel.append(self.server_action_task)

            # Cancel all tasks
            for task in tasks_to_cancel:
                if not task.done():
                    task.cancel()

            # Wait for cancellation with timeout
            if tasks_to_cancel:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks_to_cancel, return_exceptions=True),
                        timeout=0.1,  # Short timeout to avoid hanging
                    )
                except TimeoutError:
                    self.logger.debug("Task cancellation timed out")
                except Exception as e:  # noqa: BLE001
                    self.logger.debug("Error during task cancellation: %s", e)

            # Close server
            if self.server is not None:
                try:
                    self.server.close()
                    await asyncio.wait_for(self.server.wait_closed(), timeout=0.1)
                except TimeoutError:
                    self.logger.debug("Server close timed out")
                except Exception as e:  # noqa: BLE001
                    self.logger.debug("Error closing server: %s", e)

    async def join(self) -> None:
        """Wait for all expectations to be processed and check for errors."""
        __tracebackhide__ = True

        if self.join_already_failed:
            return

        # Wait for all expectations to be completed, which includes failure
        await self.expecations_queue.join()

        if self.errors:
            self.join_already_failed = True
            pytest.fail(interpret_error(self.errors[0]))

    def check_not_stopped(self) -> None:
        """Check if the server has been stopped and raise exception if so."""
        if self.stopped:  # pragma: no cover
            raise Exception("Fixture is stopped")

    def expect_connect(self, timeout: float = 1) -> None:
        """Add expectation that a client will connect.

        Args:
            timeout: Timeout in seconds for the connection

        """
        self.check_not_stopped()
        self.expecations_queue.put_nowait(ExpectConnect(self, timeout=timeout))

    def expect_bytes(self, expected_bytes: bytes, timeout: float = 1) -> None:
        """Add expectation that client will send specific bytes.

        Args:
            expected_bytes: The bytes expected from client
            timeout: Timeout in seconds

        """
        self.check_not_stopped()
        self.expecations_queue.put_nowait(
            ExpectBytes(
                self,
                expected_bytes=expected_bytes,
                timeout=timeout,
            ),
        )

    def send_bytes(self, data: bytes) -> None:
        """Add action to send bytes from server to client.

        Args:
            data: The bytes to send

        """
        self.check_not_stopped()
        self.expecations_queue.put_nowait(SendBytes(self, data))

    def expect_frame(self, expected_payload: bytes, timeout: float = 1) -> None:
        """Add expectation that client will send a specific frame.

        Args:
            expected_payload: The frame payload expected from client
            timeout: Timeout in seconds

        """
        self.check_not_stopped()
        self.expecations_queue.put_nowait(
            ExpectFrame(
                self,
                expected_payload=expected_payload,
                timeout=timeout,
            ),
        )

    def send_frame(self, payload: bytes) -> None:
        """Add action to send a frame from server to client.

        Args:
            payload: The frame payload to send

        """
        self.check_not_stopped()
        self.expecations_queue.put_nowait(SendFrame(self, payload))

    def expect_disconnect(self, timeout: float = 1) -> None:
        """Add expectation that client will disconnect properly.

        Args:
            timeout: Timeout in seconds

        """
        self.check_not_stopped()
        self.expecations_queue.put_nowait(ExpectIsConnected(self))
        self.expecations_queue.put_nowait(ExpectClientCalledWriterClose(self, timeout))
        self.expecations_queue.put_nowait(
            ExpectClientCalledWriterWaitClosed(self, timeout),
        )
        self.expecations_queue.put_nowait(ExpectReadZeroBytes(self, timeout))
        self.expecations_queue.put_nowait(ExpectClientReadAllSentBytes(self, timeout))

    def disconnect(self) -> None:
        """Add action to disconnect server from client."""
        self.check_not_stopped()
        self.expecations_queue.put_nowait(Disconnect(self))


class MockTcpServerFactory:
    """Factory for creating mock TCP servers with connection interception."""

    def __init__(
        self,
        unused_tcp_port_factory: Callable[[], int],
        mocker: "MockerFixture",
    ) -> None:
        """Initialize the factory.

        Args:
            unused_tcp_port_factory: Function to get unused TCP ports
            mocker: Pytest mocker fixture

        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.unused_tcp_port_factory = unused_tcp_port_factory
        self.mocker = mocker
        self.servers: dict[int, MockTcpServer] = {}
        self.original_open_connection = asyncio.open_connection
        self.mocker.patch(
            "asyncio.open_connection",
            self.intercept_open_connection,
        )
        self.orignal_create_connection = asyncio.get_event_loop().create_connection
        self.mocker.patch.object(
            asyncio.get_event_loop(),
            "create_connection",
            self.intercept_create_connection,
        )

    async def __call__(self) -> MockTcpServer:
        """Create and start a new mock TCP server.

        Returns:
            A started MockTcpServer instance

        """
        server = MockTcpServer(self.unused_tcp_port_factory(), self.mocker)
        await server.start()
        self.servers[server.service_port] = server
        return server

    async def intercept_open_connection(
        self,
        host: str,
        port: int,
    ) -> tuple["StreamReader", "StreamWriter"]:
        """Intercept asyncio.open_connection calls to mock servers.

        Args:
            host: Host to connect to
            port: Port to connect to

        Returns:
            Tuple of StreamReader and StreamWriter

        """
        client_reader, client_writer = await self.original_open_connection(host, port)
        server = self.servers[port]
        server.register_client_streams(client_reader, client_writer)
        return client_reader, client_writer

    async def intercept_create_connection(
        self,
        protocol_factory: Callable[[], Any],
        host: str,
        port: int,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Intercept asyncio.create_connection calls to mock servers.

        Args:
            protocol_factory: Factory function for creating protocols
            host: Host to connect to
            port: Port to connect to
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments

        Returns:
            Connection result

        """
        server = self.servers[port]

        def factory() -> Any:
            return server.protocol_factory(protocol_factory())

        return await self.orignal_create_connection(
            factory,
            host,
            port,
            *args,
            **kwargs,
        )

    async def stop(self) -> None:
        """Stop all created servers."""
        __tracebackhide__ = True
        errors: list[BaseException] = []
        for server in self.servers.values():
            try:
                # Don't add expect_disconnect if the server already failed
                # This prevents adding more expectations that might hang during cleanup
                if not server.join_already_failed and not server.stopped:
                    server.expect_disconnect()
                await server.stop()
            except BaseException as e:
                # `pytest.fail` raises `_pytest.outcomes.OutcomeException` which
                # is a subclass of `BaseException`. `OutcomeException` is not public
                # so we can rely on it's existence.
                errors.append(e)
        if errors:
            raise errors[0]


@pytest_asyncio.fixture(loop_scope="function", scope="function")
async def tcpserver_factory(
    unused_tcp_port_factory: Callable[[], int],
    mocker: "MockerFixture",
) -> AsyncGenerator[MockTcpServerFactory, None]:
    """Pytest fixture providing a MockTcpServerFactory.

    Args:
        unused_tcp_port_factory: Function to get unused TCP ports
        mocker: Pytest mocker fixture

    Yields:
        MockTcpServerFactory instance

    """
    factory = MockTcpServerFactory(unused_tcp_port_factory, mocker)
    yield factory
    await factory.stop()


@pytest_asyncio.fixture(loop_scope="function", scope="function")
async def tcpserver(tcpserver_factory: MockTcpServerFactory) -> MockTcpServer:
    """Pytest fixture providing a single MockTcpServer.

    Args:
        tcpserver_factory: Factory for creating mock servers

    Returns:
        MockTcpServer instance

    """
    return await tcpserver_factory()
