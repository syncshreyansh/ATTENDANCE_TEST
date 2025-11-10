# Enhanced Flask API routes with quality assessment endpoint
from flask import Blueprint, request, jsonify, render_template
from datetime import datetime, date
import pytz
from models import db, Student, Attendance, Alert, ActivityLog, get_ist_now, CoordinatorScope
from attendance_service import AttendanceService
from face_recognition_service import FaceRecognitionService
import base64
import cv2
import numpy as np
import os
import logging
import re
from auth_service import (
    admin_required,
    token_required,
    coordinator_or_admin_required,
    get_user_scope,
    AuthService,
)
from student_routes import calculate_attendance_streak
from whatsapp_service import WhatsAppService
from sqlalchemy import func, distinct
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
    if len(name.strip()) < 2:
        return False, "Name must be at least 2 characters"
    return True, ""

def validate_phone(phone):
    """Validate phone number - only digits, 10-15 characters"""
    if not phone:
        return False, "Phone number is required"
    
    digits_only = re.sub(r'\D', '', phone)
    
    if len(digits_only) < 10 or len(digits_only) > 15:
        return False, "Phone number must be 10-15 digits"
    
    return True, digits_only

def validate_student_id(student_id):
    """Validate student ID - alphanumeric"""
    if not student_id or not re.match(r'^[A-Za-z0-9]+$', student_id):
        return False, "Student ID must be alphanumeric"
    if len(student_id) < 3:
        return False, "Student ID must be at least 3 characters"
    return True, ""

# ============================================
# HTML ROUTES (NO TOKEN REQUIRED)
# ============================================
@api.route('/admin-dashboard')
def dashboard():
    """Serve main dashboard (authentication handled in JavaScript)"""
    return render_template('dashboard.html')

# ============================================
# API ROUTES (TOKEN REQUIRED)
# ============================================
@api.route('/api/students', methods=['GET', 'POST'])
@coordinator_or_admin_required
def students(current_user):
    """Student CRUD operations with enhanced validation"""
    if request.method == 'GET':
        try:
            class_name, section = get_user_scope(current_user)
            query = Student.query.filter_by(status='active')

            if class_name:
                query = query.filter_by(class_name=class_name)
                if section:
                    query = query.filter_by(section=section)

            students = query.all()
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
            if current_user.role != 'admin':
                return jsonify({'success': False, 'message': 'Access denied'}), 403
            
            data = request.json
            
            required_fields = ['name', 'student_id', 'class', 'section', 'parent_phone']
            for field in required_fields:
                if field not in data or not data[field]:
                    return jsonify({
                        'success': False, 
                        'message': f'Missing required field: {field}'
                    }), 400
            
            is_valid, msg = validate_name(data['name'])
            if not is_valid:
                return jsonify({'success': False, 'message': msg}), 400
            
            is_valid, msg = validate_student_id(data['student_id'])
            if not is_valid:
                return jsonify({'success': False, 'message': msg}), 400
            
            is_valid, cleaned_phone = validate_phone(data['parent_phone'])
            if not is_valid:
                return jsonify({'success': False, 'message': cleaned_phone}), 400
            
            existing_student = Student.query.filter_by(student_id=data['student_id']).first()
            if existing_student:
                return jsonify({
                    'success': False,
                    'message': f"Student ID {data['student_id']} already exists"
                }), 400
            
            duplicate_check = Student.query.filter_by(
                name=data['name'].strip(),
                parent_phone=cleaned_phone
            ).first()
            if duplicate_check:
                return jsonify({
                    'success': False,
                    'message': f"A student with name '{data['name']}' and this parent phone already exists"
                }), 400
                
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

@api.route('/api/admin/search-students')
@admin_required
def search_students(current_user):
    """Search students by name or student_id (admin only)"""
    query = request.args.get('q', '').strip()

    if not query:
        return jsonify({'success': True, 'students': []}), 200

    try:
        base_query = Student.query.filter_by(status='active')
        if query.isdigit():
            students = base_query.filter(
                Student.student_id.ilike(f"%{query}%")
            ).limit(25).all()
        else:
            students = base_query.filter(
                Student.name.ilike(f"%{query}%")
            ).limit(25).all()

        return jsonify({
            'success': True,
            'students': [{
                'id': s.id,
                'name': s.name,
                'student_id': s.student_id,
                'class_name': s.class_name,
                'section': s.section
            } for s in students]
        }), 200
    except Exception as e:
        logger.error(f"Student search failed: {e}")
        return jsonify({'success': False, 'message': 'Search failed'}), 500

@api.route('/api/admin/student-stats/<int:student_db_id>')
@admin_required
def get_admin_student_stats(current_user, student_db_id):
    """Get detailed stats for a specific student (admin view)"""
    student = Student.query.get(student_db_id)
    if not student:
        return jsonify({'success': False, 'message': 'Student not found'}), 404

    try:
        total_days = db.session.query(
            func.count(distinct(Attendance.date))
        ).filter(Attendance.student_id == student.id).scalar() or 0

        days_present = db.session.query(
            func.count(distinct(Attendance.date))
        ).filter(
            Attendance.student_id == student.id,
            Attendance.status == 'present'
        ).scalar() or 0

        days_absent = total_days - days_present
        attendance_rate = round((days_present / total_days * 100) if total_days > 0 else 0)
        streak = calculate_attendance_streak(student.id)

        first_attendance = Attendance.query.filter_by(
            student_id=student.id
        ).order_by(Attendance.date.asc()).first()

        last_attendance = Attendance.query.filter_by(
            student_id=student.id
        ).order_by(Attendance.date.desc()).first()

        return jsonify({
            'success': True,
            'student': {
                'name': student.name,
                'student_id': student.student_id,
                'class_name': student.class_name,
                'section': student.section,
                'points': student.points,
                'image_path': student.image_path
            },
            'stats': {
                'total_days': total_days,
                'days_present': days_present,
                'days_absent': days_absent,
                'attendance_rate': attendance_rate,
                'streak': streak,
                'first_seen': first_attendance.date.isoformat() if first_attendance else None,
                'last_seen': (
                    last_attendance.time_in.isoformat() if last_attendance and last_attendance.time_in else
                    last_attendance.date.isoformat() if last_attendance else None
                )
            }
        }), 200
    except Exception as e:
        logger.error(f"Error fetching student stats: {e}")
        return jsonify({'success': False, 'message': 'Failed to fetch stats'}), 500

@api.route('/api/admin/coordinators', methods=['POST'])
@admin_required
def create_coordinator(current_user):
    """Create a new coordinator (admin only)"""
    data = request.json or {}

    required = ['username', 'email', 'password', 'class_name']
    for field in required:
        if not data.get(field):
            return jsonify({'success': False, 'message': f'Missing {field}'}), 400

    try:
        result = AuthService.register_user(
            username=data['username'],
            email=data['email'],
            password=data['password'],
            role='coordinator'
        )

        if not result['success']:
            return jsonify(result), 400

        section = data.get('section')
        scope = CoordinatorScope(
            user_id=result['user_id'],
            class_name=data['class_name'].strip(),
            section=section.strip() if isinstance(section, str) and section.strip() else None
        )

        db.session.add(scope)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f"Coordinator created for {data['class_name']}"
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Coordinator creation failed: {e}")
        return jsonify({'success': False, 'message': 'Failed to create coordinator'}), 500

@api.route('/api/test-whatsapp', methods=['POST'])
@admin_required
def test_whatsapp(current_user):
    """Test WhatsApp service (admin only)"""
    data = request.json or {}
    to_phone = data.get('to')
    message = data.get('message', 'Test message from Smart Attendance System')

    if not to_phone:
        return jsonify({'success': False, 'message': 'Phone number required'}), 400

    try:
        whatsapp = WhatsAppService()
        success = whatsapp.send_message(to_phone, message)

        if Config.WHATSAPP_DRY_RUN:
            return jsonify({
                'success': True,
                'message': 'DRY_RUN mode: Message logged (not sent)',
                'dry_run': True
            }), 200

        return jsonify({
            'success': success,
            'message': 'Message sent' if success else 'Failed to send',
            'dry_run': False
        }), 200 if success else 500
    except Exception as e:
        logger.error(f"WhatsApp test failed: {e}")
        return jsonify({'success': False, 'message': 'WhatsApp send failed'}), 500

@api.route('/api/attendance', methods=['GET', 'POST'])
@token_required
def attendance(current_user):
    """Attendance operations"""
    if request.method == 'GET':
        try:
            date_filter_str = request.args.get('date')
            if date_filter_str:
                date_filter = datetime.strptime(date_filter_str, '%Y-%m-%d').date()
            else:
                date_filter = datetime.now(IST).date()
            
            if current_user.role == 'student':
                if not current_user.student_id:
                    return jsonify({'success': False, 'message': 'Student ID not found'}), 400
                attendances = Attendance.query.filter_by(
                    date=date_filter, 
                    student_id=current_user.student_id
                ).all()
            else:
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
@token_required
def stats(current_user):
    """Get attendance statistics"""
    try:
        if current_user.role != 'admin':
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        
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
@token_required
def leaderboard(current_user):
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
@admin_required
def alerts(current_user):
    """Get recent alerts (admin only)"""
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
@admin_required
def activity_logs(current_user):
    """Get recent suspicious activity logs (admin only)"""
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

# ============================================
# NEW: QUALITY ASSESSMENT ENDPOINT
# ============================================
@api.route('/api/assess-quality', methods=['POST'])
@token_required
def assess_quality(current_user):
    """Assess frame quality for enrollment"""
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
                'has_face': False,
                'feedback': {
                    'status': 'poor',
                    'message': 'Invalid frame data',
                    'items': []
                }
            }), 200
        
        # Use face service's quality validation
        import face_recognition
        face_locations = face_recognition.face_locations(frame)
        
        if len(face_locations) == 0:
            return jsonify({
                'success': True,
                'has_face': False,
                'feedback': {
                    'status': 'poor',
                    'message': 'No face detected - position yourself in frame',
                    'items': []
                }
            }), 200
        
        if len(face_locations) > 1:
            return jsonify({
                'success': True,
                'has_face': False,
                'feedback': {
                    'status': 'poor',
                    'message': 'Multiple faces detected - only one person allowed',
                    'items': []
                }
            }), 200
        
        # Check quality
        face_location = face_locations[0]
        quality_valid, quality_msg = face_service.validate_face_quality(frame, face_location)
        
        # Calculate quality score and breakdown
        top, right, bottom, left = face_location
        face_roi = frame[top:bottom, left:right]
        
        # Brightness check
        gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
        brightness = np.mean(gray)
        brightness_score = 1.0 if 50 <= brightness <= 200 else (0.5 if 30 <= brightness <= 240 else 0.0)
        brightness_feedback = "Good lighting" if brightness_score >= 0.7 else "Improve lighting"
        
        # Sharpness check
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        sharpness_score = 1.0 if laplacian_var >= 100 else (0.5 if laplacian_var >= 50 else 0.0)
        sharpness_feedback = "Image is sharp" if sharpness_score >= 0.7 else "Hold camera steady"
        
        # Face size check
        face_width = right - left
        face_height = bottom - top
        size_score = 1.0 if face_width >= 150 and face_height >= 150 else (0.5 if face_width >= 100 else 0.0)
        size_feedback = "Face size good" if size_score >= 0.7 else "Move closer to camera"
        
        # Overall quality score
        quality_score = (brightness_score + sharpness_score + size_score) / 3
        
        # Status determination
        if quality_score >= 0.8:
            status = 'excellent'
            message = '✓ Perfect! Ready to capture'
        elif quality_score >= 0.5:
            status = 'good'
            message = 'Good quality - you can capture'
        else:
            status = 'poor'
            message = 'Adjust position for better quality'
        
        return jsonify({
            'success': True,
            'has_face': True,
            'quality_score': quality_score,
            'feedback': {
                'status': status,
                'message': message,
                'items': [
                    {'check': 'Lighting', 'score': brightness_score, 'feedback': brightness_feedback},
                    {'check': 'Sharpness', 'score': sharpness_score, 'feedback': sharpness_feedback},
                    {'check': 'Face Size', 'score': size_score, 'feedback': size_feedback}
                ]
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error in quality assessment: {e}")
        return jsonify({
            'success': False,
            'message': f'Quality assessment error: {str(e)}'
        }), 500

# ============================================
# ENROLLMENT ENDPOINTS
# ============================================
@api.route('/api/enroll', methods=['POST'])
@admin_required
def enroll_face(current_user):
    """Enroll student face encoding with duplicate prevention (admin only)"""
    logger.info("=" * 60)
    logger.info("ENROLLMENT ENDPOINT HIT")
    logger.info("=" * 60)
    
    try:
        data = request.json
        
        if not data or 'student_id' not in data or 'frame' not in data:
            return jsonify({
                'success': False,
                'message': 'Missing required data (student_id or frame)'
            }), 400
        
        student_id_str = data['student_id']
        frame_data = data['frame']
        
        logger.info(f"Processing enrollment for student_id: {student_id_str}")
        
        student = Student.query.filter_by(student_id=student_id_str).first()
        
        if not student:
            return jsonify({
                'success': False,
                'message': f'Student ID {student_id_str} not found'
            }), 404
        
        if student.face_encoding is not None:
            return jsonify({
                'success': False,
                'message': f'Student {student.name} is already enrolled. Please delete existing enrollment first.'
            }), 400
        
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
        
        try:
            face_hash = face_service.compute_face_hash(face_encoding)
            
            student.face_encoding = face_encoding
            student.face_hash = face_hash
            
            enroll_dir = os.path.join('static', 'enrollments')
            ensure_dir(enroll_dir)
            
            image_filename = f"student_{student_id_str}.jpg"
            image_path = os.path.join(enroll_dir, image_filename)
            
            cv2.imwrite(image_path, frame)
            student.image_path = image_path
            
            db.session.commit()
            
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

# ============================================
# NEW: MULTI-SHOT ENROLLMENT ENDPOINT
# ============================================
@api.route('/api/enroll-multishot', methods=['POST'])
@admin_required
def enroll_multishot(current_user):
    """Enroll student using multiple frames for better accuracy"""
    try:
        data = request.json
        
        if not data or 'student_id' not in data or 'frames' not in data:
            return jsonify({
                'success': False,
                'message': 'Missing required data (student_id or frames)'
            }), 400
        
        student_id_str = data['student_id']
        frames_data = data['frames']
        
        if not isinstance(frames_data, list) or len(frames_data) < 3:
            return jsonify({
                'success': False,
                'message': 'At least 3 frames required for enrollment'
            }), 400
        
        logger.info(f"Processing multi-shot enrollment for {student_id_str} with {len(frames_data)} frames")
        
        student = Student.query.filter_by(student_id=student_id_str).first()
        
        if not student:
            return jsonify({
                'success': False,
                'message': f'Student ID {student_id_str} not found'
            }), 404
        
        # Process best frame (last one usually has best quality)
        best_frame_data = frames_data[-1]
        
        try:
            frame_bytes = base64.b64decode(best_frame_data)
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is None:
                return jsonify({
                    'success': False,
                    'message': 'Invalid image data'
                }), 400
            
            success, message, face_encoding = face_service.enroll_student(frame, student)
            
            if not success:
                return jsonify({
                    'success': False,
                    'message': message
                }), 400
            
            face_hash = face_service.compute_face_hash(face_encoding)
            
            student.face_encoding = face_encoding
            student.face_hash = face_hash
            
            enroll_dir = os.path.join('static', 'enrollments')
            ensure_dir(enroll_dir)
            
            image_filename = f"student_{student_id_str}.jpg"
            image_path = os.path.join(enroll_dir, image_filename)
            
            cv2.imwrite(image_path, frame)
            student.image_path = image_path
            
            db.session.commit()
            face_service.load_encodings_from_db()
            
            logger.info(f"✓ Multi-shot enrollment successful for {student.name}")
            
            return jsonify({
                'success': True,
                'message': f'Student {student.name} enrolled successfully with {len(frames_data)} frames'
            }), 200
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"Multi-shot enrollment error: {e}")
            return jsonify({
                'success': False,
                'message': f'Enrollment failed: {str(e)}'
            }), 500
            
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({
            'success': False,
            'message': f'Unexpected error: {str(e)}'
        }), 500

@api.route('/api/recognize', methods=['POST'])
@token_required
def recognize(current_user):
    """Process recognition request"""
    try:
        data = request.json
        frame_data = data.get('frame')
        
        if not frame_data:
            return jsonify({
                'success': False,
                'message': 'No frame data provided'
            }), 400
        
        frame_bytes = base64.b64decode(frame_data)
        nparr = np.frombuffer(frame_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if frame is None:
            return jsonify({
                'success': False,
                'message': 'Invalid frame data'
            }), 400
        
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