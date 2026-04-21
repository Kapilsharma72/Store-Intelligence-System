# 🏪 Store Intelligence System

> Real-time retail analytics platform that transforms CCTV footage into actionable business insights

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18.3.0-blue.svg)](https://reactjs.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Installation & Setup](#installation--setup)
- [Running the Project](#running-the-project)
- [API Documentation](#api-documentation)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
- [Testing](#testing)
- [Deployment](#deployment)
- [Contributing](#contributing)

---

## 🎯 Overview

The **Store Intelligence System** is an advanced retail analytics platform that processes CCTV footage to provide real-time insights into customer behavior, store performance, and operational efficiency. It uses computer vision (YOLOv8) to detect and track visitors, analyze their movement patterns, and generate actionable metrics.

### Key Capabilities

- **Visitor Detection & Tracking**: Automatic detection and tracking of customers across multiple camera feeds
- **Zone Analytics**: Heatmaps showing customer movement and dwell time in different store zones
- **Conversion Funnel**: Track customer journey from entry to purchase
- **Real-time Metrics**: Live dashboard with visitor count, conversion rates, and queue depth
- **Anomaly Detection**: Automatic alerts for unusual patterns (queue spikes, conversion drops, dead zones)
- **Video Management**: Upload, process, and manage CCTV footage with automatic cleanup
- **Export Capabilities**: Generate PDF/Excel reports for business analysis

---

## ✨ Features

### 🎥 Video Processing
- Multi-camera CCTV feed processing
- YOLOv8-based person detection and tracking
- Zone mapping and movement analysis
- Staff vs. customer classification

### 📊 Analytics Dashboard
- Real-time visitor metrics
- Interactive heatmaps
- Conversion funnel visualization
- Queue depth monitoring
- Anomaly alerts

### 🔐 Security & Performance
- JWT-based authentication
- Rate limiting with Redis
- Request tracing (X-Trace-ID)
- Async processing with background workers
- Automatic video retention and cleanup

### 📈 Business Intelligence
- Conversion rate analysis
- Average dwell time tracking
- Zone performance metrics
- Abandonment rate calculation
- Historical trend analysis

---

## 🏗️ Architecture

```
┌─────────────────┐
│  CCTV Cameras   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐      ┌──────────────┐
│  Video Upload   │─────▶│  Detection   │
│   & Storage     │      │   Pipeline   │
└─────────────────┘      └──────┬───────┘
                                │
                                ▼
                         ┌──────────────┐
                         │  Event Queue │
                         │   (Redis)    │
                         └──────┬───────┘
                                │
                                ▼
┌─────────────────┐      ┌──────────────┐      ┌──────────────┐
│  React Frontend │◀────▶│  FastAPI     │◀────▶│  PostgreSQL  │
│   Dashboard     │      │   Backend    │      │   Database   │
└─────────────────┘      └──────────────┘      └──────────────┘
```

### Data Flow

1. **Video Ingestion**: CCTV footage uploaded via API or processed from local files
2. **Detection**: YOLOv8 detects and tracks persons in each frame
3. **Zone Mapping**: Visitor positions mapped to store zones (entry, aisles, checkout, etc.)
4. **Event Generation**: Structured events (ENTRY, ZONE_VISIT, PURCHASE, etc.) created
5. **Storage**: Events stored in PostgreSQL, cached in Redis
6. **Analytics**: Real-time aggregation and metric calculation
7. **Visualization**: Live dashboard displays insights

---

## 🛠️ Tech Stack

### Backend
- **FastAPI** - Modern Python web framework
- **SQLAlchemy** - ORM for database operations
- **Alembic** - Database migrations
- **PostgreSQL** - Primary database
- **Redis** - Caching, job queue, pub/sub
- **Uvicorn** - ASGI server

### Frontend
- **React 18** - UI library
- **TypeScript** - Type-safe JavaScript
- **Vite** - Build tool
- **Chart.js** - Data visualization
- **Axios** - HTTP client
- **TailwindCSS** - Styling

### Computer Vision
- **YOLOv8** (Ultralytics) - Object detection
- **OpenCV** - Video processing
- **Shapely** - Geometric operations

### DevOps
- **Docker** - Containerization
- **Docker Compose** - Multi-container orchestration
- **pytest** - Testing framework
- **Hypothesis** - Property-based testing

---

## 📦 Prerequisites

### Required Software

- **Python 3.11+** - [Download](https://www.python.org/downloads/)
- **Node.js 18+** - [Download](https://nodejs.org/)
- **PostgreSQL 15+** - [Download](https://www.postgresql.org/download/) (or use SQLite for development)
- **Redis 7+** - [Download](https://redis.io/download/) (optional for development)

### Optional (for Docker deployment)
- **Docker** - [Download](https://www.docker.com/get-started)
- **Docker Compose** - Included with Docker Desktop

---

## 🚀 Installation & Setup

### Option 1: Local Development (Without Docker)

#### Step 1: Clone the Repository

```bash
git clone https://github.com/Kapilsharma72/Store-Intelligence-System.git
cd Store-Intelligence-System
```

#### Step 2: Set Up Python Environment

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

#### Step 3: Configure Environment Variables

```bash
# Copy example environment file
cp .env.example .env

# Edit .env file with your configuration
# For local development, the default SQLite configuration works fine
```

**Key Environment Variables:**

```env
# Database (SQLite for local dev)
DATABASE_URL=sqlite:///./store_intelligence.db

# API Configuration
API_BASE_URL=http://localhost:8000

# Redis (optional for local dev)
REDIS_URL=redis://localhost:6379/0

# JWT Secret
JWT_SECRET=your-secret-key-change-in-production

# Storage
STORAGE_BACKEND=local
LOCAL_STORAGE_PATH=data/videos
```

#### Step 4: Initialize Database

```bash
# Run database migrations
alembic upgrade head
```

#### Step 5: Set Up Frontend

```bash
cd frontend

# Install Node dependencies
npm install

# Return to project root
cd ..
```

#### Step 6: Download YOLOv8 Model (Optional)

```bash
# The model will auto-download on first use, or manually download:
# Place yolov8n.pt in the project root
```

---

### Option 2: Docker Deployment

```bash
# Clone repository
git clone https://github.com/Kapilsharma72/Store-Intelligence-System.git
cd Store-Intelligence-System

# Copy environment file
cp .env.example .env

# Edit .env with your PostgreSQL credentials
# POSTGRES_USER=store_user
# POSTGRES_PASSWORD=store_password

# Start all services
docker compose up --build

# Services will be available at:
# - API: http://localhost:8000
# - Frontend: http://localhost:80
# - Dashboard: http://localhost:8501
```

---

## 🎮 Running the Project

### Start Backend API

```bash
# Make sure you're in the project root with venv activated
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at: **http://localhost:8000**

### Start Frontend Dashboard

```bash
# In a new terminal, navigate to frontend directory
cd frontend

# Start development server
npm run dev
```

The dashboard will be available at: **http://localhost:5173**

### Verify Installation

```bash
# Test API health endpoint
curl http://localhost:8000/health

# Expected response:
# {"status":"ok","db":"ok","stores":[...]}
```

---

## 📚 API Documentation

### Interactive API Docs

Once the backend is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Key Endpoints

#### Health Check
```bash
GET /health
```
Returns system status and database connectivity

#### Ingest Events
```bash
POST /events/ingest
Content-Type: application/json

[{
  "event_id": "uuid",
  "store_id": "STORE_001",
  "camera_id": "CAM_ENTRY",
  "visitor_id": "VIS_123",
  "event_type": "ENTRY",
  "timestamp": "2024-01-15T10:00:00+00:00",
  "is_staff": false,
  "confidence": 0.92
}]
```

#### Store Metrics
```bash
GET /stores/{store_id}/metrics
GET /stores/{store_id}/metrics?start=2024-01-15T09:00:00Z&end=2024-01-15T18:00:00Z
```

#### Visitor Funnel
```bash
GET /stores/{store_id}/funnel
```

#### Zone Heatmap
```bash
GET /stores/{store_id}/heatmap
```

#### Anomaly Detection
```bash
GET /stores/{store_id}/anomalies
```

#### Video Management
```bash
POST /api/v1/videos/upload          # Upload video
GET /api/v1/videos                   # List videos
GET /api/v1/videos/{video_id}        # Get video details
DELETE /api/v1/videos/{video_id}     # Delete video
POST /api/v1/videos/{video_id}/process  # Process video
```

---

## 📁 Project Structure

```
Store-Intelligence-System/
│
├── app/                          # Backend application
│   ├── main.py                   # FastAPI app entry point
│   ├── database.py               # Database configuration
│   ├── models.py                 # SQLAlchemy models
│   ├── ingestion.py              # Event ingestion endpoints
│   ├── metrics.py                # Metrics calculation
│   ├── funnel.py                 # Funnel analysis
│   ├── heatmap.py                # Heatmap generation
│   ├── anomalies.py              # Anomaly detection
│   ├── videos.py                 # Video management
│   ├── auth.py                   # Authentication
│   ├── websocket.py              # Real-time updates
│   ├── worker.py                 # Background job processor
│   └── ...
│
├── frontend/                     # React frontend
│   ├── src/
│   │   ├── components/           # React components
│   │   ├── pages/                # Page components
│   │   ├── services/             # API services
│   │   └── App.tsx               # Main app component
│   ├── package.json
│   └── vite.config.ts
│
├── alembic/                      # Database migrations
│   ├── versions/                 # Migration scripts
│   └── env.py
│
├── tests/                        # Test suite
│   ├── test_ingestion.py
│   ├── test_metrics.py
│   ├── test_funnel.py
│   └── ...
│
├── data/                         # Data directory
│   ├── clips/                    # Input video files
│   ├── events/                   # Generated event logs
│   └── videos/                   # Uploaded videos
│
├── docs/                         # Documentation
│   ├── DESIGN.md                 # System design
│   └── CHOICES.md                # Technical decisions
│
├── .env                          # Environment variables
├── .env.example                  # Example environment file
├── requirements.txt              # Python dependencies
├── docker-compose.yml            # Docker orchestration
├── Dockerfile.api                # API container
├── Dockerfile.frontend           # Frontend container
└── README.md                     # This file
```

---

## 🔍 How It Works

### 1. Video Processing Pipeline

```
Video Input → Frame Extraction → Person Detection (YOLOv8) → Tracking → Zone Mapping → Event Generation
```

**Detection Pipeline Steps:**

1. **Frame Extraction**: Extract frames from video at configured FPS
2. **Person Detection**: YOLOv8 detects persons in each frame with bounding boxes
3. **Tracking**: Assign unique IDs to track individuals across frames
4. **Zone Mapping**: Map person coordinates to store zones using Shapely polygons
5. **Classification**: Distinguish staff from customers based on movement patterns
6. **Event Emission**: Generate structured events (ENTRY, ZONE_VISIT, PURCHASE, etc.)

### 2. Event Types

- **ENTRY**: Customer enters the store
- **ZONE_VISIT**: Customer enters a specific zone
- **ZONE_DWELL**: Customer stays in zone for threshold duration
- **BILLING_QUEUE_JOIN**: Customer joins checkout queue
- **BILLING_QUEUE_ABANDON**: Customer leaves queue without purchase
- **PURCHASE**: Transaction completed at POS
- **EXIT**: Customer leaves the store

### 3. Metrics Calculation

**Conversion Rate**:
```
Conversion Rate = (Purchases / Unique Visitors) × 100
```

**Average Dwell Time**:
```
Avg Dwell Time = Total Time in Store / Number of Visitors
```

**Abandonment Rate**:
```
Abandonment Rate = (Queue Abandons / Queue Joins) × 100
```

### 4. Anomaly Detection

The system monitors for:

- **Queue Spikes** (HIGH): Queue depth exceeds threshold for extended period
- **Conversion Drops** (MEDIUM): Conversion rate falls below historical average
- **Dead Zones** (LOW): Zones with significantly lower traffic than expected

### 5. Real-time Updates

- WebSocket connections for live metric updates
- Redis pub/sub for event broadcasting
- Background workers process video uploads asynchronously

---

## 🧪 Testing

### Run All Tests

```bash
# Run test suite with coverage
pytest --cov=app tests/

# Run with detailed coverage report
pytest --cov=app --cov-report=term-missing tests/

# Run specific test file
pytest tests/test_ingestion.py -v
```

### Property-Based Testing

The project uses Hypothesis for property-based testing to ensure correctness:

```bash
# Tests automatically include property-based tests
pytest tests/ -v
```

### Smoke Tests

```bash
# Run behavioral assertions against live API
python assertions.py

# Test against remote instance
API_BASE_URL=http://your-host:8000 python assertions.py
```

---

## 🚢 Deployment

### Production Checklist

- [ ] Change `JWT_SECRET` to a strong random value
- [ ] Use PostgreSQL instead of SQLite
- [ ] Configure Redis for production
- [ ] Set up SSL/TLS certificates
- [ ] Configure CORS for your domain
- [ ] Set up monitoring and logging
- [ ] Configure automatic backups
- [ ] Set up CI/CD pipeline
- [ ] Review and adjust rate limits
- [ ] Configure video retention policy

### Environment Variables for Production

```env
DATABASE_URL=postgresql://user:password@host:5432/dbname
REDIS_URL=redis://host:6379/0
JWT_SECRET=<strong-random-secret>
STORAGE_BACKEND=s3
S3_BUCKET=your-bucket-name
S3_REGION=us-east-1
S3_ACCESS_KEY=your-access-key
S3_SECRET_KEY=your-secret-key
```

### Docker Production Deployment

```bash
# Build and start services
docker compose -f docker-compose.prod.yml up -d

# View logs
docker compose logs -f

# Scale workers
docker compose up -d --scale worker=3
```

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Guidelines

- Follow PEP 8 for Python code
- Use TypeScript for frontend code
- Write tests for new features
- Update documentation as needed
- Ensure all tests pass before submitting PR

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 👥 Authors

- **Kapil Sharma** - [GitHub](https://github.com/Kapilsharma72)

---

## 🙏 Acknowledgments

- YOLOv8 by Ultralytics for object detection
- FastAPI for the excellent web framework
- React team for the UI library
- All open-source contributors

---

## 📞 Support

For questions or issues:

- **GitHub Issues**: [Create an issue](https://github.com/Kapilsharma72/Store-Intelligence-System/issues)
- **Email**: [Your Email]
- **Documentation**: See `/docs` folder for detailed design docs

---

## 🗺️ Roadmap

- [ ] Multi-store dashboard
- [ ] Advanced ML models for behavior prediction
- [ ] Mobile app for store managers
- [ ] Integration with POS systems
- [ ] Real-time alerts via SMS/Email
- [ ] A/B testing for store layouts
- [ ] Customer segmentation analysis

---

**Made with ❤️ for retail analytics**
