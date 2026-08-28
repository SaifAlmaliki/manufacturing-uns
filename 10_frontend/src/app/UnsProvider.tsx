import { createContext, useContext, useReducer, type Dispatch, type ReactNode } from 'react'
import { initialUnsState, unsReducer, type UnsAction, type UnsState } from './uns-reducer'

const StateCtx = createContext<UnsState | null>(null)
const DispatchCtx = createContext<Dispatch<UnsAction> | null>(null)

export function UnsProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(unsReducer, undefined, initialUnsState)
  return (
    <StateCtx.Provider value={state}>
      <DispatchCtx.Provider value={dispatch}>{children}</DispatchCtx.Provider>
    </StateCtx.Provider>
  )
}

export function useUnsState(): UnsState {
  const s = useContext(StateCtx)
  if (!s) {
    throw new Error('useUnsState outside UnsProvider')
  }
  return s
}

export function useUnsDispatch(): Dispatch<UnsAction> {
  const d = useContext(DispatchCtx)
  if (!d) {
    throw new Error('useUnsDispatch outside UnsProvider')
  }
  return d
}
