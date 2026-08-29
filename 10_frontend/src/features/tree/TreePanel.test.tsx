import { MockedProvider, type MockedResponse } from '@apollo/client/testing'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { UnsProvider, useUnsState } from '../../app/UnsProvider'
import { GET_UNS_NODES } from '../../lib/graphql/operations'
import { TreePanel } from './TreePanel'

const NOW = new Date().toISOString()

function unsNode(namespace: string, nodeType: string) {
  return {
    __typename: 'UNSNode',
    nodeName: namespace.split('/').at(-1) ?? namespace,
    nodeType,
    namespace,
    payload: { __typename: 'JSONPayload', data: { ok: true } },
    created: NOW,
    lastUpdated: NOW,
  }
}

function TreePanelHarness() {
  const selected = useUnsState().selectedNamespace
  return (
    <>
      <TreePanel />
      <div data-testid="selected">{selected ?? ''}</div>
    </>
  )
}

function renderTree(mocks: MockedResponse[]) {
  return render(
    <MockedProvider mocks={mocks}>
      <UnsProvider>
        <TreePanelHarness />
      </UnsProvider>
    </MockedProvider>,
  )
}

test('loads root nodes and selects on click', async () => {
  const user = userEvent.setup()
  renderTree([
    {
      request: { query: GET_UNS_NODES, variables: { topics: [{ topic: '+' }] } },
      result: { data: { getUnsNodes: [unsNode('acme', 'ENTERPRISE')] } },
    },
  ])
  expect(await screen.findByText('acme', { selector: 'span.truncate' })).toBeInTheDocument()
  await user.click(screen.getByRole('treeitem'))
  expect(screen.getByTestId('selected').textContent).toBe('acme')
  expect(screen.getByRole('treeitem')).toHaveAttribute('aria-selected', 'true')
})

test('expands a namespace and loads its children', async () => {
  const user = userEvent.setup()
  renderTree([
    {
      request: { query: GET_UNS_NODES, variables: { topics: [{ topic: '+' }] } },
      result: { data: { getUnsNodes: [unsNode('acme', 'ENTERPRISE')] } },
    },
    {
      request: { query: GET_UNS_NODES, variables: { topics: [{ topic: 'acme/+' }] } },
      result: { data: { getUnsNodes: [unsNode('acme/plant1', 'FACILITY')] } },
    },
  ])
  expect(await screen.findByText('acme', { selector: 'span.truncate' })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Expand' }))
  expect(await screen.findByText('plant1')).toBeInTheDocument()
})
