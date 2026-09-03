import React, { useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { platformConfig } from '../../lib/platform/config';
import { consoleTokens } from '../ui/console-ui';

export const LoginView: React.FC = () => {
  const navigate = useNavigate();
  const { login, isAuthenticated, isReady } = useAuth();

  useEffect(() => {
    if (isReady && isAuthenticated) {
      navigate('/tree');
    }
  }, [isReady, isAuthenticated, navigate]);

  return (
    <div className="flex min-h-dvh items-center justify-center bg-[#0a0a0b] p-4 font-sans text-zinc-100">
      <div className={`w-full max-w-sm ${consoleTokens.card} p-8`}>
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex size-11 items-center justify-center rounded-xl bg-[#FF7A00]">
            <span className="text-lg font-bold text-white">U</span>
          </div>
          <h1 className="text-xl font-semibold text-white">UNS Console</h1>
          <p className="mt-1 text-sm text-zinc-500">Sign in to continue</p>
        </div>

        <button
          data-testid="sign-in"
          type="button"
          onClick={login}
          className={`${consoleTokens.btnPrimary} w-full items-center justify-center gap-2 py-2.5`}
        >
          <span>Sign in with Keycloak</span>
          <ChevronRight className="w-4 h-4" />
        </button>

        <p className="mt-6 text-center text-[11px] text-zinc-600">
          Sign-in happens on the plant's Keycloak realm at{' '}
          <span className="font-mono">{platformConfig.authBaseUrl}</span>. The console never
          sees your password.
        </p>

        <p className="mt-4 text-center">
          <Link to="/" className="text-xs text-zinc-500 transition-colors hover:text-[#FF7A00]">
            ← Back to home
          </Link>
        </p>
      </div>
    </div>
  );
};
