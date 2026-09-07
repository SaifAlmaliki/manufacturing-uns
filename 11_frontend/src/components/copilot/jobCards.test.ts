import { describe, expect, it } from 'vitest';
import { JOB_CARDS } from './jobCards';

describe('JOB_CARDS', () => {
  it('has four plant-focused prompts', () => {
    expect(JOB_CARDS).toHaveLength(4);
  });

  it('does not mention schedule or work instructions', () => {
    expect(JOB_CARDS.map((c) => c.prompt).join(' ')).not.toMatch(
      /schedule|instruction|SOP|Brent|Hot Rolling/i,
    );
  });
});
