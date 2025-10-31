# Enhanced Flask API routes with strict validation
from flask import Blueprint, request, jsonify, render_template
from datetime import datetime, date
import pytz
from models import db, Student, Attendance, Alert, ActivityLog, get_ist_now
from attendance_service import AttendanceService
from face_recognition_service import FaceRecognitionService
import base64
import cv2
import numpy as np
import os
import logging
import re
from auth_service import admin_required
from config import Config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

api = Blueprint('api', __name__)
attendance_service = AttendanceService()
face_service = FaceRecognitionService()

IST = pytz.timezone(Config.TIMEZONE)

def ensure_dir(directory):
    """Create directory if it doesn't exist"""
    if not os.path.exists(directory):
        os.makedirs(directory)
        logger.info(f"Created directory: {directory}")

def validate_name(name):
    """Validate name - only alphabets and spaces"""
    if not name or not re.match(r'^[A-Za-z\s]+$', name):
        return False, "Name must contain only alphabets and spaces"
    return True, ""

def validate_phone(phone):
    """Validate phone number - only digits, 10-15 characters"""
    if not phone:
        return False, "Phone number is required"
    
    # Remove any non-digit characters for validation
    digits_only = re.sub(r'\D', '', phone)
    
    if len(digits_only) < 10 or len(digits_only) > 15:
        return False, "Phone number must be 10-15 digits"
    
    return True, digits_only

def validate_student_id(student_id):
    """Validate student ID - alphanumeric"""
    if not student_id or not re.match(r'^[A-Za-z0-9]+$', student_id):
        return False, "Student ID must be alphanumeric"
    return True, ""

@api.route('/admin-dashboard')
def dashboard():
    """Serve main dashboard"""
    return render_template('dashboard.html')

@api.route('/api/students', methods=['GET', 'POST'])
def students():
    """Student CRUD operations with enhanced validation"""
    if request.method == 'GET':
        try:
            students = Student.query.filter_by(status='active').all()
            return jsonify([{
                'id': s.id,
                'name': s.name,
                'student_id': s.student_id,
                'class': s.class_name,
                'section': s.section,
                'points': s.points,
                'parent_phone': s.parent_phone
            } for s in students])
        except Exception as e:
            logger.error(f"Error fetching students: {e}")
            return jsonify({'success': False, 'message': 'Error fetching students'}), 500
            
    elif request.method == 'POST':
        try:
            data = request.json
            
            # Validate required fields
            required_fields = ['name', 'student_id', 'class', 'section', 'parent_phone']
            for field in required_fields:
                if field not in data or not data[field]:
                    return jsonify({
                        'success': False, 
                        'message': f'Missing required field: {field}'
                    }), 400
            
            # Validate name (only alphabets)
            is_valid, msg = validate_name(data['name'])
            if not is_valid:
                return jsonify({'success': False, 'message': msg}), 400
            
            # Validate student ID
            is_valid, msg = validate_student_id(data['student_id'])
            if not is_valid:
                return jsonify({'success': False, 'message': msg}), 400
            
            # Validate phone number (only digits)
            is_valid, cleaned_phone = validate_phone(data['parent_phone'])
            if not is_valid:
                return jsonify({'success': False, 'message': cleaned_phone}), 400
            
            # Check for duplicate student_id
            existing_student = Student.query.filter_by(student_id=data['student_id']).first()
            if existing_student:
                return jsonify({
                    'success': False,
                    'message': f"Student ID {data['student_id']} already exists"
                }), 400
            
            # Check for duplicate name + parent_phone combination
            duplicate_check = Student.query.filter_by(
                name=data['name'].strip(),
                parent_phone=cleaned_phone
            ).first()
            if duplicate_check:
                return jsonify({
                    'success': False,
                    'message': f"A student with name '{data['name']}' and this parent phone already exists"
                }), 400
                
            # Create new student
            student = Student(
                name=data['name'].strip(),
                student_id=data['student_id'].strip(),
                class_name=data['class'].strip(),
                section=data['section'].strip(),
                parent_phone=cleaned_phone
            )
            
            db.session.add(student)
            db.session.commit()
            
            logger.info(f"Student created successfully: {data['student_id']}")
            return jsonify({
                'success': True,
                'id': student.id, 
                'message': 'Student created successfully'
            }), 201
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error creating student: {e}")
            return jsonify({
                'success': False,
                'message': f'Error creating student: {str(e)}'
            }), 500

@api.route('/api/attendance', methods=['GET', 'POST'])
def attendance():
    """Attendance operations"""
    if request.method == 'GET':
        try:
            date_filter_str = request.args.get('date')
            if date_filter_str:
                date_filter = datetime.strptime(date_filter_str, '%Y-%m-%d').date()
            else:
                date_filter = datetime.now(IST).date()
            
            attendances = Attendance.query.filter_by(date=date_filter).all()
            
            return jsonify([{
                'id': a.id,
                'student_name': Student.query.get(a.student_id).name if Student.query.get(a.student_id) else 'Unknown',
                'time_in': a.time_in.astimezone(IST).strftime('%I:%M %p') if a.time_in else None,
                'status': a.status,
                'confidence': a.confidence,
                'points': a.points_earned,
                'blink_verified': a.blink_verified,
                'eye_contact_verified': a.eye_contact_verified
            } for a in attendances])
            
        except Exception as e:
            logger.error(f"Error fetching attendance: {e}")
            return jsonify({'success': False, 'message': 'Error fetching attendance'}), 500
            
    elif request.method == 'POST':
        try:
            data = request.json
            result = attendance_service.mark_attendance(
                data['student_id'],
                data.get('confidence', 0.5),
                data.get('blink_verified', False),
                data.get('eye_contact_verified', False)
            )
            return jsonify(result)
        except Exception as e:
            logger.error(f"Error marking attendance: {e}")
            return jsonify({'success': False, 'message': str(e)}), 500

@api.route('/api/stats')
def stats():
    """Get attendance statistics"""
    try:
        stats_data = attendance_service.get_attendance_stats()
        return jsonify(stats_data)
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        return jsonify({
            'total_students': 0,
            'present_today': 0,
            'absent_today': 0,
            'attendance_rate': 0
        })

@api.route('/api/leaderboard')
def leaderboard():
    """Get top students by points"""
    try:
        top_students = Student.query.filter_by(status='active').order_by(
            Student.points.desc()
        ).limit(10).all()
        
        return jsonify([{
            'rank': idx + 1,
            'name': s.name,
            'points': s.points,
            'class': f"{s.class_name}-{s.section}"
        } for idx, s in enumerate(top_students)])
    except Exception as e:
        logger.error(f"Error fetching leaderboard: {e}")
        return jsonify([])

@api.route('/api/alerts')
def alerts():
    """Get recent alerts"""
    try:
        recent_alerts = Alert.query.order_by(
            Alert.timestamp.desc()
        ).limit(20).all()
        
        return jsonify([{
            'id': a.id,
            'type': a.alert_type,
            'message': a.message,
            'timestamp': a.timestamp.astimezone(IST).isoformat(),
            'sent': a.sent
        } for a in recent_alerts])
    except Exception as e:
        logger.error(f"Error fetching alerts: {e}")
        return jsonify([])

@api.route('/api/activity-logs')
def activity_logs():
    """Get recent suspicious activity logs"""
    try:
        logs = ActivityLog.query.order_by(
            ActivityLog.timestamp.desc()
        ).limit(50).all()
        
        return jsonify([{
            'id': l.id,
            'student_id': l.student_id,
            'name': l.name,
            'activity_type': l.activity_type,
            'message': l.message,
            'severity': l.severity,
            'timestamp': l.timestamp.astimezone(IST).isoformat()
        } for l in logs])
    except Exception as e:
        logger.error(f"Error fetching activity logs: {e}")
        return jsonify([])

@api.route('/api/enroll', methods=['POST'])
def enroll_face():
    """Enroll student face encoding with duplicate prevention"""
    logger.info("=" * 60)
    logger.info("ENROLLMENT ENDPOINT HIT")
    logger.info("=" * 60)
    
    try:
        data = request.json
        
        # Validate input
        if not data or 'student_id' not in data or 'frame' not in data:
            return jsonify({
                'success': False,
                'message': 'Missing required data (student_id or frame)'
            }), 400
        
        student_id_str = data['student_id']
        frame_data = data['frame']
        
        logger.info(f"Processing enrollment for student_id: {student_id_str}")
        
        # Find student in database
        student = Student.query.filter_by(student_id=student_id_str).first()
        
        if not student:
            return jsonify({
                'success': False,
                'message': f'Student ID {student_id_str} not found'
            }), 404
        
        # Check if already enrolled
        if student.face_encoding is not None:
            return jsonify({
                'success': False,
                'message': f'Student {student.name} is already enrolled. Please delete existing enrollment first.'
            }), 400
        
        # Decode frame
        try:
            frame_bytes = base64.b64decode(frame_data)
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is None:
                return jsonify({
                    'success': False,
                    'message': 'Invalid image data'
                }), 400
                
        except Exception as e:
            logger.error(f"Error decoding frame: {e}")
            return jsonify({
                'success': False,
                'message': f'Failed to decode image: {str(e)}'
            }), 400
        
        # Enroll face (includes duplicate check)
        try:
            success, message, face_encoding = face_service.enroll_student(frame, student)
            
            if not success:
                return jsonify({
                    'success': False,
                    'message': message
                }), 400
                
            if face_encoding is None:
                return jsonify({
                    'success': False,
                    'message': 'Face encoding failed'
                }), 400
                
        except Exception as e:
            logger.error(f"Error during face enrollment: {e}")
            return jsonify({
                'success': False,
                'message': f'Face encoding error: {str(e)}'
            }), 500
        
        # Save to database
        try:
            # Compute face hash for duplicate detection
            face_hash = face_service.compute_face_hash(face_encoding)
            
            student.face_encoding = face_encoding
            student.face_hash = face_hash
            
            # Save image
            enroll_dir = os.path.join('static', 'enrollments')
            ensure_dir(enroll_dir)
            
            image_filename = f"student_{student_id_str}.jpg"
            image_path = os.path.join(enroll_dir, image_filename)
            
            cv2.imwrite(image_path, frame)
            student.image_path = image_path
            
            db.session.commit()
            
            # Reload encodings
            face_service.load_encodings_from_db()
            
            logger.info(f"✓ Enrollment successful for {student.name}")
            
            return jsonify({
                'success': True,
                'message': f'Face enrolled successfully for {student.name}'
            }), 200
                
        except Exception as e:
            db.session.rollback()
            logger.error(f"Database error: {e}")
            return jsonify({
                'success': False,
                'message': f'Database error: {str(e)}'
            }), 500
            
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({
            'success': False,
            'message': f'Unexpected error: {str(e)}'
        }), 500

@api.route('/api/recognize', methods=['POST'])
def recognize():
    """Process recognition request"""
    try:
        data = request.json
        frame_data = data.get('frame')
        
        if not frame_data:
            return jsonify({
                'success': False,
                'message': 'No frame data provided'
            }), 400
        
        # Decode frame
        frame_bytes = base64.b64decode(frame_data)
        nparr = np.frombuffer(frame_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if frame is None:
            return jsonify({
                'success': False,
                'message': 'Invalid frame data'
            }), 400
        
        # Recognize faces
        recognition_result = face_service.recognize_faces(frame)
        
        return jsonify({
            'success': True,
            'matches': recognition_result.get('matches', []),
            'total_faces': recognition_result.get('total_faces', 0)
        })
        
    except Exception as e:
        logger.error(f"Error in recognition: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500