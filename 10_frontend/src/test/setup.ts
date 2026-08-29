import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
})

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: unknown }) => children,
  LineChart: ({ children }: { children: unknown }) => children,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
}))

