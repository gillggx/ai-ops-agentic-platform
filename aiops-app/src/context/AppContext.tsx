"use client";

import React, { createContext, useContext, useState } from "react";
import type { AIOpsReportContract } from "aiops-contract";

export interface SelectedEquipment {
  equipment_id: string;
  name: string;
  status: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export interface DataExplorerState {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  flatData: Record<string, any[]>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  metadata: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  uiConfig?: any;
  queryInfo?: { mcp: string; params: Record<string, unknown>; resultSummary: string };
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
  dataExplorer: DataExplorerState | null;
  setDataExplorer: (de: DataExplorerState | null) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [selectedEquipment, setSelectedEquipment] = useState<SelectedEquipment | null>(null);
  const [triggerMessage, setTriggerMessage]       = useState<string | null>(null);
  const [contract, setContract]                   = useState<AIOpsReportContract | null>(null);
  const [investigateMode, setInvestigateMode]     = useState(false);
  const [dataExplorer, setDataExplorer]           = useState<DataExplorerState | null>(null);

  return (
    <AppContext.Provider value={{
      selectedEquipment, setSelectedEquipment,
      triggerMessage, setTriggerMessage,
      contract, setContract,
      investigateMode, setInvestigateMode,
      dataExplorer, setDataExplorer,
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
