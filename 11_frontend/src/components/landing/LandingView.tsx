import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Layers,
  ArrowRight,
  Shield,
  Activity,
  Cpu,
  Radio,
  Workflow,
  Search,
  Bell,
  CheckCircle2,
  Database,
  Lock,
  ChevronRight,
  Sun,
  Moon,
  Zap,
  Globe,
  Factory,
  BarChart3,
  Terminal,
  Server,
  Play,
  Award,
  Box,
  Binary,
  GitBranch,
  RefreshCw,
  Sliders,
  FileCode2,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useTheme } from '../../context/ThemeContext';
import heroImage from '../../assets/images/smart_factory_uns_1788007138686.jpg';

export const LandingView: React.FC = () => {
  const navigate = useNavigate();
  const { isAuthenticated, currentUser, login } = useAuth();
  const { isDark, toggleTheme } = useTheme();

  const [activeProtobufTab, setActiveProtobufTab] = useState<'decoded' | 'raw' | 'schema'>('decoded');

  const scrollToSection = (sectionId: string) => {
    const el = document.getElementById(sectionId);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' });
    }
  };

  const handleLaunchConsole = (roleId?: string) => {
    if (roleId) {
      login(roleId);
    }
    if (isAuthenticated || roleId) {
      navigate('/tree');
    } else {
      navigate('/login');
    }
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-[#050505] text-[#0F172A] dark:text-[#F8FAFC] flex flex-col font-sans selection:bg-amber-400/30 selection:text-amber-900 dark:selection:text-[#FFC107] transition-colors duration-200">
      {/* Top Navigation Bar */}
      <header className="sticky top-0 z-50 bg-white/90 dark:bg-[#0B0B0C]/90 backdrop-blur-md border-b border-[#E2E8F0] dark:border-[#1E293B] px-4 sm:px-8 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-amber-500/10 dark:bg-[#FFC107]/10 border border-amber-500/30 dark:border-[#FFC107]/30 flex items-center justify-center text-amber-600 dark:text-[#FFC107] shadow-xs">
            <Layers className="w-5 h-5" />
          </div>
          <div>
            <div className="font-serif font-bold text-base sm:text-lg tracking-tight leading-none text-[#0F172A] dark:text-[#F8FAFC]">
              UNS<span className="text-amber-600 dark:text-[#FFC107]">CONSOLE</span>
            </div>
            <div className="text-[10px] text-[#64748B] font-mono tracking-wider uppercase mt-0.5">
              ISA-95 Unified Namespace
            </div>
          </div>
        </div>

        {/* Center Desktop Navigation Links (Smooth scrolling handlers, avoids modifying HashRouter route) */}
        <nav className="hidden lg:flex items-center gap-6 text-xs font-medium text-[#475569] dark:text-[#94A3B8]">
          <button
            onClick={() => scrollToSection('features-section')}
            className="hover:text-amber-600 dark:hover:text-[#FFC107] transition-colors cursor-pointer"
          >
            Core Engine
          </button>
          <button
            onClick={() => scrollToSection('architecture-section')}
            className="hover:text-amber-600 dark:hover:text-[#FFC107] transition-colors cursor-pointer"
          >
            ISA-95 Hierarchy
          </button>
          <button
            onClick={() => scrollToSection('sparkplug-section')}
            className="hover:text-amber-600 dark:hover:text-[#FFC107] transition-colors cursor-pointer flex items-center gap-1"
          >
            <span>Sparkplug B &amp; Edge</span>
            <span className="px-1.5 py-0.2 rounded bg-amber-500/10 dark:bg-amber-500/20 text-amber-600 dark:text-amber-400 font-mono text-[9px] font-bold">
              v3.0
            </span>
          </button>
          <button
            onClick={() => scrollToSection('compliance-section')}
            className="hover:text-amber-600 dark:hover:text-[#FFC107] transition-colors cursor-pointer"
          >
            Security &amp; RBAC
          </button>
          <button
            onClick={() => scrollToSection('plants-section')}
            className="hover:text-amber-600 dark:hover:text-[#FFC107] transition-colors cursor-pointer"
          >
            Multi-Site Operations
          </button>
        </nav>

        {/* Right Actions */}
        <div className="flex items-center gap-3">
          {/* Light / Dark Mode Toggle */}
          <button
            id="landing-theme-toggle-btn"
            onClick={toggleTheme}
            className="p-2 rounded-lg bg-[#F8FAFC] dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] hover:border-amber-400 dark:hover:border-[#334155] text-[#475569] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC] transition-colors cursor-pointer"
            title={`Switch to ${isDark ? 'Light' : 'Dark'} mode`}
          >
            {isDark ? <Sun className="w-4 h-4 text-[#FFC107]" /> : <Moon className="w-4 h-4 text-slate-700" />}
          </button>

          {isAuthenticated ? (
            <button
              id="landing-nav-enter-console-btn"
              onClick={() => navigate('/tree')}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-600 dark:bg-[#FFC107] dark:hover:bg-[#FFB300] text-slate-950 font-bold text-xs shadow-sm transition-all cursor-pointer"
            >
              <span>Enter Console ({currentUser.name})</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          ) : (
            <>
              <button
                id="landing-nav-login-btn"
                onClick={() => navigate('/login')}
                className="hidden sm:inline-flex px-3.5 py-2 text-xs font-semibold text-[#0F172A] dark:text-[#F8FAFC] hover:text-amber-600 dark:hover:text-[#FFC107] transition-colors cursor-pointer"
              >
                Sign In
              </button>
              <button
                id="landing-nav-get-started-btn"
                onClick={() => navigate('/login')}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-600 dark:bg-[#FFC107] dark:hover:bg-[#FFB300] text-slate-950 font-bold text-xs shadow-sm transition-all cursor-pointer"
              >
                <span>Access Console</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </>
          )}
        </div>
      </header>

      {/* Main Hero Section */}
      <section className="relative pt-12 pb-16 lg:pt-20 lg:pb-24 px-4 sm:px-8 max-w-7xl mx-auto w-full">
        {/* Background ambient accents */}
        <div className="absolute top-10 left-1/2 -translate-x-1/2 w-3/4 h-96 bg-amber-500/5 dark:bg-[#FFC107]/5 blur-3xl -z-10 rounded-full pointer-events-none" />

        <div className="text-center max-w-4xl mx-auto space-y-6">
          {/* Eyebrow badge */}
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-[#FFC107]/30 text-amber-900 dark:text-[#FFC107] text-[11px] font-semibold tracking-wide shadow-xs">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="font-mono uppercase">ISA-95 &amp; Sparkplug B Certified</span>
            <span className="text-[#CBD5E1] dark:text-[#334155]">|</span>
            <span>Multi-Tenant Enterprise Platform v2.8</span>
          </div>

          {/* High-Impact Classic Serif Headline */}
          <h1 className="font-serif text-3xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-[#0F172A] dark:text-[#F8FAFC] leading-[1.15]">
            The Unified Namespace for Modern Smart Manufacturing
          </h1>

          {/* Subtitle */}
          <p className="text-base sm:text-lg text-[#475569] dark:text-[#94A3B8] font-normal leading-relaxed max-w-3xl mx-auto">
            A universal, multi-tenant industrial data platform. Standardize shop-floor telemetry, Sparkplug B edge computing, TimescaleDB time-series historian analytics, and ISO/IEC 62443 security across any manufacturing site or enterprise client.
          </p>

          {/* Primary Action Buttons */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3.5 pt-2">
            <button
              id="hero-launch-primary-btn"
              onClick={() => handleLaunchConsole()}
              className="w-full sm:w-auto flex items-center justify-center gap-2.5 px-6 py-3.5 rounded-lg bg-amber-500 hover:bg-amber-600 dark:bg-[#FFC107] dark:hover:bg-[#FFB300] text-slate-950 font-bold text-sm shadow-md transition-all cursor-pointer"
            >
              <span>Launch Enterprise Console</span>
              <ArrowRight className="w-4 h-4" />
            </button>

            <button
              onClick={() => scrollToSection('architecture-section')}
              className="w-full sm:w-auto flex items-center justify-center gap-2 px-5 py-3.5 rounded-lg bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] hover:border-amber-400 dark:hover:border-[#334155] text-[#0F172A] dark:text-[#F8FAFC] font-semibold text-sm transition-colors cursor-pointer shadow-xs"
            >
              <span>Explore ISA-95 Architecture</span>
              <ChevronRight className="w-4 h-4 text-[#64748B]" />
            </button>
          </div>

          {/* Instant Role Access Bar */}
          <div className="pt-3 flex flex-wrap items-center justify-center gap-2 text-xs text-[#64748B]">
            <span className="font-medium text-[#475569] dark:text-[#94A3B8]">Quick Demo Logins:</span>
            <button
              onClick={() => handleLaunchConsole('usr-admin-01')}
              className="px-2.5 py-1 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] hover:border-amber-500 text-[#0F172A] dark:text-[#F8FAFC] font-mono text-[11px] font-semibold transition-colors cursor-pointer"
            >
              👑 System Admin
            </button>
            <button
              onClick={() => handleLaunchConsole('usr-eng-02')}
              className="px-2.5 py-1 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] hover:border-amber-500 text-[#0F172A] dark:text-[#F8FAFC] font-mono text-[11px] font-semibold transition-colors cursor-pointer"
            >
              ⚙️ Process Engineer
            </button>
            <button
              onClick={() => handleLaunchConsole('usr-op-03')}
              className="px-2.5 py-1 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] hover:border-amber-500 text-[#0F172A] dark:text-[#F8FAFC] font-mono text-[11px] font-semibold transition-colors cursor-pointer"
            >
              🎛️ Shift Operator
            </button>
          </div>
        </div>

        {/* Hero Visual Showcase with Generated Image */}
        <div className="mt-12 lg:mt-16 relative rounded-2xl overflow-hidden border border-[#CBD5E1] dark:border-[#1E293B] shadow-2xl bg-slate-900 group">
          {/* Top Industrial Header Overlay */}
          <div className="absolute top-0 inset-x-0 bg-slate-950/80 backdrop-blur-md px-4 py-2.5 border-b border-white/10 flex items-center justify-between z-20 text-xs">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" />
              <span className="font-mono text-emerald-400 font-bold text-[11px] tracking-wider uppercase">
                EMQX Broker: CONNECTED
              </span>
              <span className="text-slate-500">|</span>
              <span className="font-mono text-slate-300 text-[11px] hidden sm:inline">
                Enterprise/Site_Alpha/Processing_Plant_01
              </span>
            </div>
            <div className="flex items-center gap-2 font-mono text-[10px] text-amber-400">
              <span className="px-2 py-0.5 rounded bg-amber-500/20 border border-amber-500/40">
                MQTT 5.0 + Protobuf
              </span>
            </div>
          </div>

          {/* Generated Hero Image */}
          <div className="relative aspect-[16/9] w-full max-h-[580px] overflow-hidden">
            <img
              src={heroImage}
              alt="Smart Factory Industrial Control Room with ISA-95 Unified Namespace"
              className="w-full h-full object-cover object-center transform group-hover:scale-[1.01] transition-transform duration-700"
              referrerPolicy="no-referrer"
            />
            {/* Dark vignette gradient overlay for contrast */}
            <div className="absolute inset-0 bg-gradient-to-t from-slate-950 via-slate-950/30 to-transparent" />
          </div>

          {/* Bottom Floating Telemetry Bar */}
          <div className="absolute bottom-4 inset-x-4 sm:inset-x-6 bg-slate-950/85 backdrop-blur-md border border-white/15 rounded-xl p-4 z-20 grid grid-cols-2 sm:grid-cols-4 gap-4 text-left">
            <div>
              <div className="text-[10px] font-mono text-slate-400 uppercase tracking-wider">Broker Throughput</div>
              <div className="text-base sm:text-lg font-mono font-bold text-amber-400 flex items-center gap-1.5 mt-0.5">
                <Activity className="w-4 h-4 text-amber-400" />
                <span>64.8 msg/sec</span>
              </div>
            </div>
            <div>
              <div className="text-[10px] font-mono text-slate-400 uppercase tracking-wider">ISA-95 Hierarchy</div>
              <div className="text-base sm:text-lg font-mono font-bold text-white flex items-center gap-1.5 mt-0.5">
                <Layers className="w-4 h-4 text-sky-400" />
                <span>142 Active Nodes</span>
              </div>
            </div>
            <div>
              <div className="text-[10px] font-mono text-slate-400 uppercase tracking-wider">Sparkplug B Edge</div>
              <div className="text-base sm:text-lg font-mono font-bold text-emerald-400 flex items-center gap-1.5 mt-0.5">
                <Radio className="w-4 h-4 text-emerald-400" />
                <span>8 Gateways Online</span>
              </div>
            </div>
            <div>
              <div className="text-[10px] font-mono text-slate-400 uppercase tracking-wider">Historian Latency</div>
              <div className="text-base sm:text-lg font-mono font-bold text-purple-400 flex items-center gap-1.5 mt-0.5">
                <Database className="w-4 h-4 text-purple-400" />
                <span>1.4ms Ingestion</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Industrial Key Metric Stats */}
      <section className="border-y border-[#E2E8F0] dark:border-[#1E293B] bg-white dark:bg-[#0B0B0C] py-8 px-4 sm:px-8">
        <div className="max-w-7xl mx-auto grid grid-cols-2 md:grid-cols-4 gap-6 text-center">
          <div>
            <div className="font-serif text-2xl sm:text-3xl font-bold text-[#0F172A] dark:text-[#F8FAFC]">
              99.999%
            </div>
            <div className="text-xs text-[#64748B] font-medium mt-1">Message Delivery SLA</div>
          </div>
          <div>
            <div className="font-serif text-2xl sm:text-3xl font-bold text-amber-600 dark:text-[#FFC107]">
              &lt; 5 ms
            </div>
            <div className="text-xs text-[#64748B] font-medium mt-1">End-to-End MQTT Latency</div>
          </div>
          <div>
            <div className="font-serif text-2xl sm:text-3xl font-bold text-[#0F172A] dark:text-[#F8FAFC]">
              Multi-Client
            </div>
            <div className="text-xs text-[#64748B] font-medium mt-1">Automotive, Chemicals, Pharma, F&amp;B, Energy</div>
          </div>
          <div>
            <div className="font-serif text-2xl sm:text-3xl font-bold text-emerald-600 dark:text-emerald-400">
              ISO/IEC 62443
            </div>
            <div className="text-xs text-[#64748B] font-medium mt-1">Industrial Security Compliance</div>
          </div>
        </div>
      </section>

      {/* Core Platform Features Section */}
      <section id="features-section" className="py-16 sm:py-24 px-4 sm:px-8 max-w-7xl mx-auto w-full">
        <div className="text-center max-w-3xl mx-auto space-y-3 mb-14">
          <div className="text-xs font-mono uppercase tracking-widest text-amber-600 dark:text-[#FFC107] font-semibold">
            Enterprise Architecture
          </div>
          <h2 className="font-serif text-2xl sm:text-4xl font-bold text-[#0F172A] dark:text-[#F8FAFC]">
            Engineered for Mission-Critical Manufacturing
          </h2>
          <p className="text-sm sm:text-base text-[#475569] dark:text-[#94A3B8]">
            An open, standard-based operational technology stack that replaces proprietary protocols with clean, discoverable event streams.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {/* Card 1: ISA-95 Hierarchy */}
          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-6 space-y-4 hover:border-amber-400 dark:hover:border-amber-500/50 transition-all shadow-xs group">
            <div className="w-10 h-10 rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800/40 flex items-center justify-center text-amber-600 dark:text-[#FFC107]">
              <Layers className="w-5 h-5" />
            </div>
            <h3 className="font-serif text-lg font-bold text-[#0F172A] dark:text-[#F8FAFC]">
              ISA-95 Semantic Tree Hierarchy
            </h3>
            <p className="text-xs sm:text-sm text-[#475569] dark:text-[#94A3B8] leading-relaxed">
              Standardized tree topology from Enterprise down to individual sensor telemetry. Dynamic single-level wildcards (+) and multi-level hierarchy queries (#).
            </p>
            <div className="pt-2 text-[11px] font-mono text-amber-600 dark:text-[#FFC107] flex items-center gap-1">
              <span>Enterprise / Site / Area / Line / WorkCell</span>
            </div>
          </div>

          {/* Card 2: Sparkplug B */}
          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-6 space-y-4 hover:border-amber-400 dark:hover:border-amber-500/50 transition-all shadow-xs group">
            <div className="w-10 h-10 rounded-lg bg-sky-50 dark:bg-sky-950/40 border border-sky-200 dark:border-sky-800/40 flex items-center justify-center text-sky-600 dark:text-sky-400">
              <Radio className="w-5 h-5" />
            </div>
            <h3 className="font-serif text-lg font-bold text-[#0F172A] dark:text-[#F8FAFC]">
              Sparkplug B Edge Decoder
            </h3>
            <p className="text-xs sm:text-sm text-[#475569] dark:text-[#94A3B8] leading-relaxed">
              Real-time Google Protobuf payload unpacking, NBIRTH, DBIRTH, NDATA, and DDATA state tracking with automatic metric aliases and quality codes.
            </p>
            <div className="pt-2 text-[11px] font-mono text-sky-600 dark:text-sky-400 flex items-center gap-1">
              <span>spBv1.0 Payload &amp; Device Lifecycle</span>
            </div>
          </div>

          {/* Card 3: TimescaleDB Historian */}
          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-6 space-y-4 hover:border-amber-400 dark:hover:border-amber-500/50 transition-all shadow-xs group">
            <div className="w-10 h-10 rounded-lg bg-purple-50 dark:bg-purple-950/40 border border-purple-200 dark:border-purple-800/40 flex items-center justify-center text-purple-600 dark:text-purple-400">
              <Database className="w-5 h-5" />
            </div>
            <h3 className="font-serif text-lg font-bold text-[#0F172A] dark:text-[#F8FAFC]">
              TimescaleDB Telemetry Historian
            </h3>
            <p className="text-xs sm:text-sm text-[#475569] dark:text-[#94A3B8] leading-relaxed">
              Time-bucket aggregations (1s, 5s, 1m, 1h), interactive multi-variable trend charts, anomaly bounds, and one-click CSV / JSON telemetry export.
            </p>
            <div className="pt-2 text-[11px] font-mono text-purple-600 dark:text-purple-400 flex items-center gap-1">
              <span>Sub-second Hypertable Analytics</span>
            </div>
          </div>

          {/* Card 4: Alarm Management */}
          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-6 space-y-4 hover:border-amber-400 dark:hover:border-amber-500/50 transition-all shadow-xs group">
            <div className="w-10 h-10 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800/40 flex items-center justify-center text-rose-600 dark:text-rose-400">
              <Bell className="w-5 h-5" />
            </div>
            <h3 className="font-serif text-lg font-bold text-[#0F172A] dark:text-[#F8FAFC]">
              ISA-18.2 Process Alarm Matrix
            </h3>
            <p className="text-xs sm:text-sm text-[#475569] dark:text-[#94A3B8] leading-relaxed">
              Configurable threshold triggers (High-High, High, Low, Low-Low), audible alarms, operator shelving, role-scoped dispatch, and audit logging.
            </p>
            <div className="pt-2 text-[11px] font-mono text-rose-600 dark:text-rose-400 flex items-center gap-1">
              <span>Critical Alert State Engine</span>
            </div>
          </div>

          {/* Card 5: Kafka Event Streams */}
          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-6 space-y-4 hover:border-amber-400 dark:hover:border-amber-500/50 transition-all shadow-xs group">
            <div className="w-10 h-10 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/40 flex items-center justify-center text-emerald-600 dark:text-emerald-400">
              <Workflow className="w-5 h-5" />
            </div>
            <h3 className="font-serif text-lg font-bold text-[#0F172A] dark:text-[#F8FAFC]">
              Kafka Event Stream Pipeline
            </h3>
            <p className="text-xs sm:text-sm text-[#475569] dark:text-[#94A3B8] leading-relaxed">
              Industrial Kafka bridge streaming enterprise events across multiple partitions, consumer groups, dead-letter queues, and deterministic replays.
            </p>
            <div className="pt-2 text-[11px] font-mono text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
              <span>Distributed Enterprise Bus</span>
            </div>
          </div>

          {/* Card 6: ISO/IEC 62443 Security */}
          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-6 space-y-4 hover:border-amber-400 dark:hover:border-amber-500/50 transition-all shadow-xs group">
            <div className="w-10 h-10 rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800/40 flex items-center justify-center text-amber-600 dark:text-[#FFC107]">
              <Lock className="w-5 h-5" />
            </div>
            <h3 className="font-serif text-lg font-bold text-[#0F172A] dark:text-[#F8FAFC]">
              RBAC &amp; Security Compliance
            </h3>
            <p className="text-xs sm:text-sm text-[#475569] dark:text-[#94A3B8] leading-relaxed">
              Granular permission matrix across 5 industrial roles (Admin, Engineer, Operator, Auditor, Viewer), plant-level authorization, and immutable audit logs.
            </p>
            <div className="pt-2 text-[11px] font-mono text-amber-600 dark:text-[#FFC107] flex items-center gap-1">
              <span>ISO/IEC 62443 Cybersecurity</span>
            </div>
          </div>
        </div>
      </section>

      {/* Interactive ISA-95 Tree Hierarchy Showcase (Generic Multi-Client) */}
      <section id="architecture-section" className="py-16 bg-[#F1F5F9] dark:bg-[#0B0B0C] border-y border-[#E2E8F0] dark:border-[#1E293B] px-4 sm:px-8">
        <div className="max-w-7xl mx-auto space-y-8">
          <div className="text-center max-w-2xl mx-auto space-y-2">
            <div className="text-xs font-mono uppercase tracking-wider text-amber-600 dark:text-[#FFC107] font-semibold">
              Semantic Architecture
            </div>
            <h2 className="font-serif text-2xl sm:text-3xl font-bold text-[#0F172A] dark:text-[#F8FAFC]">
              How the ISA-95 Namespace Bridges OT &amp; IT
            </h2>
            <p className="text-xs sm:text-sm text-[#475569] dark:text-[#94A3B8]">
              Every sensor, machine, PLC, and robot publishes to a strictly standardized, self-describing topic path adaptable to any plant topology.
            </p>
          </div>

          {/* Interactive Topology Visualizer (Generic Multi-Tenant) */}
          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-6 shadow-sm">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 text-xs font-mono">
              <div className="p-3.5 rounded-lg bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800/30 space-y-1">
                <div className="text-[10px] text-amber-700 dark:text-amber-400 font-bold uppercase">Level 1: Enterprise</div>
                <div className="font-bold text-[#0F172A] dark:text-[#F8FAFC]">Global Enterprise</div>
                <div className="text-[10px] text-[#64748B]">Multi-Tenant Corporate Group</div>
              </div>
              <div className="p-3.5 rounded-lg bg-slate-50 dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] space-y-1">
                <div className="text-[10px] text-sky-700 dark:text-sky-400 font-bold uppercase">Level 2: Site</div>
                <div className="font-bold text-[#0F172A] dark:text-[#F8FAFC]">Facility Alpha</div>
                <div className="text-[10px] text-[#64748B]">Primary Manufacturing Campus</div>
              </div>
              <div className="p-3.5 rounded-lg bg-slate-50 dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] space-y-1">
                <div className="text-[10px] text-emerald-700 dark:text-emerald-400 font-bold uppercase">Level 3: Area</div>
                <div className="font-bold text-[#0F172A] dark:text-[#F8FAFC]">Processing Area 01</div>
                <div className="text-[10px] text-[#64748B]">Continuous Operations Facility</div>
              </div>
              <div className="p-3.5 rounded-lg bg-slate-50 dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] space-y-1">
                <div className="text-[10px] text-purple-700 dark:text-purple-400 font-bold uppercase">Level 4: Line</div>
                <div className="font-bold text-[#0F172A] dark:text-[#F8FAFC]">Production Line 01</div>
                <div className="text-[10px] text-[#64748B]">Automated Continuous Line</div>
              </div>
              <div className="p-3.5 rounded-lg bg-slate-50 dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] space-y-1">
                <div className="text-[10px] text-rose-700 dark:text-rose-400 font-bold uppercase">Level 5: Work Cell</div>
                <div className="font-bold text-[#0F172A] dark:text-[#F8FAFC]">Robotics &amp; Unit 01</div>
                <div className="text-[10px] text-[#64748B]">Vibration &amp; Sensor Telemetry</div>
              </div>
            </div>

            {/* Example Live Topic Result */}
            <div className="mt-4 p-3 rounded-lg bg-[#0B0B0C] text-emerald-400 font-mono text-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 border border-[#1E293B]">
              <div className="flex items-center gap-2">
                <span className="text-amber-400 font-bold">MQTT TOPIC:</span>
                <span className="text-white">Enterprise/Facility_Alpha/Processing_Area_01/Production_Line_01/Robotics_01/telemetry</span>
              </div>
              <span className="px-2 py-0.5 rounded bg-emerald-950/60 border border-emerald-700/60 text-[10px] text-emerald-300">
                RETAINED • JSON • 100ms
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* DEDICATED SPARKPLUG B & EDGE TECHNOLOGY SECTION */}
      <section id="sparkplug-section" className="py-16 sm:py-24 px-4 sm:px-8 max-w-7xl mx-auto w-full">
        <div className="text-center max-w-3xl mx-auto space-y-3 mb-14">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-sky-50 dark:bg-sky-950/40 border border-sky-300 dark:border-sky-800/40 text-sky-800 dark:text-sky-400 text-xs font-mono font-semibold">
            <Radio className="w-3.5 h-3.5 text-sky-500" />
            <span>Sparkplug B 2.2 / 3.0 Standard Protocol</span>
          </div>
          <h2 className="font-serif text-2xl sm:text-4xl font-bold text-[#0F172A] dark:text-[#F8FAFC]">
            High-Performance Sparkplug B Edge Computing
          </h2>
          <p className="text-sm sm:text-base text-[#475569] dark:text-[#94A3B8]">
            Turn raw telemetry into strongly-typed industrial metrics with Google Protocol Buffers, state awareness, and automated birth/death edge lifecycle management.
          </p>
        </div>

        {/* Sparkplug Protocol Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: Protocol Features */}
          <div className="lg:col-span-5 space-y-4">
            <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-5 space-y-3 shadow-xs">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-sky-50 dark:bg-sky-950/50 border border-sky-200 dark:border-sky-800/50 flex items-center justify-center text-sky-600 dark:text-sky-400">
                  <Binary className="w-4 h-4" />
                </div>
                <div>
                  <div className="font-serif font-bold text-sm text-[#0F172A] dark:text-[#F8FAFC]">
                    Google Protobuf Encoding
                  </div>
                  <div className="text-[11px] text-[#64748B]">80% Bandwidth Compression vs JSON</div>
                </div>
              </div>
              <p className="text-xs text-[#475569] dark:text-[#94A3B8] leading-relaxed">
                Binary payload unpacking with sub-millisecond parsing speed. Eliminates network congestion on constrained cellular and industrial wireless fieldbuses.
              </p>
            </div>

            <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-5 space-y-3 shadow-xs">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-emerald-50 dark:bg-emerald-950/50 border border-emerald-200 dark:border-emerald-800/50 flex items-center justify-center text-emerald-600 dark:text-emerald-400">
                  <RefreshCw className="w-4 h-4" />
                </div>
                <div>
                  <div className="font-serif font-bold text-sm text-[#0F172A] dark:text-[#F8FAFC]">
                    Deterministic Lifecycle State Machine
                  </div>
                  <div className="text-[11px] text-[#64748B]">NBIRTH • DBIRTH • NDATA • DDATA • NDEATH</div>
                </div>
              </div>
              <p className="text-xs text-[#475569] dark:text-[#94A3B8] leading-relaxed">
                Never wonder if a machine is silent or disconnected. Sparkplug B manages online/offline state transitions with MQTT Last Will and Testament (LWT).
              </p>
            </div>

            <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-5 space-y-3 shadow-xs">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-amber-50 dark:bg-amber-950/50 border border-amber-200 dark:border-amber-800/50 flex items-center justify-center text-amber-600 dark:text-[#FFC107]">
                  <Sliders className="w-4 h-4" />
                </div>
                <div>
                  <div className="font-serif font-bold text-sm text-[#0F172A] dark:text-[#F8FAFC]">
                    Metric Aliasing &amp; Quality Codes
                  </div>
                  <div className="text-[11px] text-[#64748B]">OPC-UA Quality Integration (560 Good)</div>
                </div>
              </div>
              <p className="text-xs text-[#475569] dark:text-[#94A3B8] leading-relaxed">
                Publish heavy string metric names only on birth messages, transmitting lightweight numeric integer aliases during continuous operational cycles.
              </p>
            </div>
          </div>

          {/* Right Column: Interactive Sparkplug Payload Inspector */}
          <div className="lg:col-span-7 bg-[#0B0B0C] border border-[#1E293B] rounded-xl overflow-hidden shadow-xl flex flex-col">
            {/* Header / Tabs */}
            <div className="p-3 bg-[#111114] border-b border-[#1E293B] flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Radio className="w-4 h-4 text-sky-400" />
                <span className="font-mono text-xs font-bold text-white">
                  spBv1.0/Enterprise/DDATA/Gateway_01/Cell_Robotics
                </span>
              </div>
              <div className="flex items-center gap-1 bg-[#1E293B] p-0.5 rounded">
                <button
                  onClick={() => setActiveProtobufTab('decoded')}
                  className={`px-2 py-1 rounded text-[10px] font-mono font-semibold transition-colors cursor-pointer ${
                    activeProtobufTab === 'decoded'
                      ? 'bg-amber-500 text-slate-950 font-bold'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  Decoded Metrics
                </button>
                <button
                  onClick={() => setActiveProtobufTab('raw')}
                  className={`px-2 py-1 rounded text-[10px] font-mono font-semibold transition-colors cursor-pointer ${
                    activeProtobufTab === 'raw'
                      ? 'bg-amber-500 text-slate-950 font-bold'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  Raw Protobuf Hex
                </button>
              </div>
            </div>

            {/* Payload Body */}
            <div className="p-4 font-mono text-xs text-slate-300 overflow-x-auto flex-1 bg-[#050505] space-y-3">
              {activeProtobufTab === 'decoded' ? (
                <div className="space-y-2">
                  <div className="text-[11px] text-slate-500 flex justify-between border-b border-[#1E293B] pb-1.5">
                    <span>METRIC NAME / ALIAS</span>
                    <span>DATATYPE</span>
                    <span>VALUE</span>
                    <span>QUALITY</span>
                  </div>
                  <div className="flex items-center justify-between py-1 border-b border-[#1E293B]/40 hover:bg-[#111114] px-1 rounded">
                    <span className="text-amber-400 font-bold">Motor_Spindle_RPM [alias: 1]</span>
                    <span className="text-sky-400">Float (Float32)</span>
                    <span className="text-emerald-400 font-bold">1482.4 RPM</span>
                    <span className="text-emerald-400 text-[10px] bg-emerald-950 px-1.5 py-0.5 rounded">560 GOOD</span>
                  </div>
                  <div className="flex items-center justify-between py-1 border-b border-[#1E293B]/40 hover:bg-[#111114] px-1 rounded">
                    <span className="text-amber-400 font-bold">Bearing_Vibration_RMS [alias: 2]</span>
                    <span className="text-sky-400">Float (Float32)</span>
                    <span className="text-emerald-400 font-bold">1.48 mm/s</span>
                    <span className="text-emerald-400 text-[10px] bg-emerald-950 px-1.5 py-0.5 rounded">560 GOOD</span>
                  </div>
                  <div className="flex items-center justify-between py-1 border-b border-[#1E293B]/40 hover:bg-[#111114] px-1 rounded">
                    <span className="text-amber-400 font-bold">Inlet_Hydraulic_Pressure [alias: 3]</span>
                    <span className="text-sky-400">Float (Float32)</span>
                    <span className="text-emerald-400 font-bold">4.82 bar</span>
                    <span className="text-emerald-400 text-[10px] bg-emerald-950 px-1.5 py-0.5 rounded">560 GOOD</span>
                  </div>
                  <div className="flex items-center justify-between py-1 border-b border-[#1E293B]/40 hover:bg-[#111114] px-1 rounded">
                    <span className="text-amber-400 font-bold">Execution_State [alias: 4]</span>
                    <span className="text-purple-400">String (UTF-8)</span>
                    <span className="text-white font-bold">&quot;AUTOMATIC_RUNNING&quot;</span>
                    <span className="text-emerald-400 text-[10px] bg-emerald-950 px-1.5 py-0.5 rounded">560 GOOD</span>
                  </div>
                  <div className="flex items-center justify-between py-1 hover:bg-[#111114] px-1 rounded">
                    <span className="text-amber-400 font-bold">Safety_Curtain_Engaged [alias: 5]</span>
                    <span className="text-amber-400">Boolean</span>
                    <span className="text-sky-400 font-bold">true</span>
                    <span className="text-emerald-400 text-[10px] bg-emerald-950 px-1.5 py-0.5 rounded">560 GOOD</span>
                  </div>
                </div>
              ) : (
                <div className="text-[11px] text-slate-400 leading-relaxed font-mono">
                  <div className="text-emerald-400">// Protobuf wire binary packet (48 bytes)</div>
                  <div className="text-slate-500">08 e8 07 10 01 1a 0c 4d 6f 74 6f 72 5f 53 70 69</div>
                  <div className="text-slate-500">6e 64 6c 65 20 09 2d 00 48 b9 44 10 02 1a 15 42</div>
                  <div className="text-slate-500">65 61 72 69 6e 67 5f 56 69 62 72 61 74 69 6f 6e</div>
                  <div className="text-amber-400 pt-2 font-semibold">
                    ✓ Decompressed to 5 metric fields with 0 dropped sequence frames.
                  </div>
                </div>
              )}
            </div>

            {/* Footer Summary */}
            <div className="p-3 bg-[#111114] border-t border-[#1E293B] flex items-center justify-between text-xs">
              <div className="flex items-center gap-2 text-slate-400 font-mono text-[11px]">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                <span>Seq: 14,892 • CRC: Verified • Latency: 0.9ms</span>
              </div>
              <button
                onClick={() => handleLaunchConsole()}
                className="px-3 py-1 rounded bg-amber-500 hover:bg-amber-600 text-slate-950 font-bold text-xs flex items-center gap-1 cursor-pointer"
              >
                <span>Open Live Decoder</span>
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* Multi-Site Operations (Generic Across All Clients) */}
      <section id="plants-section" className="py-16 sm:py-20 px-4 sm:px-8 max-w-7xl mx-auto w-full border-t border-[#E2E8F0] dark:border-[#1E293B]">
        <div className="text-center max-w-2xl mx-auto space-y-2 mb-10">
          <div className="text-xs font-mono uppercase tracking-wider text-amber-600 dark:text-[#FFC107] font-semibold">
            Enterprise Scale
          </div>
          <h2 className="font-serif text-2xl sm:text-3xl font-bold text-[#0F172A] dark:text-[#F8FAFC]">
            Scalable Across Distributed Global Facilities
          </h2>
          <p className="text-xs sm:text-sm text-[#475569] dark:text-[#94A3B8]">
            Deployable on premise, hybrid-cloud, or edge nodes for multi-site organizations.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-5 space-y-2.5 shadow-xs">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono text-amber-600 dark:text-[#FFC107] font-bold">FACILITY-ALPHA</span>
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            </div>
            <div className="font-serif font-bold text-base text-[#0F172A] dark:text-[#F8FAFC]">
              Manufacturing Campus
            </div>
            <div className="text-xs text-[#64748B]">High-Throughput Continuous Automation</div>
            <div className="pt-2 border-t border-[#E2E8F0] dark:border-[#1E293B] text-[11px] font-mono text-[#475569] dark:text-[#94A3B8] flex justify-between">
              <span>64 UNS Nodes</span>
              <span className="text-emerald-600 dark:text-emerald-400 font-semibold">0.8ms ping</span>
            </div>
          </div>

          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-5 space-y-2.5 shadow-xs">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono text-sky-600 dark:text-sky-400 font-bold">FACILITY-BETA</span>
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            </div>
            <div className="font-serif font-bold text-base text-[#0F172A] dark:text-[#F8FAFC]">
              Advanced Assembly Center
            </div>
            <div className="text-xs text-[#64748B]">Automated Robotics &amp; Workcells</div>
            <div className="pt-2 border-t border-[#E2E8F0] dark:border-[#1E293B] text-[11px] font-mono text-[#475569] dark:text-[#94A3B8] flex justify-between">
              <span>48 UNS Nodes</span>
              <span className="text-emerald-600 dark:text-emerald-400 font-semibold">1.1ms ping</span>
            </div>
          </div>

          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-5 space-y-2.5 shadow-xs">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono text-purple-600 dark:text-purple-400 font-bold">FACILITY-GAMMA</span>
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            </div>
            <div className="font-serif font-bold text-base text-[#0F172A] dark:text-[#F8FAFC]">
              Regional Operations Hub
            </div>
            <div className="text-xs text-[#64748B]">Continuous Processing &amp; Packaging</div>
            <div className="pt-2 border-t border-[#E2E8F0] dark:border-[#1E293B] text-[11px] font-mono text-[#475569] dark:text-[#94A3B8] flex justify-between">
              <span>36 UNS Nodes</span>
              <span className="text-emerald-600 dark:text-emerald-400 font-semibold">1.4ms ping</span>
            </div>
          </div>

          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-5 space-y-2.5 shadow-xs">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono text-emerald-600 dark:text-emerald-400 font-bold">FACILITY-DELTA</span>
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            </div>
            <div className="font-serif font-bold text-base text-[#0F172A] dark:text-[#F8FAFC]">
              Distributed Edge Node
            </div>
            <div className="text-xs text-[#64748B]">Edge IoT Gateway &amp; Telemetry Relay</div>
            <div className="pt-2 border-t border-[#E2E8F0] dark:border-[#1E293B] text-[11px] font-mono text-[#475569] dark:text-[#94A3B8] flex justify-between">
              <span>24 UNS Nodes</span>
              <span className="text-emerald-600 dark:text-emerald-400 font-semibold">2.1ms ping</span>
            </div>
          </div>
        </div>
      </section>

      {/* Security & Compliance Section */}
      <section id="compliance-section" className="py-16 px-4 sm:px-8 max-w-7xl mx-auto w-full border-t border-[#E2E8F0] dark:border-[#1E293B]">
        <div className="text-center max-w-2xl mx-auto space-y-2 mb-10">
          <div className="text-xs font-mono uppercase tracking-wider text-amber-600 dark:text-[#FFC107] font-semibold">
            Enterprise Security
          </div>
          <h2 className="font-serif text-2xl sm:text-3xl font-bold text-[#0F172A] dark:text-[#F8FAFC]">
            ISO/IEC 62443 Certified Cyber Defense
          </h2>
          <p className="text-xs sm:text-sm text-[#475569] dark:text-[#94A3B8]">
            Zero-Trust architecture with role-based access control, cryptographic payload validation, and non-repudiable audit logs.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-6 space-y-3">
            <div className="w-9 h-9 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/40 flex items-center justify-center text-emerald-600 dark:text-emerald-400">
              <Shield className="w-5 h-5" />
            </div>
            <h3 className="font-serif font-bold text-base text-[#0F172A] dark:text-[#F8FAFC]">
              5 Granular RBAC Tiers
            </h3>
            <p className="text-xs text-[#475569] dark:text-[#94A3B8] leading-relaxed">
              System Admin, Process Engineer, Shift Operator, Compliance Auditor, and External Viewer with strict command authorization.
            </p>
          </div>

          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-6 space-y-3">
            <div className="w-9 h-9 rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800/40 flex items-center justify-center text-amber-600 dark:text-[#FFC107]">
              <Lock className="w-5 h-5" />
            </div>
            <h3 className="font-serif font-bold text-base text-[#0F172A] dark:text-[#F8FAFC]">
              End-to-End Encryption
            </h3>
            <p className="text-xs text-[#475569] dark:text-[#94A3B8] leading-relaxed">
              TLS 1.3 encrypted MQTT transport with mutual client certificate authentication (mTLS) for every edge gateway and plant bridge.
            </p>
          </div>

          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-6 space-y-3">
            <div className="w-9 h-9 rounded-lg bg-purple-50 dark:bg-purple-950/40 border border-purple-200 dark:border-purple-800/40 flex items-center justify-center text-purple-600 dark:text-purple-400">
              <FileCode2 className="w-5 h-5" />
            </div>
            <h3 className="font-serif font-bold text-base text-[#0F172A] dark:text-[#F8FAFC]">
              Immutable Audit Logs
            </h3>
            <p className="text-xs text-[#475569] dark:text-[#94A3B8] leading-relaxed">
              All payload publishes, alarm acknowledgments, user logins, and schema mutations are cryptographically timestamped and logged.
            </p>
          </div>
        </div>
      </section>

      {/* Call to Action Banner */}
      <section className="py-16 px-4 sm:px-8 max-w-7xl mx-auto w-full">
        <div className="bg-amber-500 dark:bg-amber-500/10 border border-amber-600/30 dark:border-[#FFC107]/30 rounded-2xl p-8 sm:p-12 text-center text-slate-950 dark:text-[#F8FAFC] space-y-6 shadow-xl relative overflow-hidden">
          <div className="max-w-2xl mx-auto space-y-3">
            <h2 className="font-serif text-2xl sm:text-4xl font-bold tracking-tight">
              Ready to Access the Unified Namespace Console?
            </h2>
            <p className="text-sm sm:text-base text-slate-900/90 dark:text-[#94A3B8]">
              Sign in with your enterprise credentials or choose one of the pre-configured role profiles to test real-time MQTT telemetry, Sparkplug B decoding, and process alarms.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <button
              onClick={() => handleLaunchConsole()}
              className="w-full sm:w-auto px-8 py-3.5 rounded-lg bg-slate-950 dark:bg-[#FFC107] hover:bg-slate-900 dark:hover:bg-[#FFB300] text-white dark:text-slate-950 font-bold text-sm shadow-md transition-all cursor-pointer"
            >
              Sign In to Management Console
            </button>
            <button
              onClick={() => handleLaunchConsole('usr-admin-01')}
              className="w-full sm:w-auto px-6 py-3.5 rounded-lg bg-white/30 dark:bg-[#111114] hover:bg-white/40 dark:hover:bg-[#1E293B] border border-slate-950/20 dark:border-[#1E293B] text-slate-950 dark:text-[#F8FAFC] font-semibold text-sm transition-colors cursor-pointer"
            >
              One-Click Admin Demo
            </button>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="mt-auto border-t border-[#E2E8F0] dark:border-[#1E293B] bg-white dark:bg-[#0B0B0C] py-8 px-4 sm:px-8 text-xs text-[#64748B]">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-amber-500/20 flex items-center justify-center text-amber-600 dark:text-[#FFC107]">
              <Layers className="w-3.5 h-3.5" />
            </div>
            <span className="font-serif font-bold text-sm text-[#0F172A] dark:text-[#F8FAFC]">
              UNS Console
            </span>
            <span>• Universal Enterprise Unified Namespace Operating System</span>
          </div>

          <div className="flex items-center gap-6 font-mono text-[11px]">
            <span>ISA-95 Hierarchy</span>
            <span>Sparkplug B 2.2 / 3.0</span>
            <span>TimescaleDB</span>
            <span>Kafka Streams</span>
            <button
              onClick={() => navigate('/login')}
              className="text-amber-600 dark:text-[#FFC107] hover:underline font-bold"
            >
              Sign In →
            </button>
          </div>
        </div>
      </footer>
    </div>
  );
};
