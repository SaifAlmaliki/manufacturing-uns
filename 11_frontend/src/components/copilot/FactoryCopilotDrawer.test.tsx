import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const copilotApi = vi.hoisted(() => ({
  listConversations: vi.fn(async () => []),
  createConversation: vi.fn(async () => ({
    id: 'conv-new',
    title: 'New chat',
    updatedAt: new Date().toISOString(),
  })),
  getConversation: vi.fn(async () => ({ id: 'conv-1', title: 'Test', updatedAt: '', messages: [] })),
  deleteConversation: vi.fn(async () => undefined),
  sendChat: vi.fn(async () => ({
    text: 'Pump P101 flow dropped 12% over three weeks.',
    citations: [{ asset: 'P101', topic: 'Halabja/RawWater/Train10/P101/Flow', time: '2026-09-06T09:00:00Z', source: 'historian' as const }],
  })),
  checkCopilotHealth: vi.fn(async () => true),
}));

vi.mock('./copilotApi', () => ({
  ...copilotApi,
  CopilotUnavailableError: class CopilotUnavailableError extends Error {},
}));

const uns = vi.hoisted(() => ({
  selectedNode: { topic: 'Halabja/RawWater/Train10/P101' },
  copilotMetricKey: 'Halabja/RawWater/Train10/P101/Flow',
  jumpToHistorian: vi.fn(),
  jumpToTopicInTree: vi.fn(),
}));

vi.mock('../../context/UNSContext', () => ({
  useUNS: () => uns,
}));

vi.mock('../../context/AlarmContext', () => ({
  useAlarms: () => ({ focusedAlarmTopic: 'Halabja/RawWater/Train10/P101' }),
}));

import { FactoryCopilotDrawer } from './FactoryCopilotDrawer';
import { CopilotUnavailableError } from './copilotApi';
import { JOB_CARDS } from './jobCards';

function renderDrawer(open = true) {
  const onClose = vi.fn();
  render(
    <MemoryRouter initialEntries={['/condition-monitoring']}>
      <FactoryCopilotDrawer isOpen={open} onClose={onClose} />
    </MemoryRouter>,
  );
  return { onClose };
}

beforeEach(() => {
  vi.clearAllMocks();
  copilotApi.sendChat.mockResolvedValue({
    text: 'Pump P101 flow dropped 12% over three weeks.',
    citations: [
      {
        asset: 'P101',
        topic: 'Halabja/RawWater/Train10/P101/Flow',
        time: '2026-09-06T09:00:00Z',
        source: 'historian' as const,
      },
    ],
  });
});

describe('FactoryCopilotDrawer', () => {
  it('shows job cards on an empty thread', async () => {
    renderDrawer();
    expect(screen.getByText('Hello, how can I help you today?')).toBeTruthy();
    expect(screen.getByRole('button', { name: JOB_CARDS[0].prompt })).toBeTruthy();
  });

  it('POSTs page context and conversationId on send', async () => {
    renderDrawer();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: JOB_CARDS[0].prompt }));
    await waitFor(() => {
      expect(copilotApi.sendChat).toHaveBeenCalledWith(
        expect.objectContaining({
          conversationId: 'conv-new',
          context: expect.objectContaining({
            route: '/condition-monitoring',
            assetPath: 'Halabja/RawWater/Train10/P101',
            metricKey: 'Halabja/RawWater/Train10/P101/Flow',
            alarmTopic: 'Halabja/RawWater/Train10/P101',
          }),
        }),
      );
    });
  });

  it('lists threads and deletes one', async () => {
    copilotApi.listConversations.mockResolvedValue([
      { id: 'conv-1', title: 'Pump question', updatedAt: new Date().toISOString() },
    ]);
    renderDrawer();
    await waitFor(() => {
      expect(screen.getByText('Pump question')).toBeTruthy();
    });
    const user = userEvent.setup();
    await user.click(screen.getByLabelText('Delete Pump question'));
    expect(copilotApi.deleteConversation).toHaveBeenCalledWith('conv-1');
  });

  it('shows a spinner while the reply is in flight', async () => {
    let resolve!: (value: unknown) => void;
    copilotApi.sendChat.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    renderDrawer();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: JOB_CARDS[0].prompt }));
    expect(screen.getByText('Looking…')).toBeTruthy();
    resolve({
      text: 'done',
      citations: [],
    });
    await waitFor(() => expect(screen.queryByText('Looking…')).toBeNull());
  });

  it('renders citation tickets that navigate and leave the bay open', async () => {
    const onClose = vi.fn();
    render(
      <MemoryRouter initialEntries={['/condition-monitoring']}>
        <FactoryCopilotDrawer isOpen onClose={onClose} />
      </MemoryRouter>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: JOB_CARDS[0].prompt }));
    await waitFor(() => {
      expect(screen.getByTestId('copilot-citation')).toBeTruthy();
    });
    await user.click(screen.getByTestId('copilot-citation'));
    expect(uns.jumpToHistorian).toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('shows unavailable when health check fails on open', async () => {
    copilotApi.checkCopilotHealth.mockResolvedValue(false);
    renderDrawer();
    await waitFor(() => {
      expect(screen.getByText('Factory Copilot is unavailable.')).toBeTruthy();
    });
  });

  it('shows unavailable when sendChat throws CopilotUnavailableError', async () => {
    copilotApi.sendChat.mockRejectedValue(new CopilotUnavailableError());
    renderDrawer();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: JOB_CARDS[0].prompt }));
    await waitFor(() => {
      expect(screen.getByText('Factory Copilot is unavailable.')).toBeTruthy();
    });
  });

  it('does not mention schedule or work instructions on the job cards', () => {
    renderDrawer();
    const text = JOB_CARDS.map((c) => c.prompt).join(' ');
    expect(text).not.toMatch(/schedule|instruction|SOP|Brent|Hot Rolling/i);
  });
});
