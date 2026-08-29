import React, { useState } from 'react';
import { ArrowRight, ArrowUpRight, Layers, Menu, Play, X } from 'lucide-react';

export interface NavLink {
  label: string;
  href?: string;
  onClick?: () => void;
  isActive?: boolean;
}

export interface Partner {
  label: string;
  href?: string;
}

export interface ResponsiveHeroBannerProps {
  backgroundImageUrl: string;
  navLinks?: NavLink[];
  ctaButtonText?: string;
  onCtaClick?: () => void;
  badgeText?: string;
  badgeLabel?: string;
  title?: string;
  titleLine2?: string;
  description?: string;
  primaryButtonText?: string;
  onPrimaryClick?: () => void;
  secondaryButtonText?: string;
  onSecondaryClick?: () => void;
  partnersTitle?: string;
  partners?: Partner[];
  logo?: React.ReactNode;
}

export const ResponsiveHeroBanner: React.FC<ResponsiveHeroBannerProps> = ({
  backgroundImageUrl,
  navLinks = [],
  ctaButtonText = 'Access Console',
  onCtaClick,
  badgeLabel = 'Live',
  badgeText = 'ISA-95 & Sparkplug B Unified Namespace',
  title = 'Unified Namespace',
  titleLine2 = 'for Smart Manufacturing',
  description = 'Standardize shop-floor telemetry, Sparkplug B edge computing, Timescale historian analytics, and enterprise MQTT streams across every plant in your organization.',
  primaryButtonText = 'Launch Console',
  onPrimaryClick,
  secondaryButtonText = 'Explore Architecture',
  onSecondaryClick,
  partnersTitle = 'Built on open industrial standards',
  partners = [],
  logo,
}) => {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const handleNav = (link: NavLink) => {
    link.onClick?.();
    if (link.href) {
      window.location.hash = link.href;
    }
    setMobileMenuOpen(false);
  };

  return (
    <section className="relative isolate min-h-screen w-full overflow-hidden">
      <img
        src={backgroundImageUrl}
        alt=""
        className="absolute inset-0 h-full w-full object-cover"
      />
      <div className="absolute inset-0 bg-gradient-to-b from-black/70 via-black/55 to-black/85" />
      <div className="pointer-events-none absolute inset-0 ring-1 ring-black/30 ring-inset" />

      <header className="relative z-10 xl:top-4">
        <div className="mx-6">
          <div className="flex items-center justify-between pt-4">
            <div className="inline-flex items-center gap-2.5">
              {logo ?? (
                <>
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-amber-400/30 bg-amber-500/10 text-amber-400">
                    <Layers className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="font-serif text-lg font-bold tracking-tight text-white">
                      UNS<span className="text-amber-400">CONSOLE</span>
                    </div>
                    <div className="font-mono text-[10px] uppercase tracking-wider text-white/60">
                      Unified Namespace
                    </div>
                  </div>
                </>
              )}
            </div>

            <nav className="hidden items-center gap-2 md:flex">
              <div className="flex items-center gap-1 rounded-full bg-white/5 px-1 py-1 ring-1 ring-white/10 backdrop-blur">
                {navLinks.map((link) => (
                  <button
                    key={link.label}
                    type="button"
                    onClick={() => handleNav(link)}
                    className={`rounded-full px-3 py-2 font-sans text-sm font-medium transition-colors ${
                      link.isActive ? 'text-white/90' : 'text-white/80 hover:text-white'
                    }`}
                  >
                    {link.label}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={onCtaClick}
                  className="ml-1 inline-flex items-center gap-2 rounded-full bg-white px-3.5 py-2 font-sans text-sm font-medium text-neutral-900 transition-colors hover:bg-white/90"
                >
                  {ctaButtonText}
                  <ArrowUpRight className="h-4 w-4" />
                </button>
              </div>
            </nav>

            <button
              type="button"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-white/10 ring-1 ring-white/15 backdrop-blur md:hidden"
              aria-expanded={mobileMenuOpen}
              aria-label="Toggle menu"
            >
              {mobileMenuOpen ? (
                <X className="h-5 w-5 text-white/90" />
              ) : (
                <Menu className="h-5 w-5 text-white/90" />
              )}
            </button>
          </div>

          {mobileMenuOpen && (
            <div className="mt-3 rounded-2xl bg-black/60 p-3 ring-1 ring-white/10 backdrop-blur md:hidden">
              <div className="flex flex-col gap-1">
                {navLinks.map((link) => (
                  <button
                    key={link.label}
                    type="button"
                    onClick={() => handleNav(link)}
                    className="rounded-lg px-3 py-2.5 text-left font-sans text-sm text-white/90 hover:bg-white/10"
                  >
                    {link.label}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => {
                    onCtaClick?.();
                    setMobileMenuOpen(false);
                  }}
                  className="mt-1 inline-flex items-center justify-center gap-2 rounded-full bg-white px-4 py-2.5 font-sans text-sm font-medium text-neutral-900"
                >
                  {ctaButtonText}
                  <ArrowUpRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}
        </div>
      </header>

      <div className="relative z-10">
        <div className="mx-auto max-w-7xl px-6 pb-16 pt-28 sm:pt-28 md:pt-32 lg:pt-40">
          <div className="mx-auto max-w-3xl text-center">
            <div className="animate-fade-slide-in-1 mb-6 inline-flex items-center gap-3 rounded-full bg-white/10 px-2.5 py-2 ring-1 ring-white/15 backdrop-blur">
              <span className="inline-flex items-center rounded-full bg-white/90 px-2 py-0.5 font-sans text-xs font-medium text-neutral-900">
                {badgeLabel}
              </span>
              <span className="font-sans text-sm font-medium text-white/90">{badgeText}</span>
            </div>

            <h1 className="animate-fade-slide-in-2 font-instrument-serif text-4xl font-normal leading-tight tracking-tight text-white sm:text-5xl md:text-6xl lg:text-7xl">
              {title}
              <br className="hidden sm:block" />
              {titleLine2}
            </h1>

            <p className="animate-fade-slide-in-3 mx-auto mt-6 max-w-2xl text-base text-white/80 sm:text-lg">
              {description}
            </p>

            <div className="animate-fade-slide-in-4 mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row sm:gap-4">
              <button
                type="button"
                onClick={onPrimaryClick}
                className="inline-flex items-center gap-2 rounded-full bg-white/10 px-5 py-3 font-sans text-sm font-medium text-white ring-1 ring-white/15 transition-colors hover:bg-white/15"
              >
                {primaryButtonText}
                <ArrowRight className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={onSecondaryClick}
                className="inline-flex items-center gap-2 rounded-full bg-transparent px-5 py-3 font-sans text-sm font-medium text-white/90 transition-colors hover:text-white"
              >
                {secondaryButtonText}
                <Play className="h-4 w-4" />
              </button>
            </div>
          </div>

          {partners.length > 0 && (
            <div className="mx-auto mt-20 max-w-5xl">
              <p className="animate-fade-slide-in-1 text-center text-sm text-white/70">{partnersTitle}</p>
              <div className="animate-fade-slide-in-2 mt-6 grid grid-cols-2 items-center justify-items-center gap-4 sm:grid-cols-3 md:grid-cols-5">
                {partners.map((partner) => (
                  <div
                    key={partner.label}
                    className="inline-flex h-9 min-w-[120px] items-center justify-center rounded-full border border-white/10 bg-white/5 px-4 font-mono text-[11px] font-semibold uppercase tracking-wider text-white/75 backdrop-blur transition-opacity hover:text-white"
                  >
                    {partner.label}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
};

export default ResponsiveHeroBanner;
