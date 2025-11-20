# Complete main Flask application - working version with spoof detection
from flask import Flask, redirect, url_for
from flask_socketio import SocketIO, emit
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
    
    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    
    app.register_blueprint(api)
    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    
    @app.route('/')
    def index():
        return redirect(url_for('auth.login_page'))
    
    return app

app = create_app()
socketio = SocketIO(
    app, 
    cors_allowed_origins="*",
    max_http_buffer_size=10000000,
    ping_timeout=60,
    ping_interval=25,
    async_mode='threading'
)

def broadcast_spoof_event(event_data):
    """
    Broadcast spoof detection event to all connected clients
    event_data: {timestamp, student_id, name, status, spoof_type, confidence, details}
    """
    try:
        socketio.emit('activity_update', event_data, namespace='/')
        logger.info(f"Broadcasted spoof event: {event_data.get('spoof_type')}")
    except Exception as e:
        logger.error(f"Failed to broadcast event: {e}")

class EnhancedCameraService:
    def __init__(self):
        self.is_running = False
        self.last_recognition_time = {}
        self.recognition_cooldown = 5
        self.last_event_log_time = {}
        
        from face_recognition_service import FaceRecognitionService
        from attendance_service import AttendanceService
        
        self.face_service = FaceRecognitionService()
        self.attendance_service = AttendanceService()

    def start_system(self):
        """Start the attendance system"""
        if self.is_running:
            logger.warning("System is already running")
            return
        
        self.is_running = True
        self.last_recognition_time = {}
        
        with app.app_context():
            try:
                self.face_service.load_encodings_from_db()
                logger.info(f"Face encodings loaded: {len(self.face_service.known_ids)} students")
            except Exception as e:
                logger.error(f"Failed to load face encodings: {e}")
        
        logger.info("Enhanced camera service started with intelligent state management")

    def stop_system(self):
        """Stop the attendance system"""
        self.is_running = False
        self.last_recognition_time = {}
        logger.info("Camera service stopped")

    def process_frame(self, frame_data):
        """Process frame with intelligent state-based notifications and spoof detection"""
        if not self.is_running:
            return {'status': 'system_stopped'}
        
        try:
            # Decode frame
            frame_bytes = base64.b64decode(frame_data)
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is None:
                return {'status': 'invalid_frame'}
            
            # Use enhanced recognition with state management
            status, message, data = self.face_service.recognize_faces_with_state(frame)
            
            current_time = time.time()
            
            # Handle different states
            if status == 'obstructed':
                self._log_recent_event('camera_obstructed', message)
                return {
                    'status': 'obstructed',
                    'message': message
                }
            
            if status == 'no_face':
                return {'status': 'clear'}
            
            if status == 'multiple_faces':
                return {
                    'status': 'error',
                    'message': message
                }
            
            if status == 'unknown':
                return {
                    'status': 'unknown',
                    'message': message
                }
            
            if status in ['verifying_gaze', 'verifying_blink']:
                return {
                    'status': 'verifying',
                    'message': message
                }
            
            # Handle spoof detection results
            if status in ['spoof_blocked', 'spoof_flagged']:
                student_name = data.get('student_name', 'Unknown')
                spoof_type = data.get('spoof_type', 'Unknown')
                
                from attendance_service import AttendanceService
                service = AttendanceService()
                service.log_spoofing_attempt(
                    data.get('student_id'),
                    student_name,
                    spoof_type,
                    data.get('spoof_confidence', 0)
                )
                
                broadcast_spoof_event({
                    'timestamp': current_time,
                    'student_id': data.get('student_id'),
                    'name': student_name,
                    'status': 'BLOCKED - SPOOFING ATTEMPT',
                    'spoof_type': spoof_type,
                    'spoof_confidence': data.get('spoof_confidence'),
                    'details': f"Someone tried to mark attendance for {student_name} using {spoof_type}",
                    'evidence': data.get('evidence')
                })
                
                return {
                    'status': 'error',
                    'message': message
                }
            
            if status == 'verified':
                student_id = data['student_id']
                student_name = data['student_name']
                confidence = data['confidence']
                
                # Check cooldown
                if student_id in self.last_recognition_time:
                    last_time = self.last_recognition_time[student_id]
                    time_diff = current_time - last_time
                    
                    if time_diff < self.recognition_cooldown:
                        remaining = int(self.recognition_cooldown - time_diff)
                        return {
                            'status': 'cooldown',
                            'message': f"{student_name} already marked ({remaining}s cooldown)"
                        }
                
                # Mark attendance
                result = self.attendance_service.mark_attendance(
                    student_id,
                    confidence,
                    blink_verified=True,
                    eye_contact_verified=True
                )
                
                if result['success']:
                    logger.info(f"✓ Attendance marked for {student_name}")
                    
                    self.last_recognition_time[student_id] = current_time
                    
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
                    self.last_recognition_time[student_id] = current_time
                    
                    return {
                        'status': 'already_marked',
                        'message': f"{student_name} - {result.get('message', 'Already marked today')}"
                    }
            
            return {'status': 'processing'}
        
        except Exception as e:
            logger.error(f"Error processing frame: {e}")
            import traceback
            traceback.print_exc()
            return {'status': 'error', 'message': str(e)}

    def _log_recent_event(self, event_type, message):
        """Log events to Recent Events"""
        current_time = time.time()
        
        if event_type in self.last_event_log_time:
            if current_time - self.last_event_log_time[event_type] < 10:
                return
        
        self.last_event_log_time[event_type] = current_time
        
        socketio.emit('recent_event', {
            'type': event_type,
            'message': message,
            'timestamp': current_time
        })

camera_service = EnhancedCameraService()

# SocketIO Handlers
@socketio.on('start_system')
def handle_start_system():
    """Start the attendance system"""
    try:
        camera_service.start_system()
        emit('system_started', {'status': 'System activated'})
        logger.info("System started via socket")
    except Exception as e:
        logger.error(f"Error starting system: {e}")
        emit('system_error', {'message': str(e)})

@socketio.on('stop_system')
def handle_stop_system():
    """Stop the attendance system"""
    try:
        camera_service.stop_system()
        emit('system_stopped', {'status': 'System deactivated'})
        logger.info("System stopped via socket")
    except Exception as e:
        logger.error(f"Error stopping system: {e}")
        emit('system_error', {'message': str(e)})

@socketio.on('process_frame')
def handle_process_frame(data):
    """Process frame from frontend"""
    try:
        frame_data = data.get('frame')
        if not frame_data:
            return
        
        result = camera_service.process_frame(frame_data)
        
        if result['status'] == 'attendance_marked':
            for attendance_result in result['results']:
                emit('attendance_update', attendance_result)
        elif result['status'] in ['verifying', 'unknown', 'already_marked', 'cooldown', 'error', 'obstructed']:
            emit('recognition_status', result)
        elif result['status'] == 'clear':
            emit('recognition_status', {'status': 'clear'})
    except Exception as e:
        logger.error(f"Error handling frame: {e}")

# Scheduler for daily tasks
def setup_scheduler():
    """Setup daily attendance reset scheduler"""
    scheduler = BackgroundScheduler(timezone=IST)
    
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
        db.create_all()
        logger.info("Database tables created")
        
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
    
    setup_scheduler()
    
    logger.info(f"Starting server on port {Config.FLASK_PORT}")
    logger.info(f"Timezone: {Config.TIMEZONE}")
    logger.info(f"Current IST time: {datetime.now(IST).strftime('%Y-%m-%d %I:%M:%S %p')}")
    
    socketio.run(
        app, 
        host='0.0.0.0', 
        port=Config.FLASK_PORT, 
        debug=Config.DEBUG
    )