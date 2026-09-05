"""Browse, discover, and read helpers for anonymous OPC UA sessions."""

import datetime
import time
from collections.abc import Sequence
from dataclasses import dataclass

from asyncua import Client, ua

from uns_opcua.payload import quality_from_code
from uns_opcua.session import open_client


@dataclass(frozen=True, slots=True)
class BrowseNode:
    node_id: str
    browse_name: str
    display_name: str
    browse_path: str
    node_class: str
    has_children: bool


@dataclass(frozen=True, slots=True)
class DataValueRow:
    node_id: str
    display_name: str
    browse_path: str
    value: object
    data_type: str | None
    source_timestamp: datetime.datetime | None
    server_timestamp: datetime.datetime | None
    status: str


# OpcPlc and other .NET servers accept None/Anonymous, then refuse Value or
# Browse on a subset of nodes (diagnostics, certificates). One of those must
# not abort discovery of the plant tags.
_SKIPPABLE_STATUS_CODES = frozenset(
    {
        ua.StatusCodes.BadSecurityModeInsufficient,
        ua.StatusCodes.BadUserAccessDenied,
        ua.StatusCodes.BadNotReadable,
        ua.StatusCodes.BadAttributeIdInvalid,
        ua.StatusCodes.BadWaitingForInitialData,
    }
)


def _is_skippable(exc: BaseException) -> bool:
    code = getattr(exc, "code", None)
    return code in _SKIPPABLE_STATUS_CODES


async def _children_or_empty(node) -> list:
    try:
        return await node.get_children()
    except ua.UaError as exc:
        if _is_skippable(exc):
            return []
        raise


async def _node_has_children(node: ua.Node) -> bool:
    return bool(await _children_or_empty(node))


async def _browse_node(node, browse_path: str) -> BrowseNode:
    browse_name = await node.read_browse_name()
    display_name = await node.read_display_name()
    node_class = await node.read_node_class()
    return BrowseNode(
        node_id=node.nodeid.to_string(),
        browse_name=browse_name.Name,
        display_name=display_name.Text,
        browse_path=browse_path,
        node_class=node_class.name,
        has_children=await _node_has_children(node),
    )


async def browse_children(client: Client, node_id: str | None) -> list[BrowseNode]:
    """Return direct children of `node_id`, or of Objects when `node_id` is None."""
    parent = client.nodes.objects if node_id is None else client.get_node(node_id)
    parent_path = "" if node_id is None else (await _node_browse_path(parent))
    rows: list[BrowseNode] = []
    for child in await _children_or_empty(parent):
        try:
            browse_name = await child.read_browse_name()
            segment = browse_name.Name
            path = segment if not parent_path else f"{parent_path}/{segment}"
            rows.append(await _browse_node(child, path))
        except ua.UaError as exc:
            if _is_skippable(exc):
                continue
            raise
    return rows


def unique_by_node_id(rows: Sequence[BrowseNode]) -> list[BrowseNode]:
    """Keep the first browse path for each NodeId.

    OPC UA inverse references walk the same Variable twice; React keys and
    Subscribe must see one row per node.
    """
    seen: set[str] = set()
    unique: list[BrowseNode] = []
    for row in rows:
        if row.node_id in seen:
            continue
        seen.add(row.node_id)
        unique.append(row)
    return unique


async def discover_variables(client: Client, node_id: str | None = None) -> list[BrowseNode]:
    """Recursively collect Variable nodes under `node_id`, or under Objects."""
    rows: list[BrowseNode] = []
    if node_id is None:
        start = client.nodes.objects
        path_parts: list[str] = []
    else:
        start = client.get_node(node_id)
        prefix = await _node_browse_path(start)
        path_parts = [part for part in prefix.split("/") if part]
        if await start.read_node_class() == ua.NodeClass.Variable:
            path = "/".join(path_parts) or (await start.read_browse_name()).Name
            return unique_by_node_id([await _browse_node(start, path)])
    await _collect_variables(start, path_parts, rows)
    return unique_by_node_id(rows)


async def _collect_variables(node: ua.Node, path_parts: list[str], rows: list[BrowseNode]) -> None:
    for child in await _children_or_empty(node):
        try:
            browse_name = await child.read_browse_name()
            segment = browse_name.Name
            path = segment if not path_parts else "/".join([*path_parts, segment])
            node_class = await child.read_node_class()
            if node_class == ua.NodeClass.Variable:
                rows.append(await _browse_node(child, path))
            else:
                await _collect_variables(child, [*path_parts, segment], rows)
        except ua.UaError as exc:
            if _is_skippable(exc):
                continue
            raise


async def read_nodes(client: Client, node_ids: Sequence[str]) -> list[DataValueRow]:
    """Read current values for the given node ids."""
    rows: list[DataValueRow] = []
    for node_id in node_ids:
        node = client.get_node(node_id)
        try:
            data_value = await node.read_data_value()
            display_name = await node.read_display_name()
            browse_path = await _node_browse_path(node)
            data_type = await _node_data_type(node)
            value = data_value.Value.Value if data_value.Value is not None else None
            rows.append(
                DataValueRow(
                    node_id=node.nodeid.to_string(),
                    display_name=display_name.Text,
                    browse_path=browse_path,
                    value=value,
                    data_type=data_type,
                    source_timestamp=data_value.SourceTimestamp,
                    server_timestamp=data_value.ServerTimestamp,
                    status=quality_from_code(int(data_value.StatusCode.value)),
                )
            )
        except ua.UaError as exc:
            if not _is_skippable(exc):
                raise
            rows.append(
                DataValueRow(
                    node_id=node_id,
                    display_name="",
                    browse_path="",
                    value=None,
                    data_type=None,
                    source_timestamp=None,
                    server_timestamp=None,
                    status="Bad",
                )
            )
    return rows


async def test_connection(url: str) -> tuple[bool, str | None, float]:
    """Try to open a session and read the server node; return ok, error, elapsed_ms."""
    started = time.perf_counter()
    try:
        async with await open_client(url) as client:
            # get_server_node() is a Node, not a coroutine. Read it so Test
            # actually talks to the server instead of awaiting the Node object.
            await client.get_server_node().read_browse_name()
    except Exception as exc:  # noqa: BLE001 - callers need the message for UI feedback
        elapsed_ms = (time.perf_counter() - started) * 1000
        return False, str(exc), elapsed_ms
    elapsed_ms = (time.perf_counter() - started) * 1000
    return True, None, elapsed_ms


async def _node_browse_path(node: ua.Node) -> str:
    try:
        path_parts = await node.get_path(as_string=True)
    except ua.UaError:
        browse_name = await node.read_browse_name()
        return browse_name.Name
    if not path_parts:
        browse_name = await node.read_browse_name()
        return browse_name.Name
    segments = [
        part.split(":", 1)[-1]
        for part in path_parts
        if part.split(":", 1)[-1] not in _ROOT_BROWSE_NAMES
    ]
    if not segments:
        browse_name = await node.read_browse_name()
        return browse_name.Name
    return "/".join(segments)


async def _node_data_type(node: ua.Node) -> str | None:
    try:
        variant_type = await node.read_data_type_as_variant_type()
    except ua.UaError:
        return None
    return variant_type.name


test_connection.__test__ = False

_ROOT_BROWSE_NAMES = frozenset({"Root", "Objects"})
