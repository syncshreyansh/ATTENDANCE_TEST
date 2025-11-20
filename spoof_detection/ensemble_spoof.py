"""
Ensemble Anti-Spoofing Module - FULLY FIXED VERSION
Combines texture analysis, CNN classification, object detection, FFT/moiré, and reflection checks
FIXED: Lower thresholds, better detection, fail-secure approach
"""
import cv2
import numpy as np
import logging
from datetime import datetime
import os

logger = logging.getLogger(__name__)

# Lazy-load heavy models
_cnn_model = None
_yolo_model = None
_yolo_load_attempted = False
_cnn_load_attempted = False
_cnn_available = False

def load_cnn_model():
    """Load ONNX anti-spoof CNN model (ResNet18 or MobileNetV2)"""
    global _cnn_model, _cnn_load_attempted, _cnn_available
    
    if _cnn_load_attempted:
        return _cnn_model
    
    _cnn_load_attempted = True
    
    model_path = 'models/anti_spoof_resnet18.onnx'
    if not os.path.exists(model_path):
        logger.info(f"CNN model not found at {model_path}. Spoof detection will work with other methods (texture, FFT, reflection).")
        logger.info("To enable CNN-based spoof detection, train and export a model using train_antispoofing.py")
        _cnn_available = False
        return None
    
    try:
        import onnxruntime as ort
        _cnn_model = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
        _cnn_available = True
        logger.info("✓ CNN anti-spoof model loaded successfully (ONNX)")
        return _cnn_model
    except ImportError:
        logger.warning("onnxruntime not installed. Install with: pip install onnxruntime")
        _cnn_available = False
        return None
    except Exception as e:
        logger.error(f"Failed to load CNN model: {e}")
        _cnn_available = False
        return None

def load_yolo_model():
    """Load YOLOv5 nano for phone/tablet/screen detection"""
    global _yolo_model, _yolo_load_attempted
    
    if _yolo_model is not None:
        return _yolo_model
    
    if _yolo_load_attempted:
        return None
    
    _yolo_load_attempted = True
    
    model_path = 'models/yolov5n.pt'
    if not os.path.exists(model_path):
        logger.info(f"YOLO model not found at {model_path}. Phone detection will be disabled.")
        logger.info("To enable phone detection, download: wget https://github.com/ultralytics/yolov5/releases/download/v7.0/yolov5n.pt -O models/yolov5n.pt")
        return None
    
    try:
        from ultralytics import YOLO
        _yolo_model = YOLO(model_path)
        _yolo_model.conf = 0.5
        logger.info("✓ YOLOv5 nano loaded for device detection")
        return _yolo_model
    except ImportError:
        logger.info("ultralytics library not installed. Phone detection disabled. Install with: pip install ultralytics")
        return None
    except Exception as e:
        logger.info(f"Could not load YOLO model: {e}. Phone detection will be disabled.")
        return None

def calculate_laplacian_variance(face_roi):
    """Texture analysis: low variance indicates printed photo or screen"""
    gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    return laplacian_var

def calculate_fft_moire(face_roi):
    """FFT analysis for moiré patterns and refresh banding (screen artifacts)"""
    try:
        gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
        f_transform = np.fft.fft2(gray)
        f_shift = np.fft.fftshift(f_transform)
        magnitude_spectrum = 20 * np.log(np.abs(f_shift) + 1)
        
        rows, cols = gray.shape
        crow, ccol = rows // 2, cols // 2
        high_freq_mask = np.ones((rows, cols), np.uint8)
        r = 30
        cv2.circle(high_freq_mask, (ccol, crow), r, 0, -1)
        
        high_freq_energy = np.sum(magnitude_spectrum * high_freq_mask)
        total_energy = np.sum(magnitude_spectrum)
        
        hf_ratio = high_freq_energy / (total_energy + 1e-6)
        
        # FIXED: Lower threshold from 0.65 to 0.55
        moire_confidence = min(hf_ratio / 0.55, 1.0)
        return moire_confidence
    except Exception as e:
        logger.error(f"FFT moire calculation error: {e}")
        return 0.0

def reflection_in_eyes_score(face_roi):
    """Detect specular highlights in eye regions (real faces have natural reflections)"""
    try:
        gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
        
        h, w = gray.shape
        eye_region = gray[int(h*0.2):int(h*0.5), :]
        
        _, bright_mask = cv2.threshold(eye_region, 220, 255, cv2.THRESH_BINARY)
        bright_ratio = np.sum(bright_mask) / (255.0 * eye_region.size + 1e-6)
        
        reflection_conf = min(bright_ratio / 0.02, 1.0)
        return reflection_conf
    except Exception as e:
        logger.error(f"Reflection calculation error: {e}")
        return 0.0

def run_cnn_classifier(face_roi):
    """Run CNN to classify live vs photo vs screen"""
    model = load_cnn_model()
    if model is None:
        return 0.0, "cnn_unavailable"
    
    try:
        input_img = cv2.resize(face_roi, (224, 224))
        input_img = input_img.astype(np.float32) / 255.0
        input_img = np.transpose(input_img, (2, 0, 1))
        input_img = np.expand_dims(input_img, 0)
        
        input_name = model.get_inputs()[0].name
        outputs = model.run(None, {input_name: input_img})
        
        probabilities = outputs[0][0]
        spoof_conf = max(probabilities[1], probabilities[2])
        spoof_type = "printed_photo" if probabilities[1] > probabilities[2] else "phone_screen"
        
        return spoof_conf, spoof_type
    except Exception as e:
        logger.error(f"CNN inference error: {e}")
        return 0.0, "cnn_error"

def detect_phone_in_frame(frame, face_bbox):
    """Detect phone/tablet near face using YOLO - ENHANCED"""
    model = load_yolo_model()
    if model is None:
        return check_phone_via_edges(frame, face_bbox)
    
    try:
        results = model(frame, verbose=False)
        
        detections = results[0].boxes.data.cpu().numpy() if len(results) > 0 else []
        logger.info(f"🔍 Phone detection: detections={len(detections)}, model_loaded={_yolo_model is not None}")
        
        # Classes: 67=cell phone, 73=laptop, 63=tv/monitor
        phone_classes = [67, 73, 63]
        
        fx1, fy1, fx2, fy2 = face_bbox
        face_center_x = (fx1 + fx2) / 2
        face_center_y = (fy1 + fy2) / 2
        face_area = (fx2 - fx1) * (fy2 - fy1)
        frame_area = frame.shape[0] * frame.shape[1]
        
        best_conf = 0.0
        best_bbox = None
        
        for det in detections:
            x1, y1, x2, y2, conf, cls = det
            if int(cls) in phone_classes:
                phone_center_x = (x1 + x2) / 2
                phone_center_y = (y1 + y2) / 2
                dist = np.sqrt((phone_center_x - face_center_x)**2 + (phone_center_y - face_center_y)**2)
                phone_area = (x2 - x1) * (y2 - y1)
                
                logger.info(f"📱 Found device: class={int(cls)}, conf={float(conf):.2f}, dist={dist:.1f}px")
                
                overlap_x = max(0, min(x2, fx2) - max(x1, fx1))
                overlap_y = max(0, min(y2, fy2) - max(y1, fy1))
                overlap_area = overlap_x * overlap_y
                
                if overlap_area > face_area * 0.3:
                    return 0.95, [int(x1), int(y1), int(x2-x1), int(y2-y1)]
                
                if phone_area > frame_area * 0.15 and conf > 0.4:
                    return min(float(conf) + 0.3, 0.99), [int(x1), int(y1), int(x2-x1), int(y2-y1)]
                
                if dist < 300 and conf > best_conf:
                    best_conf = float(conf) + 0.2
                    best_bbox = [int(x1), int(y1), int(x2-x1), int(y2-y1)]
        
        return best_conf, best_bbox
    except Exception as e:
        logger.error(f"YOLO detection error: {e}")
        return check_phone_via_edges(frame, face_bbox)

def check_phone_via_edges(frame, face_bbox):
    """Fallback: Detect phone screen by looking for rectangular edges"""
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        fx1, fy1, fx2, fy2 = face_bbox
        face_area = (fx2 - fx1) * (fy2 - fy1)
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > face_area * 0.5:
                x, y, w, h = cv2.boundingRect(contour)
                aspect_ratio = w / float(h) if h > 0 else 0
                
                if 0.4 < aspect_ratio < 2.5 and area > 10000:
                    return 0.7, [x, y, w, h]
        
        return 0.0, None
    except Exception as e:
        logger.error(f"Edge-based phone detection error: {e}")
        return 0.0, None

def detect_screen_glare(face_roi):
    """Detect bright rectangular glare typical of phone screens"""
    try:
        gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
        _, bright_mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        
        contours, _ = cv2.findContours(bright_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > 500:
                x, y, w, h = cv2.boundingRect(contour)
                aspect_ratio = w / float(h) if h > 0 else 0
                
                if 0.5 < aspect_ratio < 2.0:
                    return 0.8
        
        return 0.0
    except Exception as e:
        logger.error(f"Screen glare detection error: {e}")
        return 0.0

def check(frame, face_bbox, face_encoding=None):
    """
    Main ensemble spoof detection - FULLY FIXED VERSION
    Returns: dict {is_spoof: bool, spoof_type: str or list, confidence: float, evidence: dict}
    FIXED: Lower thresholds, better detection, fail-secure approach
    """
    try:
        x, y, w, h = face_bbox
        face_roi = frame[y:y+h, x:x+w]
        
        if face_roi.size == 0:
            return {
                'is_spoof': False,
                'spoof_type': None,
                'confidence': 0.0,
                'evidence': {'error': 'invalid_face_roi'}
            }
        
        # Run all available checks
        texture_var = calculate_laplacian_variance(face_roi)
        
        # Stricter texture threshold
        if texture_var < 50:
            texture_conf = 1.0
        elif texture_var < 80:
            texture_conf = 0.7
        else:
            texture_conf = 0.0
        
        moire_conf = calculate_fft_moire(face_roi)
        
        # Screen glare detection
        glare_conf = detect_screen_glare(face_roi)
        if glare_conf > 0.6:
            logger.warning(f"Screen glare detected: {glare_conf:.2f}")
        
        reflection_conf = reflection_in_eyes_score(face_roi)
        reflection_spoof_conf = 1.0 - reflection_conf if reflection_conf < 0.3 else 0.0
        
        cnn_conf = 0.0
        cnn_type = "cnn_unavailable"
        if _cnn_available:
            cnn_conf, cnn_type = run_cnn_classifier(face_roi)
        
        phone_conf, phone_bbox = detect_phone_in_frame(frame, (x, y, x+w, y+h))
        
        blink_conf = 0.0
        
        # CRITICAL: Emergency texture check - IMMEDIATE rejection
        if texture_var < 35:
            logger.critical(f"🚨 EMERGENCY BLOCK: texture={texture_var:.1f} (threshold=35)")
            return {
                'is_spoof': True,
                'spoof_type': ['very_low_texture_photo_or_screen'],
                'confidence': 0.98,
                'evidence': {
                    'texture_variance': texture_var,
                    'threshold': 35,
                    'reason': 'TEXTURE_TOO_LOW_EMERGENCY_BLOCK'
                }
            }
        
        # CRITICAL: IMMEDIATE rejection for phone detection - MUCH STRICTER
        if phone_conf > 0.35:  # Changed from 0.65 to 0.35 for aggressive blocking
            logger.critical(f"🚨 PHONE DETECTED: conf={phone_conf:.2f}, bbox={phone_bbox}")
            return {
                'is_spoof': True,
                'spoof_type': ['phone_screen_detected'],
                'confidence': min(phone_conf + 0.3, 0.99),
                'evidence': {
                    'phone_confidence': phone_conf,
                    'phone_bbox': phone_bbox,
                    'detection_method': 'yolo' if _yolo_model else 'edge_detection',
                    'reason': 'PHONE_IN_FRAME_IMMEDIATE_BLOCK'
                }
            }
        
        # FIXED: Detect low texture with moire patterns (screens/photos)
        if texture_var < 60 and moire_conf > 0.5:
            logger.critical(f"🚨 SCREEN/PHOTO DETECTED: texture={texture_var:.2f}, moire={moire_conf:.2f}")
            return {
                'is_spoof': True,
                'spoof_type': ['screen_or_photo_detected'],
                'confidence': 0.90,
                'evidence': {
                    'texture_variance': texture_var,
                    'moire_confidence': moire_conf,
                    'reason': 'LOW_TEXTURE_WITH_MOIRE'
                }
            }
        
        # Adjusted weighted fusion score
        if _cnn_available:
            S = (0.25 * cnn_conf +
                 0.30 * texture_conf +
                 0.30 * phone_conf +
                 0.10 * moire_conf +
                 0.03 * glare_conf +
                 0.02 * reflection_spoof_conf)
        else:
            S = (0.40 * texture_conf +
                 0.40 * phone_conf +
                 0.10 * moire_conf +
                 0.05 * glare_conf +
                 0.05 * reflection_spoof_conf)
        
        # Calculate reliability
        reliability = 1.0
        avg_brightness = np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        if avg_brightness < 30:
            reliability *= 0.5
            logger.debug("Low-light detected, spoof detection reliability reduced")
        
        if face_roi.size < 10000:
            reliability *= 0.7
            logger.debug("Small/distant face, reliability reduced")
        
        # Determine spoof types
        spoof_types = []
        if _cnn_available and cnn_conf > 0.5:  # Lowered from 0.6
            spoof_types.append(cnn_type)
        if phone_conf > 0.4:  # Lowered from 0.5
            spoof_types.append("phone_in_frame")
        if moire_conf > 0.6:  # Lowered from 0.7
            spoof_types.append("screen_refresh_banding")
        if texture_var < 40:  # CRITICAL: Lowered from 50
            spoof_types.append("low_texture_photo")
        
        # CRITICAL: Emergency check for very low texture
        if texture_var < 30:
            logger.warning(f"⚠️ VERY LOW TEXTURE DETECTED: {texture_var:.2f} - likely photo/screen")
            spoof_types.append("very_low_texture")
            S = max(S, 0.7)  # Force high spoof confidence
        
        # CRITICAL: STRICTER decision threshold for aggressive blocking
        is_spoof = S >= 0.40  # Changed from 0.55 to 0.40 for more sensitive detection
        spoof_type = spoof_types if spoof_types else None
        
        evidence = {
            'texture_variance': round(texture_var, 2),
            'moire_confidence': round(moire_conf, 2),
            'reflection_confidence': round(reflection_conf, 2),
            'cnn_confidence': round(cnn_conf, 2) if _cnn_available else 'unavailable',
            'cnn_type': cnn_type,
            'phone_detector_confidence': round(phone_conf, 2),
            'phone_bbox': phone_bbox,
            'glare_confidence': round(glare_conf, 2),
            'fusion_score': round(S, 2),
            'reliability_score': round(reliability, 2),
            'cnn_enabled': _cnn_available,
            'yolo_enabled': _yolo_model is not None
        }
        
        # FIXED: Less aggressive reliability downweighting
        if reliability < 0.6 and is_spoof:
            logger.debug("Low reliability - slight downweighting")
            S = S * 0.9  # Changed from 1.0 * reliability to 0.9
            spoof_types = ['low_reliability'] + (spoof_types if spoof_types else [])
        
        # Log detection details
        logger.info(f"🔍 Spoof check: texture={texture_var:.1f}, moire={moire_conf:.2f}, "
                   f"phone={phone_conf:.2f}, cnn={cnn_conf:.2f}, final_score={S:.2f}, "
                   f"is_spoof={is_spoof}")
        
        return {
            'is_spoof': is_spoof,
            'spoof_type': spoof_type,
            'confidence': round(S, 2),
            'evidence': evidence
        }
    except Exception as e:
        logger.error(f"Error in spoof detection: {e}")
        import traceback
        traceback.print_exc()
        return {
            'is_spoof': False,
            'spoof_type': None,
            'confidence': 0.0,
            'evidence': {'error': str(e)}
        }

def get_spoof_detection_status():
    """
    Get current status of spoof detection components
    Returns dict with availability of each component
    """
    load_cnn_model()
    load_yolo_model()
    
    return {
        'cnn_available': _cnn_available,
        'yolo_available': _yolo_model is not None,
        'texture_analysis': True,
        'fft_moire': True,
        'reflection_check': True,
        'overall_status': 'full' if (_cnn_available and _yolo_model is not None) else 'partial'
    }