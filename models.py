# Database models with enhanced security and activity logging
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import pytz

db = SQLAlchemy()

# Timezone for India (IST)
IST = pytz.timezone('Asia/Kolkata')

def get_ist_now():
    """Get current time in IST"""
    return datetime.now(IST)

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    student_id = db.Column(db.String(20), unique=True, nullable=False)
    class_name = db.Column(db.String(20), nullable=False)
    section = db.Column(db.String(10), nullable=False)
    parent_phone = db.Column(db.String(15), nullable=False)  # Now mandatory
    face_encoding = db.Column(db.PickleType, nullable=True)
    enrollment_date = db.Column(db.DateTime, default=get_ist_now)
    status = db.Column(db.String(20), default='active')
    points = db.Column(db.Integer, default=0)
    image_path = db.Column(db.String(200), nullable=True)
    
    # New field to track face hash for duplicate detection
    face_hash = db.Column(db.String(64), unique=True, nullable=True)

class Attendance(db.Model):
    """Main attendance table - stores all historical records"""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time_in = db.Column(db.DateTime, nullable=True)  # Changed to DateTime for IST
    time_out = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False)
    confidence = db.Column(db.Float, nullable=True)
    blink_verified = db.Column(db.Boolean, default=False)
    eye_contact_verified = db.Column(db.Boolean, default=False)  # New field
    points_earned = db.Column(db.Integer, default=0)

class ActivityLog(db.Model):
    """New table to log suspicious activities and proxy attempts"""
    __tablename__ = 'activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=True)
    name = db.Column(db.String(100), nullable=True)
    activity_type = db.Column(db.String(50), nullable=False)  # 'camera_covered', 'proxy_attempt', 'phone_detected', etc.
    timestamp = db.Column(db.DateTime, default=get_ist_now)
    message = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(20), default='warning')  # 'info', 'warning', 'critical'

class Alert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    alert_type = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=get_ist_now)
    sent = db.Column(db.Boolean, default=False)
    delivered = db.Column(db.Boolean, default=False)

class SystemLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=get_ist_now)
    severity = db.Column(db.String(20), default='info')

class AbsenceTracker(db.Model):
    """New table to track consecutive absences for notifications"""
    __tablename__ = 'absence_tracker'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False, unique=True)
    consecutive_absences = db.Column(db.Integer, default=0)
    last_present_date = db.Column(db.Date, nullable=True)
    notification_sent = db.Column(db.Boolean, default=False)
    last_notification_date = db.Column(db.Date, nullable=True)
    
    student = db.relationship('Student', backref='absence_tracker')