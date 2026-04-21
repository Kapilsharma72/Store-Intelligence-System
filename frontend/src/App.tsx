import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { ThemeProvider } from './components/ThemeProvider'
import Layout from './components/Layout'
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

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout><HomePage /></Layout>} />
          <Route
            path="/videos"
            element={
              <Layout><div className="col-span-full"><h1 className="text-2xl font-bold">Videos</h1></div></Layout>
            }
          />
          <Route
            path="/analytics"
            element={
              <Layout><div className="col-span-full"><h1 className="text-2xl font-bold">Analytics</h1></div></Layout>
            }
          />
          <Route
            path="/analytics/:videoId"
            element={
              <Layout><div className="col-span-full"><AnalyticsDashboard /></div></Layout>
            }
          />
          <Route
            path="/compare"
            element={
              <Layout><div className="col-span-full"><ComparePage /></div></Layout>
            }
          />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  )
}
