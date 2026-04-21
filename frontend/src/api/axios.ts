import axios from 'axios'

const api = axios.create({
  baseURL: '/',
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
