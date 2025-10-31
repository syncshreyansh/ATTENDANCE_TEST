"""
Authentication Routes for Smart Attendance System
Handles login, registration, and token management
"""
from flask import Blueprint, request, jsonify, render_template
from auth_service import AuthService, token_required, admin_required, User
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