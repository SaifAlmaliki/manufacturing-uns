import { beforeEach, describe, expect, it, vi } from 'vitest'
import { UnsGraphQLClient } from './client'

const auth = vi.hoisted(() => ({
  token: vi.fn(() => 'test.access.token' as string | null),
  refresh: vi.fn(async () => null),
  onExpired: vi.fn(),
}))

const ok = (data: unknown) =>
  ({ ok: true, status: 200, json: async () => ({ data }) }) as unknown as Response

beforeEach(() => {
  vi.clearAllMocks()
})

const client = () => new UnsGraphQLClient('/graphql', 'ws://test/graphql', auth)

const PLANT = {
  enterprise: 'DemoWTP',
  sites: [
    {
      name: 'Site10',
      areas: [
        {
          name: 'RawWater',
          kind: 'production',
          lines: [{ name: 'Train10', cells: [{ name: 'P202', machines: ['Machine3050'] }] }],
        },
      ],
    },
  ],
}

function mockGraphql(handlers: Record<string, unknown>) {
  const fetchMock = vi.fn().mockImplementation(async (_url: string, init: { body: string }) => {
    const body = JSON.parse(init.body) as { query: string }
    for (const [needle, data] of Object.entries(handlers)) {
      if (body.query.includes(needle)) return ok(data)
    }
    throw new Error(`unexpected query: ${body.query.slice(0, 80)}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('getUnsRootNodes', () => {
  it('uses the plant hierarchy enterprise as the only root', async () => {
    const fetchMock = mockGraphql({
      getHierarchy: { getHierarchy: PLANT },
      getAssetChildren: {
        getAssetChildren: [
          {
            path: 'AcmeWater',
            name: 'AcmeWater',
            segment: 'AcmeWater',
            level: 'ENTERPRISE',
            isActive: true,
          },
        ],
      },
      getUnsNodes: { getUnsNodes: [{ nodeName: 'test', nodeType: 'ENTERPRISE', namespace: 'test' }] },
    })

    const roots = await client().getUnsRootNodes()

    expect(roots).toHaveLength(1)
    expect(roots[0].topic).toBe('DemoWTP')
    expect(roots[0].name).toBe('DemoWTP')
    expect(fetchMock.mock.calls.some(([, init]) => JSON.parse(init.body).query.includes('getAssetChildren'))).toBe(
      false,
    )
  })
})

describe('getUnsNodeChildren', () => {
  it('expands the plant tree instead of leftover MQTT prefixes', async () => {
    mockGraphql({
      getHierarchy: { getHierarchy: PLANT },
      getAssetChildren: { getAssetChildren: [] },
      getUnsNodes: { getUnsNodes: [{ nodeName: 'sim', nodeType: 'AREA', namespace: 'test/uns/edge/sim' }] },
    })

    const children = await client().getUnsNodeChildren('DemoWTP')

    expect(children.map((n) => n.topic)).toEqual(['DemoWTP/Site10'])
  })
})
