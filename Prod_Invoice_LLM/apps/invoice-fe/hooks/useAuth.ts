import { useState, useEffect } from "react";

export interface AuthContextType {
  tenantId: string;
  userId: string;
  role: string;
  billingPlan: string;
  loading: boolean;
}

export function useAuth(): AuthContextType {
  const [auth, setAuth] = useState<AuthContextType>({
    tenantId: "00000000-0000-0000-0000-000000000000",
    userId: "user_test_default",
    role: "Admin",
    billingPlan: "active",
    loading: true,
  });

  useEffect(() => {
    // Simulates identity retrieval.
    // Falls back to standard local mock values corresponding to the FastAPI backend defaults.
    const mockAuth = {
      tenantId: typeof window !== "undefined" ? localStorage.getItem("tenant_id") || "00000000-0000-0000-0000-000000000000" : "00000000-0000-0000-0000-000000000000",
      userId: typeof window !== "undefined" ? localStorage.getItem("user_id") || "user_test_default" : "user_test_default",
      role: typeof window !== "undefined" ? localStorage.getItem("user_role") || "Admin" : "Admin",
      billingPlan: typeof window !== "undefined" ? localStorage.getItem("billing_plan") || "active" : "active",
      loading: false,
    };
    
    setAuth(mockAuth);
  }, []);

  return auth;
}
