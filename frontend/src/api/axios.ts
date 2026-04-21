import axios from 'axios'

const api = axios.create({
  baseURL: '/',
})

// Request interceptor: attach Authorization header if token exists
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token')
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`
  }
  return config
})

// Response interceptor: retry once on 5xx after 2-second delay
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config
    if (
      error.response &&
      error.response.status >= 500 &&
      !config._retried
    ) {
      config._retried = true
      await new Promise((resolve) => setTimeout(resolve, 2000))
      return api(config)
    }
    return Promise.reject(error)
  }
)

export default api
