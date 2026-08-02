import { AgentShowcaseSection } from "./sections/agent-showcase-section";
import { ArchitectureSection } from "./sections/architecture-section";
import { CallToActionSection } from "./sections/call-to-action-section";
import { FeatureSections } from "./sections/feature-sections";
import { HeroSection } from "./sections/hero-section";
import { HowItWorksSection } from "./sections/how-it-works-section";
import { LandingFooter } from "./sections/landing-footer";
import { LandingNavigation } from "./sections/landing-navigation";
import { PhilosophySection } from "./sections/philosophy-section";
import { TechStackSection } from "./sections/tech-stack-section";

export function LandingPage() {
  return (
    <div className="min-h-screen bg-[var(--color-bg-base)] text-[var(--color-fg-primary)] overflow-x-hidden">
      <LandingNavigation />
      <HeroSection />
      <HowItWorksSection />
      <AgentShowcaseSection />
      <FeatureSections />
      <ArchitectureSection />
      <PhilosophySection />
      <TechStackSection />
      <CallToActionSection />
      <LandingFooter />
    </div>
  );
}
