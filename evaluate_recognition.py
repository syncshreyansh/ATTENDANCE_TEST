#!/usr/bin/env python3
"""
Recognition Accuracy Evaluation Script
Tests the face recognition system against a test dataset
"""

import os
import cv2
from face_recognition_service import FaceRecognitionService
from models import db, Student
from main import create_app
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RecognitionEvaluator:
    def __init__(self):
        self.face_service = FaceRecognitionService()
        self.test_images_dir = 'test_images'
        
    def load_test_images(self):
        """Load test images organized by student_id folders"""
        test_data = []
        
        if not os.path.exists(self.test_images_dir):
            logger.warning(f"Test images directory not found: {self.test_images_dir}")
            logger.info("Creating directory structure for test images...")
            os.makedirs(self.test_images_dir)
            logger.info(f"Please add test images in: {self.test_images_dir}/<student_id>/*.jpg")
            return test_data
        
        for student_folder in os.listdir(self.test_images_dir):
            folder_path = os.path.join(self.test_images_dir, student_folder)
            
            if not os.path.isdir(folder_path):
                continue
            
            student_id = student_folder
            
            for image_file in os.listdir(folder_path):
                if image_file.lower().endswith(('.jpg', '.jpeg', '.png')):
                    image_path = os.path.join(folder_path, image_file)
                    test_data.append({
                        'student_id': student_id,
                        'image_path': image_path
                    })
        
        return test_data
    
    def evaluate(self):
        """Run evaluation on test dataset"""
        logger.info("=" * 60)
        logger.info("STARTING FACE RECOGNITION ACCURACY EVALUATION")
        logger.info("=" * 60)
        
        # Load face encodings from database
        try:
            self.face_service.load_encodings_from_db()
            logger.info(f"✓ Loaded {len(self.face_service.known_ids)} face encodings from database")
        except Exception as e:
            logger.error(f"✗ Failed to load face encodings: {e}")
            return
        
        if len(self.face_service.known_ids) == 0:
            logger.warning("No enrolled students found in database!")
            logger.info("Please enroll students first using the web interface")
            return
        
        # Load test images
        test_data = self.load_test_images()
        
        if len(test_data) == 0:
            logger.warning("No test images found!")
            logger.info(f"Please add test images to: {self.test_images_dir}/<student_id>/*.jpg")
            logger.info("Example structure:")
            logger.info("  test_images/")
            logger.info("    101/")
            logger.info("      photo1.jpg")
            logger.info("      photo2.jpg")
            logger.info("    102/")
            logger.info("      photo1.jpg")
            return
        
        logger.info(f"✓ Found {len(test_data)} test images")
        logger.info("-" * 60)
        
        # Evaluate each test image
        correct_predictions = 0
        total_predictions = 0
        results_by_student = {}
        
        for idx, test_item in enumerate(test_data, 1):
            student_id = test_item['student_id']
            image_path = test_item['image_path']
            
            # Read image
            frame = cv2.imread(image_path)
            
            if frame is None:
                logger.warning(f"✗ Could not read image: {image_path}")
                continue
            
            # Recognize faces
            recognition_result = self.face_service.recognize_faces(frame)
            matches = recognition_result['matches']
            
            # Check if prediction is correct
            predicted_correctly = False
            predicted_id = None
            confidence = 0.0
            
            if len(matches) > 0:
                # Get the student object to compare student_id
                predicted_student = Student.query.get(matches[0]['student_id'])
                if predicted_student:
                    predicted_id = predicted_student.student_id
                    confidence = matches[0]['confidence']
                    
                    if predicted_id == student_id:
                        predicted_correctly = True
                        correct_predictions += 1
            
            total_predictions += 1
            
            # Track results by student
            if student_id not in results_by_student:
                results_by_student[student_id] = {
                    'correct': 0,
                    'total': 0
                }
            
            results_by_student[student_id]['total'] += 1
            if predicted_correctly:
                results_by_student[student_id]['correct'] += 1
            
            # Log result
            status = "✓" if predicted_correctly else "✗"
            logger.info(f"{status} Test {idx}/{len(test_data)}: "
                       f"Expected: {student_id}, "
                       f"Predicted: {predicted_id or 'None'}, "
                       f"Confidence: {confidence:.2%}")
        
        # Print summary
        logger.info("=" * 60)
        logger.info("EVALUATION SUMMARY")
        logger.info("=" * 60)
        
        if total_predictions > 0:
            overall_accuracy = (correct_predictions / total_predictions) * 100
            logger.info(f"Overall Accuracy: {correct_predictions}/{total_predictions} = {overall_accuracy:.2f}%")
            logger.info("-" * 60)
            
            # Per-student accuracy
            logger.info("Per-Student Accuracy:")
            for student_id, results in sorted(results_by_student.items()):
                student_accuracy = (results['correct'] / results['total']) * 100
                logger.info(f"  Student {student_id}: {results['correct']}/{results['total']} = {student_accuracy:.2f}%")
        else:
            logger.warning("No predictions were made!")
        
        logger.info("=" * 60)

def main():
    """Main function"""
    # Create Flask app context
    app = create_app()
    
    with app.app_context():
        evaluator = RecognitionEvaluator()
        evaluator.evaluate()

if __name__ == '__main__':
    main()