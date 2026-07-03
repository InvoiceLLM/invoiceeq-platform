import axios from "axios";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api/v1";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
});

// Request interceptor to automatically add tenant/auth headers when available
apiClient.interceptors.request.use(
  (config) => {
    // For local development, if we want to simulate tenant context, 
    // we can pass a mock test token. Otherwise, the backend defaults to 
    // MOCK_TENANT_ID = 00000000-0000-0000-0000-000000000000
    const token = typeof window !== "undefined" ? localStorage.getItem("auth_token") : null;
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);
