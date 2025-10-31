# Enhanced face recognition with liveness and duplicate detection
import cv2
import face_recognition
import dlib
import numpy as np
from scipy.spatial import distance as dist
import logging
import hashlib
from models import Student, db, ActivityLog, get_ist_now

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FaceRecognitionService:
    def __init__(self):
        self.detector = dlib.get_frontal_face_detector()
        self.predictor = dlib.shape_predictor("shape_predictor_68_face_landmarks.dat")
        self.known_encodings = []
        self.known_names = []
        self.known_ids = []
        self.loaded = False
        
        # Eye contact detection thresholds
        self.HEAD_POSE_THRESHOLD = 15  # degrees

    def _ensure_loaded(self):
        """Lazy loading of face encodings"""
        if not self.loaded:
            try:
                self.load_encodings_from_db()
            except Exception as e:
                logger.error(f"Error lazily loading faces: {e}")

    def load_encodings_from_db(self):
        """Load all face encodings from database into memory"""
        logger.info("Loading face encodings from database...")
        try:
            students = Student.query.filter_by(status='active').all()
            self.known_encodings = []
            self.known_names = []
            self.known_ids = []
            
            for student in students:
                if student.face_encoding is not None:
                    self.known_encodings.append(student.face_encoding)
                    self.known_names.append(student.name)
                    self.known_ids.append(student.id)
            
            self.loaded = True
            logger.info(f"Successfully loaded {len(self.known_ids)} face encodings")
        except Exception as e:
            logger.error(f"Error loading face encodings from database: {e}")
            raise

    def load_known_faces(self):
        """Alias for load_encodings_from_db for backward compatibility"""
        self.load_encodings_from_db()

    def calculate_ear(self, eye):
        """Calculate Eye Aspect Ratio for blink detection"""
        A = dist.euclidean(eye[1], eye[5])
        B = dist.euclidean(eye[2], eye[4])
        C = dist.euclidean(eye[0], eye[3])
        ear = (A + B) / (2.0 * C)
        return ear

    def detect_blink(self, frame):
        """Detect blink for liveness verification"""
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.detector(gray)
            
            for face in faces:
                landmarks = self.predictor(gray, face)
                landmarks = np.array([(p.x, p.y) for p in landmarks.parts()])
                
                left_eye = landmarks[42:48]
                right_eye = landmarks[36:42]
                
                left_ear = self.calculate_ear(left_eye)
                right_ear = self.calculate_ear(right_eye)
                ear = (left_ear + right_ear) / 2.0
                
                if ear < 0.25:
                    return True
            return False
        except Exception as e:
            logger.error(f"Error in blink detection: {e}")
            return False

    def estimate_head_pose(self, landmarks, frame_shape):
        """
        Estimate head pose to verify eye contact
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
        except Exception as e:
            logger.error(f"Error in head pose estimation: {e}")
            return 0, 0, 0

    def check_eye_contact(self, frame):
        """
        Check if person is looking at camera (eye contact)
        Returns: (has_eye_contact: bool, angles: tuple)
        """
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.detector(gray)
            
            if len(faces) == 0:
                return False, (0, 0, 0)
            
            face = faces[0]
            landmarks = self.predictor(gray, face)
            landmarks_np = np.array([(p.x, p.y) for p in landmarks.parts()])
            
            # Get head pose
            pitch, yaw, roll = self.estimate_head_pose(landmarks_np, frame.shape)
            
            # Check if looking at camera (within threshold)
            has_eye_contact = (abs(pitch) < self.HEAD_POSE_THRESHOLD and 
                             abs(yaw) < self.HEAD_POSE_THRESHOLD)
            
            return has_eye_contact, (pitch, yaw, roll)
            
        except Exception as e:
            logger.error(f"Error checking eye contact: {e}")
            return False, (0, 0, 0)

    def detect_texture_quality(self, face_roi):
        """
        Analyze texture to detect if it's a real face or a photo/screen
        Returns texture quality score
        """
        try:
            gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            return laplacian_var
        except Exception as e:
            logger.error(f"Error in texture analysis: {e}")
            return 0

    def detect_spoofing(self, frame, face_location):
        """
        Detect if someone is using a phone/photo (spoofing attempt)
        Returns: (is_spoof: bool, confidence: float, reason: str)
        """
        try:
            top, right, bottom, left = face_location
            face_roi = frame[top:bottom, left:right]
            
            if face_roi.size == 0:
                return False, 0.0, "No face ROI"
            
            # Check texture quality
            texture = self.detect_texture_quality(face_roi)
            
            # Low texture = likely a photo/screen
            if texture < 100:
                return True, 1.0 - (texture / 100), "Low texture quality - possible photo/screen"
            
            # Check for screen glare patterns (simplified)
            hsv = cv2.cvtColor(face_roi, cv2.COLOR_BGR2HSV)
            v_channel = hsv[:, :, 2]
            bright_pixels = np.sum(v_channel > 200)
            total_pixels = v_channel.size
            brightness_ratio = bright_pixels / total_pixels
            
            if brightness_ratio > 0.3:
                return True, brightness_ratio, "Excessive brightness - possible screen"
            
            return False, 0.0, "Liveness check passed"
            
        except Exception as e:
            logger.error(f"Error in spoofing detection: {e}")
            return False, 0.0, f"Error: {str(e)}"

    def compute_face_hash(self, face_encoding):
        """
        Compute a hash of face encoding for duplicate detection
        """
        # Convert to string and hash
        encoding_str = ','.join(map(str, face_encoding))
        return hashlib.sha256(encoding_str.encode()).hexdigest()

    def check_duplicate_face(self, face_encoding):
        """
        Check if this face encoding already exists in database
        Returns: (is_duplicate: bool, existing_student: Student or None)
        """
        try:
            face_hash = self.compute_face_hash(face_encoding)
            
            # Check by hash first (fast)
            existing = Student.query.filter_by(face_hash=face_hash).first()
            if existing:
                return True, existing
            
            # Check by similarity (more accurate but slower)
            all_students = Student.query.filter(Student.face_encoding.isnot(None)).all()
            
            for student in all_students:
                if student.face_encoding is not None:
                    distance = face_recognition.face_distance([student.face_encoding], face_encoding)[0]
                    if distance < 0.4:  # Very similar face
                        return True, student
            
            return False, None
            
        except Exception as e:
            logger.error(f"Error checking duplicate face: {e}")
            return False, None

    def recognize_faces(self, frame):
        """Recognize faces in the given frame"""
        self._ensure_loaded()
        
        try:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            face_locations = face_recognition.face_locations(rgb_frame)
            face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
            
            results = []
            
            for idx, face_encoding in enumerate(face_encodings):
                if len(self.known_encodings) == 0:
                    logger.warning("No known faces in database")
                    break
                
                # Check for spoofing
                is_spoof, spoof_confidence, spoof_reason = self.detect_spoofing(frame, face_locations[idx])
                if is_spoof:
                    logger.warning(f"Spoofing detected: {spoof_reason}")
                    # Log suspicious activity
                    log = ActivityLog(
                        activity_type='proxy_attempt',
                        message=f"Spoofing detected: {spoof_reason}",
                        severity='critical'
                    )
                    db.session.add(log)
                    db.session.commit()
                    continue
                
                matches = face_recognition.compare_faces(
                    self.known_encodings, 
                    face_encoding,
                    tolerance=0.6
                )
                face_distances = face_recognition.face_distance(
                    self.known_encodings, 
                    face_encoding
                )
                
                if len(face_distances) > 0:
                    best_match_index = np.argmin(face_distances)
                    
                    if matches[best_match_index] and face_distances[best_match_index] < 0.6:
                        results.append({
                            'student_id': self.known_ids[best_match_index],
                            'name': self.known_names[best_match_index],
                            'confidence': 1 - face_distances[best_match_index]
                        })
            
            return {'matches': results, 'total_faces': len(face_locations)}
            
        except Exception as e:
            logger.error(f"Error in face recognition: {e}")
            return {'matches': [], 'total_faces': 0}

    def enroll_student(self, frame, student):
        """
        Enroll a new student's face with duplicate detection
        Returns (success, message, face_encoding)
        """
        self._ensure_loaded()
        
        try:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Try HOG model first (faster)
            face_locations = face_recognition.face_locations(rgb_frame, model='hog')
            
            # If no face found, try CNN model (more accurate)
            if len(face_locations) == 0:
                logger.info("HOG model found 0 faces, trying CNN model...")
                face_locations = face_recognition.face_locations(rgb_frame, model='cnn')

            # Validate face detection results
            if len(face_locations) == 0:
                return (False, "No face found in the image. Please try again with better lighting or a clearer photo.", None)
            
            if len(face_locations) > 1:
                return (False, "Multiple faces found. Please ensure only one person is in the photo.", None)

            # Compute face encoding
            face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
            
            if len(face_encodings) == 0:
                return (False, "Could not compute face encoding. Please try again.", None)
            
            face_encoding = face_encodings[0]
            
            # Check for duplicate face
            is_duplicate, existing_student = self.check_duplicate_face(face_encoding)
            if is_duplicate:
                return (False, f"This face is already enrolled for student: {existing_student.name} ({existing_student.student_id})", None)
            
            logger.info(f"Face encoding successfully created for student {getattr(student, 'student_id', 'unknown')}")
            
            return (True, "Face encoding successful.", face_encoding)
            
        except Exception as e:
            logger.error(f"Error enrolling student: {e}")
            return (False, f"Enrollment error: {str(e)}", None)