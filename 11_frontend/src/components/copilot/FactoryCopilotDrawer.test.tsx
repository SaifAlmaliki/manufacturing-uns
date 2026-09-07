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
  fetchCopilotScope: vi.fn(async () => ({ roots: [], unrestricted: false })),
}));

vi.mock('./copilotApi', () => ({
  ...copilotApi,
  CopilotAuthError: class CopilotAuthError extends Error {},
  CopilotUnavailableError: class CopilotUnavailableError extends Error {},
}));

const uns = vi.hoisted(() => ({
  selectedNode: { topic: 'Halabja/RawWater/Train10/P101' } as { topic?: string } | undefined,
  copilotMetricKey: 'Halabja/RawWater/Train10/P101/Flow' as string | undefined,
  jumpToHistorian: vi.fn(),
  jumpToTopicInTree: vi.fn(),
}));

const alarms = vi.hoisted(() => ({
  focusedAlarmTopic: 'Halabja/RawWater/Train10/P101' as string | undefined,
}));

vi.mock('../../context/UNSContext', () => ({
  useUNS: () => uns,
}));

vi.mock('../../context/AlarmContext', () => ({
  useAlarms: () => alarms,
}));

import { FactoryCopilotDrawer } from './FactoryCopilotDrawer';
import { CopilotUnavailableError } from './copilotApi';
import { JOB_CARDS, jobCards } from './jobCards';

function renderDrawer(open = true) {
  const onClose = vi.fn();
  render(
    <MemoryRouter initialEntries={['/condition-monitoring']}>
      <FactoryCopilotDrawer isOpen={open} onClose={onClose} />
    </MemoryRouter>,
  );
  return { onClose };
}

function clearFocus() {
  uns.selectedNode = undefined;
  uns.copilotMetricKey = undefined;
  alarms.focusedAlarmTopic = undefined;
}

beforeEach(() => {
  vi.clearAllMocks();
  uns.selectedNode = { topic: 'Halabja/RawWater/Train10/P101' };
  uns.copilotMetricKey = 'Halabja/RawWater/Train10/P101/Flow';
  alarms.focusedAlarmTopic = 'Halabja/RawWater/Train10/P101';
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
  copilotApi.checkCopilotHealth.mockResolvedValue(true);
  copilotApi.fetchCopilotScope.mockResolvedValue({ roots: [], unrestricted: false });
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

  it('shows the Access Group chip once scope resolves and nothing is focused', async () => {
    clearFocus();
    copilotApi.fetchCopilotScope.mockResolvedValue({ roots: ['Acme/Site1'], unrestricted: false });
    renderDrawer();
    await waitFor(() => {
      expect(screen.getByTestId('copilot-context').textContent).toBe('Plant · Acme/Site1');
    });
  });

  it('shows plant-scoped job card copy when nothing is focused', async () => {
    clearFocus();
    renderDrawer();
    const plantCard = jobCards(false)[0];
    await waitFor(() => {
      expect(screen.getByRole('button', { name: plantCard.prompt })).toBeTruthy();
    });
    expect(screen.getByText(/my plant right now/i)).toBeTruthy();
  });

  it('does not mark unavailable when scope fetch fails but health check is ok', async () => {
    copilotApi.checkCopilotHealth.mockResolvedValue(true);
    copilotApi.fetchCopilotScope.mockRejectedValue(new CopilotUnavailableError());
    renderDrawer();
    await waitFor(() => {
      expect(screen.getByText('Hello, how can I help you today?')).toBeTruthy();
    });
    expect(screen.queryByText('Factory Copilot is unavailable.')).toBeNull();
  });
});
