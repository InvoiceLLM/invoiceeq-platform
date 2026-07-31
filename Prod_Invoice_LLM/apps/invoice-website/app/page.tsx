"use client";

import React, { useState } from "react";
import { Header } from "@/components/marketing/Header";
import { Hero } from "@/components/marketing/Hero";
import { FlowsShowcaseSection } from "@/components/marketing/FlowsShowcaseSection";
import { AITeamSection } from "@/components/marketing/AITeamSection";
import { WorkspaceShowcase } from "@/components/marketing/WorkspaceShowcase";
import { PricingTable } from "@/components/marketing/PricingTable";
import { BenefitsStrip } from "@/components/marketing/BenefitsStrip";
import { FlowsModal } from "@/components/marketing/FlowsModal";

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

  return (
    <div className="flex flex-col min-h-screen">
      <Header onOpenFlowsModal={() => handleOpenModal("inbound")} />
      <main className="flex-1 relative z-10">
        <Hero onOpenFlowsModal={() => handleOpenModal("inbound")} />
        <FlowsShowcaseSection onOpenModal={(flowId) => handleOpenModal(flowId)} />
        <AITeamSection />
        <WorkspaceShowcase />
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
