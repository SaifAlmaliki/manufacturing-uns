import { MockedProvider } from '@apollo/client/testing'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { GET_UNS_NODES } from '../../lib/graphql/operations'
import { UnsProvider } from '../../app/UnsProvider'
import { TreePanel } from './TreePanel'

test('loads root nodes and selects one', async () => {
  const user = userEvent.setup()
  const mocks = [
    {
      request: {
        query: GET_UNS_NODES,
        variables: { topics: [{ topic: '+' }] },
      },
      result: {
        data: {
          getUnsNodes: [
            {
              nodeName: 'acme',
              nodeType: 'ENTERPRISE',
              namespace: 'acme',
              payload: { data: { site: 1 } },
              created: 'c',
              lastUpdated: new Date().toISOString(),
            },
          ],
        },
      },
    },
  ]
  render(
    <MockedProvider mocks={mocks} addTypename={false}>
      <UnsProvider>
        <TreePanel />
      </UnsProvider>
    </MockedProvider>,
  )
  expect(await screen.findByText('acme')).toBeInTheDocument()
  await user.click(screen.getByText('acme'))
  expect(screen.getByRole('treeitem').getAttribute('aria-selected')).toBe('true')
})
