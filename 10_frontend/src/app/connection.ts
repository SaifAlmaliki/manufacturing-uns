export type ConnectionChip = 'live' | 'degraded' | 'down'

export function connectionChip(httpOk: boolean, wsOk: boolean): ConnectionChip {
  if (httpOk && wsOk) {
    return 'live'
  }
  if (httpOk || wsOk) {
    return 'degraded'
  }
  return 'down'
}

export function connectionLabel(chip: ConnectionChip, httpOk: boolean, wsOk: boolean): string {
  if (chip === 'live') {
    return 'Live'
  }
  if (chip === 'down') {
    return 'Down'
  }
  if (!httpOk && wsOk) {
    return 'Degraded — GraphQL queries down'
  }
  return 'Degraded — live feed down'
}
