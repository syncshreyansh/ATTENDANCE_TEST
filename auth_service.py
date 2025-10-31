"""
Authentication Service for Smart Attendance System
Handles user login, JWT tokens, and role-based access control
"""
from flask import request, jsonify
from functools import wraps
import jwt
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from models import db
import os

# Secret key for JWT (move to config.py in production)
JWT_SECRET = os.environ.get('JWT_SECRET') or 'your-secret-key-change-in-production'
JWT_ALGORITHM = 'HS256'
JWT_EXP_DELTA_SECONDS = 86400  # 24 hours

class User(db.Model):
    """User model for authentication"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='student')  # 'student', 'admin', 'teacher'
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    
    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verify password"""
        return check_password_hash(self.password_hash, password)
    
    def generate_token(self):
        """Generate JWT token"""
        payload = {
            'user_id': self.id,
            'username': self.username,
            'role': self.role,
            'exp': datetime.utcnow() + timedelta(seconds=JWT_EXP_DELTA_SECONDS)
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        return token
    
    @staticmethod
    def verify_token(token):
        """Verify and decode JWT token"""
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            return None  # Token expired
        except jwt.InvalidTokenError:
            return None  # Invalid token

class AuthService:
    """Authentication service methods"""
    
    @staticmethod
    def register_user(username, email, password, role='student', student_id=None):
        """Register a new user"""
        # Check if user exists
        if User.query.filter_by(username=username).first():
            return {'success': False, 'message': 'Username already exists'}
        
        if User.query.filter_by(email=email).first():
            return {'success': False, 'message': 'Email already exists'}
        
        # Create new user
        user = User(
            username=username,
            email=email,
            role=role,
            student_id=student_id
        )
        user.set_password(password)
        
        try:
            db.session.add(user)
            db.session.commit()
            return {
                'success': True,
                'message': 'User registered successfully',
                'user_id': user.id
            }
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': f'Registration failed: {str(e)}'}
    
    @staticmethod
    def login(username, password):
        """Authenticate user and return token"""
        user = User.query.filter_by(username=username).first()
        
        if not user or not user.check_password(password):
            return {'success': False, 'message': 'Invalid credentials'}
        
        if not user.is_active:
            return {'success': False, 'message': 'Account is disabled'}
        
        # Update last login
        user.last_login = datetime.utcnow()
        db.session.commit()
        
        # Generate token
        token = user.generate_token()
        
        return {
            'success': True,
            'token': token,
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role,
                'student_id': user.student_id
            }
        }

def token_required(f):
    """Decorator to protect routes with JWT authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Check for token in headers
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer <token>
            except IndexError:
                return jsonify({'message': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'message': 'Token is missing'}), 401
        
        # Verify token
        payload = User.verify_token(token)
        if not payload:
            return jsonify({'message': 'Token is invalid or expired'}), 401
        
        # Get user from database
        current_user = User.query.get(payload['user_id'])
        if not current_user or not current_user.is_active:
            return jsonify({'message': 'User not found or inactive'}), 401
        
        # Pass user to route
        return f(current_user, *args, **kwargs)
    
    return decorated

def admin_required(f):
    """Decorator to restrict access to admin users only"""
    @wraps(f)
    def decorated(current_user, *args, **kwargs):
        if current_user.role != 'admin':
            return jsonify({'message': 'Admin access required'}), 403
        return f(current_user, *args, **kwargs)
    
    return token_required(decorated)