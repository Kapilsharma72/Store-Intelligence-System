import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ThemeProvider } from './components/ThemeProvider'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import AnalyticsDashboard from './pages/AnalyticsDashboard'
import ComparePage from './pages/ComparePage'

function HomePage() {
  return (
    <>
      <div className="col-span-full">
        <h1 className="text-2xl font-bold">Welcome to Store Intelligence</h1>
        <p className="mt-2 text-gray-600 dark:text-gray-400">
          Upload and analyze CCTV footage to gain store performance insights.
        </p>
      </div>
    </>
  )
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<Layout><HomePage /></Layout>} />
            <Route
              path="/videos"
              element={
                <ProtectedRoute>
                  <Layout><div className="col-span-full"><h1 className="text-2xl font-bold">Videos</h1></div></Layout>
                </ProtectedRoute>
              }
            />
            <Route
              path="/analytics"
              element={
                <ProtectedRoute>
                  <Layout><div className="col-span-full"><h1 className="text-2xl font-bold">Analytics</h1></div></Layout>
                </ProtectedRoute>
              }
            />
            <Route
              path="/analytics/:videoId"
              element={
                <ProtectedRoute>
                  <Layout><div className="col-span-full"><AnalyticsDashboard /></div></Layout>
                </ProtectedRoute>
              }
            />
            <Route
              path="/compare"
              element={
                <ProtectedRoute>
                  <Layout><div className="col-span-full"><ComparePage /></div></Layout>
                </ProtectedRoute>
              }
            />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  )
}
