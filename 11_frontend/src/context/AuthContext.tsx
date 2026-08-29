/**
 * Auth & RBAC State Provider
 * Manages user accounts, active user session simulation, granular feature permissions,
 * and security audit logs with LocalStorage persistence.
 */

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import {
  UserAccount,
  UserRole,
  FeatureKey,
  AuditLogEntry,
  ROLE_CONFIGS,
  SYSTEM_FEATURES,
} from '../types/rbac';

const STORAGE_KEYS = {
  USERS: 'uns_rbac_users_v2',
  CURRENT_USER_ID: 'uns_rbac_current_user_id_v2',
  AUDIT_LOGS: 'uns_rbac_audit_logs_v2',
  IS_LOGGED_IN: 'uns_rbac_logged_in_v2',
};

// Initial Seed Users for Industrial UNS Console
const INITIAL_USERS: UserAccount[] = [
  {
    id: 'usr-admin-01',
    name: 'Saif (Admin)',
    email: 'saif.wsm@gmail.com',
    role: 'admin',
    department: 'Enterprise Architecture & SecOps',
    plantLocation: 'Dormagen Global HQ',
    avatarColor: 'bg-rose-500',
    status: 'active',
    createdAt: '2026-01-15T08:00:00.000Z',
    lastLogin: '2026-08-29T04:40:00.000Z',
    customPermissions: { ...ROLE_CONFIGS.admin.defaultPermissions },
    notes: 'Primary System Administrator with root access to UNS infrastructure and RBAC grants.',
  },
  {
    id: 'usr-eng-02',
    name: 'Elena Rostova',
    email: 'elena.rostova@covestro.com',
    role: 'engineer',
    department: 'Automation & Process Engineering',
    plantLocation: 'Line 1 Extrusion Plant',
    avatarColor: 'bg-[#FFC107]',
    status: 'active',
    createdAt: '2026-02-10T10:15:00.000Z',
    lastLogin: '2026-08-29T02:15:00.000Z',
    customPermissions: { ...ROLE_CONFIGS.engineer.defaultPermissions },
    notes: 'Process Lead for Dormagen Polymer reactors and Sparkplug B edge node mapping.',
  },
  {
    id: 'usr-op-03',
    name: 'Marcus Weber',
    email: 'marcus.weber@covestro.com',
    role: 'operator',
    department: 'Plant Operations & Dispatch',
    plantLocation: 'Control Room B',
    avatarColor: 'bg-emerald-500',
    status: 'active',
    createdAt: '2026-03-01T14:30:00.000Z',
    lastLogin: '2026-08-28T22:00:00.000Z',
    customPermissions: { ...ROLE_CONFIGS.operator.defaultPermissions },
    notes: 'Shift supervisor monitoring real-time reactor telemetry and Sparkplug edge health.',
  },
  {
    id: 'usr-aud-04',
    name: 'Sarah Jenkins',
    email: 'sarah.jenkins@covestro.com',
    role: 'auditor',
    department: 'ISO/IEC 62443 Compliance',
    plantLocation: 'Quality & Audit Center',
    avatarColor: 'bg-purple-500',
    status: 'active',
    createdAt: '2026-04-12T09:00:00.000Z',
    lastLogin: '2026-08-27T11:20:00.000Z',
    customPermissions: { ...ROLE_CONFIGS.auditor.defaultPermissions },
    notes: 'Audits historical Timescale historian events and Kafka message retention policies.',
  },
  {
    id: 'usr-view-05',
    name: 'Alex Chen',
    email: 'alex.chen@partner.com',
    role: 'viewer',
    department: 'External Integration Partner',
    plantLocation: 'Remote Access',
    avatarColor: 'bg-slate-500',
    status: 'active',
    createdAt: '2026-06-20T16:00:00.000Z',
    lastLogin: '2026-08-26T18:45:00.000Z',
    customPermissions: { ...ROLE_CONFIGS.viewer.defaultPermissions },
    notes: 'Contractor given limited read-only visibility into public UNS tree namespaces.',
  },
];

const INITIAL_AUDIT_LOGS: AuditLogEntry[] = [
  {
    id: 'log-001',
    timestamp: new Date(Date.now() - 3600000 * 24 * 3).toISOString(),
    actorEmail: 'saif.wsm@gmail.com',
    targetUserEmail: 'elena.rostova@covestro.com',
    action: 'CREATE_USER',
    details: 'Created Engineer account with default engineering telemetry permissions.',
  },
  {
    id: 'log-002',
    timestamp: new Date(Date.now() - 3600000 * 12).toISOString(),
    actorEmail: 'saif.wsm@gmail.com',
    targetUserEmail: 'marcus.weber@covestro.com',
    action: 'UPDATE_PERMISSIONS',
    details: 'Granted topic_bookmarks access for shift monitoring.',
  },
];

interface AuthContextType {
  currentUser: UserAccount;
  users: UserAccount[];
  auditLogs: AuditLogEntry[];
  isAdmin: boolean;
  isAuthenticated: boolean;
  login: (identifier: string, password?: string) => boolean;
  logout: () => void;
  switchUser: (userId: string) => void;
  createUser: (userData: Omit<UserAccount, 'id' | 'createdAt' | 'lastLogin'>) => UserAccount;
  updateUser: (userId: string, updates: Partial<UserAccount>) => void;
  deleteUser: (userId: string) => void;
  toggleUserFeaturePermission: (userId: string, feature: FeatureKey, allowed: boolean) => void;
  resetUserToRoleDefaults: (userId: string, role?: UserRole) => void;
  hasPermission: (feature: FeatureKey) => boolean;
  getUserPermission: (user: UserAccount, feature: FeatureKey) => boolean;
  canAccessTab: (tab: string) => { allowed: boolean; requiredFeature: FeatureKey; featureName: string };
  restoreDefaults: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [users, setUsers] = useState<UserAccount[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.USERS);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }
    } catch {
      // ignore
    }
    return INITIAL_USERS;
  });

  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.IS_LOGGED_IN);
      return saved === 'true';
    } catch {
      return false;
    }
  });

  const [currentUserId, setCurrentUserId] = useState<string>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.CURRENT_USER_ID);
      if (saved) return saved;
    } catch {
      // ignore
    }
    return 'usr-admin-01'; // Default to Admin
  });

  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.AUDIT_LOGS);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch {
      // ignore
    }
    return INITIAL_AUDIT_LOGS;
  });

  // Save changes to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.IS_LOGGED_IN, String(isAuthenticated));
    } catch {
      // ignore
    }
  }, [isAuthenticated]);

  // Save changes to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.USERS, JSON.stringify(users));
    } catch {
      // ignore
    }
  }, [users]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.CURRENT_USER_ID, currentUserId);
    } catch {
      // ignore
    }
  }, [currentUserId]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.AUDIT_LOGS, JSON.stringify(auditLogs));
    } catch {
      // ignore
    }
  }, [auditLogs]);

  // Current active user
  const currentUser = users.find((u) => u.id === currentUserId) || users[0] || INITIAL_USERS[0];
  const isAdmin = currentUser.role === 'admin' || currentUser.customPermissions.user_management === true;

  const logAction = useCallback(
    (action: AuditLogEntry['action'], targetUserEmail: string, details: string) => {
      const newEntry: AuditLogEntry = {
        id: `log-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`,
        timestamp: new Date().toISOString(),
        actorEmail: currentUser.email,
        targetUserEmail,
        action,
        details,
      };
      setAuditLogs((prev) => [newEntry, ...prev]);
    },
    [currentUser.email]
  );

  const switchUser = useCallback((userId: string) => {
    const target = users.find((u) => u.id === userId);
    if (target) {
      setCurrentUserId(userId);
      // Update lastLogin
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, lastLogin: new Date().toISOString() } : u))
      );
    }
  }, [users]);

  const createUser = useCallback(
    (userData: Omit<UserAccount, 'id' | 'createdAt' | 'lastLogin'>): UserAccount => {
      const newId = `usr-${Date.now().toString(36)}`;
      const roleConfig = ROLE_CONFIGS[userData.role] || ROLE_CONFIGS.viewer;
      const initialPermissions = userData.customPermissions || { ...roleConfig.defaultPermissions };

      const colors = ['bg-rose-500', 'bg-amber-500', 'bg-emerald-500', 'bg-purple-500', 'bg-cyan-500', 'bg-blue-500'];
      const randomColor = colors[Math.floor(Math.random() * colors.length)];

      const newUser: UserAccount = {
        ...userData,
        id: newId,
        avatarColor: userData.avatarColor || randomColor,
        createdAt: new Date().toISOString(),
        lastLogin: 'Never',
        customPermissions: initialPermissions,
      };

      setUsers((prev) => [...prev, newUser]);
      logAction('CREATE_USER', newUser.email, `Created user account with role '${newUser.role}'`);
      return newUser;
    },
    [logAction]
  );

  const updateUser = useCallback(
    (userId: string, updates: Partial<UserAccount>) => {
      setUsers((prev) =>
        prev.map((u) => {
          if (u.id === userId) {
            const updated = { ...u, ...updates };
            if (updates.role && updates.role !== u.role) {
              logAction('UPDATE_ROLE', u.email, `Changed role from '${u.role}' to '${updates.role}'`);
            }
            if (updates.status && updates.status !== u.status) {
              logAction('TOGGLE_STATUS', u.email, `Changed account status to '${updates.status}'`);
            }
            return updated;
          }
          return u;
        })
      );
    },
    [logAction]
  );

  const deleteUser = useCallback(
    (userId: string) => {
      const target = users.find((u) => u.id === userId);
      if (!target) return;
      if (target.id === currentUser.id) {
        alert('Cannot delete the currently logged-in account.');
        return;
      }
      setUsers((prev) => prev.filter((u) => u.id !== userId));
      logAction('DELETE_USER', target.email, `Deleted user account '${target.name}'`);
    },
    [users, currentUser.id, logAction]
  );

  const toggleUserFeaturePermission = useCallback(
    (userId: string, feature: FeatureKey, allowed: boolean) => {
      setUsers((prev) =>
        prev.map((u) => {
          if (u.id === userId) {
            const nextPermissions = {
              ...u.customPermissions,
              [feature]: allowed,
            };
            logAction(
              'UPDATE_PERMISSIONS',
              u.email,
              `${allowed ? 'Granted' : 'Revoked'} permission for feature '${feature}'`
            );
            return { ...u, customPermissions: nextPermissions };
          }
          return u;
        })
      );
    },
    [logAction]
  );

  const resetUserToRoleDefaults = useCallback(
    (userId: string, newRole?: UserRole) => {
      setUsers((prev) =>
        prev.map((u) => {
          if (u.id === userId) {
            const effectiveRole = newRole || u.role;
            const roleConfig = ROLE_CONFIGS[effectiveRole] || ROLE_CONFIGS.viewer;
            const nextPermissions = { ...roleConfig.defaultPermissions };
            logAction(
              'UPDATE_PERMISSIONS',
              u.email,
              `Reset permissions to '${effectiveRole}' default profile`
            );
            return {
              ...u,
              role: effectiveRole,
              customPermissions: nextPermissions,
            };
          }
          return u;
        })
      );
    },
    [logAction]
  );

  const getUserPermission = useCallback((user: UserAccount, feature: FeatureKey): boolean => {
    if (user.role === 'admin') return true;
    if (user.status !== 'active') return false;
    return !!user.customPermissions?.[feature];
  }, []);

  const hasPermission = useCallback(
    (feature: FeatureKey): boolean => {
      return getUserPermission(currentUser, feature);
    },
    [currentUser, getUserPermission]
  );

  const canAccessTab = useCallback(
    (tab: string): { allowed: boolean; requiredFeature: FeatureKey; featureName: string } => {
      let requiredFeature: FeatureKey = 'uns_tree';
      let featureName = 'UNS Tree';

      switch (tab) {
        case 'home':
          requiredFeature = 'uns_tree';
          featureName = 'UNS Tree & Node Hierarchy';
          break;
        case 'explore':
          requiredFeature = 'historian';
          featureName = 'TimescaleDB Historian';
          break;
        case 'sparkplug':
          requiredFeature = 'sparkplug';
          featureName = 'Sparkplug B Decoder';
          break;
        case 'streams':
          requiredFeature = 'streams';
          featureName = 'Kafka Streams Monitor';
          break;
        case 'alarms':
          requiredFeature = 'alarms';
          featureName = 'Alarms & Alert Management';
          break;
        case 'system':
          requiredFeature = 'system_ops';
          featureName = 'System Health & Operations';
          break;
        case 'users':
          requiredFeature = 'user_management';
          featureName = 'User Management & RBAC';
          break;
      }

      const allowed = hasPermission(requiredFeature);
      return { allowed, requiredFeature, featureName };
    },
    [hasPermission]
  );

  const login = useCallback(
    (identifier: string, _password?: string): boolean => {
      // Find matching user by id or email or case-insensitive search
      const user =
        users.find((u) => u.id === identifier) ||
        users.find((u) => u.email.toLowerCase() === identifier.toLowerCase().trim()) ||
        users.find((u) => u.name.toLowerCase().includes(identifier.toLowerCase().trim())) ||
        users[0];

      if (user) {
        setCurrentUserId(user.id);
        setIsAuthenticated(true);
        setUsers((prev) =>
          prev.map((u) => (u.id === user.id ? { ...u, lastLogin: new Date().toISOString() } : u))
        );
        logAction('USER_LOGIN' as any, user.email, `User '${user.name}' logged into UNS Console via Enterprise Portal`);
        return true;
      }
      return false;
    },
    [users, logAction]
  );

  const logout = useCallback(() => {
    setIsAuthenticated(false);
    logAction('USER_LOGOUT' as any, currentUser.email, `User '${currentUser.name}' signed out of console`);
  }, [currentUser, logAction]);

  const restoreDefaults = useCallback(() => {
    setUsers(INITIAL_USERS);
    setCurrentUserId('usr-admin-01');
    setIsAuthenticated(false);
    setAuditLogs(INITIAL_AUDIT_LOGS);
    try {
      localStorage.removeItem(STORAGE_KEYS.USERS);
      localStorage.removeItem(STORAGE_KEYS.CURRENT_USER_ID);
      localStorage.removeItem(STORAGE_KEYS.AUDIT_LOGS);
      localStorage.removeItem(STORAGE_KEYS.IS_LOGGED_IN);
    } catch {
      // ignore
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        currentUser,
        users,
        auditLogs,
        isAdmin,
        isAuthenticated,
        login,
        logout,
        switchUser,
        createUser,
        updateUser,
        deleteUser,
        toggleUserFeaturePermission,
        resetUserToRoleDefaults,
        hasPermission,
        getUserPermission,
        canAccessTab,
        restoreDefaults,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
};
