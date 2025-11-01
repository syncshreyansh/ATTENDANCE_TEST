<div align="center">

# 🔮 Smart Attendance System 🔮

### An AI-Powered Face Recognition System with Advanced Liveness Detection, Dual Dashboards, and Automated WhatsApp Alerts

<p>
  <img src="https://img.shields.io/badge/Python-3.10+-3670A0?logo=python&logoColor=ffdd54&style=for-the-badge" alt="Python Badge" />
  <img src="https://img.shields.io/badge/Flask-3.0-000000?logo=flask&logoColor=white&style=for-the-badge" alt="Flask Badge" />
  <img src="https://img.shields.io/badge/Socket.IO-4.5-010101?logo=socketdotio&logoColor=white&style=for-the-badge" alt="Socket.IO Badge" />
  <img src="https://img.shields.io/badge/OpenCV-4.8-5C3EE8?logo=opencv&logoColor=white&style=for-the-badge" alt="OpenCV Badge" />
  <img src="https://img.shields.io/badge/dlib-20.0-blue?style=for-the-badge" alt="dlib Badge" />
  <img src="https://img.shields.io/badge/JWT-Secure-DB00A1?logo=jsonwebtokens&style=for-the-badge" alt="JWT Badge" />
</p>

</div>

---

## 🚀 Overview

**Smart Attendance System** is a complete, production-ready solution to eliminate proxy attendance and manual tracking. It leverages AI-driven facial recognition with a critical enhancement: a **multi-step liveness and anti-spoofing engine**.

The system is built as a robust full-stack application featuring a Python (Flask) backend, a real-time (Socket.IO) admin dashboard, a separate secure (JWT) dashboard for students, and an automated **WhatsApp alert system** for chronic absenteeism.

---

## ✨ Core Features

### 🔐 Advanced Liveness & Anti-Spoofing
- **Blink Detection (EAR):** Ensures the subject is a live person, not a photo
- **Gaze Tracking (Head Pose):** Verifies the student is looking at the camera, preventing side-on or recorded video attacks
- **Texture Analysis:** Detects the texture quality of the face to differentiate between real skin and a digital screen or high-gloss photo
- **Camera Obstruction Detection:** Senses if the camera is covered, dark, or unfocused and logs the event

### 📲 Automated WhatsApp Absence Alerts
- APScheduler runs a daily job to check attendance patterns
- If a student is marked absent for **3 consecutive days**, the system automatically sends a WhatsApp alert to both the **parent's phone** and the designated **Class Coordinator**

### 🖥️ Dual Dashboard System
- **Admin Dashboard:** A real-time command center showing the live camera feed, a log of all recognition events, and live-updating stats (Present, Absent, Attendance Rate)
- **Student Dashboard:** A secure, individual portal where students can log in (using JWT) to view their own attendance calendar, performance charts, and total points

### 🏆 Gamification & Student Motivation
- Students earn **points** for being on time and passing liveness checks
- The student dashboard features a **Leaderboard** to publicly reward punctuality, turning attendance into a positive and engaging habit

### 🔒 Secure & Robust Backend
- **JWT Authentication:** Secure, token-based auth for all API routes, with distinct `admin` and `student` roles
- **Stateful Recognition:** The system intelligently manages recognition state to prevent spamming, handle multiple faces, and manage "cooldown" periods
- **Suspicious Activity Logging:** Any potential proxy attempts, camera obstructions, or unknown faces are logged to an `ActivityLog` in the database for admin review
- **Duplicate Face-Check:** Prevents enrolling a face that is already associated with another student

---

## 🧩 System Architecture

| Component | Technology / File | Role & Responsibility |
|:---|:---|:---|
| **Application Server** | `main.py` (Flask) | Runs the web server, handles Socket.IO events, and manages the camera service |
| **Authentication** | `auth_service.py`, `auth_routes.py` | Manages user registration, login, and JWT token generation/verification for all roles |
| **Admin Interface** | `routes.py`, `dashboard.html` | Serves the admin dashboard, handles student enrollment, and provides APIs for stats and activity logs |
| **Student Interface** | `student_routes.py`, `student_dashboard.html` | Provides secure, individual access to attendance history, stats, trends, and the leaderboard |
| **AI Core** | `face_recognition_service.py` | Handles face detection, encoding, matching, and duplicate checks |
| **Liveness Engine** | `liveness_detection.py` | Performs advanced anti-spoofing checks (EAR, Head Pose, Texture) |
| **Core Logic** | `attendance_service.py` | Manages marking attendance, calculating points, and tracking consecutive absences |
| **Database** | `models.py` (SQLAlchemy) | Defines the schema for `Student`, `Attendance`, `User`, `ActivityLog`, and `AbsenceTracker` |
| **Notification** | `whatsapp_service.py` | Manages integration with the WhatsApp Business API for sending alerts |
| **Scheduler** | `main.py` (APScheduler) | Triggers the `daily_attendance_check` function every night to find and report absentees |
| **Real-Time Layer** | `main.py` (Flask-SocketIO) | Pushes live updates from the server to the admin dashboard |

---

## 🛠️ Tech Stack

| Layer | Technologies |
|:---|:---|
| **Backend** | Flask, Flask-SocketIO, Flask-SQLAlchemy, JWT |
| **AI & Computer Vision** | OpenCV, dlib, face_recognition, numpy |
| **Frontend** | HTML5, CSS3, Vanilla JavaScript, Chart.js |
| **Database** | SQLite (default), easily swappable to PostgreSQL |
| **Notifications** | WhatsApp Business API |
| **Scheduling** | APScheduler |
| **Deployment** | Ready for Gunicorn, Docker, Render |

---

## ⚙️ Getting Started

### 1. Prerequisites

This project relies on `dlib`, which must be compiled. This requires C++ build tools and `cmake`.

**On Debian/Ubuntu:**
```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake libopenblas-dev liblapack-dev libjpeg-dev
```

**On Windows:** Install Microsoft C++ Build Tools and CMake

### 2. Clone & Install

```bash
# Clone the repository
git clone https://github.com/your-username/AI_ATTENDENCE_SYSTEM.git
cd AI_ATTENDENCE_SYSTEM

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# Install all Python dependencies
pip install -r requirements.txt
```

### 3. Set Up Environment Variables

Create a `.env` file in the root directory:

```env
# Flask
SECRET_KEY='your_super_secret_key_here'

# WhatsApp (Meta Business API)
WHATSAPP_TOKEN='YOUR_WHATSAPP_API_TOKEN'
WHATSAPP_PHONE_ID='YOUR_WHATSAPP_SENDER_PHONE_ID'

# Contact for alerts
COORDINATOR_PHONE='+919876543210'
```

### 4. Initialize the Database

```bash
python main.py
```

This creates the `attendance.db` file and a default admin user:
- **Username:** admin
- **Password:** admin123

### 5. Run the System

```bash
python main.py
```

Open your browser and navigate to `http://127.0.0.1:5000`

---

## 💡 How It Works

### Admin Workflow
1. **Admin Login:** Navigate to `http://127.0.0.1:5000/` and log in with admin credentials
2. **Enroll Student:** Click "Enroll Student," fill in details, and capture a photo
3. **Start System:** Click "Start" to activate the camera service

### Real-Time Recognition
1. Student stands in front of the camera
2. System detects face and performs liveness checks
3. Matches face against database
4. Marks attendance and awards points
5. Updates admin dashboard in real-time

### Student Experience
- Log in to Student Dashboard at `/student-dashboard`
- View attendance calendar and performance charts
- Track points and leaderboard position

### Automated Alerts
- Nightly job runs at midnight (IST)
- Identifies students with 3+ consecutive absences
- Sends WhatsApp alerts to parents and coordinators

---

## 🔬 Evaluation

Test the recognition accuracy using the evaluation script:

```bash
# Add test images to test_images/ following this structure:
# test_images/
#   <student_id_1>/
#     image1.jpg
#     image2.png
#   <student_id_2>/
#     image3.jpg

# Run evaluation
python evaluate_recognition.py
```

The script prints overall accuracy and per-student breakdown.

---

## 📁 Project Structure

```
AI_ATTENDENCE_SYSTEM/
├── main.py                          # Application entry point
├── models.py                        # Database models
├── auth_service.py                  # Authentication logic
├── auth_routes.py                   # Auth API routes
├── routes.py                        # Admin routes
├── student_routes.py                # Student routes
├── face_recognition_service.py      # Face recognition core
├── liveness_detection.py            # Anti-spoofing engine
├── attendance_service.py            # Attendance logic
├── whatsapp_service.py              # WhatsApp integration
├── evaluate_recognition.py          # Model evaluation script
├── requirements.txt                 # Python dependencies
├── .env                             # Environment variables
├── templates/                       # HTML templates
│   ├── dashboard.html
│   ├── student_dashboard.html
│   └── login.html
├── static/                          # CSS, JS, images
└── test_images/                     # Evaluation dataset
```

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

