# student_routes.py - FIXED: Prevents counting duplicate attendance records
"""
Student-specific API routes with fixed attendance counting
"""
from flask import Blueprint, jsonify, render_template, request
from auth_service import token_required
from models import db, Student, Attendance
from datetime import datetime, timedelta, date
from sqlalchemy import func, and_, distinct
import logging

logger = logging.getLogger(__name__)

student_bp = Blueprint('student', __name__)

@student_bp.route('/student-dashboard')
def student_dashboard_page():
    """Serve student dashboard page (authentication handled in JavaScript)"""
    return render_template('student_dashboard.html')

@student_bp.route('/api/student-profile/<int:student_id>')
@token_required
def get_student_profile(current_user, student_id):
    """Get student profile information"""
    try:
        # Verify user can access this student's data
        if current_user.role == 'student' and current_user.student_id != student_id:
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        
        student = Student.query.get(student_id)
        if not student:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        return jsonify({
            'success': True,
            'student': {
                'id': student.id,
                'name': student.name,
                'student_id': student.student_id,
                'class': student.class_name,
                'section': student.section,
                'points': student.points,
                'enrollment_date': student.enrollment_date.isoformat() if student.enrollment_date else None,
                'image_path': student.image_path
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching student profile: {e}")
        return jsonify({'success': False, 'message': 'Failed to fetch profile'}), 500

@student_bp.route('/api/student-stats/<int:student_id>')
@token_required
def get_student_stats(current_user, student_id):
    """Get attendance statistics for a student - FIXED to count unique days only"""
    try:
        # Verify access
        if current_user.role == 'student' and current_user.student_id != student_id:
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        
        student = Student.query.get(student_id)
        if not student:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        # FIXED: Count distinct dates only (prevents duplicate counting)
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
        
        # Calculate current streak
        streak = calculate_attendance_streak(student.id)
        
        return jsonify({
            'success': True,
            'total_days': total_days,
            'days_present': days_present,
            'days_absent': days_absent,
            'attendance_rate': attendance_rate,
            'streak': streak
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching student stats: {e}")
        return jsonify({'success': False, 'message': 'Failed to fetch stats'}), 500

@student_bp.route('/api/student-attendance/<int:student_id>')
@token_required
def get_student_attendance(current_user, student_id):
    """Get attendance records for a student - FIXED to return unique dates only"""
    try:
        # Verify access
        if current_user.role == 'student' and current_user.student_id != student_id:
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        
        student = Student.query.get(student_id)
        if not student:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        # Check if month/year filters are provided
        month = request.args.get('month', type=int)
        year = request.args.get('year', type=int)
        
        query = Attendance.query.filter_by(student_id=student.id)
        
        if month and year:
            # Filter by specific month and year
            start_date = date(year, month, 1)
            if month == 12:
                end_date = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date(year, month + 1, 1) - timedelta(days=1)
            
            query = query.filter(
                and_(
                    Attendance.date >= start_date,
                    Attendance.date <= end_date
                )
            )
        else:
            # Default: recent 30 days
            query = query.limit(30)
        
        # FIXED: Get records ordered by date and ID to get latest record per date
        records = query.order_by(Attendance.date.desc(), Attendance.id.desc()).all()
        
        # Remove duplicates - keep only first record per date
        seen_dates = set()
        unique_records = []
        for record in records:
            if record.date not in seen_dates:
                seen_dates.add(record.date)
                unique_records.append(record)
        
        return jsonify({
            'success': True,
            'attendance': [{
                'id': r.id,
                'date': r.date.isoformat(),
                'time_in': r.time_in.isoformat() if r.time_in else None,
                'status': r.status,
                'confidence': r.confidence,
                'points_earned': r.points_earned,
                'blink_verified': r.blink_verified
            } for r in unique_records]
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching attendance: {e}")
        return jsonify({'success': False, 'message': 'Failed to fetch attendance'}), 500

@student_bp.route('/api/student-attendance-month/<int:student_id>')
@token_required
def get_student_attendance_month(current_user, student_id):
    """Get present and absent dates for a month"""
    try:
        if current_user.role == 'student' and current_user.student_id != student_id:
            return jsonify({'success': False, 'message': 'Access denied'}), 403

        student = Student.query.get(student_id)
        if not student:
            return jsonify({'success': False, 'message': 'Student not found'}), 404

        month = request.args.get('month', type=int)
        year = request.args.get('year', type=int)

        if not month or not year:
            today = date.today()
            month, year = today.month, today.year

        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        records = Attendance.query.filter(
            and_(
                Attendance.student_id == student.id,
                Attendance.date >= start_date,
                Attendance.date <= end_date
            )
        ).all()

        present_dates = [r.date.isoformat() for r in records if r.status == 'present']

        absent_dates = []
        current = start_date
        today_date = date.today()

        while current <= min(end_date, today_date):
            if current.weekday() < 5:
                date_str = current.isoformat()
                if date_str not in present_dates:
                    absent_dates.append(date_str)
            current += timedelta(days=1)

        return jsonify({
            'success': True,
            'present_dates': present_dates,
            'absent_dates': absent_dates
        }), 200
    except Exception as e:
        logger.error(f"Error fetching monthly attendance: {e}")
        return jsonify({'success': False, 'message': 'Failed to fetch monthly attendance'}), 500

@student_bp.route('/api/student-trend/<int:student_id>')
@token_required
def get_student_trend(current_user, student_id):
    """Get attendance trend data for visualization"""
    try:
        # Verify access
        if current_user.role == 'student' and current_user.student_id != student_id:
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        
        student = Student.query.get(student_id)
        if not student:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        # Get days parameter (default 30)
        days = request.args.get('days', 30, type=int)
        
        # Get last N days
        end_date = date.today()
        start_date = end_date - timedelta(days=days-1)
        
        # Query attendance for date range
        records = Attendance.query.filter(
            and_(
                Attendance.student_id == student.id,
                Attendance.date >= start_date,
                Attendance.date <= end_date
            )
        ).order_by(Attendance.date.desc(), Attendance.id.desc()).all()
        
        # Create date map (only first record per date)
        attendance_map = {}
        for r in records:
            if r.date not in attendance_map:
                attendance_map[r.date] = r.status
        
        # Generate data for each day
        labels = []
        values = []
        current_date = start_date
        present_count = 0
        total_count = 0
        
        while current_date <= end_date:
            labels.append(current_date.strftime('%m/%d'))
            
            if current_date in attendance_map:
                if attendance_map[current_date] == 'present':
                    present_count += 1
                total_count += 1
            
            # Calculate cumulative attendance rate
            rate = round((present_count / total_count * 100) if total_count > 0 else 0)
            values.append(rate)
            
            current_date += timedelta(days=1)
        
        return jsonify({
            'success': True,
            'labels': labels,
            'values': values
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching trend data: {e}")
        return jsonify({'success': False, 'message': 'Failed to fetch trend'}), 500

def calculate_attendance_streak(student_id):
    """Calculate current consecutive attendance streak"""
    try:
        # Get recent attendance records in descending order
        records = Attendance.query.filter_by(
            student_id=student_id
        ).order_by(Attendance.date.desc(), Attendance.id.desc()).all()
        
        if not records:
            return 0
        
        # Remove duplicates - keep only first record per date
        seen_dates = set()
        unique_records = []
        for record in records:
            if record.date not in seen_dates:
                seen_dates.add(record.date)
                unique_records.append(record)
        
        streak = 0
        expected_date = date.today()
        
        for record in unique_records:
            if record.date == expected_date and record.status == 'present':
                streak += 1
                expected_date -= timedelta(days=1)
            else:
                break
        
        return streak
        
    except Exception as e:
        logger.error(f"Error calculating streak: {e}")
        return 0

@student_bp.route('/api/class-leaderboard')
@token_required
def get_class_leaderboard(current_user):
    """Get leaderboard for students in the same class - NEW ENDPOINT"""
    try:
        # Get current student's class and section
        if current_user.role == 'student' and current_user.student_id:
            current_student = Student.query.get(current_user.student_id)
            if not current_student:
                return jsonify({'success': False, 'message': 'Student not found'}), 404
            
            # Get all students in same class and section
            classmates = Student.query.filter_by(
                status='active',
                class_name=current_student.class_name,
                section=current_student.section
            ).all()
            
            # Calculate attendance rate for each student
            leaderboard = []
            for student in classmates:
                total_days = db.session.query(
                    func.count(distinct(Attendance.date))
                ).filter(Attendance.student_id == student.id).scalar() or 0
                
                days_present = db.session.query(
                    func.count(distinct(Attendance.date))
                ).filter(
                    Attendance.student_id == student.id,
                    Attendance.status == 'present'
                ).scalar() or 0
                
                attendance_rate = round((days_present / total_days * 100) if total_days > 0 else 0)
                
                leaderboard.append({
                    'name': student.name,
                    'student_id': student.student_id,
                    'attendance_rate': attendance_rate,
                    'days_present': days_present,
                    'total_days': total_days,
                    'points': student.points,
                    'is_current_user': student.id == current_student.id,
                    'image_path': student.image_path  # ADDED: Include profile picture
                })
            
            # Sort by attendance rate (descending), then by points
            leaderboard.sort(key=lambda x: (x['attendance_rate'], x['points']), reverse=True)
            
            # Add rank
            for idx, student in enumerate(leaderboard, 1):
                student['rank'] = idx
            
            return jsonify({
                'success': True,
                'class': f"{current_student.class_name}-{current_student.section}",
                'leaderboard': leaderboard
            }), 200
        else:
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        
    except Exception as e:
        logger.error(f"Error fetching class leaderboard: {e}")
        return jsonify({'success': False, 'message': 'Failed to fetch leaderboard'}), 500