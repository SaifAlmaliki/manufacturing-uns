import { MockedProvider } from '@apollo/client/testing'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { GET_UNS_NODES } from '../../lib/graphql/operations'
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

test('topic search lists matches', async () => {
  const user = userEvent.setup()
  const mocks = [
    {
      request: {
        query: GET_UNS_NODES,
        variables: { topics: [{ topic: 'acme/#' }] },
      },
      result: {
        data: {
          getUnsNodes: [
            {
              __typename: 'UNSNode',
              nodeName: 'l1',
              nodeType: 'LINE',
              namespace: 'acme/l1',
              payload: { data: { rpm: 1 } },
              created: 'c',
              lastUpdated: 'u',
            },
          ],
        },
      },
    },
  ]
  render(
    <MockedProvider mocks={mocks}>
      <UnsProvider>
        <ExplorePanel />
      </UnsProvider>
    </MockedProvider>,
  )
  await user.type(screen.getByPlaceholderText('MQTT topic'), 'acme/#')
  await user.click(screen.getByRole('button', { name: 'Search' }))
  expect(await screen.findByText(/acme\/l1/)).toBeInTheDocument()
})
