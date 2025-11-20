# config.py - FIXED VERSION with proper spoof detection settings
import os
from datetime import timedelta

class Config:
    # Database
    DATABASE_PATH = 'attendance_system.db'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///attendance.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production-v2'
    FLASK_PORT = 5000
    DEBUG = False
    
    # Timezone Settings
    TIMEZONE = 'Asia/Kolkata'
    
    # Camera Settings
    CAMERA_INDEX = 0
    FRAME_WIDTH = 640
    FRAME_HEIGHT = 480
    FRAME_SKIP = 2
    
    # Face Recognition Thresholds
    FACE_MATCH_THRESHOLD = 0.5
    RECOGNITION_CONFIDENCE_MIN = 0.5
    
    # Face Quality Requirements
    MIN_FACE_SIZE_PIXELS = 100
    MIN_FACE_BRIGHTNESS = 30
    MAX_FACE_BRIGHTNESS = 240
    MIN_IMAGE_SHARPNESS = 50
    
    # Enrollment Settings
    ENROLLMENT_NUM_JITTERS = 10
    ENROLLMENT_MODEL = 'large'
    DUPLICATE_FACE_THRESHOLD = 0.35
    
    # Liveness Detection - CRITICAL: Mandatory blink, strict thresholds
    EAR_THRESHOLD = 0.21
    BLINK_CONSECUTIVE_FRAMES = 2
    REQUIRED_BLINKS = 1
    EYE_CONTACT_THRESHOLD = 35
    REQUIRE_EYE_CONTACT = False
    TEXTURE_QUALITY_THRESHOLD = 45
    LIVENESS_CONFIDENCE_THRESHOLD = 0.5
    
    # Anti-Spoofing Settings - CRITICAL: Aggressive blocking
    AUTO_BLOCK_SPOOF = True
    SPOOF_CONFIDENCE_THRESHOLD_FLAG = 0.30
    SPOOF_CONFIDENCE_THRESHOLD_BLOCK = 0.35
    
    # CRITICAL: Prioritize phone/texture detection
    SPOOF_WEIGHT_CNN = 0.20
    SPOOF_WEIGHT_TEXTURE = 0.25
    SPOOF_WEIGHT_PHONE = 0.45  # Increased from 0.30 to prioritize phone detection
    SPOOF_WEIGHT_MOIRE = 0.08
    SPOOF_WEIGHT_REFLECTION = 0.03
    SPOOF_WEIGHT_BLINK = 0.02
    
    # Model paths
    ANTI_SPOOF_CNN_MODEL = 'models/anti_spoof_resnet18.onnx'
    PHONE_DETECTOR_MODEL = 'models/yolov5n.pt'
    LANDMARK_PREDICTOR = 'shape_predictor_68_face_landmarks.dat'
    
    # WhatsApp API with DRY_RUN
    WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN") or ""
    WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID") or ""
    WHATSAPP_DRY_RUN = bool(int(os.environ.get("WHATSAPP_DRY_RUN", "1")))
    WHATSAPP_WEBHOOK_VERIFY_TOKEN = os.environ.get('WHATSAPP_WEBHOOK_VERIFY_TOKEN')
    
    if not os.path.exists(PHONE_DETECTOR_MODEL):
        print(f"⚠️  CRITICAL: YOLO model missing at {PHONE_DETECTOR_MODEL}")
        print("   Download: wget https://github.com/ultralytics/yolov5/releases/download/v7.0/yolov5n.pt -O models/yolov5n.pt")
        print("   OR: pip install gdown && gdown 1Drs_Aiu7xx6S-ix95f9kNsA6ueKRpN2b -O models/yolov5n.pt")
    
    # OTP Settings
    OTP_EXP_MINUTES = int(os.environ.get("OTP_EXP_MINUTES", "10"))
    OTP_RESEND_COOLDOWN_SEC = int(os.environ.get("OTP_RESEND_COOLDOWN_SEC", "60"))
    
    # Coordinator Contact
    CLASS_COORDINATOR_PHONE = os.environ.get('COORDINATOR_PHONE') or '+919876543210'
    
    # Alert Settings
    ABSENCE_THRESHOLD = 3
    LATE_THRESHOLD_MINUTES = 10
    TAMPER_SENSITIVITY = 0.8
    
    # Daily Reset Time (IST)
    RESET_TIME_HOUR = 0
    RESET_TIME_MINUTE = 0
    
    # Performance Settings
    RECOGNITION_COOLDOWN_SECONDS = 5
    TARGET_FPS = 3
    MAX_WORKERS = 2
    
    # Security Settings
    MAX_RECOGNITION_ATTEMPTS = 5
    LOCKOUT_DURATION_SECONDS = 30
    LOG_UNKNOWN_FACES = True
    LOG_FAILED_ENROLLMENTS = True
    LOG_SPOOF_ATTEMPTS = True
    
    # Development/Debug Settings
    SHOW_DEBUG_OVERLAY = os.environ.get('SHOW_DEBUG', 'False').lower() == 'true'
    SAVE_DEBUG_IMAGES = False
    DEBUG_IMAGE_DIR = 'debug_images'
    
    @classmethod
    def validate(cls):
        """Validate configuration on startup"""
        errors = []
        
        if not os.path.exists(cls.LANDMARK_PREDICTOR):
            errors.append(f"Missing landmark predictor: {cls.LANDMARK_PREDICTOR}")
        
        if not 0 < cls.FACE_MATCH_THRESHOLD < 1:
            errors.append("FACE_MATCH_THRESHOLD must be between 0 and 1")
        
        if not 0 < cls.RECOGNITION_CONFIDENCE_MIN < 1:
            errors.append("RECOGNITION_CONFIDENCE_MIN must be between 0 and 1")
        
        # FIXED: Validate new spoof weights
        total_weight = (cls.SPOOF_WEIGHT_CNN + cls.SPOOF_WEIGHT_TEXTURE + 
                       cls.SPOOF_WEIGHT_PHONE + cls.SPOOF_WEIGHT_MOIRE + 
                       cls.SPOOF_WEIGHT_REFLECTION + cls.SPOOF_WEIGHT_BLINK)
        
        if not 0.95 <= total_weight <= 1.05:
            errors.append(f"Spoof weights must sum to ~1.0 (currently: {total_weight})")
        
        # Warn if models are missing
        if not os.path.exists(cls.ANTI_SPOOF_CNN_MODEL):
            print(f"⚠️  Warning: CNN spoof model not found at {cls.ANTI_SPOOF_CNN_MODEL}")
            print("   Spoof detection will work with reduced accuracy (texture + FFT only)")
            print("   To improve: Train model using train_antispoofing.py")
        
        if not os.path.exists(cls.PHONE_DETECTOR_MODEL):
            print(f"⚠️  Warning: YOLO phone detector not found at {cls.PHONE_DETECTOR_MODEL}")
            print("   Phone-in-frame detection disabled")
            print("   Download: wget https://github.com/ultralytics/yolov5/releases/download/v7.0/yolov5n.pt -O models/yolov5n.pt")
        
        return errors
    
    @classmethod
    def get_summary(cls):
        """Get configuration summary for logging"""
        return {
            'face_threshold': cls.FACE_MATCH_THRESHOLD,
            'confidence_min': cls.RECOGNITION_CONFIDENCE_MIN,
            'min_face_size': cls.MIN_FACE_SIZE_PIXELS,
            'spoof_auto_block': cls.AUTO_BLOCK_SPOOF,
            'spoof_threshold_flag': cls.SPOOF_CONFIDENCE_THRESHOLD_FLAG,
            'spoof_threshold_block': cls.SPOOF_CONFIDENCE_THRESHOLD_BLOCK,
            'liveness_conf_threshold': cls.LIVENESS_CONFIDENCE_THRESHOLD,
            'texture_threshold': cls.TEXTURE_QUALITY_THRESHOLD,
            'whatsapp_dry_run': cls.WHATSAPP_DRY_RUN,
            'otp_expiry_minutes': cls.OTP_EXP_MINUTES,
            'target_fps': cls.TARGET_FPS
        }

# Validate on import
validation_errors = Config.validate()
if validation_errors:
    print("⚠️  Configuration Errors:")
    for error in validation_errors:
        print(f"  - {error}")
else:
    print("✓ Configuration validated successfully")
    print(f"✓ Settings: {Config.get_summary()}")