import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { NewAssetMenu } from './NewAssetMenu';

describe('NewAssetMenu', () => {
  it('lists Line, Cell, and Machine under an Area', () => {
    const onPick = vi.fn();
    render(<NewAssetMenu parentLevel="area" onPick={onPick} />);
    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    expect(screen.getByRole('menuitem', { name: /^Line/ })).toHaveTextContent(
      'Line — a production line under this area.',
    );
    expect(screen.getByRole('menuitem', { name: /^Machine/ })).toBeTruthy();
    expect(screen.queryByRole('menuitem', { name: /^Site/ })).toBeNull();
  });

  it('calls onPick with machine when Machine is chosen', () => {
    const onPick = vi.fn();
    render(<NewAssetMenu parentLevel="cell" onPick={onPick} />);
    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    fireEvent.click(screen.getByRole('menuitem', { name: /^Machine/ }));
    expect(onPick).toHaveBeenCalledWith('machine');
  });

  it('disables New under a Machine', () => {
    render(<NewAssetMenu parentLevel="machine" onPick={vi.fn()} />);
    const button = screen.getByRole('button', { name: 'New' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute(
      'title',
      'Machine is a leaf — nothing can be added under it.',
    );
  });
});
