import { authClient } from '../../lib/auth/oidc';
import type { CopilotScope, PageContext } from './copilotContext';

export type CopilotSource = 'model' | 'historian' | 'live' | 'alarms';

export type CopilotConversation = { id: string; title: string; updatedAt: string };
export type CopilotCitation = {
  asset: string;
  topic: string;
  time: string;
  source: CopilotSource;
};
export type CopilotMessage = {
  role: 'user' | 'assistant';
  body: string;
  citations: CopilotCitation[];
};

export class CopilotAuthError extends Error {
  constructor(message = 'Sign in again to use Factory Copilot.') {
    super(message);
    this.name = 'CopilotAuthError';
  }
}

export class CopilotUnavailableError extends Error {
  constructor(message = 'Factory Copilot is unavailable.') {
    super(message);
    this.name = 'CopilotUnavailableError';
  }
}

const BASE = '/agent';

export function agentHeaders(): HeadersInit {
  const token = authClient.accessToken();
  return token
    ? { Authorization: `Bearer ${token}`, Accept: 'application/json', 'Content-Type': 'application/json' }
    : { Accept: 'application/json', 'Content-Type': 'application/json' };
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (response.status === 401) {
    throw new CopilotAuthError();
  }
  if (response.status === 502 || response.status === 503) {
    throw new CopilotUnavailableError();
  }
  if (!response.ok) {
    throw new CopilotUnavailableError(`Factory Copilot returned ${response.status}.`);
  }
  return (await response.json()) as T;
}

export async function listConversations(): Promise<CopilotConversation[]> {
  const response = await fetch(`${BASE}/conversations`, { headers: agentHeaders() });
  return handleResponse(response);
}

export async function createConversation(): Promise<CopilotConversation> {
  const response = await fetch(`${BASE}/conversations`, {
    method: 'POST',
    headers: agentHeaders(),
  });
  return handleResponse(response);
}

export async function getConversation(id: string): Promise<{
  id: string;
  title: string;
  updatedAt: string;
  messages: CopilotMessage[];
}> {
  const response = await fetch(`${BASE}/conversations/${id}`, { headers: agentHeaders() });
  return handleResponse(response);
}

export async function deleteConversation(id: string): Promise<void> {
  const response = await fetch(`${BASE}/conversations/${id}`, {
    method: 'DELETE',
    headers: agentHeaders(),
  });
  if (response.status === 401) throw new CopilotAuthError();
  if (response.status === 502 || response.status === 503) throw new CopilotUnavailableError();
  if (!response.ok && response.status !== 204) {
    throw new CopilotUnavailableError();
  }
}

export async function sendChat(body: {
  message: string;
  conversationId: string;
  context: PageContext;
}): Promise<{ text: string; citations: CopilotCitation[] }> {
  const response = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: agentHeaders(),
    body: JSON.stringify(body),
  });
  return handleResponse(response);
}

export async function fetchCopilotScope(): Promise<CopilotScope> {
  const response = await fetch(`${BASE}/scope`, { headers: agentHeaders() });
  return handleResponse(response);
}

export async function checkCopilotHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${BASE}/health`);
    if (!response.ok) return false;
    const body = (await response.json()) as { status?: string };
    return body.status === 'ok';
  } catch {
    return false;
  }
}
