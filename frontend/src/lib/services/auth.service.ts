import api from "@/lib/api";
import type { AuthResponse, User } from "@/types";

export const authService = {
  register: (data: { name: string; email: string; password: string }) =>
    api.post<AuthResponse>("/auth/register", data),

  login: (data: { email: string; password: string }) =>
    api.post<AuthResponse>("/auth/login", data),

  logout: (refresh_token?: string | null) =>
    api.post("/auth/logout", { refresh_token }),

  me: () => api.get<User>("/auth/me"),
};
