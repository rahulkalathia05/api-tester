import axios, { type AxiosRequestConfig, type AxiosError } from "axios";
import { useAuthStore } from "@/stores/authStore";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Main client — every request goes through the auth interceptor ─────────────
export const api = axios.create({
  baseURL: BASE_URL,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

// Separate instance for token refresh so a failed refresh never triggers
// another refresh (no infinite loop).
const refreshClient = axios.create({ baseURL: BASE_URL });

// ── Request: attach current access token ──────────────────────────────────────
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// ── Response: auto-refresh on 401 ────────────────────────────────────────────
let refreshing = false;
let refreshQueue: Array<(token: string) => void> = [];

api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as AxiosRequestConfig & { _retry?: boolean };

    if (error.response?.status !== 401 || original._retry) {
      return Promise.reject(error);
    }

    original._retry = true;

    if (refreshing) {
      return new Promise((resolve) => {
        refreshQueue.push((token) => {
          original.headers = { ...original.headers, Authorization: `Bearer ${token}` };
          resolve(api(original));
        });
      });
    }

    refreshing = true;
    const { refreshToken, setTokens, clearAuth } = useAuthStore.getState();

    try {
      const { data } = await refreshClient.post("/auth/refresh", {
        refresh_token: refreshToken,
      });
      const newToken: string = data.access_token;
      setTokens(newToken, data.refresh_token);
      refreshQueue.forEach((cb) => cb(newToken));
      refreshQueue = [];
      original.headers = { ...original.headers, Authorization: `Bearer ${newToken}` };
      return api(original);
    } catch {
      clearAuth();
      if (typeof window !== "undefined") window.location.href = "/login";
      return Promise.reject(error);
    } finally {
      refreshing = false;
    }
  }
);

export default api;
