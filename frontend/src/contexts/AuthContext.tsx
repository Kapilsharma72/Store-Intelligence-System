import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import api from '../api/axios'

export interface User {
  username: string
  role: string
}

interface AuthContextValue {
  user: User | null
  token: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  refreshToken: () => Promise<void>
}

function decodeJwt(token: string): Record<string, unknown> {
  try {
    const payload = token.split('.')[1]
    const padded = payload.replace(/-/g, '+').replace(/_/g, '/')
    const json = atob(padded)
    return JSON.parse(json)
  } catch {
    return {}
  }
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)

  // Restore session from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem('auth_token')
    if (stored) {
      const payload = decodeJwt(stored)
      if (payload.sub || payload.username) {
        setToken(stored)
        setUser({
          username: (payload.username ?? payload.sub ?? '') as string,
          role: (payload.role ?? 'user') as string,
        })
      }
    }
  }, [])

  async function login(username: string, password: string): Promise<void> {
    const response = await api.post('/api/v1/auth/login', { username, password })
    const { access_token } = response.data
    localStorage.setItem('auth_token', access_token)
    const payload = decodeJwt(access_token)
    setToken(access_token)
    setUser({
      username: (payload.username ?? payload.sub ?? username) as string,
      role: (payload.role ?? 'user') as string,
    })
  }

  function logout(): void {
    localStorage.removeItem('auth_token')
    setToken(null)
    setUser(null)
  }

  async function refreshToken(): Promise<void> {
    if (!token) return
    const response = await api.post('/api/v1/auth/refresh', { token })
    const { access_token } = response.data
    localStorage.setItem('auth_token', access_token)
    const payload = decodeJwt(access_token)
    setToken(access_token)
    setUser({
      username: (payload.username ?? payload.sub ?? '') as string,
      role: (payload.role ?? 'user') as string,
    })
  }

  return (
    <AuthContext.Provider value={{ user, token, login, logout, refreshToken }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
