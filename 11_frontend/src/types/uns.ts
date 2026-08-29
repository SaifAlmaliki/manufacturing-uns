/**
 * Unified Namespace (UNS) & GraphQL Domain Types
 * Based on ISA-95 IIoT Hierarchy and 07_uns_graphql schema
 */

export type BinaryOperator = 'OR' | 'AND' | 'NOT';

export type SparkplugDataType =
  | 'Int8'
  | 'Int16'
  | 'Int32'
  | 'Int64'
  | 'UInt8'
  | 'UInt16'
  | 'UInt32'
  | 'UInt64'
  | 'Float'
  | 'Double'
  | 'Boolean'
  | 'String'
  | 'DateTime'
  | 'Text'
  | 'Bytes'
  | 'File'
  | 'DataSet'
  | 'Template'
  | 'PropertySet'
  | 'Unknown';

export interface UnsNode {
  topic: string;
  name: string;
  namespace?: string;
  nodeType?: string;
  payload?: Record<string, unknown> | string | number | boolean | null;
  lastUpdated: string; // ISO 8601 string
  publisher?: string;
  properties?: Record<string, string>;
  isLeaf: boolean;
  children?: UnsNode[];
  isStale?: boolean;
  isSparkplug?: boolean;
}

export interface HistoricEvent {
  id: string;
  topic: string;
  payload: Record<string, unknown> | string | number | boolean | null;
  timestamp: string; // ISO 8601 string
  publisher?: string;
  properties?: Record<string, string>;
}

export interface SparkplugMetric {
  name: string;
  alias?: number;
  datatype: SparkplugDataType;
  value: unknown;
  timestamp: string;
  isHistorical?: boolean;
  isTransient?: boolean;
  metadata?: Record<string, unknown>;
  properties?: Record<string, string>;
  isBinary?: boolean;
  binaryByteSize?: number;
}

export interface SparkplugNode {
  groupId: string;
  edgeNodeId: string;
  deviceId?: string;
  topic: string;
  metrics: SparkplugMetric[];
  sequenceNumber?: number;
  timestamp: string;
  online: boolean;
}

export interface MqttMessage {
  id: string;
  topic: string;
  payload: Record<string, unknown> | string | number | boolean | null;
  rawPayload?: string;
  timestamp: string;
  qos?: number;
  retain?: boolean;
  publisher?: string;
  isSparkplug?: boolean;
}

export interface KafkaMessage {
  id: string;
  topic: string;
  partition?: number;
  offset?: number;
  key?: string;
  payload: Record<string, unknown> | string | number | boolean | null;
  rawPayload?: string;
  timestamp: string;
  headers?: Record<string, string>;
}

export type ConnectionStatus = 'LIVE' | 'DEGRADED' | 'DOWN';

export interface SystemHealthInfo {
  status: ConnectionStatus;
  graphqlHttp: boolean;
  graphqlWs: boolean;
  mqttBroker: 'ONLINE' | 'DEGRADED' | 'OFFLINE' | 'PENDING_GRAPHQL_SCHEMA';
  neo4jTree: 'ONLINE' | 'DEGRADED' | 'OFFLINE' | 'PENDING_GRAPHQL_SCHEMA';
  timescaleHistorian: 'ONLINE' | 'DEGRADED' | 'OFFLINE' | 'PENDING_GRAPHQL_SCHEMA';
  kafkaBroker: 'ONLINE' | 'DEGRADED' | 'OFFLINE' | 'PENDING_GRAPHQL_SCHEMA';
  sparkplugMapper: 'ONLINE' | 'DEGRADED' | 'OFFLINE' | 'PENDING_GRAPHQL_SCHEMA';
  lastPingMs: number;
  endpointUrl: string;
  mode: 'LIVE_GRAPHQL' | 'SIMULATED_MOCK';
}

export interface TopicBookmark {
  topic: string;
  alias?: string;
  addedAt: string;
  notes?: string;
}

export interface AppSettings {
  displayName: string;
  organization: string;
  instance: string;
  graphqlUrl: string;
  graphqlWsUrl: string;
  maxFeedBuffer: number;
  staleThresholdMinutes: number;
  autoScrollFeed: boolean;
  followSelectionInFeed: boolean;
}
