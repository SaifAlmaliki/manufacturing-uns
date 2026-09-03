import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { ROLE_CONFIGS } from '../../types/rbac';
import { consoleTokens } from '../ui/console-ui';

export const LoginView: React.FC = () => {
  const navigate = useNavigate();
  const { users, login } = useAuth();

  const [userId, setUserId] = useState(users[0]?.id ?? '');
  const [isLoading, setIsLoading] = useState(false);

  const selectedUser = users.find((u) => u.id === userId) ?? users[0];
  const roleLabel = selectedUser ? ROLE_CONFIGS[selectedUser.role]?.label : 'Viewer';

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setTimeout(() => {
      if (login(userId)) {
        navigate('/dashboard');
      }
      setIsLoading(false);
    }, 300);
  };

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

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="login-role" className={consoleTokens.label}>
              Demo account
            </label>
            <select
              id="login-role"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              className={`${consoleTokens.input} cursor-pointer text-sm`}
            >
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} · {ROLE_CONFIGS[u.role]?.label ?? u.role}
                </option>
              ))}
            </select>
          </div>

          <button
            id="login-submit-btn"
            type="submit"
            disabled={isLoading}
            className={`${consoleTokens.btnPrimary} w-full justify-center py-2.5`}
          >
            {isLoading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="mt-6 text-center text-[11px] text-zinc-600">
          {roleLabel} access · demo only
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
