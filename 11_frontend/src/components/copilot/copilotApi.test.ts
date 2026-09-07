import { beforeEach, describe, expect, it, vi } from 'vitest';
import { sendChat } from './copilotApi';

const accessToken = vi.hoisted(() => vi.fn(() => 'test-token'));

vi.mock('../../lib/auth/oidc', () => ({
  authClient: { accessToken },
}));

describe('copilotApi', () => {
  beforeEach(() => {
    accessToken.mockReturnValue('test-token');
    vi.restoreAllMocks();
  });

  it('sendChat posts to /agent/chat with bearer token', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ text: 'ok', citations: [] }), { status: 200 }),
    );

    await sendChat({
      message: 'Pump P101 performance?',
      conversationId: 'conv-1',
      context: {
        route: '/condition-monitoring',
        assetPath: 'Halabja/RawWater/Train10/P101',
        metricKey: '',
        alarmTopic: '',
      },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/agent/chat',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer test-token',
        }),
        body: JSON.stringify({
          message: 'Pump P101 performance?',
          conversationId: 'conv-1',
          context: {
            route: '/condition-monitoring',
            assetPath: 'Halabja/RawWater/Train10/P101',
            metricKey: '',
            alarmTopic: '',
          },
        }),
      }),
    );
  });
});
