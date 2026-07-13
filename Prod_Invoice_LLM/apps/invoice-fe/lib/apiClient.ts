import axios from "axios";

// Same-origin: routed through this app's own Route Handlers (app/api/**),
// which run server-side and call the backend using BACKEND_API_URL.
export const apiClient = axios.create({
  baseURL: "/api",
});
