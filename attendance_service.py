# Enhanced attendance management with 3-day absence WhatsApp alerts
from datetime import datetime, date, time, timedelta
import pytz
from models import db, Student, Attendance, Alert, AbsenceTracker, ActivityLog, get_ist_now
from whatsapp_service import WhatsAppService
from config import Config
import logging

logger = logging.getLogger(__name__)

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
                
                # Update absence tracker - RESET consecutive absences
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
        
        # FIXED: Count distinct students who are present today (not all attendance records)
        # This prevents counting duplicate records that might exist
        present_today = db.session.query(Attendance.student_id).filter_by(
            date=date_filter,
            status='present'
        ).distinct().count()
        
        # FIXED: Ensure absent_today is never negative
        absent_today = max(0, total_students - present_today)
        
        # FIXED: Calculate attendance rate and cap at 100% to prevent impossible values
        if total_students > 0:
            attendance_rate = min((present_today / total_students * 100), 100.0)
        else:
            attendance_rate = 0
        
        return {
            'total_students': total_students,
            'present_today': present_today,
            'absent_today': absent_today,
            'attendance_rate': attendance_rate
        }

    def log_spoofing_attempt(self, student_id, student_name, spoof_type, confidence):
        """Log spoofing attempts with student info"""
        try:
            message = f"🚨 SPOOFING ATTEMPT: Someone tried to mark attendance for {student_name} using {spoof_type}"
            
            log = ActivityLog(
                student_id=student_id,
                name=student_name,
                activity_type='spoofing_attempt',
                message=message,
                severity='critical',
                spoof_type=spoof_type,
                spoof_confidence=confidence
            )
            db.session.add(log)
            db.session.commit()
            
            logger.critical(f"🚨 {message} (confidence={confidence:.2f})")
            
            # Optional: Send alert to admin
            # self.whatsapp.send_message(Config.ADMIN_PHONE, message)
            
        except Exception as e:
            logger.error(f"Failed to log spoofing attempt: {e}")
            db.session.rollback()

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
                # IMPORTANT: Reset consecutive absences when present
                tracker.consecutive_absences = 0
                tracker.last_present_date = today
                tracker.notification_sent = False
                logger.info(f"Reset absence counter for student_id={student_id}")
            else:
                # Increment consecutive absences
                tracker.consecutive_absences += 1
                logger.info(f"Incremented absence counter for student_id={student_id}: {tracker.consecutive_absences} days")
            
            db.session.commit()
            
        except Exception as e:
            logger.error(f"Error updating absence tracker: {e}")
            db.session.rollback()

    def check_absence_patterns(self):
        """
        Check for consecutive absences and send WhatsApp alerts
        This should be run daily (e.g., via cron job or scheduler)
        
        ENHANCED: Sends WhatsApp alerts to both student and coordinator
        """
        try:
            today = self.get_current_date()
            
            logger.info(f"Running absence check for date: {today}")
            
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
                    # Mark as absent (increment counter)
                    self.update_absence_tracker(student.id, is_present=False)
                
                # Get tracker
                tracker = AbsenceTracker.query.filter_by(student_id=student.id).first()
                
                if tracker and tracker.consecutive_absences >= Config.ABSENCE_THRESHOLD:
                    # Check if notification already sent recently
                    if not tracker.notification_sent or (tracker.last_notification_date and 
                                                         (today - tracker.last_notification_date).days >= 7):
                        
                        logger.warning(f"🚨 ALERT: {student.name} has {tracker.consecutive_absences} consecutive absences")
                        
                        # Send WhatsApp alerts
                        self.send_absence_notification(student, tracker.consecutive_absences)
                        
                        # Update tracker
                        tracker.notification_sent = True
                        tracker.last_notification_date = today
                        db.session.commit()
                        
                        logger.info(f"✅ Absence notification sent for {student.name} ({tracker.consecutive_absences} days)")
            
        except Exception as e:
            logger.error(f"Error checking absence patterns: {e}")
            db.session.rollback()

    def send_absence_notification(self, student, consecutive_days):
        """
        Send WhatsApp notification to both student and coordinator
        for consecutive absences (3+ days)
        """
        try:
            # Calculate attendance percentage
            total_days = Attendance.query.filter_by(student_id=student.id).count()
            present_days = Attendance.query.filter_by(
                student_id=student.id,
                status='present'
            ).count()
            
            attendance_percentage = round((present_days / total_days * 100) if total_days > 0 else 0, 1)
            
            # Message for parent/student
            student_message = (
                f"⚠️ *Attendance Alert*\n\n"
                f"Dear Parent/Guardian,\n\n"
                f"This is to inform you that *{student.name}* "
                f"(ID: {student.student_id}) has been absent for "
                f"*{consecutive_days} consecutive days*.\n\n"
                f"Class: {student.class_name}-{student.section}\n"
                f"Overall Attendance: {attendance_percentage}%\n\n"
                f"Please contact the school if there are any concerns.\n\n"
                f"Thank you,\n"
                f"School Administration"
            )
            
            # Message for coordinator
            coordinator_message = (
                f"🚨 *Absence Alert - Action Required*\n\n"
                f"Student: *{student.name}*\n"
                f"ID: {student.student_id}\n"
                f"Class: {student.class_name}-{student.section}\n\n"
                f"❌ Consecutive Absences: *{consecutive_days} days*\n"
                f"📊 Overall Attendance: {attendance_percentage}%\n"
                f"📞 Parent Contact: {student.parent_phone}\n\n"
                f"Please follow up with the student/parent."
            )
            
            # Send to parent
            if student.parent_phone:
                try:
                    result_parent = self.whatsapp.send_message(
                        student.parent_phone,
                        student_message
                    )
                    if result_parent:
                        logger.info(f"✅ Parent WhatsApp sent to {student.parent_phone}")
                    else:
                        logger.error(f"❌ Failed to send WhatsApp to parent {student.parent_phone}")
                except Exception as e:
                    logger.error(f"Error sending WhatsApp to parent: {e}")
            
            # Send to coordinator
            try:
                result_coordinator = self.whatsapp.send_message(
                    Config.CLASS_COORDINATOR_PHONE,
                    coordinator_message
                )
                if result_coordinator:
                    logger.info(f"✅ Coordinator WhatsApp sent to {Config.CLASS_COORDINATOR_PHONE}")
                else:
                    logger.error(f"❌ Failed to send WhatsApp to coordinator")
            except Exception as e:
                logger.error(f"Error sending WhatsApp to coordinator: {e}")
            
            # Log alert in database
            alert = Alert(
                student_id=student.id,
                alert_type='consecutive_absence',
                message=student_message,
                sent=True
            )
            db.session.add(alert)
            db.session.commit()
            
            logger.info(f"✅ Absence alert logged for {student.name}")
            
        except Exception as e:
            logger.error(f"Error sending absence notification: {e}")
            db.session.rollback()

    def reset_daily_attendance(self):
        """
        Reset logic for new day (called at midnight IST)
        This ensures absence tracking is updated daily
        """
        try:
            logger.info("=" * 60)
            logger.info("RUNNING DAILY ATTENDANCE RESET")
            logger.info("=" * 60)
            
            # Check absence patterns and send alerts
            self.check_absence_patterns()
            
            logger.info("Daily reset completed successfully")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Error in daily reset: {e}")

    def test_whatsapp_service(self):
        """
        Test WhatsApp service with a sample message
        Returns: (success: bool, message: str)
        """
        try:
            test_message = (
                "🧪 *Test Message*\n\n"
                "This is a test message from the Smart Attendance System.\n\n"
                "If you received this, WhatsApp integration is working correctly!\n\n"
                f"Timestamp: {datetime.now(IST).strftime('%Y-%m-%d %I:%M:%S %p IST')}"
            )
            
            result = self.whatsapp.send_message(
                Config.CLASS_COORDINATOR_PHONE,
                test_message
            )
            
            if result:
                return True, "Test message sent successfully!"
            else:
                return False, "Failed to send test message. Check WhatsApp configuration."
                
        except Exception as e:
            logger.error(f"Error testing WhatsApp service: {e}")
            return False, f"Error: {str(e)}"