# Main Flask application with liveness detection and IST timezone
from flask import Flask, redirect, url_for
from flask_socketio import SocketIO
from flask_cors import CORS
from models import db, AbsenceTracker, ActivityLog
from routes import api
from auth_routes import auth_bp
from student_routes import student_bp
from config import Config
from auth_service import User
import cv2
import threading
import time
import logging
import base64
import numpy as np
import pytz
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

IST = pytz.timezone(Config.TIMEZONE)

def create_app():
    """Create and configure Flask app"""
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize extensions
    db.init_app(app)
    
    # Enable CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    
    # Register blueprints
    app.register_blueprint(api)
    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    
    # Root redirect to login
    @app.route('/')
    def index():
        return redirect(url_for('auth.login_page'))
    
    return app

app = create_app()
socketio = SocketIO(app, cors_allowed_origins="*")

class EnhancedCameraService:
    def __init__(self):
        self.is_running = False
        self.last_recognition_time = 0
        self.recognition_cooldown = 5
        self.recognition_history = {}
        
        # Blink detection state
        self.blink_counters = {}  # Per student
        self.ear_history = {}  # Track EAR values
        
        # Import services
        from face_recognition_service import FaceRecognitionService
        from attendance_service import AttendanceService
        from liveness_detection import LivenessDetector
        
        self.face_service = FaceRecognitionService()
        self.attendance_service = AttendanceService()
        self.liveness_detector = LivenessDetector()

    def start_system(self):
        """Start the attendance system"""
        if self.is_running:
            logger.warning("System is already running")
            return
        
        self.is_running = True
        self.recognition_history = {}
        self.blink_counters = {}
        self.ear_history = {}
        
        # Load face encodings
        with app.app_context():
            try:
                self.face_service.load_encodings_from_db()
                logger.info(f"Face encodings loaded: {len(self.face_service.known_ids)} students")
            except Exception as e:
                logger.error(f"Failed to load face encodings: {e}")
        
        logger.info("Enhanced camera service started with liveness detection")

    def stop_system(self):
        """Stop the attendance system"""
        self.is_running = False
        self.recognition_history = {}
        self.blink_counters = {}
        self.ear_history = {}
        logger.info("Camera service stopped")

    def process_frame(self, frame_data):
        """
        Process frame with ENHANCED liveness detection:
        - Requires blink detection
        - Requires eye contact
        - Detects spoofing attempts
        """
        if not self.is_running:
            return {'status': 'system_stopped'}
        
        try:
            # Decode frame
            frame_bytes = base64.b64decode(frame_data)
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is None:
                return {'status': 'invalid_frame'}
            
            # Step 1: Recognize faces
            rec_result = self.face_service.recognize_faces(frame)
            total_faces = rec_result['total_faces']
            matches = rec_result['matches']
            
            if total_faces == 0:
                return {'status': 'clear'}
            
            if len(matches) == 0:
                return {
                    'status': 'unknown',
                    'message': 'Face not recognized - Not enrolled'
                }
            
            # Process first match
            person = matches[0]
            student_id = person['student_id']
            confidence = person['confidence']
            student_name = person['name']
            
            current_time = time.time()
            
            # Check cooldown
            if student_id in self.recognition_history:
                last_time = self.recognition_history[student_id]['time']
                time_diff = current_time - last_time
                
                if time_diff < self.recognition_cooldown:
                    remaining = int(self.recognition_cooldown - time_diff)
                    return {
                        'status': 'cooldown',
                        'message': f"{student_name} already marked ({remaining}s cooldown)"
                    }
            
            # Step 2: Check eye contact (looking at camera)
            has_eye_contact, angles = self.face_service.check_eye_contact(frame)
            
            if not has_eye_contact:
                return {
                    'status': 'verifying',
                    'message': f"{student_name}: Please look at camera"
                }
            
            # Step 3: Check for blink (liveness)
            blink_detected = self.face_service.detect_blink(frame)
            
            # Initialize blink counter for this student
            if student_id not in self.blink_counters:
                self.blink_counters[student_id] = 0
            
            if blink_detected:
                self.blink_counters[student_id] += 1
            
            # Require at least 1 blink
            if self.blink_counters[student_id] < Config.REQUIRED_BLINKS:
                return {
                    'status': 'verifying',
                    'message': f"{student_name}: Please blink naturally"
                }
            
            # Step 4: Mark attendance (all checks passed!)
            result = self.attendance_service.mark_attendance(
                student_id,
                confidence,
                blink_verified=True,
                eye_contact_verified=True
            )
            
            if result['success']:
                logger.info(f"✓ Attendance marked for {student_name} with full verification")
                
                # Reset counters and set cooldown
                self.blink_counters[student_id] = 0
                self.recognition_history[student_id] = {
                    'time': current_time,
                    'count': 0,
                    'name': student_name
                }
                
                return {
                    'status': 'attendance_marked',
                    'results': [{
                        'student_name': result['student_name'],
                        'points': result['points'],
                        'timestamp': current_time,
                        'confidence': confidence
                    }]
                }
            else:
                # Already marked
                self.recognition_history[student_id] = {
                    'time': current_time,
                    'count': 0,
                    'name': student_name
                }
                
                return {
                    'status': 'already_marked',
                    'message': f"{student_name} - {result.get('message', 'Already marked today')}"
                }
        
        except Exception as e:
            logger.error(f"Error processing frame: {e}")
            import traceback
            traceback.print_exc()
            return {'status': 'error', 'message': str(e)}

camera_service = EnhancedCameraService()

# SocketIO Handlers
@socketio.on('start_system')
def handle_start_system():
    """Start the attendance system"""
    try:
        camera_service.start_system()
        socketio.emit('system_started', {'status': 'Enhanced system activated with liveness detection'})
        logger.info("System started via socket")
    except Exception as e:
        logger.error(f"Error starting system: {e}")
        socketio.emit('system_error', {'message': str(e)})

@socketio.on('stop_system')
def handle_stop_system():
    """Stop the attendance system"""
    try:
        camera_service.stop_system()
        socketio.emit('system_stopped', {'status': 'Camera system deactivated'})
        logger.info("System stopped via socket")
    except Exception as e:
        logger.error(f"Error stopping system: {e}")
        socketio.emit('system_error', {'message': str(e)})

@socketio.on('process_frame')
def handle_process_frame(data):
    """Process frame from frontend"""
    try:
        frame_data = data.get('frame')
        if not frame_data:
            return
        
        result = camera_service.process_frame(frame_data)
        
        # Emit appropriate response
        if result['status'] == 'attendance_marked':
            for attendance_result in result['results']:
                socketio.emit('attendance_update', attendance_result)
        elif result['status'] in ['recognizing', 'verifying', 'unknown', 'already_marked', 'cooldown']:
            socketio.emit('recognition_status', result)
        elif result['status'] == 'clear':
            socketio.emit('recognition_status', {'status': 'clear'})
    except Exception as e:
        logger.error(f"Error handling frame: {e}")

# Scheduler for daily tasks
def setup_scheduler():
    """Setup daily attendance reset scheduler"""
    scheduler = BackgroundScheduler(timezone=IST)
    
    # Run daily at midnight IST
    scheduler.add_job(
        func=daily_attendance_check,
        trigger='cron',
        hour=Config.RESET_TIME_HOUR,
        minute=Config.RESET_TIME_MINUTE,
        id='daily_attendance_check'
    )
    
    scheduler.start()
    logger.info(f"Scheduler started - Daily check at {Config.RESET_TIME_HOUR:02d}:{Config.RESET_TIME_MINUTE:02d} IST")

def daily_attendance_check():
    """Run daily attendance checks and send alerts"""
    with app.app_context():
        logger.info("Running daily attendance check...")
        from attendance_service import AttendanceService
        service = AttendanceService()
        service.reset_daily_attendance()

if __name__ == '__main__':
    with app.app_context():
        # Create database tables
        db.create_all()
        logger.info("Database tables created")
        
        # Create default admin user
        from auth_service import AuthService
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            result = AuthService.register_user(
                username='admin',
                email='admin@attendance.system',
                password='admin123',
                role='admin'
            )
            logger.info(f"Default admin user created: {result}")
    
    # Setup scheduler
    setup_scheduler()
    
    # Start Flask-SocketIO server
    logger.info(f"Starting server on port {Config.FLASK_PORT}")
    logger.info(f"Timezone: {Config.TIMEZONE}")
    logger.info(f"Current IST time: {datetime.now(IST).strftime('%Y-%m-%d %I:%M:%S %p')}")
    
    socketio.run(
        app, 
        host='0.0.0.0', 
        port=Config.FLASK_PORT, 
        debug=Config.DEBUG
    )