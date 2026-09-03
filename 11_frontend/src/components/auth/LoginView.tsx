import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Layers,
  ArrowLeft,
  Lock,
  Mail,
  KeyRound,
  Shield,
  CheckCircle2,
  Building2,
  Sun,
  Moon,
  ChevronRight,
  UserCheck,
  AlertCircle,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useTheme } from '../../context/ThemeContext';
import { ROLE_CONFIGS } from '../../types/rbac';

export const LoginView: React.FC = () => {
  const navigate = useNavigate();
  const { users, currentUser, login, isAuthenticated } = useAuth();
  const { isDark, toggleTheme } = useTheme();

  const [selectedUserId, setSelectedUserId] = useState<string>(currentUser?.id || 'usr-admin-01');
  const [email, setEmail] = useState<string>(currentUser?.email || 'admin@enterprise-domain.com');
  const [password, setPassword] = useState<string>('••••••••••••');
  const [plantLocation, setPlantLocation] = useState<string>('Facility Alpha - Manufacturing Campus');
  const [rememberMe, setRememberMe] = useState<boolean>(true);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleSelectQuickUser = (user: (typeof users)[0]) => {
    setSelectedUserId(user.id);
    setEmail(user.email);
    setPlantLocation(user.plantLocation || 'Facility Alpha - Manufacturing Campus');
    setErrorMsg(null);
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setErrorMsg(null);

    setTimeout(() => {
      const success = login(selectedUserId || email, password);
      setIsLoading(false);
      if (success) {
        navigate('/dashboard');
      } else {
        setErrorMsg('Invalid enterprise credentials. Please check your email or select a demo role.');
      }
    }, 450);
  };

  const selectedUserObj = users.find((u) => u.id === selectedUserId) || users[0];
  const roleConfig = ROLE_CONFIGS[selectedUserObj.role] || ROLE_CONFIGS.viewer;

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-[#050505] text-[#0F172A] dark:text-[#F8FAFC] flex flex-col font-sans selection:bg-amber-400/30 selection:text-amber-900 dark:selection:text-[#FFC107] transition-colors duration-200">
      {/* Top Header Bar */}
      <header className="px-4 sm:px-8 py-3.5 border-b border-[#E2E8F0] dark:border-[#1E293B] bg-white dark:bg-[#0B0B0C] flex items-center justify-between">
        <Link
          to="/"
          className="flex items-center gap-2 text-xs font-semibold text-[#475569] dark:text-[#94A3B8] hover:text-amber-600 dark:hover:text-[#FFC107] transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Return to Landing Page</span>
        </Link>

        <div className="flex items-center gap-3">
          <button
            onClick={toggleTheme}
            className="p-1.5 rounded-lg bg-[#F8FAFC] dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] hover:border-amber-400 dark:hover:border-[#334155] text-[#475569] dark:text-[#94A3B8] transition-colors cursor-pointer"
            title={`Switch to ${isDark ? 'Light' : 'Dark'} mode`}
          >
            {isDark ? <Sun className="w-4 h-4 text-[#FFC107]" /> : <Moon className="w-4 h-4 text-slate-700" />}
          </button>
        </div>
      </header>

      {/* Main Login Card Container */}
      <div className="flex-1 flex items-center justify-center p-4 sm:p-6 my-auto">
        <div className="w-full max-w-xl bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-2xl shadow-xl p-6 sm:p-8 space-y-6">
          {/* Brand & Heading */}
          <div className="text-center space-y-2">
            <div className="inline-flex w-12 h-12 rounded-xl bg-amber-500/10 dark:bg-[#FFC107]/10 border border-amber-500/30 dark:border-[#FFC107]/30 items-center justify-center text-amber-600 dark:text-[#FFC107] mb-1 shadow-xs">
              <Layers className="w-6 h-6" />
            </div>
            <h1 className="font-serif text-2xl sm:text-3xl font-bold tracking-tight text-[#0F172A] dark:text-[#F8FAFC]">
              UNS Console Sign In
            </h1>
            <p className="text-xs sm:text-sm text-[#64748B]">
              Authenticate to access your plant's ISA-95 Unified Namespace &amp; MQTT telemetry
            </p>
          </div>

          {/* Quick 1-Click Role Profiles Selector */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-[11px] font-mono uppercase tracking-wider text-[#64748B]">
              <span>Select Demo Identity (1-Click)</span>
              <span className="text-amber-600 dark:text-[#FFC107] font-bold">RBAC Ready</span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {users.slice(0, 4).map((u) => {
                const isSelected = u.id === selectedUserId;
                return (
                  <button
                    key={u.id}
                    type="button"
                    onClick={() => handleSelectQuickUser(u)}
                    className={`flex items-center gap-2.5 p-2.5 rounded-lg border text-left transition-all cursor-pointer ${
                      isSelected
                        ? 'bg-amber-50 dark:bg-amber-950/30 border-amber-500 dark:border-[#FFC107] shadow-xs'
                        : 'bg-white dark:bg-[#0B0B0C] border-[#E2E8F0] dark:border-[#1E293B] hover:border-slate-300 dark:hover:border-[#334155]'
                    }`}
                  >
                    <div
                      className={`w-7 h-7 rounded-full ${
                        u.avatarColor || 'bg-amber-500'
                      } flex items-center justify-center text-xs font-bold text-slate-950 shrink-0`}
                    >
                      {u.name.charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="font-bold text-xs text-[#0F172A] dark:text-[#F8FAFC] truncate flex items-center justify-between">
                        <span>{u.name}</span>
                        {isSelected && <CheckCircle2 className="w-3.5 h-3.5 text-amber-600 dark:text-[#FFC107]" />}
                      </div>
                      <div className="text-[10px] text-[#64748B] truncate">{u.department}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Form */}
          <form onSubmit={handleFormSubmit} className="space-y-4">
            {errorMsg && (
              <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800/40 text-rose-700 dark:text-rose-400 text-xs flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{errorMsg}</span>
              </div>
            )}

            {/* Email Field */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-[#0F172A] dark:text-[#F8FAFC]">
                Enterprise Email Address
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#64748B]" />
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] rounded-lg pl-9 pr-3 py-2 text-xs text-[#0F172A] dark:text-[#F8FAFC] placeholder-[#64748B] focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107] font-mono transition-colors"
                  placeholder="operator@enterprise-domain.com"
                />
              </div>
            </div>

            {/* Password Field */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="block text-xs font-semibold text-[#0F172A] dark:text-[#F8FAFC]">
                  Password / PIN
                </label>
                <span className="text-[10px] text-[#64748B] font-mono">Demo Auto-Filled</span>
              </div>
              <div className="relative">
                <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#64748B]" />
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] rounded-lg pl-9 pr-3 py-2 text-xs text-[#0F172A] dark:text-[#F8FAFC] placeholder-[#64748B] focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107] font-mono transition-colors"
                  placeholder="••••••••••••"
                />
              </div>
            </div>

            {/* Plant Facility Selector */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-[#0F172A] dark:text-[#F8FAFC]">
                Plant Facility &amp; Subsystem
              </label>
              <div className="relative">
                <Building2 className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#64748B]" />
                <select
                  value={plantLocation}
                  onChange={(e) => setPlantLocation(e.target.value)}
                  className="w-full bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] rounded-lg pl-9 pr-3 py-2 text-xs text-[#0F172A] dark:text-[#F8FAFC] focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107] font-mono transition-colors cursor-pointer"
                >
                  <option value="Facility Alpha - Manufacturing Campus">Facility Alpha - Manufacturing Campus</option>
                  <option value="Facility Beta - Advanced Assembly Center">Facility Beta - Advanced Assembly Center</option>
                  <option value="Facility Gamma - Regional Hub">Facility Gamma - Regional Operations Hub</option>
                  <option value="Facility Delta - Edge Operations">Facility Delta - Edge IoT &amp; Telemetry Node</option>
                  <option value="Central Control Room">Central Control Room &amp; Operations</option>
                </select>
              </div>
            </div>

            {/* Remember Me */}
            <div className="flex items-center justify-between text-xs text-[#64748B] pt-1">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  className="rounded border-[#CBD5E1] dark:border-[#334155] text-amber-500 focus:ring-amber-400"
                />
                <span>Remember session on this workstation</span>
              </label>
            </div>

            {/* Submit Button */}
            <button
              id="login-submit-btn"
              type="submit"
              disabled={isLoading}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-lg bg-amber-500 hover:bg-amber-600 dark:bg-[#FFC107] dark:hover:bg-[#FFB300] text-slate-950 font-bold text-xs uppercase tracking-wider shadow-md transition-all cursor-pointer disabled:opacity-50"
            >
              {isLoading ? (
                <span>Authenticating Session...</span>
              ) : (
                <>
                  <span>Sign In as {selectedUserObj.name}</span>
                  <ChevronRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>

          {/* Security Notice */}
          <div className="p-3 rounded-lg bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] text-[11px] text-[#64748B] flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Shield className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
              <span>ISO/IEC 62443 Security Auditing Enabled</span>
            </div>
            <span className="font-mono text-[10px] text-amber-600 dark:text-[#FFC107]">TLS 1.3</span>
          </div>
        </div>
      </div>
    </div>
  );
};
