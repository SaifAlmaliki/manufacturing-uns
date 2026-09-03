/**
 * What authentication on this deployment actually covers.
 *
 * This panel exists because the alternative is worse. A console with a sign-in screen and no
 * statement of scope implies a secured platform, and an integration engineer who believes
 * that will expose the broker. The sentence in here is quoted from the specification and
 * asserted verbatim by the test — if the deployment changes so that it is no longer true,
 * that test failing is the point.
 */

import React from 'react';
import { ShieldCheck } from 'lucide-react';

import { useAuth } from '../../context/AuthContext';
import { platformConfig } from '../../lib/platform/config';
import { ROLE_CONFIGS } from '../../types/rbac';

export const AuthenticationPanel: React.FC = () => {
  const { session } = useAuth();

  return (
    <section className="border border-[#1E293B] rounded bg-[#111114] p-4 space-y-3">
      <h2 className="text-[11px] font-bold uppercase tracking-wider text-[#F8FAFC] flex items-center gap-2">
        <ShieldCheck className="w-3.5 h-3.5 text-[#FFC107]" />
        <span>Authentication</span>
      </h2>

      <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1.5 text-[11px]">
        <dt className="text-[#64748B]">Signed in as</dt>
        <dd className="text-[#F8FAFC]">{session?.displayName ?? 'Not signed in'}</dd>

        <dt className="text-[#64748B]">Roles</dt>
        <dd className="text-[#F8FAFC]">
          {session?.roles.length
            ? session.roles.map((role) => ROLE_CONFIGS[role].label).join(', ')
            : 'No console role'}
        </dd>

        <dt className="text-[#64748B]">Realm</dt>
        <dd className="font-mono text-[#94A3B8] break-all">
          {`${platformConfig.authBaseUrl}/realms/${platformConfig.authRealm}`}
        </dd>
      </dl>

      <p className="text-[11px] leading-relaxed text-[#94A3B8]">
        Sign-in protects the console and the GraphQL read surface. The MQTT broker, the graph
        database, the historian and the Kafka broker have no authentication on this deployment.
      </p>
    </section>
  );
};
