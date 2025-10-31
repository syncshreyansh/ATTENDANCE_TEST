"""
Student-specific API routes
Provides attendance data and analytics for individual students
"""
from flask import Blueprint, jsonify, render_template, request
from auth_service import token_required
from models import db, Student, Attendance
from datetime import datetime, timedelta, date
from sqlalchemy import func, and_
import logging

logger = logging.getLogger(__name__)

student_bp = Blueprint('student', __name__)

@student_bp.route('/student-dashboard')
@token_required
def student_dashboard_page(current_user):
    """Serve student dashboard page"""
    if current_user.role != 'student':
        return jsonify({'message': 'Access denied'}), 403
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
                'enrollment_date': student.enrollment_date.isoformat() if student.enrollment_date else None
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching student profile: {e}")
        return jsonify({'success': False, 'message': 'Failed to fetch profile'}), 500

@student_bp.route('/api/student-stats/<int:student_id>')
@token_required
def get_student_stats(current_user, student_id):
    """Get attendance statistics for a student"""
    try:
        # Verify access
        if current_user.role == 'student' and current_user.student_id != student_id:
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        
        student = Student.query.get(student_id)
        if not student:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        # Calculate stats
        total_days = Attendance.query.filter_by(student_id=student.id).count()
        days_present = Attendance.query.filter_by(
            student_id=student.id,
            status='present'
        ).count()
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
    """Get attendance records for a student"""
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
        
        records = query.order_by(Attendance.date.desc()).all()
        
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
            } for r in records]
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching attendance: {e}")
        return jsonify({'success': False, 'message': 'Failed to fetch attendance'}), 500

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
        ).all()
        
        # Create date map
        attendance_map = {r.date: r.status for r in records}
        
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
        ).order_by(Attendance.date.desc()).all()
        
        if not records:
            return 0
        
        streak = 0
        expected_date = date.today()
        
        for record in records:
            if record.date == expected_date and record.status == 'present':
                streak += 1
                expected_date -= timedelta(days=1)
            else:
                break
        
        return streak
        
    except Exception as e:
        logger.error(f"Error calculating streak: {e}")
        return 0

@student_bp.route('/api/student-leaderboard')
@token_required
def get_leaderboard(current_user):
    """Get top students by points (gamification)"""
    try:
        top_students = Student.query.filter_by(
            status='active'
        ).order_by(Student.points.desc()).limit(10).all()
        
        # Check current user's rank
        user_rank = None
        if current_user.student_id:
            student = Student.query.get(current_user.student_id)
            if student:
                higher_ranked = Student.query.filter(
                    Student.status == 'active',
                    Student.points > student.points
                ).count()
                user_rank = higher_ranked + 1
        
        return jsonify({
            'success': True,
            'leaderboard': [{
                'rank': idx + 1,
                'name': s.name,
                'student_id': s.student_id,
                'points': s.points,
                'class': f"{s.class_name}-{s.section}"
            } for idx, s in enumerate(top_students)],
            'user_rank': user_rank
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching leaderboard: {e}")
        return jsonify({'success': False, 'message': 'Failed to fetch leaderboard'}), 500