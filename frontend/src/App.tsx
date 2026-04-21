import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import { ThemeProvider } from './components/ThemeProvider'
import Layout from './components/Layout'
import VideosPage from './pages/VideosPage'
import AnalyticsListPage from './pages/AnalyticsListPage'
import AnalyticsDashboard from './pages/AnalyticsDashboard'
import ComparePage from './pages/ComparePage'

function HomePage() {
  return (
    <>
      <div className="col-span-full">
        <h1 className="text-3xl font-bold mb-4">Welcome to Store Intelligence</h1>
        <p className="text-lg text-gray-600 dark:text-gray-400 mb-8">
          Real-time retail analytics platform that transforms CCTV footage into actionable business insights.
        </p>
      </div>

      {/* Feature Cards */}
      <div className="col-span-full md:col-span-1 bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-200 dark:border-gray-700">
        <div className="flex items-center mb-4">
          <svg className="w-8 h-8 text-blue-600 dark:text-blue-400 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
          <h2 className="text-xl font-semibold">Video Management</h2>
        </div>
        <p className="text-gray-600 dark:text-gray-400 mb-4">
          Upload and manage CCTV footage. Process videos to extract visitor analytics and behavior patterns.
        </p>
        <Link to="/videos" className="inline-block bg-blue-600 hover:bg-blue-700 text-white font-medium px-4 py-2 rounded transition-colors">
          Go to Videos →
        </Link>
      </div>

      <div className="col-span-full md:col-span-1 bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-200 dark:border-gray-700">
        <div className="flex items-center mb-4">
          <svg className="w-8 h-8 text-green-600 dark:text-green-400 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
          <h2 className="text-xl font-semibold">Analytics Dashboard</h2>
        </div>
        <p className="text-gray-600 dark:text-gray-400 mb-4">
          View real-time metrics, conversion funnels, heatmaps, and customer journey analysis.
        </p>
        <Link to="/analytics" className="inline-block bg-green-600 hover:bg-green-700 text-white font-medium px-4 py-2 rounded transition-colors">
          View Analytics →
        </Link>
      </div>

      <div className="col-span-full md:col-span-1 bg-white dark:bg-gray-800 rounded-lg shadow p-6 border border-gray-200 dark:border-gray-700">
        <div className="flex items-center mb-4">
          <svg className="w-8 h-8 text-purple-600 dark:text-purple-400 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
          </svg>
          <h2 className="text-xl font-semibold">Compare Videos</h2>
        </div>
        <p className="text-gray-600 dark:text-gray-400 mb-4">
          Compare performance metrics across multiple videos to identify trends and patterns.
        </p>
        <Link to="/compare" className="inline-block bg-purple-600 hover:bg-purple-700 text-white font-medium px-4 py-2 rounded transition-colors">
          Compare Videos →
        </Link>
      </div>

      {/* Key Features */}
      <div className="col-span-full mt-8">
        <h2 className="text-2xl font-bold mb-4">Key Features</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-gray-50 dark:bg-gray-800 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
            <h3 className="font-semibold mb-2">🎥 Video Processing</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">YOLOv8-powered person detection and tracking</p>
          </div>
          <div className="bg-gray-50 dark:bg-gray-800 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
            <h3 className="font-semibold mb-2">📊 Real-time Metrics</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">Live visitor count, conversion rates, dwell time</p>
          </div>
          <div className="bg-gray-50 dark:bg-gray-800 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
            <h3 className="font-semibold mb-2">🗺️ Zone Heatmaps</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">Visualize customer movement patterns</p>
          </div>
          <div className="bg-gray-50 dark:bg-gray-800 p-4 rounded-lg border border-gray-200 dark:border-gray-700">
            <h3 className="font-semibold mb-2">⚠️ Anomaly Detection</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">Automatic alerts for unusual patterns</p>
          </div>
        </div>
      </div>

      {/* Quick Start */}
      <div className="col-span-full mt-8 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-6">
        <h2 className="text-xl font-bold mb-3">🚀 Quick Start</h2>
        <ol className="list-decimal list-inside space-y-2 text-gray-700 dark:text-gray-300">
          <li>Go to <Link to="/videos" className="text-blue-600 dark:text-blue-400 hover:underline font-medium">Videos</Link> page</li>
          <li>Upload your CCTV footage (MP4 format)</li>
          <li>Click "Process" to analyze the video</li>
          <li>View analytics and insights on the dashboard</li>
        </ol>
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
              <Layout><VideosPage /></Layout>
            }
          />
          <Route
            path="/analytics"
            element={
              <Layout><AnalyticsListPage /></Layout>
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
              <Layout><ComparePage /></Layout>
            }
          />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  )
}
