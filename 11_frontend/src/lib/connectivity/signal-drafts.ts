import type {
  GraphqlConnectivityTagPatch,
  GraphqlSubscribedSignal,
} from '../../services/graphql/types';

export type SignalDrafts = Record<string, GraphqlConnectivityTagPatch>;

function sameLabels(left?: string[] | null, right?: string[] | null): boolean {
  const a = [...(left ?? [])].sort();
  const b = [...(right ?? [])].sort();
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

function pruneUnchanged(
  row: GraphqlSubscribedSignal,
  patch: GraphqlConnectivityTagPatch,
): GraphqlConnectivityTagPatch {
  const next: GraphqlConnectivityTagPatch = { ...patch };
  if ('displayName' in next && next.displayName === row.displayName) delete next.displayName;
  if ('mqttTopic' in next && next.mqttTopic === row.mqttTopic) delete next.mqttTopic;
  if ('assetId' in next && (next.assetId ?? null) === (row.assetId ?? null)) delete next.assetId;
  if ('unitOfMeasure' in next && (next.unitOfMeasure ?? null) === (row.unitOfMeasure ?? null)) {
    delete next.unitOfMeasure;
  }
  if ('semanticClass' in next && (next.semanticClass ?? null) === (row.semanticClass ?? null)) {
    delete next.semanticClass;
  }
  if ('dataType' in next && (next.dataType ?? null) === (row.dataType ?? null)) delete next.dataType;
  if ('labels' in next && sameLabels(next.labels, row.labels)) delete next.labels;
  return next;
}

export function mergeSignalDraft(
  row: GraphqlSubscribedSignal,
  draft?: GraphqlConnectivityTagPatch,
): GraphqlSubscribedSignal {
  if (!draft) return row;
  return { ...row, ...draft };
}

export function stageSignalPatch(
  drafts: SignalDrafts,
  key: string,
  row: GraphqlSubscribedSignal,
  patch: GraphqlConnectivityTagPatch,
): SignalDrafts {
  const merged = pruneUnchanged(row, { ...drafts[key], ...patch });
  const next = { ...drafts };
  if (Object.keys(merged).length === 0) delete next[key];
  else next[key] = merged;
  return next;
}

export function withAddedLabel(
  row: GraphqlSubscribedSignal,
  draft: GraphqlConnectivityTagPatch | undefined,
  name: string,
): GraphqlConnectivityTagPatch {
  const current = draft?.labels ?? row.labels ?? [];
  return { labels: Array.from(new Set([...current, name])) };
}

export function draftCount(drafts: SignalDrafts): number {
  return Object.keys(drafts).length;
}
