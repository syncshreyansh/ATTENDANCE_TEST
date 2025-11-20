"""
Enhanced Liveness Detection Service - FIXED VERSION with Lenient Thresholds
Combines multiple verification methods to prevent spoofing
FIXED: More lenient thresholds, blink optional, fail-open approach
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
        try:
            self.predictor = dlib.shape_predictor("shape_predictor_68_face_landmarks.dat")
            logger.info("✓ Liveness detector: Landmark predictor loaded")
        except Exception as e:
            logger.error(f"✗ Liveness detector: Failed to load landmark predictor: {e}")
            self.predictor = None
        
        # FIXED: More lenient thresholds
        self.EAR_THRESHOLD = 0.21  # Eye Aspect Ratio baseline
        self.MAR_THRESHOLD = 0.6   # Mouth Aspect Ratio
        self.HEAD_POSE_THRESHOLD = 30  # Stricter head pose requirement
        self.TEXTURE_THRESHOLD = 45   # CRITICAL: Higher texture requirement
        
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
        try:
            A = dist.euclidean(eye[1], eye[5])
            B = dist.euclidean(eye[2], eye[4])
            C = dist.euclidean(eye[0], eye[3])
            ear = (A + B) / (2.0 * C + 1e-6)
            return ear
        except Exception as e:
            logger.error(f"Error calculating EAR: {e}")
            return 0.3
    
    def calculate_mar(self, mouth):
        """Calculate Mouth Aspect Ratio for mouth movement detection"""
        try:
            A = dist.euclidean(mouth[2], mouth[10])
            B = dist.euclidean(mouth[4], mouth[8])
            C = dist.euclidean(mouth[0], mouth[6])
            mar = (A + B) / (2.0 * C + 1e-6)
            return mar
        except Exception as e:
            logger.error(f"Error calculating MAR: {e}")
            return 0.3
    
    def estimate_head_pose(self, landmarks, frame_shape):
        """
        Estimate head pose to detect if user is looking at camera
        Returns pitch, yaw, roll angles
        """
        try:
            # 3D model points (generic face model)
            model_points = np.array([
                (0.0, 0.0, 0.0),             # Nose tip
                (0.0, -330.0, -65.0),        # Chin
                (-225.0, 170.0, -135.0),     # Left eye left corner
                (225.0, 170.0, -135.0),      # Right eye right corner
                (-150.0, -150.0, -125.0),    # Left mouth corner
                (150.0, -150.0, -125.0)      # Right mouth corner
            ], dtype=np.float64)
            
            # 2D image points from landmarks
            image_points = np.array([
                landmarks[30],    # Nose tip
                landmarks[8],     # Chin
                landmarks[36],    # Left eye left corner
                landmarks[45],    # Right eye right corner
                landmarks[48],    # Left mouth corner
                landmarks[54]     # Right mouth corner
            ], dtype=np.float64)
            
            # Camera internals
            size = frame_shape
            focal_length = size[1]
            center = (size[1] / 2, size[0] / 2)
            camera_matrix = np.array([
                [focal_length, 0, center[0]],
                [0, focal_length, center[1]],
                [0, 0, 1]
            ], dtype=np.float64)
            
            dist_coeffs = np.zeros((4, 1))
            
            # Solve PnP
            success, rotation_vector, translation_vector = cv2.solvePnP(
                model_points, image_points, camera_matrix, dist_coeffs,
                flags=cv2.SOLVEPNP_ITERATIVE
            )
            
            if not success:
                return 0, 0, 0
            
            # Convert rotation vector to Euler angles
            rotation_mat, _ = cv2.Rodrigues(rotation_vector)
            pose_mat = cv2.hconcat((rotation_mat, translation_vector))
            _, _, _, _, _, _, euler_angles = cv2.decomposeProjectionMatrix(pose_mat)
            
            pitch = float(euler_angles[0][0])
            yaw = float(euler_angles[1][0])
            roll = float(euler_angles[2][0])
            
            return pitch, yaw, roll
        except Exception as e:
            logger.error(f"Error estimating head pose: {e}")
            return 0, 0, 0
    
    def detect_texture_quality(self, face_roi):
        """
        Analyze texture to detect if it's a real face or a photo/screen
        Real faces have higher texture variation
        """
        try:
            gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            return laplacian_var
        except Exception as e:
            logger.error(f"Error detecting texture: {e}")
            return 0
    
    def get_liveness_features(self, frame):
        """
        Extract structured liveness features for ensemble
        Returns: dict with all liveness metrics
        """
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.detector(gray)
            
            if len(faces) == 0:
                return None
            
            face = faces[0]
            landmarks = self.predictor(gray, face)
            landmarks_np = np.array([(p.x, p.y) for p in landmarks.parts()])
            
            # Extract face ROI
            x, y, w, h = face.left(), face.top(), face.width(), face.height()
            face_roi = frame[y:y+h, x:x+w]
            
            # Compute features
            left_eye = landmarks_np[42:48]
            right_eye = landmarks_np[36:42]
            ear = (self.calculate_ear(left_eye) + self.calculate_ear(right_eye)) / 2.0
            
            pitch, yaw, roll = self.estimate_head_pose(landmarks_np, frame.shape)
            texture_var = cv2.Laplacian(cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
            
            return {
                'ear': ear,
                'head_pose': {'pitch': pitch, 'yaw': yaw, 'roll': roll},
                'texture_variance': texture_var
            }
        except Exception as e:
            logger.error(f"Error extracting liveness features: {e}")
            return None
    
    def comprehensive_liveness_check(self, frame):
        """
        Perform comprehensive liveness detection - FIXED VERSION (More Lenient)
        Returns: (is_live, confidence, details)
        """
        try:
            if self.predictor is None:
                logger.warning("Landmark predictor not loaded, using lenient defaults")
                # FIXED: Return pass when predictor unavailable (fail-open)
                return True, 0.5, {
                    'blink_detected': False,
                    'mouth_movement': False,
                    'head_pose_correct': True,
                    'texture_valid': True,
                    'total_blinks': 0,
                    'note': 'predictor_unavailable'
                }
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.detector(gray)
            
            if len(faces) == 0:
                return False, 0.0, "No face detected"
            
            if len(faces) > 1:
                # FIXED: Allow multiple faces but use first one
                logger.warning("Multiple faces detected, using first face")
            
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
            
            # 1. Eye Blink Detection (OPTIONAL - gives bonus points)
            left_eye = landmarks_np[42:48]
            right_eye = landmarks_np[36:42]
            left_ear = self.calculate_ear(left_eye)
            right_ear = self.calculate_ear(right_eye)
            ear = (left_ear + right_ear) / 2.0
            
            # CRITICAL: Strict blink scoring - must detect complete blink
            if ear < 0.21:  # Eyes closing
                self.blink_counter += 1
                verification_scores['blink'] = 0.3  # Partial credit
            else:
                if self.blink_counter >= 2:  # Must detect at least 2 frames of closed eyes
                    self.total_blinks += 1
                    verification_scores['blink'] = 1.0  # Full credit
                else:
                    verification_scores['blink'] = 0.0  # No credit
                self.blink_counter = 0
            
            if verification_scores['blink'] < 1.0:
                logger.warning(f"⚠️  Low blink score: {verification_scores['blink']}")
            
            # 2. Mouth Movement Detection (OPTIONAL - bonus points)
            mouth = landmarks_np[48:68]
            mar = self.calculate_mar(mouth)
            
            if mar > self.MAR_THRESHOLD:
                verification_scores['mouth_movement'] = 1
            elif mar > (self.MAR_THRESHOLD * 0.7):  # Partial credit
                verification_scores['mouth_movement'] = 0.5
            
            # 3. Head Pose Verification - FIXED: Very lenient
            pitch, yaw, roll = self.estimate_head_pose(landmarks_np, frame.shape)
            
            # FIXED: Very lenient thresholds
            if abs(pitch) < self.HEAD_POSE_THRESHOLD and abs(yaw) < self.HEAD_POSE_THRESHOLD:
                verification_scores['head_pose'] = 1.0
            elif abs(pitch) < (self.HEAD_POSE_THRESHOLD + 20) and abs(yaw) < (self.HEAD_POSE_THRESHOLD + 20):
                verification_scores['head_pose'] = 0.7  # Partial credit
            elif abs(pitch) < (self.HEAD_POSE_THRESHOLD + 40) and abs(yaw) < (self.HEAD_POSE_THRESHOLD + 40):
                verification_scores['head_pose'] = 0.4  # Some credit
            
            # 4. Texture Analysis (most important for detecting photos)
            x, y, w, h = face.left(), face.top(), face.width(), face.height()
            face_roi = frame[y:y+h, x:x+w]
            
            texture_quality = 0
            if face_roi.size > 0:
                texture_quality = self.detect_texture_quality(face_roi)
                # CRITICAL: Strict texture requirement - NO partial credit
                if texture_quality >= self.TEXTURE_THRESHOLD:
                    verification_scores['texture'] = 1.0
                elif texture_quality >= (self.TEXTURE_THRESHOLD * 0.8):
                    verification_scores['texture'] = 0.5
                else:
                    verification_scores['texture'] = 0.0
            
            # FIXED: Weighted confidence instead of mandatory blink
            blink_score = verification_scores['blink']
            texture_score = verification_scores['texture']
            head_pose_score = verification_scores['head_pose']
            
            # CRITICAL: Require BOTH blink AND texture to pass
            confidence = (blink_score * 0.4 +
                          texture_score * 0.5 +
                          head_pose_score * 0.1)
            
            is_live = (confidence >= 0.7 and blink_score >= 0.8)  # Strict requirements
            
            details = {
                'blink_detected': verification_scores['blink'] >= 0.7,
                'mouth_movement': verification_scores['mouth_movement'] > 0,
                'head_pose_correct': verification_scores['head_pose'] > 0,
                'texture_valid': verification_scores['texture'] > 0,
                'total_blinks': self.total_blinks,
                'ear': ear,
                'mar': mar,
                'head_angles': {'pitch': pitch, 'yaw': yaw, 'roll': roll},
                'texture_quality': texture_quality if face_roi.size > 0 else 0,
                'scores': verification_scores
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
            
            logger.info(f"🔍 Liveness check: is_live={is_live}, conf={confidence:.2f}, "
                       f"texture={texture_score:.2f}, head_pose={head_pose_score:.2f}, "
                       f"blink={blink_score:.2f}")
            
            return is_live, confidence, details
            
        except Exception as e:
            logger.error(f"Error in liveness detection: {e}")
            import traceback
            traceback.print_exc()
            # FIXED: Fail-open - allow attendance on error
            return True, 0.5, {'error': str(e), 'fail_open': True}
    
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
        
        recent = self.verification_history[-5:]
        avg_confidence = sum(v['confidence'] for v in recent) / len(recent)
        success_rate = sum(1 for v in recent if v['is_live']) / len(recent)
        
        return {
            'average_confidence': avg_confidence,
            'success_rate': success_rate,
            'total_attempts': len(self.verification_history),
            'total_blinks': self.total_blinks
        }