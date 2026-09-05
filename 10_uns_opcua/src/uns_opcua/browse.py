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


async def _node_has_children(node: ua.Node) -> bool:
    return bool(await node.get_children())


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
    for child in await parent.get_children():
        browse_name = await child.read_browse_name()
        segment = browse_name.Name
        path = segment if not parent_path else f"{parent_path}/{segment}"
        rows.append(await _browse_node(child, path))
    return rows


async def discover_variables(client: Client) -> list[BrowseNode]:
    """Recursively collect Variable nodes under Objects."""
    rows: list[BrowseNode] = []
    await _collect_variables(client.nodes.objects, [], rows)
    return rows


async def _collect_variables(node: ua.Node, path_parts: list[str], rows: list[BrowseNode]) -> None:
    for child in await node.get_children():
        browse_name = await child.read_browse_name()
        segment = browse_name.Name
        path = segment if not path_parts else "/".join([*path_parts, segment])
        node_class = await child.read_node_class()
        if node_class == ua.NodeClass.Variable:
            rows.append(await _browse_node(child, path))
        else:
            await _collect_variables(child, [*path_parts, segment], rows)


async def read_nodes(client: Client, node_ids: Sequence[str]) -> list[DataValueRow]:
    """Read current values for the given node ids."""
    rows: list[DataValueRow] = []
    for node_id in node_ids:
        node = client.get_node(node_id)
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
    return rows


async def test_connection(url: str) -> tuple[bool, str | None, float]:
    """Try to open a session and read the server node; return ok, error, elapsed_ms."""
    started = time.perf_counter()
    try:
        async with await open_client(url) as client:
            await client.get_server_node()
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
    return "/".join(part.split(":", 1)[-1] for part in path_parts)


async def _node_data_type(node: ua.Node) -> str | None:
    try:
        variant_type = await node.read_data_type_as_variant_type()
    except ua.UaError:
        return None
    return variant_type.name


test_connection.__test__ = False
