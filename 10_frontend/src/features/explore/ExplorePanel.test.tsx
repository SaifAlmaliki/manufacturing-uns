import { MockedProvider, type MockedResponse } from '@apollo/client/testing'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, type ReactNode } from 'react'
import { expect, test } from 'vitest'
import { UnsProvider, useUnsDispatch, useUnsState } from '../../app/UnsProvider'
import type { UnsAction } from '../../app/uns-reducer'
import { GET_HISTORIC_EVENTS, GET_UNS_NODES } from '../../lib/graphql/operations'
import { ExplorePanel } from './ExplorePanel'

const NOW = '2026-08-28T12:00:00Z'

function unsNode(namespace: string, nodeType = 'LINE') {
  return {
    __typename: 'UNSNode',
    nodeName: namespace.split('/').at(-1) ?? namespace,
    nodeType,
    namespace,
    payload: { __typename: 'JSONPayload', data: { rpm: 10 } },
    created: NOW,
    lastUpdated: NOW,
  }
}

function ExploreHarness({
  children,
  boot,
}: {
  children: ReactNode
  boot?: (dispatch: (action: UnsAction) => void) => void
}) {
  function Boot() {
    const dispatch = useUnsDispatch()
    const selected = useUnsState().selectedNamespace
    useEffect(() => {
      boot?.(dispatch)
    }, [dispatch])
    return (
      <>
        {children}
        <div data-testid="selected">{selected ?? ''}</div>
      </>
    )
  }
  return (
    <UnsProvider>
      <Boot />
    </UnsProvider>
  )
}

function renderExplore(mocks: MockedResponse[], boot?: (dispatch: (action: UnsAction) => void) => void) {
  return render(
    <MockedProvider mocks={mocks}>
      <ExploreHarness boot={boot}>
        <ExplorePanel />
      </ExploreHarness>
    </MockedProvider>,
  )
}

test('does not query without criteria and shows hint', async () => {
  const user = userEvent.setup()
  renderExplore([])
  expect(screen.getByText('Enter a topic or property.')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Search' }))
  expect(screen.getByText('Enter a topic or property.')).toBeInTheDocument()
})

test('topic search lists matches', async () => {
  const user = userEvent.setup()
  renderExplore([
    {
      request: { query: GET_UNS_NODES, variables: { topics: [{ topic: 'acme/l1' }] } },
      result: { data: { getUnsNodes: [unsNode('acme/l1')] } },
    },
  ])
  await user.type(screen.getByPlaceholderText('MQTT topic'), 'acme/l1')
  await user.click(screen.getByRole('button', { name: 'Search' }))
  expect(await screen.findByRole('button', { name: /acme\/l1/ })).toBeInTheDocument()
})

test('match-list click selects the namespace', async () => {
  const user = userEvent.setup()
  renderExplore(
    [
      {
        request: { query: GET_UNS_NODES, variables: { topics: [{ topic: 'acme/l1' }] } },
        result: { data: { getUnsNodes: [unsNode('acme/l1')] } },
      },
    ],
    (dispatch) => {
      dispatch({
        type: 'tree/load-ok',
        parent: '',
        nodes: [
          {
            nodeName: 'acme',
            nodeType: 'ENTERPRISE',
            namespace: 'acme',
            payload: {},
            created: NOW,
            lastUpdated: NOW,
          },
          {
            nodeName: 'l1',
            nodeType: 'LINE',
            namespace: 'acme/l1',
            payload: { rpm: 10 },
            created: NOW,
            lastUpdated: NOW,
          },
        ],
      })
    },
  )
  await user.type(screen.getByPlaceholderText('MQTT topic'), 'acme/l1')
  await user.click(screen.getByRole('button', { name: 'Search' }))
  await user.click(await screen.findByRole('button', { name: /acme\/l1/ }))
  expect(await screen.findByTestId('selected')).toHaveTextContent('acme/l1')
})

test('custom from after to disables load history', async () => {
  const user = userEvent.setup()
  renderExplore([], (dispatch) => {
    dispatch({ type: 'ui/select-node', namespace: 'acme/l1' })
  })
  await user.click(screen.getByRole('button', { name: 'custom' }))
  fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-08-28T12:00' } })
  fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-08-28T11:00' } })
  expect(screen.getByText('From must be before to.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Load history' })).toBeDisabled()
})

test('empty historian range copy', async () => {
  const user = userEvent.setup()
  renderExplore(
    [
      {
        request: { query: GET_HISTORIC_EVENTS },
        variableMatcher: (variables: { topics?: { topic: string }[] }) =>
          variables.topics?.[0]?.topic === 'acme/l1/#',
        result: { data: { getHistoricEventsInTimeRange: [] } },
      },
    ],
    (dispatch) => {
      dispatch({ type: 'ui/select-node', namespace: 'acme/l1' })
    },
  )
  await user.click(screen.getByRole('button', { name: 'Load history' }))
  expect(await screen.findByText('No events in this range.')).toBeInTheDocument()
})

test('historian table shows payload preview and numeric field options', async () => {
  const user = userEvent.setup()
  renderExplore(
    [
      {
        request: { query: GET_HISTORIC_EVENTS },
        variableMatcher: (variables: { topics?: { topic: string }[] }) =>
          variables.topics?.[0]?.topic === 'acme/l1/#',
        result: {
          data: {
            getHistoricEventsInTimeRange: [
              {
                __typename: 'HistoricalUNSEvent',
                publisher: 'plc',
                timestamp: NOW,
                topic: 'acme/l1',
                payload: { __typename: 'JSONPayload', data: { rpm: 10 } },
              },
            ],
          },
        },
      },
    ],
    (dispatch) => {
      dispatch({ type: 'ui/select-node', namespace: 'acme/l1' })
    },
  )
  await user.click(screen.getByRole('button', { name: 'Load history' }))
  expect(await screen.findByText('Payload')).toBeInTheDocument()
  expect(screen.getByText('{"rpm":10}')).toBeInTheDocument()
  expect(screen.getByLabelText('Numeric field')).toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'rpm' })).toBeInTheDocument()
})
