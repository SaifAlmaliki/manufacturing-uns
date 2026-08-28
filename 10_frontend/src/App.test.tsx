import { MockedProvider } from '@apollo/client/testing'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, test } from 'vitest'
import { UnsProvider } from './app/UnsProvider'
import { AppShell } from './features/shell/AppShell'

test('renders Unified Namespace title and nav', () => {
  render(
    <MockedProvider mocks={[]} addTypename={false}>
      <MemoryRouter>
        <UnsProvider>
          <AppShell />
        </UnsProvider>
      </MemoryRouter>
    </MockedProvider>,
  )
  expect(screen.getByText('Unified Namespace')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/')
  expect(screen.getByRole('link', { name: 'Explore' })).toHaveAttribute('href', '/explore')
  expect(screen.getByText('Down')).toBeInTheDocument()
})
