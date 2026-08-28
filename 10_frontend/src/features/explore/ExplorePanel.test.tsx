import { MockedProvider } from '@apollo/client/testing'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { UnsProvider } from '../../app/UnsProvider'
import { ExplorePanel } from './ExplorePanel'

test('does not query without criteria and shows hint', async () => {
  const user = userEvent.setup()
  render(
    <MockedProvider mocks={[]}>
      <UnsProvider>
        <ExplorePanel />
      </UnsProvider>
    </MockedProvider>,
  )
  expect(screen.getByText('Enter a topic or property.')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Search' }))
  expect(screen.getByText('Enter a topic or property.')).toBeInTheDocument()
})
