import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { consoleTokens, FilterToolbar } from './console-ui';

describe('consoleTokens', () => {
  it('uses theme surfaces so light and dark share one palette', () => {
    expect(consoleTokens.page).toContain('bg-background');
    expect(consoleTokens.page).toContain('text-foreground');
    expect(consoleTokens.page).not.toContain('#070709');
    expect(consoleTokens.card).toContain('bg-surface');
    expect(consoleTokens.card).toContain('border-border');
    expect(consoleTokens.pane).toContain('bg-surface');
  });

  it('keeps the orange brand on primary actions in both themes', () => {
    expect(consoleTokens.accent).toBe('#FF7A00');
    expect(consoleTokens.btnPrimary).toContain('bg-[#FF7A00]');
    expect(consoleTokens.btnPrimary).toContain('text-[#140800]');
    expect(consoleTokens.tabActive).toContain('bg-[#FF7A00]');
  });

  it('keeps table selects compact so the selected value is not clipped', () => {
    expect(consoleTokens.select).toContain('h-7');
    expect(consoleTokens.select).toContain('text-foreground');
    expect(consoleTokens.select).not.toContain('py-2.5');
  });
});

describe('FilterToolbar', () => {
  it('stays on one row instead of wrapping selects onto a second line', () => {
    const { container } = render(
      <FilterToolbar
        search={{ value: '', onChange: () => undefined, placeholder: 'Search…' }}
        selects={[
          { value: '', onChange: () => undefined, options: [{ value: '', label: 'All servers' }] },
          { value: '', onChange: () => undefined, options: [{ value: '', label: 'All Assets' }] },
          { value: '', onChange: () => undefined, options: [{ value: '', label: 'All signals' }] },
          { value: '', onChange: () => undefined, options: [{ value: '', label: 'All classes' }] },
          { value: '', onChange: () => undefined, options: [{ value: '', label: 'All labels' }] },
        ]}
      />,
    );
    const bar = container.firstElementChild as HTMLElement;
    expect(bar.className).toMatch(/\bflex-nowrap\b/);
    expect(bar.className).not.toMatch(/\bflex-wrap\b/);
  });
});
