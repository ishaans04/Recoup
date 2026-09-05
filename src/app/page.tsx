import AuroraBackdrop from "@/components/landing/AuroraBackdrop";
import CtaSection from "@/components/landing/CtaSection";
import FlowSection from "@/components/landing/FlowSection";
import HeroSection from "@/components/landing/HeroSection";
import LandingHeader from "@/components/landing/LandingHeader";
import StatsSection from "@/components/landing/StatsSection";
import WhySection from "@/components/landing/WhySection";

/**
 * The landing page: claim, honest numbers, a run in progress, the argument, the
 * invitation. Every section sits at `z-index: 1` over the fixed aurora field,
 * which is the only element that moves with the cursor.
 */
export default function Home() {
  return (
    <div style={{ position: "relative", minHeight: "100vh", overflowX: "hidden" }}>
      <AuroraBackdrop variant="landing" />
      <LandingHeader />
      <HeroSection />
      <StatsSection />
      <FlowSection />
      <WhySection />
      <CtaSection />
    </div>
  );
}
