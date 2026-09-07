import React from 'react';
import { Radio } from 'lucide-react';

interface FactoryCopilotButtonProps {
  onOpen: () => void;
}

export const FactoryCopilotButton: React.FC<FactoryCopilotButtonProps> = ({ onOpen }) => {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="relative flex size-10 items-center justify-center rounded-md border border-border bg-surface text-muted-foreground transition-colors hover:text-[#FF7A00]"
      aria-label="Factory Copilot"
      title="Factory Copilot"
    >
      <Radio className="size-[18px]" />
    </button>
  );
};
