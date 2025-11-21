"""Frame-based protocol utilities for TCP communication."""

import asyncio
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asyncio import StreamReader, StreamWriter


def write_frame(writer: "StreamWriter", payload: bytes) -> None:
    """Write a frame with length prefix to the stream.

    Args:
        writer: The StreamWriter to write to
        payload: The payload bytes to send

    """
    writer.write(struct.pack(">I", len(payload)))
    writer.write(payload)


async def read_frame(reader: "StreamReader") -> bytes:
    """Read a frame and return the payload.

    If the connection was closed cleanly, meaning that there is no partial message,
    an empty byte array is returned.

    Args:
        reader: The StreamReader to read from

    Returns:
        The frame payload bytes, or empty bytes if connection closed cleanly

    """
    try:
        header_bytes = await reader.readexactly(4)
    except asyncio.IncompleteReadError as e:
        if len(e.partial) == 0:
            return b""
        raise
    (message_length,) = struct.unpack(">I", header_bytes)
    return await reader.readexactly(message_length)
