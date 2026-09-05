"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and is distributed "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Connectivity catalog: OPC-UA servers and the tags the console subscribes to.

`merge_discovered` is the one decision worth a unit test: when an engineer has
edited an `mqtt_topic`, a re-discovery must not overwrite it. The repository
around it is exercised by the integration tests in `test_integration.py`,
which need a migrated Postgres database.
"""

from __future__ import annotations

from uns_model.connectivity import ConnectivityTagSpec, merge_discovered


def test_merge_keeps_edited_topic():
    existing = [ConnectivityTagSpec("ns=3;s=WTP_T101_Level", "RawWater/T101/Level", "Level", "Plant/T101/Level", True)]
    discovered = [ConnectivityTagSpec("ns=3;s=WTP_T101_Level", "RawWater/T101/Level", "Level", "RawWater/T101/Level", True)]
    merged = merge_discovered(existing, discovered)
    assert merged[0].mqtt_topic == "Plant/T101/Level"


def test_merge_adds_newly_discovered_nodes():
    existing = [ConnectivityTagSpec("ns=3;s=A", "Path/A", "A", "Plant/A", True)]
    discovered = [
        ConnectivityTagSpec("ns=3;s=A", "Path/A", "A", "Plant/A", True),
        ConnectivityTagSpec("ns=3;s=B", "Path/B", "B", "Plant/B", True),
    ]
    merged = merge_discovered(existing, discovered)
    by_node = {tag.node_id: tag for tag in merged}
    assert set(by_node) == {"ns=3;s=A", "ns=3;s=B"}
    assert by_node["ns=3;s=A"].mqtt_topic == "Plant/A"
    assert by_node["ns=3;s=B"].mqtt_topic == "Plant/B"


def test_merge_does_not_unsubscribe_missing_nodes():
    """A node absent from a later discovery stays subscribed until `unsubscribe_tag`."""
    existing = [ConnectivityTagSpec("ns=3;s=A", "Path/A", "A", "Plant/A", True)]
    discovered: list[ConnectivityTagSpec] = []
    merged = merge_discovered(existing, discovered)
    assert merged[0].subscribed is True
    assert merged[0].mqtt_topic == "Plant/A"


def test_merge_updates_display_and_browse_path_for_existing_nodes():
    """Discovery may correct a browse path or display name without touching the topic."""
    existing = [ConnectivityTagSpec("ns=3;s=A", "Path/A", "A", "Plant/A", True)]
    discovered = [ConnectivityTagSpec("ns=3;s=A", "Path/A/Renamed", "Tank Level", "Plant/A", True)]
    merged = merge_discovered(existing, discovered)
    assert merged[0].browse_path == "Path/A/Renamed"
    assert merged[0].display_name == "Tank Level"
    assert merged[0].mqtt_topic == "Plant/A"
