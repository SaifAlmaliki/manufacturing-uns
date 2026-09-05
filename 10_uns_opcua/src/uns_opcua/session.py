"""Anonymous OPC UA client sessions for browse and read helpers."""

from asyncua import Client


async def open_client(url: str) -> Client:
    """Return an anonymous client; the caller owns the session via `async with`."""
    return Client(url=url)
