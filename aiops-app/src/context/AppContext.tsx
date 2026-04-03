"use client";

import React, { createContext, useContext, useState } from "react";
import type { AIOpsReportContract } from "aiops-contract";

export interface SelectedEquipment {
  equipment_id: string;
  name: string;
  status: string;
}

interface AppContextValue {
  selectedEquipment: SelectedEquipment | null;
  setSelectedEquipment: (eq: SelectedEquipment | null) => void;
  triggerMessage: string | null;
  setTriggerMessage: (msg: string | null) => void;
  contract: AIOpsReportContract | null;
  setContract: (c: AIOpsReportContract | null) => void;
  investigateMode: boolean;
  setInvestigateMode: (b: boolean) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [selectedEquipment, setSelectedEquipment] = useState<SelectedEquipment | null>(null);
  const [triggerMessage, setTriggerMessage]       = useState<string | null>(null);
  const [contract, setContract]                   = useState<AIOpsReportContract | null>(null);
  const [investigateMode, setInvestigateMode]     = useState(false);

  return (
    <AppContext.Provider value={{
      selectedEquipment, setSelectedEquipment,
      triggerMessage, setTriggerMessage,
      contract, setContract,
      investigateMode, setInvestigateMode,
    }}>
      {children}
    </AppContext.Provider>
  );
}

export function useAppContext(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useAppContext must be used within AppProvider");
  return ctx;
}
