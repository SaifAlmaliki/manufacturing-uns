import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { ResizableSidebar } from './resizable-sidebar'

beforeEach(() => {
  window.localStorage.clear()
})

describe('ResizableSidebar', () => {
  it('exposes a vertical resize separator', () => {
    render(
      <ResizableSidebar storageKey="test-tree-width" aria-label="Plant tree">
        <div>tree</div>
      </ResizableSidebar>,
    )
    expect(screen.getByRole('separator', { name: /resize plant tree/i })).toBeTruthy()
    expect(screen.getByLabelText('Plant tree').style.width).toBe('320px')
  })

  it('widens the pane when the separator is moved with the keyboard', () => {
    render(
      <ResizableSidebar storageKey="test-tree-width" defaultWidth={280} aria-label="Plant tree">
        <div>tree</div>
      </ResizableSidebar>,
    )
    fireEvent.keyDown(screen.getByRole('separator', { name: /resize plant tree/i }), {
      key: 'ArrowRight',
      shiftKey: true,
    })
    expect(screen.getByLabelText('Plant tree').style.width).toBe('320px')
  })
})
