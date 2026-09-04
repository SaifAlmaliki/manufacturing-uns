import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UnsGraphQLClient } from './client';

/** A WebSocket that records what was sent and never opens by itself. */
class RecordingSocket {
  static instances: RecordingSocket[] = [];
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  constructor(public url: string, public protocol?: string) {
    RecordingSocket.instances.push(this);
  }
  send(data: string) { this.sent.push(data); }
  close() {}
}

const auth = vi.hoisted(() => ({
  token: vi.fn(() => 'first.access.token' as string | null),
  refresh: vi.fn(async () => 'second.access.token' as string | null),
  onExpired: vi.fn(),
}));

const ok = (data: unknown) =>
  ({ ok: true, status: 200, json: async () => ({ data }) }) as unknown as Response;
const unauthorized = () =>
  ({ ok: false, status: 401, json: async () => ({}) }) as unknown as Response;

beforeEach(() => {
  vi.clearAllMocks();
  RecordingSocket.instances = [];
  auth.token.mockReturnValue('first.access.token');
  auth.refresh.mockImplementation(async () => {
    auth.token.mockReturnValue('second.access.token');
    return 'second.access.token';
  });
  vi.stubGlobal('WebSocket', RecordingSocket);
});

const client = () => new UnsGraphQLClient('/graphql', 'ws://test/graphql', auth);

describe('the Authorization header', () => {
  it('is on every request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ getUnsNodes: [] }));
    vi.stubGlobal('fetch', fetchMock);

    await client().getUnsNodes(['a/b']);

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer first.access.token');
  });

  it('is absent rather than empty when there is no token', async () => {
    auth.token.mockReturnValue(null);
    const fetchMock = vi.fn().mockResolvedValue(ok({ getUnsNodes: [] }));
    vi.stubGlobal('fetch', fetchMock);

    await client().getUnsNodes(['a/b']);

    const [, init] = fetchMock.mock.calls[0];
    expect('Authorization' in (init.headers as Record<string, string>)).toBe(false);
  });

  it('is read per request, so a renewed token is used immediately', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ getUnsNodes: [] }));
    vi.stubGlobal('fetch', fetchMock);
    const c = client();

    await c.getUnsNodes(['a/b']);
    auth.token.mockReturnValue('renewed.access.token');
    await c.getUnsNodes(['a/b']);

    const [, second] = fetchMock.mock.calls[1];
    expect((second.headers as Record<string, string>).Authorization)
      .toBe('Bearer renewed.access.token');
  });
});

describe('a 401', () => {
  it('is retried once with a refreshed token', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(unauthorized())
      .mockResolvedValueOnce(ok({ getUnsNodes: [] }));
    vi.stubGlobal('fetch', fetchMock);

    await client().getUnsNodes(['a/b']);

    expect(auth.refresh).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [, retry] = fetchMock.mock.calls[1];
    expect((retry.headers as Record<string, string>).Authorization)
      .toBe('Bearer second.access.token');
  });

  it('is retried exactly once, never in a loop', async () => {
    const fetchMock = vi.fn().mockResolvedValue(unauthorized());
    vi.stubGlobal('fetch', fetchMock);

    await client().getUnsNodes(['a/b']);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(auth.refresh).toHaveBeenCalledTimes(1);
  });

  it('sends the user back to the realm when the refresh does not help', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(unauthorized()));

    await client().getUnsNodes(['a/b']);

    expect(auth.onExpired).toHaveBeenCalledTimes(1);
  });

  it('does not refresh when there was no token to begin with', async () => {
    auth.token.mockReturnValue(null);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(unauthorized()));

    await client().getUnsNodes(['a/b']);

    expect(auth.refresh).not.toHaveBeenCalled();
  });

  it('does not send an anonymous visitor back to the realm', async () => {
    // The landing page loads UNSProvider, which queries GraphQL with no token. Treating that
    // 401 as an expired session calls signIn() and races the OIDC callback into a redirect loop.
    auth.token.mockReturnValue(null);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(unauthorized()));

    await client().getUnsNodes(['a/b']);

    expect(auth.onExpired).not.toHaveBeenCalled();
  });

  it('never reports an expired session as no data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(unauthorized()));

    await client().getUnsNodes(['a/b']);

    expect(auth.onExpired).toHaveBeenCalled();
  });
});

describe('the subscription socket', () => {
  it('carries the token in connection_init', async () => {
    client();
    const socket = RecordingSocket.instances[0];

    socket.onopen?.();

    expect(JSON.parse(socket.sent[0])).toEqual({
      type: 'connection_init',
      payload: { Authorization: 'Bearer first.access.token' },
    });
  });

  it('sends an empty payload rather than a malformed header when there is no token', () => {
    auth.token.mockReturnValue(null);
    client();
    const socket = RecordingSocket.instances[0];

    socket.onopen?.();

    expect(JSON.parse(socket.sent[0])).toEqual({ type: 'connection_init', payload: {} });
  });

  it('does not send an anonymous visitor back to the realm when the socket is refused', () => {
    auth.token.mockReturnValue(null);
    client();

    RecordingSocket.instances[0].onclose?.({ code: 4403 });

    expect(auth.onExpired).not.toHaveBeenCalled();
  });

  it('sends the user back to the realm when a socket that had a token is refused', () => {
    client();

    RecordingSocket.instances[0].onclose?.({ code: 4403 });

    expect(auth.onExpired).toHaveBeenCalledTimes(1);
  });
});
