# 🚀 Quick Setup Guide

This guide will help you get the Store Intelligence System running in under 5 minutes.

---

## ⚡ Quick Start (Local Development)

### Prerequisites Check

```bash
# Check Python version (need 3.11+)
python --version

# Check Node.js version (need 18+)
node --version

# Check npm
npm --version
```

---

## 📥 Installation Steps

### 1. Clone & Navigate

```bash
git clone https://github.com/Kapilsharma72/Store-Intelligence-System.git
cd Store-Intelligence-System
```

### 2. Backend Setup

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env

# Initialize database
alembic upgrade head
```

### 3. Frontend Setup

```bash
# Navigate to frontend
cd frontend

# Install dependencies
npm install

# Return to root
cd ..
```

---

## ▶️ Running the Application

### Terminal 1: Start Backend API

```bash
# Make sure virtual environment is activated
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

✅ API running at: **http://localhost:8000**

### Terminal 2: Start Frontend

```bash
cd frontend
npm run dev
```

✅ Dashboard running at: **http://localhost:5173**

---

## 🧪 Verify Installation

### Test API

```bash
# Health check
curl http://localhost:8000/health

# Or open in browser:
# http://localhost:8000/docs
```

### Test Frontend

Open browser and navigate to:
```
http://localhost:5173
```

---

## 🐳 Docker Alternative (Easiest)

If you have Docker installed:

```bash
# Clone repository
git clone https://github.com/Kapilsharma72/Store-Intelligence-System.git
cd Store-Intelligence-System

# Copy environment file
cp .env.example .env

# Edit .env and set PostgreSQL credentials
# POSTGRES_USER=store_user
# POSTGRES_PASSWORD=store_password

# Start everything
docker compose up --build
```

Services will be available at:
- **API**: http://localhost:8000
- **Frontend**: http://localhost:80
- **Dashboard**: http://localhost:8501

---

## 🔧 Common Issues & Solutions

### Issue: "Module not found" error

**Solution:**
```bash
# Make sure virtual environment is activated
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

### Issue: Port already in use

**Solution:**
```bash
# Change port in command
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001

# Or kill process using the port
# Windows:
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# macOS/Linux:
lsof -ti:8000 | xargs kill -9
```

### Issue: Database connection error

**Solution:**
```bash
# For local development, use SQLite (default in .env)
DATABASE_URL=sqlite:///./store_intelligence.db

# Run migrations
alembic upgrade head
```

### Issue: Frontend won't start

**Solution:**
```bash
cd frontend

# Clear cache and reinstall
rm -rf node_modules package-lock.json
npm install

# Start again
npm run dev
```

### Issue: Redis connection error

**Solution:**
For local development, Redis is optional. Comment out Redis-dependent features or install Redis:

**Windows:**
```bash
# Download from: https://github.com/microsoftarchive/redis/releases
# Or use WSL
```

**macOS:**
```bash
brew install redis
brew services start redis
```

**Linux:**
```bash
sudo apt-get install redis-server
sudo systemctl start redis
```

---

## 📊 Sample Data

The project includes sample event data in `data/events/` directory. This data will be automatically loaded when you start the API.

To add your own video data:
1. Place `.mp4` files in `data/clips/` directory
2. Use the video upload API endpoint
3. Process videos through the detection pipeline

---

## 🎯 Next Steps

1. **Explore API**: Visit http://localhost:8000/docs
2. **View Dashboard**: Open http://localhost:5173
3. **Upload Video**: Use the video upload feature in the dashboard
4. **Check Metrics**: View real-time analytics for your stores
5. **Read Documentation**: Check `docs/` folder for detailed information

---

## 📚 Additional Resources

- **Full README**: See `README.md` for complete documentation
- **API Documentation**: http://localhost:8000/docs (when running)
- **Design Docs**: See `docs/DESIGN.md`
- **Technical Choices**: See `docs/CHOICES.md`

---

## 💡 Tips for Development

1. **Use --reload flag**: API auto-reloads on code changes
2. **Check logs**: Monitor terminal output for errors
3. **Use API docs**: Interactive testing at `/docs` endpoint
4. **Enable debug mode**: Set `DEBUG=True` in `.env` for detailed logs
5. **Run tests**: Use `pytest` to ensure everything works

---

## 🆘 Getting Help

If you encounter issues:

1. Check this guide first
2. Review error messages in terminal
3. Check `README.md` for detailed documentation
4. Open an issue on GitHub: https://github.com/Kapilsharma72/Store-Intelligence-System/issues

---

**Happy Coding! 🎉**
