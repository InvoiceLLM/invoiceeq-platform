"use client";

import React, { useState, useEffect } from "react";
import { Header } from "@/components/marketing/Header";
import { Hero } from "@/components/marketing/Hero";
import { FlowsShowcaseSection } from "@/components/marketing/FlowsShowcaseSection";
import { AITeamSection } from "@/components/marketing/AITeamSection";
import { WorkspaceShowcase } from "@/components/marketing/WorkspaceShowcase";
import { PricingTable } from "@/components/marketing/PricingTable";
import { BenefitsStrip } from "@/components/marketing/BenefitsStrip";
import { FlowsModal } from "@/components/marketing/FlowsModal";
import { SageChatPreview } from "@/components/marketing/SageChatPreview";
import { WorkflowRecipeSelector } from "@/components/marketing/WorkflowRecipeSelector";

export default function Home() {
  const [modalState, setModalState] = useState<{
    isOpen: boolean;
    flowId?: string;
  }>({ isOpen: false });

  const handleOpenModal = (flowId?: string) => {
    setModalState({ isOpen: true, flowId });
  };

  const handleCloseModal = () => {
    setModalState((prev) => ({ ...prev, isOpen: false }));
  };

  useEffect(() => {
    if (typeof window !== "undefined" && window.location.hash === "#architecture-flows") {
      handleOpenModal("inbound");
    }
  }, []);

  return (
    <div className="flex flex-col min-h-screen">
      <Header onOpenFlowsModal={() => handleOpenModal("inbound")} />
      <main className="flex-1 relative z-10">
        {/* Hero also carries Feature 7's mode switcher (Gap 345) and the
            flagged-sample branch of the pipeline demo (Gap 346). */}
        <Hero />
        {/* Gap 347 — directly after the pipeline demo, matching the approved
            mockup: the demo shows the data being produced, SAGE shows it
            being asked about. */}
        <SageChatPreview />
        <FlowsShowcaseSection onOpenModal={(flowId) => handleOpenModal(flowId)} />
        <AITeamSection />
        <WorkspaceShowcase />
        {/* Gap 348 — placed immediately before pricing rather than directly
            under SAGE as in the mockup (which only rendered the hero frame,
            not the whole page): "here is the pipeline you'd get" reads better
            straight into "here is what it costs", and it keeps this CTA next
            to the pricing CTAs instead of competing with them mid-page. */}
        <WorkflowRecipeSelector />
        <PricingTable />
        <BenefitsStrip />
      </main>
      <FlowsModal
        isOpen={modalState.isOpen}
        onClose={handleCloseModal}
        initialFlowId={modalState.flowId}
      />
    </div>
  );
}
