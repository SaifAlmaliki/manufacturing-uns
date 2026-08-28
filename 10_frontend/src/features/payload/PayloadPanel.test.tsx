import { render, screen } from '@testing-library/react'
import { useEffect, type ReactNode } from 'react'
import { expect, test } from 'vitest'
import { UnsProvider, useUnsDispatch } from '../../app/UnsProvider'
import { PayloadPanel } from './PayloadPanel'

function Harness({ children, boot }: { children: ReactNode; boot: (d: ReturnType<typeof useUnsDispatch>) => void }) {
  function Boot() {
    const dispatch = useUnsDispatch()
    useEffect(() => {
      boot(dispatch)
    }, [dispatch])
    return children
  }
  return (
    <UnsProvider>
      <Boot />
    </UnsProvider>
  )
}

test('empty selection prompt', () => {
  render(
    <UnsProvider>
      <PayloadPanel />
    </UnsProvider>,
  )
  expect(screen.getByText('Pick a node in the tree.')).toBeInTheDocument()
})

test('shows node payload json', async () => {
  render(
    <Harness
      boot={(dispatch) => {
        dispatch({
          type: 'tree/load-ok',
          parent: '',
          nodes: [
            {
              nodeName: 'l1',
              nodeType: 'LINE',
              namespace: 'acme/l1',
              payload: { rpm: 42 },
              created: 'c',
              lastUpdated: 'u',
            },
          ],
        })
        dispatch({ type: 'ui/select-node', namespace: 'acme/l1' })
      }}
    >
      <PayloadPanel />
    </Harness>,
  )
  expect(await screen.findByText(/rpm/)).toBeInTheDocument()
})

test('shows historical event label', async () => {
  render(
    <Harness
      boot={(dispatch) => {
        dispatch({
          type: 'ui/select-historic-event',
          event: {
            topic: 'acme/l1',
            timestamp: 't',
            publisher: 'plc',
            payload: { temp: 1 },
          },
        })
      }}
    >
      <PayloadPanel />
    </Harness>,
  )
  expect(await screen.findByText('Historical event')).toBeInTheDocument()
})
