"""
Authentication Routes for Smart Attendance System
Handles login, registration, and token management
"""
from flask import Blueprint, request, jsonify, render_template
from auth_service import AuthService, token_required, admin_required, User
from config import Config
from models import db, OTPToken, Student, get_ist_now
from whatsapp_service import WhatsAppService
from datetime import timedelta
import random
import logging

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login')
def login_page():
    """Serve login page"""
    return render_template('login.html')

@auth_bp.route('/api/auth/register', methods=['POST'])
def register():
    """
    Register a new user
    Expected JSON: {username, email, password, role, student_id (optional)}
    """
    try:
        data = request.json
        
        # Validate required fields
        required_fields = ['username', 'email', 'password']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'message': f'Missing required field: {field}'
                }), 400
        
        # Register user
        result = AuthService.register_user(
            username=data['username'],
            email=data['email'],
            password=data['password'],
            role=data.get('role', 'student'),
            student_id=data.get('student_id')
        )
        
        status_code = 201 if result['success'] else 400
        return jsonify(result), status_code
        
    except Exception as e:
        logger.error(f"Registration error: {e}")
        return jsonify({
            'success': False,
            'message': f'Registration failed: {str(e)}'
        }), 500

@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    """
    Login user
    Expected JSON: {username, password}
    Returns: {success, token, user} or error
    """
    try:
        data = request.json
        
        if not data or 'username' not in data or 'password' not in data:
            return jsonify({
                'success': False,
                'message': 'Username and password are required'
            }), 400
        
        # Authenticate user
        result = AuthService.login(
            username=data['username'],
            password=data['password']
        )
        
        status_code = 200 if result['success'] else 401
        return jsonify(result), status_code
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({
            'success': False,
            'message': f'Login failed: {str(e)}'
        }), 500

@auth_bp.route('/api/auth/verify', methods=['GET'])
@token_required
def verify_token(current_user):
    """
    Verify if token is valid
    Protected route - requires valid JWT token
    """
    return jsonify({
        'success': True,
        'user': {
            'id': current_user.id,
            'username': current_user.username,
            'email': current_user.email,
            'role': current_user.role,
            'student_id': current_user.student_id
        }
    }), 200

@auth_bp.route('/api/auth/logout', methods=['POST'])
@token_required
def logout(current_user):
    """
    Logout user (client-side should delete token)
    This is mainly for logging purposes
    """
    logger.info(f"User {current_user.username} logged out")
    return jsonify({
        'success': True,
        'message': 'Logged out successfully'
    }), 200

@auth_bp.route('/api/auth/change-password', methods=['POST'])
@token_required
def change_password(current_user):
    """
    Change user password
    Expected JSON: {old_password, new_password}
    """
    try:
        data = request.json
        
        if not data or 'old_password' not in data or 'new_password' not in data:
            return jsonify({
                'success': False,
                'message': 'Old and new passwords are required'
            }), 400
        
        # Verify old password
        if not current_user.check_password(data['old_password']):
            return jsonify({
                'success': False,
                'message': 'Current password is incorrect'
            }), 401
        
        # Validate new password
        if len(data['new_password']) < 6:
            return jsonify({
                'success': False,
                'message': 'New password must be at least 6 characters'
            }), 400
        
        # Update password
        current_user.set_password(data['new_password'])
        from models import db
        db.session.commit()
        
        logger.info(f"Password changed for user {current_user.username}")
        
        return jsonify({
            'success': True,
            'message': 'Password changed successfully'
        }), 200
        
    except Exception as e:
        logger.error(f"Password change error: {e}")
        return jsonify({
            'success': False,
            'message': f'Password change failed: {str(e)}'
        }), 500

@auth_bp.route('/api/auth/request-reset-otp', methods=['POST'])
def request_reset_otp():
    """Request OTP for password reset"""
    try:
        data = request.json or {}
        username = data.get('username')

        if not username:
            return jsonify({'success': False, 'message': 'Username required'}), 400

        user = User.query.filter_by(username=username).first()
        if not user:
            # Do not reveal user existence
            return jsonify({'success': True, 'message': 'If account exists, OTP sent'}), 200

        now = get_ist_now()
        last_otp = OTPToken.query.filter_by(
            user_id=user.id
        ).order_by(OTPToken.created_at.desc()).first()

        if last_otp:
            elapsed = (now - last_otp.created_at).total_seconds()
            if elapsed < Config.OTP_RESEND_COOLDOWN_SEC:
                return jsonify({
                    'success': False,
                    'message': f"Please wait {int(Config.OTP_RESEND_COOLDOWN_SEC - elapsed)}s before requesting again"
                }), 429

        otp_code = f"{random.randint(0, 999999):06d}"
        expires_at = now + timedelta(minutes=Config.OTP_EXP_MINUTES)

        otp_token = OTPToken(
            user_id=user.id,
            code=otp_code,
            expires_at=expires_at
        )
        db.session.add(otp_token)
        db.session.commit()

        phone = None
        if user.student_id:
            student = Student.query.get(user.student_id)
            if student:
                phone = student.parent_phone

        if phone:
            whatsapp = WhatsAppService()
            whatsapp.send_otp(phone, otp_code)

        return jsonify({
            'success': True,
            'message': 'OTP sent to registered phone'
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"OTP request failed: {e}")
        return jsonify({'success': False, 'message': 'Failed to send OTP'}), 500

@auth_bp.route('/api/auth/verify-reset-otp', methods=['POST'])
def verify_reset_otp():
    """Verify OTP code"""
    try:
        data = request.json or {}
        username = data.get('username')
        code = data.get('code')

        if not username or not code:
            return jsonify({'success': False, 'message': 'Username and code required'}), 400

        user = User.query.filter_by(username=username).first()
        if not user:
            return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

        otp = OTPToken.query.filter_by(
            user_id=user.id,
            code=code,
            used=False
        ).order_by(OTPToken.created_at.desc()).first()

        if not otp:
            return jsonify({'success': False, 'message': 'Invalid OTP'}), 401

        now = get_ist_now()
        if now > otp.expires_at:
            return jsonify({'success': False, 'message': 'OTP expired'}), 401

        otp.used = True
        db.session.commit()

        reset_token = user.generate_token(expires_in=Config.OTP_EXP_MINUTES * 60)
        return jsonify({
            'success': True,
            'message': 'OTP verified',
            'reset_token': reset_token
        }), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"OTP verification failed: {e}")
        return jsonify({'success': False, 'message': 'Failed to verify OTP'}), 500

@auth_bp.route('/api/auth/reset-password', methods=['POST'])
@token_required
def reset_password(current_user):
    """Reset password after OTP verification"""
    try:
        data = request.json or {}
        new_password = data.get('new_password')

        if not new_password or len(new_password) < 6:
            return jsonify({'success': False, 'message': 'Password must be 6+ characters'}), 400

        current_user.set_password(new_password)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Password reset successful'}), 200
    except Exception as e:
        db.session.rollback()
        logger.error(f"Password reset failed: {e}")
        return jsonify({'success': False, 'message': 'Failed to reset password'}), 500

@auth_bp.route('/api/auth/users', methods=['GET'])
@admin_required
def get_users(current_user):
    """
    Get all users (Admin only)
    """
    try:
        users = User.query.all()
        return jsonify({
            'success': True,
            'users': [{
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'role': u.role,
                'is_active': u.is_active,
                'last_login': u.last_login.isoformat() if u.last_login else None
            } for u in users]
        }), 200
    except Exception as e:
        logger.error(f"Error fetching users: {e}")
        return jsonify({
            'success': False,
            'message': 'Failed to fetch users'
        }), 500

@auth_bp.route('/api/auth/users/<int:user_id>/status', methods=['PATCH'])
@admin_required
def toggle_user_status(current_user, user_id):
    """
    Enable/disable user account (Admin only)
    Expected JSON: {is_active: true/false}
    """
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({
                'success': False,
                'message': 'User not found'
            }), 404
        
        data = request.json
        if 'is_active' not in data:
            return jsonify({
                'success': False,
                'message': 'is_active field is required'
            }), 400
        
        user.is_active = data['is_active']
        from models import db
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f"User {'enabled' if user.is_active else 'disabled'} successfully"
        }), 200
        
    except Exception as e:
        logger.error(f"Error toggling user status: {e}")
        return jsonify({
            'success': False,
            'message': 'Failed to update user status'
        }), 500