"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
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

Encapsulates integration with the Graph database database
"""

import asyncio
import logging
import typing

from neo4j import READ_ACCESS, WRITE_ACCESS, AsyncDriver, AsyncGraphDatabase, Record
from neo4j.exceptions import Neo4jError

from uns_graphql.graphql_config import GraphDBConfig

LOGGER = logging.getLogger(__name__)

MAX_RETRIES = 5
SLEEP_BTW_ATTEMPT = 10


class GraphDB:
    """
    Encapsulates the connection and queries to the graph database.
    Provides methods to get and release the Neo4j async driver.
    """

    # Class variable to hold the shared driver for the graph DB
    _graphdb_driver: AsyncDriver = None

    @classmethod
    async def get_graphdb_driver(cls, retry: int = 0) -> AsyncDriver:
        """
        Returns the Neo4j async driver which is the connection to the database.

        Validates if the current driver is still connected, and if not, creates a new connection.
        The driver is cached and reused for subsequent requests to avoid creating multiple connections.
        Parameters
        ----------
        retry: int
            Optional parameters to retry making a connection in case of errors.
            The max number of retry is `MAX_RETRIES`
            The time between attempts is  `SLEEP_BTW_ATTEMPT` seconds

        Returns:
            AsyncDriver: The Neo4j async driver.
        """
        LOGGER.debug("GraphDB driver requested")
        try:
            if cls._graphdb_driver is None:
                LOGGER.info("Creating a new GraphDB driver")
                cls._graphdb_driver = AsyncGraphDatabase.driver(
                    uri=GraphDBConfig.conn_url,
                    auth=(GraphDBConfig.user, GraphDBConfig.password),
                    database=GraphDBConfig.database,
                )

            await cls._graphdb_driver.verify_connectivity()
            LOGGER.debug("GraphDB driver connectivity verified")
        except Neo4jError as ex:
            LOGGER.error("Failed to verify GraphDB driver connectivity: %s",
                         ex, stack_info=True, exc_info=True)
            # In case of connectivity failure, close the existing driver and create a new one
            await cls.release_graphdb_driver()
            if retry >= MAX_RETRIES:
                LOGGER.error("No. of retries exceeded %s",
                             MAX_RETRIES, stack_info=True, exc_info=True)
                raise ex  # Re-raise the exception after cleanup

            await asyncio.sleep(SLEEP_BTW_ATTEMPT)
            cls._graphdb_driver = await cls.get_graphdb_driver(retry + 1)
            LOGGER.info("Trying to Reconnect to GraphDB driver")

        return cls._graphdb_driver

    @classmethod
    async def release_graphdb_driver(cls):
        """
        Closes the Neo4j async driver and releases the connection.
        Ensures that any exceptions during the close process are logged.
        """
        if cls._graphdb_driver is not None:
            LOGGER.debug("Releasing GraphDB driver")
            try:
                # Add a 10-second timeout to prevent infinite hangs during teardown
                await asyncio.wait_for(cls._graphdb_driver.close(), timeout=10.0)
                LOGGER.info("GraphDB driver closed successfully")
            except (TimeoutError, Neo4jError) as ex:
                LOGGER.error(
                    "Error/Timeout closing the GraphDB driver: %s", ex)
            finally:
                cls._graphdb_driver = None
        else:
            LOGGER.warning("Trying to close an already closed driver")

    async def execute_read_query(self, query: str, *args, **kwargs) -> typing.AsyncGenerator[Record]:
        """
        Executes a (CQL) query with the provided positional and keyword parameters.

        Args:
            query (str): The CQL query to execute. Using the auto commit feature for transaction
            *args: Positional parameters for the CQL query.
            **kwargs: Keyword parameters for the CQL query.

        Returns:
            typing.AsyncGenerator[Record]: The results of the query.
        """

        LOGGER.debug(
            "Executing query: %s with args: %s and kwargs: %s", query, args, kwargs)
        driver = await self.get_graphdb_driver()

        async with driver.session(default_access_mode=READ_ACCESS) as session:
            try:
                result = await session.run(query, *args, **kwargs)
                async for record in result:
                    yield record

                LOGGER.debug("Query executed successfully")
            except Exception as ex:
                LOGGER.error("Error executing query: %s", ex,
                             stack_info=True, exc_info=True)
                raise


# ISA-95 nodes are one segment each (`node_name`), chained by PARENT_OF.
# Nested attribute nodes are skipped so a payload dict cannot collide with a site.
_NESTED_ATTRIBUTE_LABEL = GraphDBConfig.nested_attribute_node_type
_REWRITE_GRAPH_PREFIX_CYPHER = f"""
MATCH (root {{node_name: $segments[0]}})
WHERE NOT ()-[:PARENT_OF]->(root)
  AND NOT root:{_NESTED_ATTRIBUTE_LABEL}
MATCH path = (root)-[:PARENT_OF*0..10]->(target)
WHERE length(path) = size($segments) - 1
  AND [n IN nodes(path) | n.node_name] = $segments
  AND NONE(n IN nodes(path) WHERE n:{_NESTED_ATTRIBUTE_LABEL})
WITH DISTINCT target
OPTIONAL MATCH (parent)-[:PARENT_OF]->(target)
OPTIONAL MATCH (parent)-[:PARENT_OF]->(child_sibling {{node_name: $new_segment}})
WHERE parent IS NOT NULL
  AND child_sibling <> target
  AND NOT child_sibling:{_NESTED_ATTRIBUTE_LABEL}
OPTIONAL MATCH (root_sibling {{node_name: $new_segment}})
WHERE parent IS NULL
  AND root_sibling <> target
  AND NOT ()-[:PARENT_OF]->(root_sibling)
  AND NOT root_sibling:{_NESTED_ATTRIBUTE_LABEL}
WITH target, coalesce(child_sibling, root_sibling) AS sibling
FOREACH (_ IN CASE WHEN sibling IS NULL THEN [1] ELSE [] END |
  SET target.node_name = $new_segment
)
RETURN CASE WHEN sibling IS NOT NULL THEN 'collision' ELSE 'renamed' END AS status
"""


async def rewrite_graph_prefix(old_prefix: str, new_prefix: str) -> int:
    """Rename the ISA-95 node at the last segment of old_prefix to the last
    segment of new_prefix, under the same parent path. Returns 1 if renamed, 0 if
    the old node was absent. Raises ValueError if a sibling already has the new name."""
    if old_prefix == new_prefix:
        raise ValueError("old_prefix and new_prefix must differ")

    old_segments = old_prefix.split("/")
    new_segments = new_prefix.split("/")
    if old_segments[:-1] != new_segments[:-1]:
        raise ValueError("old_prefix and new_prefix must share the same parent path")

    new_segment = new_segments[-1]
    LOGGER.debug("Rewriting graph prefix %s -> %s", old_prefix, new_prefix)

    driver = await GraphDB.get_graphdb_driver()

    async def _rename(tx) -> Record | None:
        result = await tx.run(
            _REWRITE_GRAPH_PREFIX_CYPHER,
            segments=old_segments,
            new_segment=new_segment,
        )
        record = await result.single()
        if record is not None and record["status"] == "collision":
            # Raise inside the tx so a SET (if any) is rolled back.
            raise ValueError(f"a sibling already has the name {new_segment!r}")
        return record

    async with driver.session(default_access_mode=WRITE_ACCESS) as session:
        record = await session.execute_write(_rename)

    if record is None:
        return 0
    if record["status"] == "renamed":
        return 1
    raise RuntimeError(f"unexpected graph rewrite status: {record['status']}")

