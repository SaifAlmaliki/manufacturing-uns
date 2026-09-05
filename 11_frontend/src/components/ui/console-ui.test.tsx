import { describe, expect, it } from 'vitest';
import { consoleTokens } from './console-ui';

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
});
