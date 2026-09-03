import { describe, expect, it } from 'vitest';
import { CONSOLE_ROLES, featureAllowed, rolesFromClaims, toUserRole } from './roles';

describe('toUserRole', () => {
  it('accepts the five the platform knows', () => {
    expect(CONSOLE_ROLES.map(toUserRole)).toEqual([...CONSOLE_ROLES]);
  });

  it('is case-insensitive, because the GraphQL enum is upper case', () => {
    expect(toUserRole('ENGINEER')).toBe('engineer');
  });

  it('drops anything unrecognised rather than guessing', () => {
    // The precedent is map-alert-rules.ts: "notifying the wrong role is worse than
    // notifying nobody". The same reasoning applies to granting the wrong one.
    expect(toUserRole('offline_access')).toBeUndefined();
    expect(toUserRole('default-roles-uns')).toBeUndefined();
    expect(toUserRole('')).toBeUndefined();
    expect(toUserRole(null)).toBeUndefined();
  });
});

describe('rolesFromClaims', () => {
  it('reads Keycloak realm roles', () => {
    expect(rolesFromClaims({ realm_access: { roles: ['engineer', 'viewer'] } }))
      .toEqual(['engineer', 'viewer']);
  });

  it('drops the roles Keycloak gives everybody', () => {
    const roles = rolesFromClaims({
      realm_access: { roles: ['offline_access', 'uma_authorization', 'default-roles-uns', 'operator'] },
    });
    expect(roles).toEqual(['operator']);
  });

  it('is empty rather than throwing when the claim is missing or misshapen', () => {
    // A console that crashed on an unexpected token would be indistinguishable from an
    // outage, and this runs before anything is rendered.
    expect(rolesFromClaims({})).toEqual([]);
    expect(rolesFromClaims(null)).toEqual([]);
    expect(rolesFromClaims({ realm_access: 'engineer' })).toEqual([]);
    expect(rolesFromClaims({ realm_access: { roles: 'engineer' } })).toEqual([]);
  });

  it('deduplicates and keeps a stable order', () => {
    expect(rolesFromClaims({ realm_access: { roles: ['viewer', 'admin', 'viewer'] } }))
      .toEqual(['admin', 'viewer']);
  });
});

describe('featureAllowed', () => {
  it('reads the role profiles already in rbac.ts rather than inventing a second table', () => {
    expect(featureAllowed(['admin'], 'user_management')).toBe(true);
    expect(featureAllowed(['viewer'], 'user_management')).toBe(false);
  });

  it('grants a feature any one of the held roles grants', () => {
    // viewer.historian is false and engineer.historian is true, so this fails if the
    // implementation intersects the roles instead of unioning them.
    expect(featureAllowed(['viewer', 'engineer'], 'historian')).toBe(true);
    expect(featureAllowed(['viewer'], 'historian')).toBe(false);
  });

  it('grants nothing to a user with no recognised role', () => {
    expect(featureAllowed([], 'uns_tree')).toBe(false);
  });
});
