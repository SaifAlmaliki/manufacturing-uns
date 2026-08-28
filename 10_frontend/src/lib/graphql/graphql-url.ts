import { platformConfig } from '../platform/config'

export class GraphqlConfigError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'GraphqlConfigError'
  }
}

export function resolveGraphqlHttpUrl(args: {
  prod: boolean
  envUrl: string | undefined
  defaultProdUrl?: string
}): string {
  if (!args.prod) {
    return '/graphql'
  }
  const url = args.envUrl?.trim() || args.defaultProdUrl?.trim()
  if (!url) {
    throw new GraphqlConfigError('Missing VITE_GRAPHQL_URL for production build.')
  }
  return url
}

export function httpToWs(
  httpUrl: string,
  location: { protocol: string; host: string } = window.location,
): string {
  if (httpUrl.startsWith('https://')) {
    return `wss://${httpUrl.slice('https://'.length)}`
  }
  if (httpUrl.startsWith('http://')) {
    return `ws://${httpUrl.slice('http://'.length)}`
  }
  if (httpUrl.startsWith('/')) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    return `${proto}://${location.host}${httpUrl}`
  }
  return httpUrl
}

import { platformConfig } from '../platform/config'

export function getGraphqlHttpUrl(): string {
  return resolveGraphqlHttpUrl({
    prod: import.meta.env.PROD,
    envUrl: import.meta.env.VITE_GRAPHQL_URL,
    defaultProdUrl: platformConfig.graphqlUrl,
  })
}

export function getGraphqlWsUrl(): string {
  return httpToWs(getGraphqlHttpUrl())
}
