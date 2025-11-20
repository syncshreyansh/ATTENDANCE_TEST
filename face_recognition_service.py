# face_recognition_service.py - FULLY FIXED VERSION with ACTUAL liveness and spoof detection
import cv2
import face_recognition
import dlib
import numpy as np
from scipy.spatial import distance as dist
import logging
import hashlib
from models import Student, db, ActivityLog, get_ist_now
from datetime import datetime
import pytz
import json
from concurrent.futures import ThreadPoolExecutor
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FaceRecognitionService:
    def __init__(self):
        self.detector = dlib.get_frontal_face_detector()
        try:
            self.predictor = dlib.shape_predictor("shape_predictor_68_face_landmarks.dat")
            logger.info("✓ Landmark predictor loaded successfully")
        except Exception as e:
            logger.error(f"✗ Failed to load landmark predictor: {e}")
            self.predictor = None
            
        self.known_encodings = []
        self.known_names = []
        self.known_ids = []
        self.loaded = False
        
        # Enhanced state management with stricter thresholds
        self.last_state_result = None
        self.frame_skip_counter = 0
        self.FRAME_SKIP = 2
        self.camera_obstructed = False
        self.recognition_history = {}
        
        # Enhanced thresholds for better accuracy
        self.FACE_MATCH_THRESHOLD = 0.5
        self.CONFIDENCE_THRESHOLD = 0.5
        self.HEAD_POSE_THRESHOLD = 35
        self.EAR_THRESHOLD = 0.25
        self.TEXTURE_THRESHOLD = 50
        self.MIN_FACE_SIZE = 100
        
        # Thread pool for parallel processing
        self.executor = ThreadPoolExecutor(max_workers=2)
        
        # FIXED: Initialize liveness detector
        from liveness_detection import LivenessDetector
        self.liveness_detector = LivenessDetector()
        logger.info("✓ Liveness detector initialized")
        
        # Multi-frame verification buffer
        self.verification_frames = []
        self.required_consecutive_frames = 3

    def _ensure_loaded(self):
        """Lazy loading of face encodings with error handling"""
        if not self.loaded:
            try:
                self.load_encodings_from_db()
                return True
            except Exception as e:
                logger.error(f"Error lazily loading faces: {e}")
                return False
        return True

    def load_encodings_from_db(self):
        """Load all face encodings from database with validation"""
        logger.info("Loading face encodings from database...")
        try:
            students = Student.query.filter_by(status='active').all()
            self.known_encodings = []
            self.known_names = []
            self.known_ids = []
            
            loaded_count = 0
            for student in students:
                if student.face_encoding is not None:
                    if isinstance(student.face_encoding, np.ndarray) and len(student.face_encoding) == 128:
                        self.known_encodings.append(student.face_encoding)
                        self.known_names.append(student.name)
                        self.known_ids.append(student.id)
                        loaded_count += 1
                    else:
                        logger.warning(f"Invalid encoding for student {student.student_id}")
            
            self.loaded = True
            logger.info(f"✓ Successfully loaded {loaded_count} valid face encodings")
            return True
            
        except Exception as e:
            logger.error(f"✗ Error loading face encodings from database: {e}")
            self.loaded = False
            return False

    def detect_camera_obstruction(self, frame):
        """Enhanced camera obstruction detection"""
        try:
            if frame is None or frame.size == 0:
                return True, "Frame is empty"
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Check 1: Average brightness
            avg_brightness = np.mean(gray)
            if avg_brightness < 15:
                return True, "Camera appears to be covered or in very dark environment"
            
            # Check 2: Texture variance
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            if laplacian_var < 10:
                return True, "Camera feed shows uniform surface (possible obstruction)"
            
            # Check 3: Color distribution
            hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
            hist_normalized = hist.flatten() / (hist.sum() + 1e-6)
            
            if np.max(hist_normalized) > 0.6:
                return True, "Camera shows uniform pattern (possible obstruction)"
            
            # Check 4: Oversaturation
            bright_pixels = np.sum(gray > 240)
            if bright_pixels > (gray.size * 0.5):
                return True, "Camera feed is oversaturated"
            
            return False, ""
            
        except Exception as e:
            logger.error(f"Error detecting camera obstruction: {e}")
            return False, ""

    def validate_face_quality(self, frame, face_location):
        """Validate face quality before recognition"""
        try:
            top, right, bottom, left = face_location
            
            # Check face size
            face_width = right - left
            face_height = bottom - top
            if face_width < self.MIN_FACE_SIZE or face_height < self.MIN_FACE_SIZE:
                return False, "Face too small or far from camera"
            
            # Check if face is within frame boundaries
            h, w = frame.shape[:2]
            if left < 0 or top < 0 or right > w or bottom > h:
                return False, "Face partially outside frame"
            
            # Extract face ROI
            face_roi = frame[top:bottom, left:right]
            if face_roi.size == 0:
                return False, "Invalid face region"
            
            # Check brightness
            gray_face = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
            avg_brightness = np.mean(gray_face)
            if avg_brightness < 30:
                return False, "Face too dark - improve lighting"
            if avg_brightness > 240:
                return False, "Face overexposed - reduce lighting"
            
            # Check blur (sharpness)
            laplacian_var = cv2.Laplacian(gray_face, cv2.CV_64F).var()
            if laplacian_var < 50:
                return False, "Image too blurry - hold steady"
            
            return True, "Face quality acceptable"
            
        except Exception as e:
            logger.error(f"Error validating face quality: {e}")
            return False, "Face validation error"

    def recognize_faces_with_state(self, frame):
        """
        FIXED: Enhanced recognition with ACTUAL liveness and spoof detection
        """
        if not self._ensure_loaded():
            return ('error', 'System not initialized - please restart', {})
        
        # Performance optimization: Skip frames
        self.frame_skip_counter += 1
        if self.frame_skip_counter % self.FRAME_SKIP != 0:
            if self.last_state_result:
                return self.last_state_result
            return ('clear', None, {})
        
        try:
            # Validate frame
            if frame is None or frame.size == 0:
                return ('error', 'Invalid camera frame', {})
            
            # Check for camera obstruction
            is_obstructed, obstruction_reason = self.detect_camera_obstruction(frame)
            if is_obstructed:
                if not self.camera_obstructed:
                    self.camera_obstructed = True
                    self._log_activity('camera_obstructed', obstruction_reason)
                result = ('obstructed', obstruction_reason, {})
                self.last_state_result = result
                return result
            else:
                if self.camera_obstructed:
                    self.camera_obstructed = False
                    self._log_activity('camera_resumed', 'Camera feed restored')
            
            # Face detection with optimized model
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            face_locations = face_recognition.face_locations(rgb_frame, model='hog', number_of_times_to_upsample=1)
            
            # No face detected
            if len(face_locations) == 0:
                result = ('no_face', None, {'total_faces': 0})
                self.last_state_result = result
                return result
            
            # Multiple faces
            if len(face_locations) > 1:
                result = ('multiple_faces', 'Multiple people detected - only one person allowed', {'total_faces': len(face_locations)})
                self.last_state_result = result
                return result
            
            # Single face - validate quality
            face_location = face_locations[0]
            quality_valid, quality_msg = self.validate_face_quality(frame, face_location)
            if not quality_valid:
                result = ('error', quality_msg, {})
                self.last_state_result = result
                return result
            
            # Get face encoding
            face_encodings = face_recognition.face_encodings(rgb_frame, face_locations, num_jitters=1, model='large')
            
            if len(face_encodings) == 0:
                result = ('error', 'Could not extract face features - adjust position', {})
                self.last_state_result = result
                return result
            
            face_encoding = face_encodings[0]
            
            # Check if database has students
            if len(self.known_encodings) == 0:
                result = ('unknown', 'No enrolled students in database', {})
                self.last_state_result = result
                return result
            
            # Face matching with stricter threshold
            matches = face_recognition.compare_faces(
                self.known_encodings, 
                face_encoding,
                tolerance=self.FACE_MATCH_THRESHOLD
            )
            face_distances = face_recognition.face_distance(
                self.known_encodings, 
                face_encoding
            )
            
            if len(face_distances) == 0:
                result = ('unknown', 'Face not recognized', {})
                self.last_state_result = result
                return result
            
            best_match_index = np.argmin(face_distances)
            confidence = 1 - face_distances[best_match_index]
            
            # Enhanced matching logic
            if not matches[best_match_index] or confidence < self.CONFIDENCE_THRESHOLD:
                self._log_activity('unknown_face_attempt', f'Confidence: {confidence:.2f}')
                result = ('unknown', f'Face not recognized (confidence too low: {confidence:.0%})', {})
                self.last_state_result = result
                return result
            
            # Face recognized!
            student_id = self.known_ids[best_match_index]
            student_name = self.known_names[best_match_index]
            
            logger.info(f"✓ Face recognized: {student_name} (confidence: {confidence:.2%})")
            
            # ===== CRITICAL FIX 1: ACTUALLY RUN LIVENESS DETECTION =====
            logger.info(f"🔍 Running liveness detection for {student_name}...")
            
            try:
                is_live, liveness_conf, liveness_details = self.liveness_detector.comprehensive_liveness_check(frame)
                
                blink_verified = liveness_details.get('blink_detected', False)
                eye_contact_verified = liveness_details.get('head_pose_correct', False)
                texture_valid = liveness_details.get('texture_valid', False)
                
                logger.info(f"📊 Liveness results: is_live={is_live}, conf={liveness_conf:.2f}, "
                          f"blink={blink_verified}, eye_contact={eye_contact_verified}, texture={texture_valid}")
                
                # Enforce mandatory blink before proceeding
                if not blink_verified:
                    logger.warning(f"❌ No blink detected for {student_name}")
                    self._log_activity('no_blink_detected', 
                                     f'{student_name} failed - no blink detected')
                    result = ('error', '❌ Please blink to verify you are real', {})
                    self.last_state_result = result
                    return result
                
                # Stricter liveness threshold
                if not is_live or liveness_conf < 0.6:
                    logger.warning(f"❌ Liveness check FAILED for {student_name}: conf={liveness_conf:.2f}")
                    self._log_activity('liveness_failed', 
                                     f'{student_name} failed liveness check (conf={liveness_conf:.2f}, '
                                     f'blink={blink_verified}, eye_contact={eye_contact_verified})')
                    
                    result = ('error', '❌ Liveness verification failed - please blink and look at camera', {})
                    self.last_state_result = result
                    return result
                
                logger.info(f"✅ Liveness check PASSED for {student_name}")
                
            except Exception as e:
                logger.error(f"❌ Liveness detection error: {e}")
                import traceback
                traceback.print_exc()
                result = ('error', 'Liveness verification system error', {})
                self.last_state_result = result
                return result
            
            # ===== CRITICAL FIX 2: ACTUALLY RUN SPOOF DETECTION =====
            logger.info(f"🔍 Running spoof detection for {student_name}...")
            
            try:
                from spoof_detection.ensemble_spoof import check as spoof_check
                from config import Config
                
                top, right, bottom, left = face_location
                face_bbox_xywh = (left, top, right - left, bottom - top)
                
                # Run spoof detection
                spoof_result = spoof_check(frame, face_bbox_xywh, face_encoding)
                
                logger.info(f"📊 Spoof detection results: is_spoof={spoof_result['is_spoof']}, "
                          f"conf={spoof_result['confidence']:.2f}, type={spoof_result['spoof_type']}")
                
                if spoof_result['is_spoof']:
                    spoof_conf = spoof_result['confidence']
                    spoof_type = spoof_result['spoof_type']
                    evidence = spoof_result['evidence']
                    
                    IST = pytz.timezone('Asia/Kolkata')
                    
                    logger.warning(
                        f"🚨 SPOOF DETECTED: {student_name} | "
                        f"Type: {spoof_type} | Conf: {spoof_conf:.2f} | "
                        f"Evidence: {evidence}"
                    )
                    
                    # Log to database
                    self._log_spoof_activity(student_id, student_name, spoof_type, spoof_conf, evidence)
                    
                    # Aggressive blocking with stricter threshold
                    auto_block = getattr(Config, 'AUTO_BLOCK_SPOOF', True)
                    
                    if spoof_conf >= 0.55 or auto_block:
                        result = ('spoof_blocked', f'🚫 Spoofing attempt detected: {spoof_type}', {
                            'student_id': student_id,
                            'student_name': student_name,
                            'spoof_type': spoof_type,
                            'confidence': spoof_conf,
                            'spoof_confidence': spoof_conf,
                            'status': 'blocked',
                            'evidence': evidence
                        })
                    else:
                        result = ('spoof_flagged', f'⚠️ Potential spoofing: {spoof_type}', {
                            'student_id': student_id,
                            'student_name': student_name,
                            'confidence': confidence,
                            'spoof_type': spoof_type,
                            'spoof_confidence': spoof_conf,
                            'status': 'flagged_for_review',
                            'evidence': evidence
                        })
                    
                    self.last_state_result = result
                    return result
                
                logger.info(f"✅ Spoof detection PASSED for {student_name}")
                    
            except Exception as e:
                logger.error(f"❌ Spoof detection error: {e}")
                import traceback
                traceback.print_exc()
                # FIXED: Fail secure - don't allow on error
                result = ('error', 'Security verification system error', {})
                self.last_state_result = result
                return result
            
            # === ALL CHECKS PASSED ===
            logger.info(f"🎉 All security checks passed for {student_name}")
            
            # Multi-frame verification to prevent quick spoofing
            current_ts = time.time()
            self.verification_frames.append({
                'timestamp': current_ts,
                'student_id': student_id,
                'liveness_conf': liveness_conf,
                'spoof_conf': spoof_result['confidence']
            })
            
            cutoff_time = current_ts - 2
            self.verification_frames = [
                frame for frame in self.verification_frames
                if frame['timestamp'] > cutoff_time
            ]
            
            recent_frames = self.verification_frames[-5:]
            consecutive_count = sum(
                1 for frame in recent_frames
                if frame['student_id'] == student_id
                and frame['liveness_conf'] >= 0.6
                and frame['spoof_conf'] < 0.4
            )
            
            if consecutive_count < self.required_consecutive_frames:
                logger.info(f"Verification: {consecutive_count}/{self.required_consecutive_frames} frames for {student_name}")
                result = ('verifying', f'Verifying... ({consecutive_count}/3 frames)', {
                    'student_id': student_id,
                    'progress': consecutive_count
                })
                self.last_state_result = result
                return result
            
            self.verification_frames = []
            
            result = ('verified', None, {
                'student_id': student_id,
                'student_name': student_name,
                'confidence': confidence,
                'blink_verified': blink_verified,  # FIXED: Actual value from liveness detection
                'eye_contact_verified': eye_contact_verified  # FIXED: Actual value from liveness detection
            })
            self.last_state_result = result
            return result
            
        except Exception as e:
            logger.error(f"❌ Error in face recognition: {e}")
            import traceback
            traceback.print_exc()
            result = ('error', f'Recognition error: {str(e)}', {})
            self.last_state_result = result
            return result

    def _log_activity(self, activity_type, message):
        """Log activity to database with error handling"""
        try:
            log = ActivityLog(
                activity_type=activity_type,
                message=message,
                timestamp=get_ist_now(),
                severity='warning' if 'obstructed' in activity_type else 'info'
            )
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error logging activity: {e}")
            db.session.rollback()

    def _log_spoof_activity(self, student_id, student_name, spoof_type, confidence, evidence):
        """Log spoof detection with full details"""
        try:
            log = ActivityLog(
                student_id=student_id,
                name=student_name,
                activity_type='spoof_detected',
                message=f"Spoof detected: {spoof_type} (conf={confidence:.2f})",
                severity='critical' if confidence >= 0.65 else 'warning',
                spoof_type=str(spoof_type) if spoof_type else None,
                spoof_confidence=confidence,
                detection_details=json.dumps(evidence) if evidence else None
            )
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            logger.error(f"Failed to log spoof activity: {e}")
            db.session.rollback()

    def compute_face_hash(self, face_encoding):
        """Compute hash of face encoding for duplicate detection"""
        try:
            encoding_str = ','.join(map(str, face_encoding))
            return hashlib.sha256(encoding_str.encode()).hexdigest()
        except Exception as e:
            logger.error(f"Error computing face hash: {e}")
            return None

    def check_duplicate_face(self, face_encoding):
        """Enhanced duplicate detection"""
        try:
            face_hash = self.compute_face_hash(face_encoding)
            if not face_hash:
                return False, None
            
            # Check hash
            existing = Student.query.filter_by(face_hash=face_hash).first()
            if existing:
                return True, existing
            
            # Check all students with stricter threshold
            all_students = Student.query.filter(Student.face_encoding.isnot(None)).all()
            
            for student in all_students:
                if student.face_encoding is not None:
                    distance = face_recognition.face_distance([student.face_encoding], face_encoding)[0]
                    if distance < 0.35:
                        return True, student
            
            return False, None
            
        except Exception as e:
            logger.error(f"Error checking duplicate face: {e}")
            return False, None

    def enroll_student(self, frame, student):
        """FIXED: Enhanced enrollment with better validation"""
        if not self._ensure_loaded():
            self.load_encodings_from_db()
        
        try:
            if frame is None or frame.size == 0:
                return (False, "Invalid image - please try again", None)
            
            # Validate frame quality
            is_obstructed, msg = self.detect_camera_obstruction(frame)
            if is_obstructed:
                return (False, f"Image quality issue: {msg}", None)
            
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Detect faces with both models for reliability
            face_locations_hog = face_recognition.face_locations(rgb_frame, model='hog')
            
            if len(face_locations_hog) == 0:
                face_locations = face_recognition.face_locations(rgb_frame, model='cnn')
            else:
                face_locations = face_locations_hog

            if len(face_locations) == 0:
                return (False, "❌ No face detected - ensure good lighting and face clearly visible", None)
            
            if len(face_locations) > 1:
                return (False, "❌ Multiple faces detected - only one person should be in frame", None)

            # Validate face quality
            face_location = face_locations[0]
            quality_valid, quality_msg = self.validate_face_quality(frame, face_location)
            if not quality_valid:
                return (False, f"❌ {quality_msg}", None)

            # Generate encoding with high quality
            face_encodings = face_recognition.face_encodings(
                rgb_frame, 
                face_locations,
                num_jitters=10,
                model='large'
            )
            
            if len(face_encodings) == 0:
                return (False, "❌ Could not extract face features - please try again with better lighting", None)
            
            face_encoding = face_encodings[0]
            
            # Validate encoding
            if not isinstance(face_encoding, np.ndarray) or len(face_encoding) != 128:
                return (False, "❌ Invalid face encoding generated", None)
            
            # Check for duplicates
            is_duplicate, existing_student = self.check_duplicate_face(face_encoding)
            if is_duplicate:
                return (False, f"❌ This face is already enrolled for: {existing_student.name} ({existing_student.student_id})", None)
            
            logger.info(f"✓ Face encoding successful for student {getattr(student, 'student_id', 'unknown')}")
            
            return (True, "✓ Face enrollment successful", face_encoding)
            
        except Exception as e:
            logger.error(f"❌ Error enrolling student: {e}")
            import traceback
            traceback.print_exc()
            return (False, f"Enrollment error: {str(e)}", None)

    def recognize_faces(self, frame):
        """Legacy method for backward compatibility"""
        status, message, data = self.recognize_faces_with_state(frame)
        
        if status == 'verified':
            return {
                'matches': [{
                    'student_id': data['student_id'],
                    'name': data['student_name'],
                    'confidence': data['confidence']
                }],
                'total_faces': 1
            }
        else:
            return {'matches': [], 'total_faces': data.get('total_faces', 0)}