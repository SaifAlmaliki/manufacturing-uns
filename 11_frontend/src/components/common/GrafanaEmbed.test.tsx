import { act, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { GrafanaEmbed, grafanaKioskPath } from './GrafanaEmbed';

describe('grafanaKioskPath', () => {
  it('is same-origin, which is what makes the sign-in check possible', () => {
    expect(grafanaKioskPath('uns-oee', 'dark')).toMatch(/^\/grafana\/d\/uns-oee\?/);
  });
});

describe('GrafanaEmbed', () => {
  it('renders the dashboard', () => {
    const { container } = render(<GrafanaEmbed uid="uns-oee" theme="dark" title="OEE" />);

    const frame = container.querySelector('iframe');
    expect(frame?.getAttribute('src')).toContain('/grafana/d/uns-oee');
  });

  it('offers a way into Grafana when the frame lands on its sign-in page', async () => {
    const { container } = render(<GrafanaEmbed uid="uns-oee" theme="dark" title="OEE" />);
    const frame = container.querySelector('iframe') as HTMLIFrameElement;

    Object.defineProperty(frame, 'contentWindow', {
      configurable: true,
      value: { location: { pathname: '/grafana/login' } },
    });
    act(() => {
      frame.dispatchEvent(new Event('load'));
    });

    await waitFor(() => expect(screen.getByText(/Sign in to Grafana/i)).toBeTruthy());
    const link = screen.getByRole('link', { name: /Sign in to Grafana/i });
    expect(link.getAttribute('href')).toContain('/grafana/');
    expect(link.getAttribute('target')).toBe('_blank');
  });

  it('shows nothing extra when the dashboard loads', async () => {
    const { container } = render(<GrafanaEmbed uid="uns-oee" theme="dark" title="OEE" />);
    const frame = container.querySelector('iframe') as HTMLIFrameElement;
    Object.defineProperty(frame, 'contentWindow', {
      configurable: true,
      value: { location: { pathname: '/grafana/d/uns-oee' } },
    });
    act(() => {
      frame.dispatchEvent(new Event('load'));
    });

    await waitFor(() => expect(container.querySelector('iframe')).toBeTruthy());
    expect(screen.queryByText(/Sign in to Grafana/i)).toBeNull();
  });

  it('shows nothing extra when the frame cannot be inspected at all', async () => {
    const { container } = render(<GrafanaEmbed uid="uns-oee" theme="dark" title="OEE" />);
    const frame = container.querySelector('iframe') as HTMLIFrameElement;
    Object.defineProperty(frame, 'contentWindow', {
      configurable: true,
      get() {
        throw new DOMException('Blocked a frame', 'SecurityError');
      },
    });
    act(() => {
      frame.dispatchEvent(new Event('load'));
    });

    await waitFor(() => expect(container.querySelector('iframe')).toBeTruthy());
    expect(screen.queryByText(/Sign in to Grafana/i)).toBeNull();
  });
});
