# Graph Report - 07_uns_graphql  (2026-09-12)

## Corpus Check
- 134 files · ~68,445 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1883 nodes · 4490 edges · 106 communities (91 shown, 15 thin omitted)
- Extraction: 66% EXTRACTED · 34% INFERRED · 0% AMBIGUOUS · INFERRED: 1544 edges (avg confidence: 0.55)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ecf77788`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 83|Community 83]]
- [[_COMMUNITY_Community 84|Community 84]]
- [[_COMMUNITY_Community 85|Community 85]]
- [[_COMMUNITY_Community 86|Community 86]]
- [[_COMMUNITY_Community 87|Community 87]]
- [[_COMMUNITY_Community 88|Community 88]]
- [[_COMMUNITY_Community 89|Community 89]]

## God Nodes (most connected - your core abstractions)
1. `EdgeManagementService` - 65 edges
2. `HistorianRepository` - 60 edges
3. `EdgeServiceError` - 60 edges
4. `AccessScope` - 59 edges
5. `EdgeJobService` - 58 edges
6. `VerifiedEdgeIdentity` - 45 edges
7. `EdgeCertificateIssuer` - 42 edges
8. `BytesPayload` - 42 edges
9. `JSONPayload` - 41 edges
10. `require()` - 40 edges

## Surprising Connections (you probably didn't know these)
- `test_envelope_to_dispatched_skips_malformed_payload()` --calls--> `envelope_to_dispatched()`  [INFERRED]
  test/backend/test_event_stream.py → src/uns_graphql/backend/event_stream.py
- `authority()` --calls--> `generate_authority()`  [INFERRED]
  test/edge_api/conftest.py → src/uns_graphql/edge_api/issuer.py
- `AlertRuleInput` --uses--> `AlertRuleInput`  [INFERRED]
  test/input/test_alert_rule.py → src/uns_graphql/input/alert_rule.py
- `test_cloud_context_attaches_secret_store()` --calls--> `_cloud_context()`  [INFERRED]
  test/mutations/test_edge_configuration.py → src/uns_graphql/mutations/connectivity.py
- `MonkeyPatch` --uses--> `UNSGraphql`  [INFERRED]
  test/mutations/test_hierarchy.py → src/uns_graphql/uns_graphql_app.py

## Import Cycles
- 1-file cycle: `src/uns_graphql/backend/historian.py -> src/uns_graphql/backend/historian.py`
- 1-file cycle: `src/uns_graphql/edge_api/enrollment.py -> src/uns_graphql/edge_api/enrollment.py`
- 1-file cycle: `src/uns_graphql/edge_api/issuer.py -> src/uns_graphql/edge_api/issuer.py`
- 1-file cycle: `src/uns_graphql/edge_api/jobs.py -> src/uns_graphql/edge_api/jobs.py`
- 1-file cycle: `src/uns_graphql/edge_api/route_release.py -> src/uns_graphql/edge_api/route_release.py`
- 1-file cycle: `src/uns_graphql/edge_api/service.py -> src/uns_graphql/edge_api/service.py`
- 1-file cycle: `test/backend/test_historian.py -> test/backend/test_historian.py`
- 1-file cycle: `src/uns_graphql/queries/graph.py -> src/uns_graphql/queries/graph.py`
- 1-file cycle: `src/uns_graphql/uns_graphql_app.py -> src/uns_graphql/uns_graphql_app.py`
- 1-file cycle: `src/uns_graphql/mutations/hierarchy.py -> src/uns_graphql/mutations/hierarchy.py`
- 1-file cycle: `src/uns_graphql/publication_api/service.py -> src/uns_graphql/publication_api/service.py`
- 1-file cycle: `src/uns_graphql/queries/historian.py -> src/uns_graphql/queries/historian.py`
- 1-file cycle: `src/uns_graphql/type/streaming_event.py -> src/uns_graphql/type/streaming_event.py`
- 1-file cycle: `test/edge_api/conftest.py -> test/edge_api/conftest.py`
- 1-file cycle: `test/publication_api/conftest.py -> test/publication_api/conftest.py`
- 1-file cycle: `test/queries/test_historian.py -> test/queries/test_historian.py`
- 1-file cycle: `test/type/test_alert_rule.py -> test/type/test_alert_rule.py`
- 1-file cycle: `test/type/test_connectivity.py -> test/type/test_connectivity.py`
- 1-file cycle: `test/type/test_oee.py -> test/type/test_oee.py`

## Communities (106 total, 15 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (101): alias, BaseModel, edge_app(), active_certificate(), create_enrollment_attempt(), csr_digest(), EnrollmentError, EnrollmentRateLimiter (+93 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (80): The caller's identity when they may write one edge's connectivity catalog., The caller's identity, if their roles allow this mutation.      `KeyError` on, require(), require_edge_access(), HistorianRepository, *******************************************************************************, Historic events whose payload contains the given keys at any depth.          `, Run the assembled WHERE clause and map rows to the GraphQL type.          No S (+72 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (63): HierarchyArea, HierarchyLine, HierarchyMigrateJob, HierarchyQuery, HierarchySaveResult, HierarchySite, HierarchyTreeInput, HierarchyTreeType (+55 more)

### Community 3 - "Community 3"
Cohesion: 0.09
Nodes (62): DataSetValue, Parameter, PropertyValue, Row, SPBDataSet, SPBMetadata, SPBMetric, SPBPropertySet (+54 more)

### Community 4 - "Community 4"
Cohesion: 0.10
Nodes (59): authority(), _clean(), csrs(), database(), edge_service(), enroll_edge(), lease_headers(), open_session() (+51 more)

### Community 5 - "Community 5"
Cohesion: 0.05
Nodes (51): _browse_node(), _data_value(), Connectivity catalog writes and OPC UA probes through the schema.  The reposit, A successful TCP probe of a server still `pending` its first Edge apply keeps ED, Username/password belong in Postgres, not in the payload the console reads back., Saving an S7 server wires the repository's `after_flush` to the HiveMQ Edge XML, Discover every Variable on the endpoint and fold into the catalog via replace_su, OPC UA browse discovery has no meaning against an S7/EtherNet-IP catalog row. (+43 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (28): ActivationSnapshot, BrokerAdminClient, InMemoryRouteReleaseBackend, _json_document(), MapperControlClient, Route release staging, activation barrier, and worker lease fencing., Test and qualification harness backend without PostgreSQL., RouteReleaseRecord (+20 more)

### Community 7 - "Community 7"
Cohesion: 0.04
Nodes (47): *******************************************************************************, Nodes with different node_name should not be equal, Comparing with non-UNSNode object should return NotImplemented/False, A node should be equal to it, If a == b, then b == a, If a == b and b == c, then a == c, Equal nodes must have the same hash value, Different nodes should (likely) have different hash values (+39 more)

### Community 8 - "Community 8"
Cohesion: 0.08
Nodes (31): LeasedOutboxRecord, lims_http_route(), publication_config(), AiomqttPublicationClient, MQTT publisher used by the publication outbox worker., _immutable_metadata(), load_publication_api_config(), _parse_optional_occurred_at() (+23 more)

### Community 9 - "Community 9"
Cohesion: 0.07
Nodes (31): AuthenticatedGraphQLRouter, A router whose subscriptions need an identity too.      `on_ws_connect` runs a, ConnectivityMutation, ConnectivitySubscription, generate_authority(), EdgeMutation, GraphQLRouter, HierarchyMutation (+23 more)

### Community 10 - "Community 10"
Cohesion: 0.10
Nodes (31): historian(), historian_database(), prepare_database(), *******************************************************************************, The one engine this service uses, pointed at the configured historian.      On, Put the test rows in the hypertable, and take them out again afterwards., _cleanup(), _FakeConnection (+23 more)

### Community 11 - "Community 11"
Cohesion: 0.08
Nodes (34): publication_app(), publication_client(), publication_service(), publisher_headers(), Shared fixtures for publication API tests., publisher_identity_headers(), PublisherIdentityError, Trusted-proxy mTLS identity for business publishers. (+26 more)

### Community 12 - "Community 12"
Cohesion: 0.11
Nodes (28): DispatchedEvent, KAFKATopicInput, Info, KAFKATopicInput, StreamingMessage, datetime, KAFKASubscription, Subscription class providing methods for subscribing to live canonical events. (+20 more)

### Community 13 - "Community 13"
Cohesion: 0.10
Nodes (28): client(), Message, Info, MQTTMessage, MQTTTopicInput, MQTTSubscription, Subscription class providing methods for subscribing to MQTT messages., Subscribe to MQTT messages based on provided topics.          Args: (+20 more)

### Community 14 - "Community 14"
Cohesion: 0.11
Nodes (23): AsyncConnection, Rename the ISA-95 node at the last segment of old_prefix to the last     segmen, rewrite_graph_prefix(), Rewrite stored topics under ``old_prefix`` to sit under ``new_prefix``., _assert_sets_last_segment(), _enterprise(), _FakeDriver, _FakeResult (+15 more)

### Community 15 - "Community 15"
Cohesion: 0.23
Nodes (29): GraphDB, Encapsulates the connection and queries to the graph database.     Provides met, MQTTTopicInput, epoch_to_datetime(), Query, *******************************************************************************, Compares the labels on a node with the valid set of label types and returns the, Retrieves nested properties for a given parent node by merging the nested chid (+21 more)

### Community 16 - "Community 16"
Cohesion: 0.14
Nodes (18): The caller's identity, if their roles include one of `allowed`.      The query, require_role(), ConnectivityProtocol, ConnectivityTestResultType, OpcUaBrowseNodeType, _cloud_probe_unavailable(), _job_service(), Query (+10 more)

### Community 17 - "Community 17"
Cohesion: 0.11
Nodes (22): allowed_topic(), _connectivity_asset_path(), The caller's view of the Asset tree.  One scope per request. Admin is unrestri, True when the caller may see this topic.      Unrestricted callers skip bindin, scope_for(), visible_topic(), _identity(), A modelled but out-of-scope topic must not open the Connectivity catalog. (+14 more)

### Community 18 - "Community 18"
Cohesion: 0.20
Nodes (26): MonkeyPatch, _cells(), conf_dir(), _fresh_started_at(), _job_path(), Saving the plant hierarchy through the schema, with rewrites and conf faked., _read_job(), _read_plant() (+18 more)

### Community 19 - "Community 19"
Cohesion: 0.13
Nodes (15): AbstractEventLoop, build_broadcast_consumer_config(), ClientBudget, ConsumerPort, get_dispatcher(), LiveEventDispatcher, Process-scoped canonical live event dispatcher for GraphQL subscriptions., One Kafka consumer per process fanning out to bounded GraphQL client queues. (+7 more)

### Community 20 - "Community 20"
Cohesion: 0.10
Nodes (23): *******************************************************************************, The stored rule, not the submitted one: the console needs the timestamps and the, An unknown severity never reaches the repository: the enum is the guard, so a, `AlertRuleSpec.validate()` has the last word, and its message is what the operat, The migration path off localStorage: one round trip, or the console half-migrate, A rule deleted while an evaluator was mid-cycle is not an error worth waking any, Process data is written by publishing to the broker. Hierarchy writes YAML then, Through the real schema, not a fake info: `strawberry.Info` injection is exactly (+15 more)

### Community 21 - "Community 21"
Cohesion: 0.15
Nodes (19): The caller's identity, if `path` sits inside their Access Groups.      Unsigne, require_path(), FakeInfo, _info(), Spec test 4: one case per cell of section 7's table.  Generated from the table, test_a_role_outside_the_row_is_refused(), test_an_allowed_role_is_permitted(), test_an_unauthenticated_context_is_refused_by_name() (+11 more)

### Community 22 - "Community 22"
Cohesion: 0.15
Nodes (16): AccessScope, True when path is in scope, or is an ancestor of a granted root.          Tree, LiveStreamCapacityError, LiveStreamRegistration, LiveStreamResyncError, Raised when a slow client exceeds its bounded queue and must resubscribe., Raised when the process live-stream client limit is reached., FakeConsumer (+8 more)

### Community 23 - "Community 23"
Cohesion: 0.22
Nodes (21): AlertRuleMutation, _bind_topic(), _filt_scope(), _info(), Plant writes refuse Assets and topics outside the caller's Access Groups., Load first: an out-of-scope stop must not be attributed, then hidden., Unit tests must not open the Asset Model or Connectivity catalog., An engineer who may author rules still cannot aim one at another plant. (+13 more)

### Community 24 - "Community 24"
Cohesion: 0.11
Nodes (19): _any_plant_path(), _assigned(), *******************************************************************************, Spec success criterion 4: "a downtime reason reassignment records an identity th, The schema publishes ID, which is a string. The primary key is a BIGINT., None rather than '': the repository omits the column entirely when the note is, The return type is non-null, and an operator whose click did nothing must be tol, The repository's ValueError, not a driver-level foreign key violation. (+11 more)

### Community 25 - "Community 25"
Cohesion: 0.23
Nodes (14): NotPermittedError, The caller is authenticated and lacks the role. The message reaches the client., AlertRuleInput, Mutation, *******************************************************************************, The engine is shared with the queries, which dispose it., Refuse a write aimed at a topic the caller may not see., All write access to schema `console`, and who may exercise it.      The role e (+6 more)

### Community 26 - "Community 26"
Cohesion: 0.19
Nodes (15): envelope_to_dispatched(), _admin_scope(), FakeConsumer, Tests for v2 envelope compatibility in the GraphQL live event stream., test_business_event_does_not_reach_subscribed_clients(), test_envelope_to_dispatched_accepts_v1_telemetry(), test_envelope_to_dispatched_accepts_v2_telemetry(), test_envelope_to_dispatched_ignores_business_event() (+7 more)

### Community 27 - "Community 27"
Cohesion: 0.19
Nodes (15): DowntimeParetoBucket, FromArgument, ID, OeeShiftResult, Query, *******************************************************************************, All read access to schema `oee`., Nothing to do: the engine is shared with the Asset Model queries, which dispose (+7 more)

### Community 28 - "Community 28"
Cohesion: 0.17
Nodes (18): Enum, ConnectivityServer, EdgeStatusSnapshot, connectivity_job_from_record(), ConnectivityAuthMode, ConnectivityJobKind, ConnectivityJobStatus, ConnectivityJobType (+10 more)

### Community 29 - "Community 29"
Cohesion: 0.31
Nodes (13): AssetModelRepository, AssetModelSummary, AssetNode, scope_from_info(), _context_resolver(), Query, *******************************************************************************, One resolver per process: its cache is the reason it exists, and it has a TTL so (+5 more)

### Community 30 - "Community 30"
Cohesion: 0.16
Nodes (14): Queue, Info, OpcUaDataValueType, _DataChangeHandler, OPC UA data-change subscription for the console.  A live probe, not a collecto, asyncua handler that pushes each change onto an asyncio queue.      Called fro, _data(), _node() (+6 more)

### Community 31 - "Community 31"
Cohesion: 0.12
Nodes (11): _is_ide_page(), A GET asking for HTML is GraphiQL fetching its own page, not an operation., JwksCache, The realm's signing keys, fetched once and kept.  Fetching per request would p, No key with that `kid`, and a refetch did not produce one., Signing keys by `kid`, with one refetch on a miss., How many times the document has been fetched. Exists for the caching test., Nothing to close: each fetch owns its session. Here so callers can be symmetric. (+3 more)

### Community 32 - "Community 32"
Cohesion: 0.23
Nodes (15): assign_live_end(), _admin_scope(), _dispatched(), Tests for the process-scoped canonical live event dispatcher., _source_envelope(), test_access_revocation_drops_later_events(), test_assign_live_end_seeks_to_end(), test_client_does_not_receive_unsubscribed_topic() (+7 more)

### Community 33 - "Community 33"
Cohesion: 0.17
Nodes (13): _admin_info(), *******************************************************************************, test_get_nested_properties(), test_get_node_type(), test_get_spb_nodes_by_metric(), test_get_spb_nodes_integration(), test_get_uns_nodes(), test_get_uns_nodes_by_property() (+5 more)

### Community 34 - "Community 34"
Cohesion: 0.11
Nodes (17): *******************************************************************************, Test if the provided configurations for GraphDBHandler are valid and, Test if the historian database configurations are valid, Test if the Kafka configurations are valid, Test if the provided configurations for the MQTT server are valid and     there, Test if the provided configurations to connect to  GraphDB Server are valid and, Test if the provided configurations for the Historian DB Server are valid and, Test if the provided configurations for the Kafka Server are valid and     ther (+9 more)

### Community 35 - "Community 35"
Cohesion: 0.14
Nodes (17): AlertRule, Enum, *******************************************************************************, The console renders the list, and a set that reorders itself reads as an edit., A STALE_TIMEOUT counts seconds, a CONTAINS matches text. The JSON scalar carries, An empty console has no last edit, and that is not an error to report., A value the database accepts must be expressible in the schema, and vice versa., A duplicate would make the set comparison above pass while the CHECK body repeat (+9 more)

### Community 36 - "Community 36"
Cohesion: 0.16
Nodes (17): Enum, _event(), *******************************************************************************, Spec section 8.1: a shift with no Loading Time has no Availability. Rendering it, Performance is a sum over products, so a mixed shift's terms have to be readable, Not null: the console iterates it, and a null list is an extra branch for no rea, A value the database accepts must be expressible in the schema, and vice versa., A duplicate would make the set comparison above pass while the CHECK body repeat (+9 more)

### Community 37 - "Community 37"
Cohesion: 0.18
Nodes (12): AlertRuleSummary, Query, *******************************************************************************, Nothing to do: the engine is shared with the Asset Model queries, which, Keep rules whose topic the caller may see. Unrestricted callers skip binding., All read access to schema `console`., _repository(), _visible_rules() (+4 more)

### Community 38 - "Community 38"
Cohesion: 0.22
Nodes (15): graphql_context(), identity_in(), The identity in a Strawberry context, or None.      Tolerant on purpose. `sche, Validate the bearer token and hand the identity to the resolvers.      `HTTPCo, FakeConnection, The context dependency, tested without a server.  The dependency takes a starl, Enough of starlette's HTTPConnection for the dependency to read., test_a_bad_token_is_a_401_that_says_why() (+7 more)

### Community 39 - "Community 39"
Cohesion: 0.14
Nodes (15): DowntimeEvent, _event_row(), *******************************************************************************, Spec section 10 writes the signature down. Asserted by introspection rather than, A shift with no Loading Time must not arrive at the dashboard as 0%., Not an error: a line whose first shift has not closed yet is normal., _result_row(), test_a_null_factor_is_null_in_the_response() (+7 more)

### Community 40 - "Community 40"
Cohesion: 0.19
Nodes (14): MQTTTopic, *******************************************************************************, test_invalid_topics(), test_invalid_topics_input(), test_valid_topics(), test_valid_topics_input(), _admin_info(), ******************************************************************************* (+6 more)

### Community 41 - "Community 41"
Cohesion: 0.17
Nodes (16): _input(), *******************************************************************************, 0 is not 'no timeout': `validate()` rejects 0, and NULL is what 'never' means., The schema cannot express a bad severity, but it can express a bad range., Guards against a field added to `AlertRuleSpec` that nothing in the schema can s, Enabled by default, because a rule an engineer just wrote is one they want armed, Every `int` in this schema is the Int64 scalar, which parses to a string. Withou, test_to_spec_carries_every_field_of_the_spec() (+8 more)

### Community 42 - "Community 42"
Cohesion: 0.14
Nodes (10): args: command line params sent to health_check. should either be null of of the, test_main_multiple_scenarios(), check_connection_possible(), check_listening_port(), check_process(), main(), Check if the process is running., Check if the current server is listening on the specified port (+2 more)

### Community 43 - "Community 43"
Cohesion: 0.28
Nodes (15): filter_by_path(), _asset(), _info(), Plant reads hide Assets outside the caller's Access Groups., A Filtration operator must still see AcmeWater so the UNS tree can walk down to, test_filter_by_path_keeps_covered_items_only(), test_filter_by_path_unrestricted_keeps_all(), test_get_asset_children_none_returns_enterprise_for_filtration_operator() (+7 more)

### Community 44 - "Community 44"
Cohesion: 0.17
Nodes (9): Cloud-mode connectivity writes use transactional desired state, not local apply., _server(), test_cloud_context_attaches_secret_store(), test_cloud_mode_save_commits_pending_without_local_apply(), test_cloud_mode_save_does_not_call_finish_live_apply(), test_cloud_mode_test_connectivity_server_returns_job(), test_cloud_mode_test_rejects_disconnected_edge(), test_local_mode_still_uses_sync_edge() (+1 more)

### Community 45 - "Community 45"
Cohesion: 0.16
Nodes (10): _b64u(), make_key(), RSA keys and tokens minted in-process, so no test in this suite needs Keycloak., One RSA keypair, its JWK, and a mint() that signs with it., TestKey, Spec test 1: no bearer token, no answer - on every operation.  Enumerated rath, The gate opens. What happens next is a resolver reaching a database this test ha, allow_headers=["*"] at uns_graphql_app.py already covers this. The test exists (+2 more)

### Community 46 - "Community 46"
Cohesion: 0.30
Nodes (8): _edge_repository(), _edge_service(), Mutation, Administration mutations for cloud edge enrollment and access., EdgeDeviceType, EdgeManagementService, EdgeRepository, Info

### Community 47 - "Community 47"
Cohesion: 0.16
Nodes (11): *******************************************************************************, A console clearing its filter box must not ask for the rules watching topic ''., Null rather than an error: a console polling a rule somebody else deleted is nor, Plant-wide counts must not leak to an operator; hide, do not 403., _rule(), test_get_alert_rule_by_id(), test_get_alert_rule_is_null_for_an_unknown_id(), test_get_alert_rule_summary_counts_only_visible_rules() (+3 more)

### Community 48 - "Community 48"
Cohesion: 0.19
Nodes (9): AccessGroupMutation, _group(), Access Group mutations through the schema, with the repository replaced., test_admin_can_save_access_group(), test_admin_can_set_access_group_members(), test_engineer_cannot_delete_access_group(), test_engineer_cannot_save_access_group(), test_engineer_cannot_set_access_group_members() (+1 more)

### Community 49 - "Community 49"
Cohesion: 0.16
Nodes (13): isolate_asset_model_startup(), *******************************************************************************, Test to validate that UNSGraphql.app can be instantiated by uvicorn, Lifespan unit tests must not require Asset Model database credentials or a LISTE, Test validity of key attributes of  UNSGraphql needed to start run the GraphQL s, Test to validate that the app calls the cleanup method on the query and subscrip, Every database this service holds open is released on shutdown.      One Postg, test_uns_graphql_app_attributes() (+5 more)

### Community 50 - "Community 50"
Cohesion: 0.19
Nodes (9): Asset, MetricInfo, TopicContext, AssetModelSummary, AssetNode, MetricDefinitionType, *******************************************************************************, One Asset from the authored Asset Model. (+1 more)

### Community 51 - "Community 51"
Cohesion: 0.21
Nodes (10): _connection_params(), The gate, at the one door this service has.  `uns_graphql_app.py` mounts exact, The process-wide key cache, built on first use.      One instance, so the docu, Replace the process-wide cache. Tests only; pass None to clear it., signing_keys(), use_signing_keys(), realm_keys(), realm_keys() (+2 more)

### Community 52 - "Community 52"
Cohesion: 0.17
Nodes (11): mock_graphdb_config(), mock_graphdb_driver(), *******************************************************************************, Validates that the driver was closed, Test Read Queries from Graphdb, Reduce retries and sleep time for tests to fail fast., Fixture to mock the Neo4j async driver., Test with mock object to validate singularity of the neo4j driver (+3 more)

### Community 53 - "Community 53"
Cohesion: 0.33
Nodes (8): _as_int(), Mutation, Admin writes for Access Groups.  Role each field needs is in auth/require.py,, Int64 parses to str; the repository wants an int. Same conversion as AlertRuleIn, _repository(), AccessGroupRepository, AccessGroupType, Info

### Community 54 - "Community 54"
Cohesion: 0.21
Nodes (9): DowntimeEventRow, ShiftResultRow, DowntimeEventType, OeeShiftResult, OeeStatus, *******************************************************************************, Published as `DowntimeEvent` (spec section 10) from a Python class that does not, The current result for a shift. Superseded numbers are kept in     `oee.shift_r (+1 more)

### Community 55 - "Community 55"
Cohesion: 0.25
Nodes (9): AlertRule, AlertCategory, AlertCondition, AlertRuleSummary, AlertRuleType, AlertSeverity, ConsoleRole, ******************************************************************************* (+1 more)

### Community 56 - "Community 56"
Cohesion: 0.20
Nodes (5): *******************************************************************************, *******************************************************************************, GraphQL subscription for authorized canonical live events., *******************************************************************************, *******************************************************************************

### Community 57 - "Community 57"
Cohesion: 0.27
Nodes (7): KAFKATopic, Input object for canonical live stream filters (original MQTT browse paths)., Validation tests for live stream MQTT topic filters., test_invalid_topics(), test_invalid_topics_input(), test_valid_topics(), test_valid_topics_input()

### Community 58 - "Community 58"
Cohesion: 0.36
Nodes (7): _caller_is_admin(), Query, GraphQL queries for Access Groups.  Admin-only reads: a non-admin caller gets, _repository(), AccessGroupRepository, AccessGroupType, Info

### Community 59 - "Community 59"
Cohesion: 0.36
Nodes (8): Enum, SimpleNamespace, GraphQL connectivity enums must match the database vocabularies., _tag_ns(), test_enums_match_the_database_vocabulary(), test_from_tag_returns_asset_path_and_display_name(), test_from_tag_uses_segment_when_display_name_is_null(), test_subscribed_signal_from_tag_returns_asset_path_and_display_name()

### Community 60 - "Community 60"
Cohesion: 0.39
Nodes (7): jwks_document(), Spec test 7: fetched once and cached; an unknown kid triggers exactly one refetc, Return a fetch that yields each document in turn, and the list of calls it recor, _recording_fetch(), test_a_kid_that_is_still_unknown_after_the_refetch_raises_and_does_not_loop(), test_an_unknown_kid_refetches_once_and_then_finds_the_rotated_key(), test_the_first_lookup_fetches_and_the_second_does_not()

### Community 61 - "Community 61"
Cohesion: 0.25
Nodes (7): _E, ConnectivityTag, ConnectivityTagType, _loaded_asset(), _optional_enum(), Return `tag.asset` only when already present — never lazy-load.      `getattr(, SubscribedSignalType

### Community 62 - "Community 62"
Cohesion: 0.33
Nodes (6): _edge_repository(), Query, GraphQL queries for cloud edge devices., EdgeDeviceType, EdgeRepository, Info

### Community 64 - "Community 64"
Cohesion: 0.25
Nodes (5): AsyncDriver, Executes a (CQL) query with the provided positional and keyword parameters., Returns the Neo4j async driver which is the connection to the database., Closes the Neo4j async driver and releases the connection.         Ensures that, Record

### Community 65 - "Community 65"
Cohesion: 0.39
Nodes (7): _group(), Reading Access Groups through the schema, with the repository replaced.  Non-a, test_admin_gets_one_access_group(), test_admin_lists_access_groups(), test_engineer_gets_null_access_group(), test_engineer_lists_no_access_groups(), AccessGroupRecord

### Community 66 - "Community 66"
Cohesion: 0.25
Nodes (5): ConnectivityJobType, Info, Connectivity management job status subscription., Subscriptions own no process-wide resources., Subscription

### Community 67 - "Community 67"
Cohesion: 0.29
Nodes (5): AlertRuleSpec, _as_int(), *******************************************************************************, Whole numbers arrive as strings.      Every `int` in this schema is the Int64, Translate to the repository's value object.          The enums carry the strin

### Community 68 - "Community 68"
Cohesion: 0.33
Nodes (6): BytesPayload, JSONPayload, MQTTMessage, *******************************************************************************, test_resolve_payload(), test_strawberry_type()

### Community 69 - "Community 69"
Cohesion: 0.40
Nodes (4): AccessGroupRecord, AccessGroupRootType, AccessGroupType, GraphQL types for Access Groups: named Asset-tree roots and their members.

### Community 70 - "Community 70"
Cohesion: 0.33
Nodes (4): EdgeDevice, EdgeStatusSnapshot, EdgeDeviceType, GraphQL types for cloud edge device management.

### Community 71 - "Community 71"
Cohesion: 0.40
Nodes (4): ParetoBucket, test_downtime_pareto_returns_the_buckets_in_order(), DowntimeParetoBucket, test_pareto_bucket_from_bucket()

### Community 72 - "Community 72"
Cohesion: 0.60
Nodes (3): BytesPayload, Info, JSONPayload

### Community 74 - "Community 74"
Cohesion: 0.50
Nodes (3): *******************************************************************************, _repository(), OeeResultRepository

### Community 75 - "Community 75"
Cohesion: 0.50
Nodes (3): ShiftResultProduct, OeeShiftProduct, Stored per product because Performance is a sum over products.      A mixed sh

### Community 76 - "Community 76"
Cohesion: 0.50
Nodes (3): Shared pytest hooks for the GraphQL module., Drop cached DB engines and topic resolvers so retries and xdist workers stay iso, _reset_asset_model_singletons()

## Knowledge Gaps
- **30 isolated node(s):** `Any`, `Identity`, `_RootsFor`, `T`, `EdgeDevice` (+25 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **15 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AccessScope` connect `Community 22` to `Community 32`, `Community 2`, `Community 37`, `Community 43`, `Community 12`, `Community 13`, `Community 47`, `Community 17`, `Community 19`, `Community 20`, `Community 21`, `Community 23`, `Community 24`, `Community 26`, `Community 29`?**
  _High betweenness centrality (0.133) - this node is a cross-community bridge._
- **Why does `HistorianRepository` connect `Community 1` to `Community 2`, `Community 40`, `Community 10`, `Community 14`, `Community 15`?**
  _High betweenness centrality (0.125) - this node is a cross-community bridge._
- **Why does `EdgeManagementService` connect `Community 0` to `Community 9`, `Community 4`, `Community 46`, `Community 49`?**
  _High betweenness centrality (0.120) - this node is a cross-community bridge._
- **Are the 54 inferred relationships involving `EdgeManagementService` (e.g. with `alias` and `EdgeJobService`) actually correct?**
  _`EdgeManagementService` has 54 INFERRED edges - model-reasoned connections that need verification._
- **Are the 53 inferred relationships involving `HistorianRepository` (e.g. with `JSONPayload` and `HistoricalUNSEvent`) actually correct?**
  _`HistorianRepository` has 53 INFERRED edges - model-reasoned connections that need verification._
- **Are the 51 inferred relationships involving `EdgeServiceError` (e.g. with `alias` and `CloudDesiredContext`) actually correct?**
  _`EdgeServiceError` has 51 INFERRED edges - model-reasoned connections that need verification._
- **Are the 51 inferred relationships involving `AccessScope` (e.g. with `AbstractEventLoop` and `AlertRuleSummary`) actually correct?**
  _`AccessScope` has 51 INFERRED edges - model-reasoned connections that need verification._