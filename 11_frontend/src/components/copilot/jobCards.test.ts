import { describe, expect, it } from 'vitest';
import { JOB_CARDS, jobCards } from './jobCards';

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

describe('jobCards', () => {
  it('plant cards mention plant not this Asset', () => {
    const text = jobCards(false).map((c) => c.prompt).join(' ');
    expect(text).toMatch(/my plant/i);
    expect(text).not.toMatch(/Asset I am looking at/i);
  });

  it('focus cards mention the Asset I am looking at', () => {
    const text = jobCards(true).map((c) => c.prompt).join(' ');
    expect(text).toMatch(/Asset I am looking at/i);
  });

  it('has the same four ids regardless of focus', () => {
    const ids = (cards: { id: string }[]) => cards.map((c) => c.id).sort();
    expect(ids(jobCards(true))).toEqual(ids(jobCards(false)));
  });
});
