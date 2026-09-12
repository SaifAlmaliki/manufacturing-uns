import { describe, expect, it, vi } from 'vitest';
import { isTerminalJobStatus, parseBrowseJobResult, parseTestJobResult } from './edge-jobs';

describe('edge-jobs', () => {
  it('parses browse job payloads', () => {
    const parsed = parseBrowseJobResult({
      tags: [
        {
          node_id: 'ns=2;s=Tag1',
          browse_name: 'Tag1',
          display_name: 'Tag1',
          browse_path: 'Objects/Tag1',
          node_class: 'Variable',
          has_children: false,
        },
      ],
      has_more: true,
      next_cursor: '0.500',
    });
    expect(parsed.tags[0]?.nodeId).toBe('ns=2;s=Tag1');
    expect(parsed.hasMore).toBe(true);
    expect(parsed.nextCursor).toBe('0.500');
  });

  it('parses test job outcomes', () => {
    expect(parseTestJobResult({ ok: true }).ok).toBe(true);
    expect(parseTestJobResult({ ok: false, error_detail: 'refused' }).error).toBe('refused');
  });

  it('detects terminal job states', () => {
    expect(isTerminalJobStatus('completed')).toBe(true);
    expect(isTerminalJobStatus('RUNNING')).toBe(false);
  });
});
