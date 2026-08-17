"use client";

import React, { useEffect } from "react";
import { ApplicationInsights } from "@microsoft/applicationinsights-web";

let appInsightsInstance: ApplicationInsights | null = null;

export default function AppInsightsProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    const connectionString = process.env.NEXT_PUBLIC_APPINSIGHTS_CONNECTION_STRING;
    if (connectionString && !appInsightsInstance && typeof window !== "undefined") {
      try {
        appInsightsInstance = new ApplicationInsights({
          config: {
            connectionString,
            enableAutoRouteTracking: true,
            enableCorsCorrelation: true,
            enableRequestHeaderTracking: true,
            enableResponseHeaderTracking: true,
          },
        });
        appInsightsInstance.loadAppInsights();
        appInsightsInstance.trackPageView();
      } catch (err) {
        console.warn("Client-side Application Insights RUM initialization skipped:", err);
      }
    }
  }, []);

  return <>{children}</>;
}
