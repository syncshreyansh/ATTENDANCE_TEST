"""
Enhanced Liveness Detection Service
Combines multiple verification methods to prevent spoofing
"""
import cv2
import numpy as np
import dlib
from scipy.spatial import distance as dist
import time
import logging

logger = logging.getLogger(__name__)

class LivenessDetector:
    def __init__(self):
        self.detector = dlib.get_frontal_face_detector()
        self.predictor = dlib.shape_predictor("shape_predictor_68_face_landmarks.dat")
        
        # Thresholds
        self.EAR_THRESHOLD = 0.25
        self.MAR_THRESHOLD = 0.6  # Mouth Aspect Ratio for mouth movement
        self.HEAD_POSE_THRESHOLD = 15  # degrees
        
        # State tracking
        self.blink_counter = 0
        self.mouth_counter = 0
        self.total_blinks = 0
        self.frame_check_counter = 0
        self.last_verification_time = 0
        
        # Session tracking
        self.verification_history = []
    
    def calculate_ear(self, eye):
        """Calculate Eye Aspect Ratio for blink detection"""
        A = dist.euclidean(eye[1], eye[5])
        B = dist.euclidean(eye[2], eye[4])
        C = dist.euclidean(eye[0], eye[3])
        ear = (A + B) / (2.0 * C)
        return ear
    
    def calculate_mar(self, mouth):
        """Calculate Mouth Aspect Ratio for mouth movement detection"""
        A = dist.euclidean(mouth[2], mouth[10])  # Vertical
        B = dist.euclidean(mouth[4], mouth[8])   # Vertical
        C = dist.euclidean(mouth[0], mouth[6])   # Horizontal
        mar = (A + B) / (2.0 * C)
        return mar
    
    def estimate_head_pose(self, landmarks, frame_shape):
        """
        Estimate head pose to detect if user is looking at camera
        Returns pitch, yaw, roll angles
        """
        # 3D model points (generic face model)
        model_points = np.array([
            (0.0, 0.0, 0.0),             # Nose tip
            (0.0, -330.0, -65.0),        # Chin
            (-225.0, 170.0, -135.0),     # Left eye left corner
            (225.0, 170.0, -135.0),      # Right eye right corner
            (-150.0, -150.0, -125.0),    # Left mouth corner
            (150.0, -150.0, -125.0)      # Right mouth corner
        ])
        
        # 2D image points from landmarks
        image_points = np.array([
            landmarks[30],    # Nose tip
            landmarks[8],     # Chin
            landmarks[36],    # Left eye left corner
            landmarks[45],    # Right eye right corner
            landmarks[48],    # Left mouth corner
            landmarks[54]     # Right mouth corner
        ], dtype="double")
        
        # Camera internals
        size = frame_shape
        focal_length = size[1]
        center = (size[1] / 2, size[0] / 2)
        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1]
        ], dtype="double")
        
        dist_coeffs = np.zeros((4, 1))
        
        # Solve PnP
        success, rotation_vector, translation_vector = cv2.solvePnP(
            model_points, image_points, camera_matrix, dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE
        )
        
        # Convert rotation vector to Euler angles
        rotation_mat, _ = cv2.Rodrigues(rotation_vector)
        pose_mat = cv2.hconcat((rotation_mat, translation_vector))
        _, _, _, _, _, _, euler_angles = cv2.decomposeProjectionMatrix(pose_mat)
        
        pitch = euler_angles[0][0]
        yaw = euler_angles[1][0]
        roll = euler_angles[2][0]
        
        return pitch, yaw, roll
    
    def detect_texture_quality(self, face_roi):
        """
        Analyze texture to detect if it's a real face or a photo/screen
        Real faces have higher texture variation
        """
        # Convert to grayscale
        gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
        
        # Calculate Laplacian variance (measure of sharpness/texture)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        
        # Calculate local binary pattern variance
        # Higher variance indicates real 3D face
        
        return laplacian_var
    
    def comprehensive_liveness_check(self, frame):
        """
        Perform comprehensive liveness detection
        Returns: (is_live, confidence, details)
        """
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.detector(gray)
            
            if len(faces) == 0:
                return False, 0.0, "No face detected"
            
            if len(faces) > 1:
                return False, 0.0, "Multiple faces detected"
            
            face = faces[0]
            landmarks = self.predictor(gray, face)
            landmarks_np = np.array([(p.x, p.y) for p in landmarks.parts()])
            
            # Initialize verification scores
            verification_scores = {
                'blink': 0,
                'mouth_movement': 0,
                'head_pose': 0,
                'texture': 0
            }
            
            # 1. Eye Blink Detection
            left_eye = landmarks_np[42:48]
            right_eye = landmarks_np[36:42]
            left_ear = self.calculate_ear(left_eye)
            right_ear = self.calculate_ear(right_eye)
            ear = (left_ear + right_ear) / 2.0
            
            if ear < self.EAR_THRESHOLD:
                self.blink_counter += 1
            else:
                if self.blink_counter >= 2:  # Detected a blink
                    self.total_blinks += 1
                    verification_scores['blink'] = 1
                self.blink_counter = 0
            
            # 2. Mouth Movement Detection (optional challenge)
            mouth = landmarks_np[48:68]
            mar = self.calculate_mar(mouth)
            
            if mar > self.MAR_THRESHOLD:
                verification_scores['mouth_movement'] = 1
            
            # 3. Head Pose Verification
            pitch, yaw, roll = self.estimate_head_pose(landmarks_np, frame.shape)
            
            # Check if face is looking directly at camera
            if abs(pitch) < self.HEAD_POSE_THRESHOLD and \
               abs(yaw) < self.HEAD_POSE_THRESHOLD:
                verification_scores['head_pose'] = 1
            
            # 4. Texture Analysis (anti-photo spoofing)
            x, y, w, h = face.left(), face.top(), face.width(), face.height()
            face_roi = frame[y:y+h, x:x+w]
            
            if face_roi.size > 0:
                texture_quality = self.detect_texture_quality(face_roi)
                # Threshold determined empirically (real faces > 100, photos < 50)
                if texture_quality > 100:
                    verification_scores['texture'] = 1
            
            # Calculate overall confidence
            total_score = sum(verification_scores.values())
            max_score = len(verification_scores)
            confidence = total_score / max_score
            
            # Determine if live based on confidence threshold
            is_live = confidence >= 0.6  # At least 60% of checks passed
            
            details = {
                'blink_detected': verification_scores['blink'] == 1,
                'mouth_movement': verification_scores['mouth_movement'] == 1,
                'head_pose_correct': verification_scores['head_pose'] == 1,
                'texture_valid': verification_scores['texture'] == 1,
                'total_blinks': self.total_blinks,
                'ear': ear,
                'mar': mar,
                'head_angles': {'pitch': pitch, 'yaw': yaw, 'roll': roll}
            }
            
            # Store verification in history
            self.verification_history.append({
                'timestamp': time.time(),
                'is_live': is_live,
                'confidence': confidence,
                'details': details
            })
            
            # Keep only last 10 verifications
            if len(self.verification_history) > 10:
                self.verification_history.pop(0)
            
            return is_live, confidence, details
            
        except Exception as e:
            logger.error(f"Error in liveness detection: {e}")
            return False, 0.0, f"Error: {str(e)}"
    
    def quick_blink_check(self, frame):
        """
        Fast blink detection for real-time use
        Returns: True if blink detected
        """
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.detector(gray)
            
            for face in faces:
                landmarks = self.predictor(gray, face)
                landmarks_np = np.array([(p.x, p.y) for p in landmarks.parts()])
                
                left_eye = landmarks_np[42:48]
                right_eye = landmarks_np[36:42]
                
                left_ear = self.calculate_ear(left_eye)
                right_ear = self.calculate_ear(right_eye)
                ear = (left_ear + right_ear) / 2.0
                
                if ear < self.EAR_THRESHOLD:
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error in quick blink check: {e}")
            return False
    
    def reset_session(self):
        """Reset session tracking for new user"""
        self.blink_counter = 0
        self.mouth_counter = 0
        self.total_blinks = 0
        self.frame_check_counter = 0
        self.verification_history = []
    
    def get_verification_summary(self):
        """Get summary of recent verification attempts"""
        if not self.verification_history:
            return None
        
        recent = self.verification_history[-5:]  # Last 5 attempts
        avg_confidence = sum(v['confidence'] for v in recent) / len(recent)
        success_rate = sum(1 for v in recent if v['is_live']) / len(recent)
        
        return {
            'average_confidence': avg_confidence,
            'success_rate': success_rate,
            'total_attempts': len(self.verification_history),
            'total_blinks': self.total_blinks
        }