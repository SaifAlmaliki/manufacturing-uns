import React from 'react';
import { ShieldAlert, Lock } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { FeatureKey, ROLE_CONFIGS, SYSTEM_FEATURES, UserRole } from '../../types/rbac';

interface AccessRestrictedProps {
  featureKey: FeatureKey;
  featureName?: string;
  onNavigateHome?: () => void;
}

function rolesThatGrant(featureKey: FeatureKey): UserRole[] {
  return (Object.keys(ROLE_CONFIGS) as UserRole[]).filter(
    (role) => ROLE_CONFIGS[role].defaultPermissions[featureKey] === true,
  );
}

export const AccessRestricted: React.FC<AccessRestrictedProps> = ({
  featureKey,
  featureName,
  onNavigateHome,
}) => {
  const { currentUser, roles } = useAuth();

  const featureDef = SYSTEM_FEATURES.find((f) => f.key === featureKey);
  const primaryRole = currentUser?.role ?? roles[0];
  const roleConfig = primaryRole ? ROLE_CONFIGS[primaryRole] : undefined;
  const grantingRoles = rolesThatGrant(featureKey);

  return (
    <div
      id="access-restricted-screen"
      className="flex-1 flex flex-col items-center justify-center p-6 bg-background text-foreground font-mono select-none"
    >
      <div className="w-full max-w-lg bg-surface border border-rose-500/40 rounded-lg p-6 space-y-5 shadow-2xl relative overflow-hidden">
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-rose-600 via-amber-500 to-rose-600" />

        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded bg-rose-950/60 border border-rose-800/80 flex items-center justify-center text-rose-400 shrink-0">
            <Lock className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 rounded bg-rose-950/80 border border-rose-800 text-rose-300 text-[9px] font-bold uppercase tracking-wider">
                RBAC Access Restricted
              </span>
            </div>
            <h2 className="text-base font-bold text-foreground mt-1">
              Permission Required: {featureName || featureDef?.label || featureKey}
            </h2>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              Your signed-in account does not hold a role that opens this screen.
            </p>
          </div>
        </div>

        <div className="p-3.5 rounded bg-muted/60 border border-border space-y-2 text-xs">
          {currentUser && (
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-muted-foreground">Current identity:</span>
              <span className="text-foreground font-bold">{currentUser.name} ({currentUser.email})</span>
            </div>
          )}
          {roleConfig && (
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-muted-foreground">Assigned role:</span>
              <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${roleConfig.badgeBg} ${roleConfig.badgeText} ${roleConfig.badgeBorder}`}>
                {roleConfig.label.toUpperCase()}
              </span>
            </div>
          )}
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-muted-foreground">Required permission:</span>
            <code className="text-[#FF7A00] bg-background px-1.5 py-0.5 rounded border border-border text-[10px]">
              {featureKey}
            </code>
          </div>
          {featureDef && (
            <p className="text-[10px] text-muted-foreground pt-1 border-t border-border">
              {featureDef.description}
            </p>
          )}
        </div>

        <div className="space-y-2.5 pt-1">
          <div className="text-[10px] text-muted-foreground flex items-center gap-1.5">
            <ShieldAlert className="w-3.5 h-3.5 text-[#FF7A00]" />
            <span>
              {grantingRoles.length > 0 ? (
                <>
                  A plant administrator grants the{' '}
                  <b>{grantingRoles.map((r) => ROLE_CONFIGS[r].label).join(' or ')}</b> role in Keycloak.
                </>
              ) : (
                <>No console role grants this feature by default. Ask a plant administrator in Keycloak.</>
              )}
            </span>
          </div>

          {onNavigateHome && (
            <button
              onClick={onNavigateHome}
              className="w-full px-3 py-2 rounded bg-background border border-border hover:bg-muted text-muted-foreground hover:text-foreground text-xs transition-colors cursor-pointer"
            >
              Return to UNS Tree
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
