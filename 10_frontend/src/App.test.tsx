import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, test } from 'vitest'
import { UnsProvider } from './app/UnsProvider'
import { ConsoleHeader } from './features/shell/AppShell'

test('renders Unified Namespace title and nav', () => {
  render(
    <MemoryRouter>
      <UnsProvider>
        <ConsoleHeader />
      </UnsProvider>
    </MemoryRouter>,
  )
  expect(screen.getByText('Unified Namespace')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/')
  expect(screen.getByRole('link', { name: 'Explore' })).toHaveAttribute('href', '/explore')
  expect(screen.getByText('Down')).toBeInTheDocument()
})
