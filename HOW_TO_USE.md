# 🎯 How to Use the Store Intelligence System

## Current Status

✅ **Working Features:**
- Video upload (MP4, AVI, MOV files)
- Video library display
- Video deletion
- Basic video management

⚠️ **Requires Setup:**
- Video processing (needs Redis + Background Worker)
- Analytics generation
- Heatmaps and funnels

---

## 🚀 Quick Start Guide

### What You Have Now

1. **Backend API** running on `http://localhost:8000`
2. **Frontend Dashboard** running on `http://localhost:5173`
3. **Video Upload** - Working without FFmpeg (basic validation only)
4. **Video Library** - Shows uploaded videos

### What's Missing for Full Functionality

The **core analytics features** require:
1. **Redis** - For job queue and caching
2. **Background Worker** - To process videos and generate analytics
3. **YOLOv8 Model** - For person detection (auto-downloads on first use)

---

## 📋 Complete Setup Instructions

### Option 1: Quick Demo (Current State)

**What works:**
- Upload videos
- View video library
- Delete videos

**What doesn't work:**
- Processing videos
- Viewing analytics
- Heatmaps/funnels

### Option 2: Full System (Recommended)

To get the complete system working with analytics:

#### Step 1: Install Redis

**Windows:**
```bash
# Download Redis for Windows from:
# https://github.com/microsoftarchive/redis/releases
# Or use WSL2 with:
wsl --install
wsl
sudo apt-get update
sudo apt-get install redis-server
redis-server
```

**macOS:**
```bash
brew install redis
brew services start redis
```

**Linux:**
```bash
sudo apt-get update
sudo apt-get install redis-server
sudo systemctl start redis
```

#### Step 2: Verify Redis is Running

```bash
# Test Redis connection
redis-cli ping
# Should return: PONG
```

#### Step 3: Start the Background Worker

Open a **new terminal** (keep backend and frontend running):

```bash
# Activate virtual environment
venv\Scripts\activate  # Windows
# or
source venv/bin/activate  # macOS/Linux

# Start the worker
python -m app.worker
```

You should see:
```
worker_loop_started pid=12345
```

#### Step 4: Process a Video

1. Go to **Videos** page
2. Upload a video (one of the sample videos from `data/clips/`)
3. Click the **"Process"** button next to the uploaded video
4. Wait for processing to complete (status will change from "pending" → "processing" → "completed")

#### Step 5: View Analytics

1. Go to **Analytics** page
2. Select the processed video
3. View:
   - Heatmaps
   - Visitor metrics
   - Zone analytics
   - Conversion funnels

---

## 🎬 How the System Works

### 1. Video Upload Flow

```
User uploads video → Validates format → Stores in data/sample/ → Saves to database → Shows in library
```

### 2. Video Processing Flow (Requires Redis + Worker)

```
User clicks "Process" → Job added to Redis queue → Worker picks up job → 
YOLOv8 detects people → Tracks movement → Maps to zones → Generates events → 
Stores analytics → Status: "completed"
```

### 3. Analytics Generation

The system analyzes:
- **Person Detection**: Where people are in each frame
- **Tracking**: Following individuals across frames
- **Zone Mapping**: Which store areas they visit
- **Dwell Time**: How long they stay in each zone
- **Conversion**: Did they make a purchase?
- **Heatmaps**: Visual representation of traffic patterns

---

## 🔧 Troubleshooting

### Problem: "Process" button doesn't work

**Solution:** Redis and worker are not running.

1. Start Redis (see Step 1 above)
2. Start the worker (see Step 3 above)
3. Try processing again

### Problem: Video upload fails with 422 error

**Solution:** This was fixed! Make sure you pulled the latest code:

```bash
git pull origin main
# Restart backend
python -m uvicorn app.main:app --reload
```

### Problem: Analytics page shows "No Processed Videos"

**Solution:** You need to:
1. Upload a video
2. **Process** the video (requires Redis + worker)
3. Wait for status to become "completed"
4. Then analytics will be available

### Problem: Worker crashes or shows errors

**Common causes:**
- YOLOv8 model not downloaded (it auto-downloads on first use)
- OpenCV not installed properly
- Video file is corrupted

**Solution:**
```bash
# Reinstall dependencies
pip install --upgrade -r requirements.txt

# Check if OpenCV works
python -c "import cv2; print(cv2.__version__)"
```

---

## 📊 Understanding the Data Flow

### Without Worker (Current State)

```
┌─────────────┐
│   Upload    │
│   Video     │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Store     │
│   in DB     │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Show in   │
│   Library   │
└─────────────┘
```

### With Worker (Full System)

```
┌─────────────┐
│   Upload    │
│   Video     │
└──────┬──────┘
       │
       ▼
┌─────────────┐      ┌─────────────┐
│   Store     │─────▶│   Click     │
│   in DB     │      │  "Process"  │
└─────────────┘      └──────┬──────┘
                            │
                            ▼
                     ┌─────────────┐
                     │  Add to     │
                     │  Redis      │
                     │  Queue      │
                     └──────┬──────┘
                            │
                            ▼
                     ┌─────────────┐
                     │  Worker     │
                     │  Processes  │
                     └──────┬──────┘
                            │
                            ▼
                     ┌─────────────┐
                     │  YOLOv8     │
                     │  Detection  │
                     └──────┬──────┘
                            │
                            ▼
                     ┌─────────────┐
                     │  Generate   │
                     │  Analytics  │
                     └──────┬──────┘
                            │
                            ▼
                     ┌─────────────┐
                     │  View in    │
                     │  Dashboard  │
                     └─────────────┘
```

---

## 🎯 Next Steps

### For Demo/Testing (Without Full Setup)

1. **Show video upload functionality**
2. **Show video library management**
3. **Explain that analytics requires background processing**

### For Full Functionality

1. **Install Redis** (5 minutes)
2. **Start worker** (1 command)
3. **Process a sample video** (2-5 minutes depending on video length)
4. **View analytics** (instant once processed)

---

## 📝 Sample Videos

The project includes sample videos in `data/clips/`:
- `CAM_1.mp4` - Entry camera footage
- `CAM_2.mp4` - Aisle camera footage
- `CAM_3.mp4` - Checkout camera footage
- `CAM_4.mp4` - Exit camera footage
- `CAM_5.mp4` - Store overview

These are perfect for testing the system!

---

## 🚀 Production Deployment

For a production environment, use Docker:

```bash
# Start all services (API, Frontend, Redis, Worker, PostgreSQL)
docker compose up --build

# Everything will be configured automatically
# Access at: http://localhost
```

---

## 💡 Key Features to Demonstrate

### 1. Video Management
- Upload multiple videos
- View library with metadata
- Delete unwanted videos

### 2. Processing (with Redis + Worker)
- Process videos to extract analytics
- Monitor processing progress
- Cancel processing if needed

### 3. Analytics Dashboard (after processing)
- Real-time visitor metrics
- Heatmaps showing traffic patterns
- Conversion funnel analysis
- Zone performance metrics
- Anomaly detection

### 4. Business Intelligence
- Conversion rate tracking
- Average dwell time
- Queue depth monitoring
- Zone effectiveness analysis

---

## 📞 Need Help?

If you encounter issues:

1. Check that all services are running:
   - Backend: `http://localhost:8000/health`
   - Frontend: `http://localhost:5173`
   - Redis: `redis-cli ping`

2. Check logs:
   - Backend logs in terminal
   - Worker logs in worker terminal
   - Browser console for frontend errors

3. Restart services:
   ```bash
   # Stop all (Ctrl+C in each terminal)
   # Then restart in order:
   # 1. Redis
   # 2. Backend
   # 3. Worker
   # 4. Frontend
   ```

---

**Made with ❤️ for retail analytics**
