# System configuration settings with timezone and coordinator info
import os
from datetime import timedelta

class Config:
    # Database
    DATABASE_PATH = 'attendance_system.db'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///attendance.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    FLASK_PORT = 5000
    DEBUG = False
    
    # Timezone Settings
    TIMEZONE = 'Asia/Kolkata'
    
    # Camera
    CAMERA_INDEX = 0
    FRAME_WIDTH = 1280
    FRAME_HEIGHT = 720
    
    # Face Recognition
    FACE_TOLERANCE = 0.6
    RECOGNITION_CONFIDENCE = 0.4
    
    # Blink Detection (Enhanced)
    EAR_THRESHOLD = 0.25
    BLINK_CONSECUTIVE_FRAMES = 3
    REQUIRED_BLINKS = 1  # Must blink at least once
    
    # Eye Contact Detection (New)
    EYE_CONTACT_THRESHOLD = 15  # Degrees of head rotation allowed
    REQUIRE_EYE_CONTACT = True
    
    # Liveness Detection
    TEXTURE_QUALITY_THRESHOLD = 100  # Threshold for photo vs real face
    LIVENESS_CONFIDENCE_THRESHOLD = 0.6
    
    # WhatsApp API
    WHATSAPP_TOKEN = os.environ.get('WHATSAPP_TOKEN')
    WHATSAPP_PHONE_ID = os.environ.get('WHATSAPP_PHONE_ID')
    WHATSAPP_WEBHOOK_VERIFY_TOKEN = os.environ.get('WHATSAPP_WEBHOOK_VERIFY_TOKEN')
    
    # Coordinator Contact (New)
    CLASS_COORDINATOR_PHONE = os.environ.get('COORDINATOR_PHONE') or '+919876543210'
    
    # Alert Settings
    ABSENCE_THRESHOLD = 3  # Send alert after 3 consecutive absences
    LATE_THRESHOLD_MINUTES = 10
    TAMPER_SENSITIVITY = 0.8
    
    # Daily Reset Time (IST)
    RESET_TIME_HOUR = 0  # 12:00 AM
    RESET_TIME_MINUTE = 0