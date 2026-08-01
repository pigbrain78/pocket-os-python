import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

type User = { id: string; email: string; name: string };
type AuthCtx = {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  loginWithApple: (identityToken: string, fullName?: string | null, email?: string | null) => Promise<void>;
  logout: () => Promise<void>;
};

const Ctx = createContext<AuthCtx>({} as AuthCtx);
export const useAuth = () => useContext(Ctx);

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

const store = {
  async get(key: string) {
    if (Platform.OS === "web") return AsyncStorage.getItem(key);
    return SecureStore.getItemAsync(key);
  },
  async set(key: string, val: string) {
    if (Platform.OS === "web") return AsyncStorage.setItem(key, val);
    return SecureStore.setItemAsync(key, val);
  },
  async del(key: string) {
    if (Platform.OS === "web") return AsyncStorage.removeItem(key);
    return SecureStore.deleteItemAsync(key);
  },
};

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const t = await store.get("pocketos_token");
        const u = await store.get("pocketos_user");
        if (t && u) {
          setToken(t);
          setUser(JSON.parse(u));
        }
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const persist = async (t: string, u: User) => {
    await store.set("pocketos_token", t);
    await store.set("pocketos_user", JSON.stringify(u));
    setToken(t);
    setUser(u);
  };

  const login = useCallback(async (email: string, password: string) => {
    const r = await fetch(`${BACKEND}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "Login failed");
    await persist(data.token, data.user);
  }, []);

  const register = useCallback(async (name: string, email: string, password: string) => {
    const r = await fetch(`${BACKEND}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, email, password }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "Register failed");
    await persist(data.token, data.user);
  }, []);

  const loginWithApple = useCallback(async (identityToken: string, fullName?: string | null, email?: string | null) => {
    const r = await fetch(`${BACKEND}/api/auth/apple`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identity_token: identityToken, full_name: fullName, email }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "Apple sign-in failed");
    await persist(data.token, data.user);
  }, []);

  const logout = useCallback(async () => {
    await store.del("pocketos_token");
    await store.del("pocketos_user");
    setToken(null);
    setUser(null);
  }, []);

  return (
    <Ctx.Provider value={{ user, token, loading, login, register, loginWithApple, logout }}>
      {children}
    </Ctx.Provider>
  );
};

export async function api<T = any>(path: string, opts: RequestInit & { token?: string | null } = {}): Promise<T> {
  const { token, headers, ...rest } = opts;
  const r = await fetch(`${BACKEND}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers || {}),
    },
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((data as any).detail || `HTTP ${r.status}`);
  return data as T;
}
