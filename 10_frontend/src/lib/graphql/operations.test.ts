import { Kind, visit, type FieldNode } from 'graphql'
import { expect, test } from 'vitest'
import { MQTT_FEED } from './operations'

function dataFieldInFragment(typeName: string): FieldNode | undefined {
  let field: FieldNode | undefined
  visit(MQTT_FEED, {
    InlineFragment(node) {
      if (node.typeCondition?.name.value !== typeName) {
        return
      }
      for (const selection of node.selectionSet.selections) {
        if (selection.kind === Kind.FIELD && selection.name.value === 'data') {
          field = selection
        }
      }
    },
  })
  return field
}

test('mqtt feed aliases BytesPayload data so it does not conflict with JSONPayload data', () => {
  const jsonData = dataFieldInFragment('JSONPayload')
  const bytesData = dataFieldInFragment('BytesPayload')
  expect(jsonData).toBeDefined()
  expect(bytesData).toBeDefined()
  expect(bytesData?.alias?.value).toBe('bytesData')
  expect(jsonData?.alias).toBeUndefined()
})
