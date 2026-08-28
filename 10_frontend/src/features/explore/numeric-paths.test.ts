import { expect, test } from 'vitest'
import { getNumericPath, numericLeafPaths } from './numeric-paths'

test('flattens numeric leaves', () => {
  const paths = numericLeafPaths({
    rpm: 10,
    nested: { temp: 3.2, name: 'x' },
    tags: [{ v: 1 }, { v: 2 }],
  })
  expect(paths).toContain('rpm')
  expect(paths).toContain('nested.temp')
  expect(paths).toContain('tags[0].v')
  expect(paths).not.toContain('nested.name')
})

test('reads a numeric path', () => {
  expect(getNumericPath({ nested: { temp: 3.2 } }, 'nested.temp')).toBe(3.2)
  expect(getNumericPath({ tags: [{ v: 1 }] }, 'tags[0].v')).toBe(1)
  expect(getNumericPath({ rpm: 1 }, 'missing')).toBeUndefined()
})
