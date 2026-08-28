import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: unknown }) => children,
  LineChart: ({ children }: { children: unknown }) => children,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
}))

