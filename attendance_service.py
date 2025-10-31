# Enhanced attendance management with absence tracking and WhatsApp alerts
from datetime import datetime, date, time, timedelta
import pytz
from models import db, Student, Attendance, Alert, AbsenceTracker, ActivityLog, get_ist_now
from whatsapp_service import WhatsAppService
from config import Config
import logging

logger = logging.getLogger(__name__)

# Timezone
IST = pytz.timezone(Config.TIMEZONE)

class AttendanceService:
    def __init__(self):
        self.whatsapp = WhatsAppService()

    def get_current_date(self):
        """Get current date in IST"""
        return datetime.now(IST).date()

    def mark_attendance(self, student_id, confidence, blink_verified=False, eye_contact_verified=False):
        """
        Mark student attendance with enhanced verification
        """
        today = self.get_current_date()
        current_time = datetime.now(IST)
        
        # Check if already marked today
        existing = Attendance.query.filter_by(
            student_id=student_id,
            date=today
        ).first()
        
        if not existing:
            points = self.calculate_points(current_time.time(), blink_verified, eye_contact_verified)
            attendance = Attendance(
                student_id=student_id,
                date=today,
                time_in=current_time,
                status='present',
                confidence=confidence,
                blink_verified=blink_verified,
                eye_contact_verified=eye_contact_verified,
                points_earned=points
            )
            
            # Update student points
            student = Student.query.get(student_id)
            if student:
                student.points += points
                db.session.add(attendance)
                
                # Update absence tracker
                self.update_absence_tracker(student_id, is_present=True)
                
                db.session.commit()
                
                logger.info(f"Attendance marked for {student.name} - Blink: {blink_verified}, Eye Contact: {eye_contact_verified}")
                
                return {
                    'success': True,
                    'points': points,
                    'student_name': student.name,
                    'time': current_time.strftime('%I:%M %p')
                }
        
        return {'success': False, 'message': 'Already marked today'}

    def calculate_points(self, time_in, blink_verified=False, eye_contact_verified=False):
        """Calculate points based on arrival time and verification"""
        base_points = 10
        
        # Early arrival bonus
        if time_in < time(8, 30):
            base_points += 5
        elif time_in > time(9, 0):
            base_points -= 3
        
        # Liveness verification bonuses
        if blink_verified:
            base_points += 2
        
        if eye_contact_verified:
            base_points += 3
            
        return max(base_points, 1)

    def get_attendance_stats(self, date_filter=None):
        """Get attendance statistics"""
        if not date_filter:
            date_filter = self.get_current_date()
            
        total_students = Student.query.filter_by(status='active').count()
        present_today = Attendance.query.filter_by(
            date=date_filter,
            status='present'
        ).count()
        
        return {
            'total_students': total_students,
            'present_today': present_today,
            'absent_today': total_students - present_today,
            'attendance_rate': (present_today / total_students * 100) if total_students > 0 else 0
        }

    def update_absence_tracker(self, student_id, is_present=True):
        """
        Update absence tracker for a student
        """
        try:
            tracker = AbsenceTracker.query.filter_by(student_id=student_id).first()
            today = self.get_current_date()
            
            if not tracker:
                tracker = AbsenceTracker(student_id=student_id)
                db.session.add(tracker)
            
            if is_present:
                # Reset consecutive absences
                tracker.consecutive_absences = 0
                tracker.last_present_date = today
                tracker.notification_sent = False
            else:
                # Increment consecutive absences
                tracker.consecutive_absences += 1
            
            db.session.commit()
            
        except Exception as e:
            logger.error(f"Error updating absence tracker: {e}")
            db.session.rollback()

    def check_absence_patterns(self):
        """
        Check for consecutive absences and send alerts
        This should be run daily (e.g., via cron job or scheduler)
        """
        try:
            today = self.get_current_date()
            
            # Get all active students
            students = Student.query.filter_by(status='active').all()
            
            for student in students:
                # Check if attended today
                attendance_today = Attendance.query.filter_by(
                    student_id=student.id,
                    date=today,
                    status='present'
                ).first()
                
                if not attendance_today:
                    # Mark as absent
                    self.update_absence_tracker(student.id, is_present=False)
                
                # Get tracker
                tracker = AbsenceTracker.query.filter_by(student_id=student.id).first()
                
                if tracker and tracker.consecutive_absences >= Config.ABSENCE_THRESHOLD:
                    # Check if notification already sent recently
                    if not tracker.notification_sent or (tracker.last_notification_date and 
                                                         (today - tracker.last_notification_date).days >= 7):
                        # Send absence alert
                        self.send_absence_notification(student, tracker.consecutive_absences)
                        
                        # Update tracker
                        tracker.notification_sent = True
                        tracker.last_notification_date = today
                        db.session.commit()
                        
                        logger.info(f"Absence notification sent for {student.name} ({tracker.consecutive_absences} days)")
            
        except Exception as e:
            logger.error(f"Error checking absence patterns: {e}")
            db.session.rollback()

    def send_absence_notification(self, student, consecutive_days):
        """
        Send WhatsApp notification for consecutive absences
        """
        try:
            # Calculate attendance percentage
            total_days = Attendance.query.filter_by(student_id=student.id).count()
            present_days = Attendance.query.filter_by(
                student_id=student.id,
                status='present'
            ).count()
            
            attendance_percentage = round((present_days / total_days * 100) if total_days > 0 else 0, 1)
            
            # Message content
            message = (
                f"⚠️ Absence Alert\n\n"
                f"Student: {student.name}\n"
                f"ID: {student.student_id}\n"
                f"Class: {student.class_name}-{student.section}\n\n"
                f"Consecutive Absences: {consecutive_days} days\n"
                f"Overall Attendance: {attendance_percentage}%\n\n"
                f"Please contact the school if there are any concerns."
            )
            
            # Send to parent
            if student.parent_phone:
                result_parent = self.whatsapp.send_absence_alert(
                    student.parent_phone,
                    student.name,
                    consecutive_days
                )
                logger.info(f"Parent notification sent: {result_parent}")
            
            # Send to coordinator
            result_coordinator = self.whatsapp.send_message(
                Config.CLASS_COORDINATOR_PHONE,
                message
            )
            logger.info(f"Coordinator notification sent: {result_coordinator}")
            
            # Log alert
            alert = Alert(
                student_id=student.id,
                alert_type='consecutive_absence',
                message=message,
                sent=True
            )
            db.session.add(alert)
            db.session.commit()
            
        except Exception as e:
            logger.error(f"Error sending absence notification: {e}")

    def reset_daily_attendance(self):
        """
        Reset logic for new day (called at midnight IST)
        This ensures absence tracking is updated daily
        """
        try:
            logger.info("Running daily attendance reset...")
            self.check_absence_patterns()
            logger.info("Daily reset completed")
        except Exception as e:
            logger.error(f"Error in daily reset: {e}")