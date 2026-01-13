"""
Facial Mouse Controller
Controls mouse cursor using facial movements
Author: AI Assistant
Date: 2023
"""

import cv2
import numpy as np
import pyautogui
import dlib
import time
from enum import Enum
import tkinter as tk
from tkinter import ttk
import threading
import queue
from collections import deque
import argparse
import json
import os

# Initialize PyAutoGUI safety
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.01

class ClickAction(Enum):
    """Types of click actions"""
    LEFT_CLICK = 1
    RIGHT_CLICK = 2
    DOUBLE_CLICK = 3
    DRAG_START = 4
    DRAG_END = 5

class FacialMouseController:
    """Main controller class for facial mouse control"""
    
    def __init__(self, config_path=None):
        """Initialize the facial mouse controller"""
        self.running = False
        self.cap = None
        self.detector = None
        self.predictor = None
        self.screen_width, self.screen_height = pyautogui.size()
        
        # Configuration with defaults
        self.config = {
            'smoothing_factor': 0.5,  # Cursor smoothing (0-1)
            'cursor_speed': 1.5,       # Cursor movement speed multiplier
            'click_threshold': 0.25,   # Eye closure threshold for clicking
            'click_duration': 15,      # Frames eye must be closed for click
            'calibrated': False,
            'face_region': None,       # Normalized face bounding box
            'enable_left_click': True,
            'enable_right_click': True,
            'enable_dragging': True,
            'show_visual_feedback': True,
            'use_relative_movement': True
        }
        
        # Load configuration if provided
        if config_path and os.path.exists(config_path):
            self.load_config(config_path)
        
        # State variables
        self.eye_closed_frames = {'left': 0, 'right': 0}
        self.prev_cursor_pos = None
        self.cursor_pos_smoothed = None
        self.is_dragging = False
        self.calibration_points = []
        self.calibration_data = []
        self.landmark_history = deque(maxlen=10)
        
        # Initialize face detector
        self._initialize_face_detector()
        
    def _initialize_face_detector(self):
        """Initialize the facial landmark detector"""
        try:
            # Try to load dlib's pre-trained face detector and shape predictor
            self.detector = dlib.get_frontal_face_detector()
            
            # Try to download or use local shape predictor
            predictor_path = "shape_predictor_68_face_landmarks.dat"
            
            # Check if predictor file exists, otherwise provide instructions
            if os.path.exists(predictor_path):
                self.predictor = dlib.shape_predictor(predictor_path)
            else:
                print("Warning: Face landmark predictor file not found.")
                print("Please download 'shape_predictor_68_face_landmarks.dat' from:")
                print("http://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2")
                print("Extract it and place in the same directory as this script.")
                # We'll use a fallback method using simple face detection
                self.predictor = None
                
        except Exception as e:
            print(f"Error initializing face detector: {e}")
            self.predictor = None
    
    def load_config(self, config_path):
        """Load configuration from JSON file"""
        try:
            with open(config_path, 'r') as f:
                loaded_config = json.load(f)
                self.config.update(loaded_config)
                print(f"Configuration loaded from {config_path}")
        except Exception as e:
            print(f"Error loading config: {e}")
    
    def save_config(self, config_path):
        """Save configuration to JSON file"""
        try:
            with open(config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
                print(f"Configuration saved to {config_path}")
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def start_camera(self, camera_index=0):
        """Start the camera capture"""
        try:
            self.cap = cv2.VideoCapture(camera_index)
            if not self.cap.isOpened():
                raise Exception("Could not open camera")
            
            # Set camera properties for better performance
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            
            print("Camera started successfully")
            return True
        except Exception as e:
            print(f"Error starting camera: {e}")
            return False
    
    def _calculate_eye_aspect_ratio(self, eye_points):
        """Calculate eye aspect ratio to detect blinks"""
        # Vertical distances
        A = np.linalg.norm(eye_points[1] - eye_points[5])
        B = np.linalg.norm(eye_points[2] - eye_points[4])
        
        # Horizontal distance
        C = np.linalg.norm(eye_points[0] - eye_points[3])
        
        # Eye aspect ratio
        ear = (A + B) / (2.0 * C)
        return ear
    
    def _get_face_landmarks(self, frame):
        """Detect facial landmarks in the frame"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.detector(gray)
        
        if len(faces) == 0:
            return None
        
        face = faces[0]
        
        if self.predictor:
            landmarks = self.predictor(gray, face)
            landmarks_np = np.array([[p.x, p.y] for p in landmarks.parts()])
            return landmarks_np
        else:
            # Fallback: simple face detection without landmarks
            x, y, w, h = face.left(), face.top(), face.width(), face.height()
            return np.array([
                [x, y],  # Top-left of face
                [x + w, y],  # Top-right
                [x + w, y + h],  # Bottom-right
                [x, y + h]  # Bottom-left
            ])
    
    def _map_face_to_screen(self, face_center, face_size, frame_shape):
        """Map face position to screen coordinates"""
        frame_height, frame_width = frame_shape[:2]
        
        # Normalize face position (0 to 1)
        norm_x = face_center[0] / frame_width
        norm_y = face_center[1] / frame_height
        
        # Invert Y axis (camera vs screen coordinates)
        norm_y = 1 - norm_y
        
        # Apply calibration if available
        if self.config['calibrated'] and self.config['face_region']:
            cal_x1, cal_y1, cal_x2, cal_y2 = self.config['face_region']
            # Scale normalized coordinates to calibrated region
            norm_x = (norm_x - cal_x1) / (cal_x2 - cal_x1)
            norm_y = (norm_y - cal_y1) / (cal_y2 - cal_y1)
            
            # Clamp to [0, 1]
            norm_x = max(0, min(1, norm_x))
            norm_y = max(0, min(1, norm_y))
        
        # Map to screen coordinates
        screen_x = int(norm_x * self.screen_width)
        screen_y = int(norm_y * self.screen_height)
        
        return screen_x, screen_y
    
    def _detect_clicks(self, landmarks):
        """Detect eye blinks for click actions"""
        click_action = None
        
        if landmarks is not None and len(landmarks) >= 68:
            # Left eye landmarks (indices 36-41)
            left_eye = landmarks[36:42]
            # Right eye landmarks (indices 42-47)
            right_eye = landmarks[42:48]
            
            # Calculate eye aspect ratios
            left_ear = self._calculate_eye_aspect_ratio(left_eye)
            right_ear = self._calculate_eye_aspect_ratio(right_eye)
            
            # Check for eye closure
            if left_ear < self.config['click_threshold']:
                self.eye_closed_frames['left'] += 1
            else:
                self.eye_closed_frames['left'] = 0
            
            if right_ear < self.config['click_threshold']:
                self.eye_closed_frames['right'] += 1
            else:
                self.eye_closed_frames['right'] = 0
            
            # Detect click actions
            if self.config['enable_left_click']:
                if self.eye_closed_frames['left'] >= self.config['click_duration']:
                    if self.eye_closed_frames['right'] < self.config['click_duration']:
                        click_action = ClickAction.LEFT_CLICK
                        self.eye_closed_frames['left'] = 0
            
            if self.config['enable_right_click']:
                if self.eye_closed_frames['right'] >= self.config['click_duration']:
                    if self.eye_closed_frames['left'] < self.config['click_duration']:
                        click_action = ClickAction.RIGHT_CLICK
                        self.eye_closed_frames['right'] = 0
            
            # Detect double click (both eyes closed)
            if (self.eye_closed_frames['left'] >= self.config['click_duration'] and 
                self.eye_closed_frames['right'] >= self.config['click_duration']):
                click_action = ClickAction.DOUBLE_CLICK
                self.eye_closed_frames['left'] = 0
                self.eye_closed_frames['right'] = 0
            
            # Detect drag start/stop (wink left then right)
            if self.config['enable_dragging']:
                if (self.eye_closed_frames['left'] >= self.config['click_duration'] and 
                    self.eye_closed_frames['right'] < self.config['click_duration'] and
                    not self.is_dragging):
                    click_action = ClickAction.DRAG_START
                    self.is_dragging = True
                elif (self.eye_closed_frames['right'] >= self.config['click_duration'] and 
                      self.eye_closed_frames['left'] < self.config['click_duration'] and
                      self.is_dragging):
                    click_action = ClickAction.DRAG_END
                    self.is_dragging = False
        
        return click_action
    
    def _execute_click_action(self, action):
        """Execute the detected click action"""
        if action == ClickAction.LEFT_CLICK:
            pyautogui.click()
            print("Left click")
        elif action == ClickAction.RIGHT_CLICK:
            pyautogui.rightClick()
            print("Right click")
        elif action == ClickAction.DOUBLE_CLICK:
            pyautogui.doubleClick()
            print("Double click")
        elif action == ClickAction.DRAG_START:
            pyautogui.mouseDown()
            print("Drag start")
        elif action == ClickAction.DRAG_END:
            pyautogui.mouseUp()
            print("Drag end")
    
    def calibrate(self, frame):
        """Calibrate the face tracking region"""
        height, width = frame.shape[:2]
        
        # Detect face
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.detector(gray)
        
        if len(faces) == 0:
            return False
        
        face = faces[0]
        
        # Get face bounding box
        x, y, w, h = face.left(), face.top(), face.width(), face.height()
        
        # Add padding
        padding = 0.3
        x1 = max(0, x - int(w * padding))
        y1 = max(0, y - int(h * padding))
        x2 = min(width, x + w + int(w * padding))
        y2 = min(height, y + h + int(h * padding))
        
        # Convert to normalized coordinates
        norm_x1 = x1 / width
        norm_y1 = y1 / height
        norm_x2 = x2 / width
        norm_y2 = y2 / height
        
        self.config['face_region'] = [norm_x1, norm_y1, norm_x2, norm_y2]
        self.config['calibrated'] = True
        
        # Save calibration
        self.save_config("calibration.json")
        
        print(f"Calibration complete: {self.config['face_region']}")
        return True
    
    def process_frame(self, frame):
        """Process a single frame and control cursor"""
        if not self.running:
            return frame
        
        # Get facial landmarks
        landmarks = self._get_face_landmarks(frame)
        
        if landmarks is not None:
            # Calculate face center
            if len(landmarks) >= 68:
                # Use nose tip (landmark 30) for cursor control
                face_center = landmarks[30]
            else:
                # Use center of face bounding box
                face_center = np.mean(landmarks, axis=0)
            
            # Add to history for smoothing
            self.landmark_history.append(face_center)
            
            # Apply temporal smoothing
            if len(self.landmark_history) > 0:
                smoothed_center = np.mean(self.landmark_history, axis=0)
            else:
                smoothed_center = face_center
            
            # Map to screen coordinates
            cursor_x, cursor_y = self._map_face_to_screen(
                smoothed_center, 
                np.linalg.norm(landmarks[0] - landmarks[1]) if len(landmarks) >= 2 else 50,
                frame.shape
            )
            
            # Initialize cursor_x_smooth and cursor_y_smooth
            cursor_x_smooth = cursor_x
            cursor_y_smooth = cursor_y
            
            # Apply smoothing to cursor movement
            if self.cursor_pos_smoothed is None:
                self.cursor_pos_smoothed = (cursor_x, cursor_y)
                cursor_x_smooth, cursor_y_smooth = cursor_x, cursor_y
            else:
                prev_x, prev_y = self.cursor_pos_smoothed
                smooth = self.config['smoothing_factor']
                cursor_x_smooth = int(prev_x * (1 - smooth) + cursor_x * smooth)
                cursor_y_smooth = int(prev_y * (1 - smooth) + cursor_y * smooth)
                self.cursor_pos_smoothed = (cursor_x_smooth, cursor_y_smooth)
            
            # Move cursor
            if self.config['use_relative_movement']:
                # Relative movement (better for continuous control)
                if self.prev_cursor_pos is not None:
                    dx = cursor_x_smooth - self.prev_cursor_pos[0]
                    dy = cursor_y_smooth - self.prev_cursor_pos[1]
                    pyautogui.moveRel(
                        dx * self.config['cursor_speed'],
                        dy * self.config['cursor_speed'],
                        duration=0.01
                    )
            else:
                # Absolute movement
                pyautogui.moveTo(cursor_x_smooth, cursor_y_smooth, duration=0.01)
            
            self.prev_cursor_pos = (cursor_x_smooth, cursor_y_smooth)
            
            # Detect and execute click actions
            click_action = self._detect_clicks(landmarks)
            if click_action:
                self._execute_click_action(click_action)
            
            # Draw visual feedback
            if self.config['show_visual_feedback']:
                frame = self._draw_visual_feedback(frame, landmarks, face_center)
        
        return frame
    
    def _draw_visual_feedback(self, frame, landmarks, face_center):
        """Draw visual feedback on the frame"""
        height, width = frame.shape[:2]
        
        # Draw face landmarks
        if landmarks is not None and len(landmarks) >= 68:
            for i, point in enumerate(landmarks):
                color = (0, 255, 0) if i in [36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47] else (0, 200, 255)
                cv2.circle(frame, tuple(point), 1, color, -1)
            
            # Draw eye closure indicators
            left_eye_closed = self.eye_closed_frames['left'] > 0
            right_eye_closed = self.eye_closed_frames['right'] > 0
            
            left_color = (0, 0, 255) if left_eye_closed else (0, 255, 0)
            right_color = (0, 0, 255) if right_eye_closed else (0, 255, 0)
            
            cv2.rectangle(frame, (10, 10), (60, 60), left_color, 3)
            cv2.putText(frame, "L", (25, 45), cv2.FONT_HERSHEY_SIMPLEX, 1, left_color, 2)
            
            cv2.rectangle(frame, (70, 10), (120, 60), right_color, 3)
            cv2.putText(frame, "R", (85, 45), cv2.FONT_HERSHEY_SIMPLEX, 1, right_color, 2)
            
            # Draw drag indicator
            if self.is_dragging:
                cv2.putText(frame, "DRAGGING", (width - 150, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        # Draw calibration region
        if self.config['calibrated'] and self.config['face_region']:
            x1, y1, x2, y2 = self.config['face_region']
            x1_px = int(x1 * width)
            y1_px = int(y1 * height)
            x2_px = int(x2 * width)
            y2_px = int(y2 * height)
            cv2.rectangle(frame, (x1_px, y1_px), (x2_px, y2_px), (255, 0, 0), 2)
            cv2.putText(frame, "Calibrated Region", (x1_px, y1_px - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
        
        # Draw status text
        status_text = f"Facial Mouse Controller - {'Running' if self.running else 'Paused'}"
        cv2.putText(frame, status_text, (10, height - 20), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(frame, "Press 'c' to calibrate, 'q' to quit", (10, height - 50),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        
        return frame
    
    def run(self):
        """Main run loop"""
        if not self.start_camera():
            print("Failed to start camera")
            return
        
        print("\n" + "="*50)
        print("Facial Mouse Controller Started")
        print("="*50)
        print("\nControls:")
        print("- Move your face to control cursor")
        print("- Blink left eye for left click")
        print("- Blink right eye for right click")
        print("- Blink both eyes for double click")
        print("- Wink left then right to drag")
        print("- Press 'c' to calibrate")
        print("- Press 'p' to pause/resume")
        print("- Press 'q' to quit")
        print("\n" + "="*50)
        
        self.running = True
        
        while True:
            ret, frame = self.cap.read()
            if not ret:
                print("Failed to capture frame")
                break
            
            # Flip frame horizontally for mirror effect
            frame = cv2.flip(frame, 1)
            
            # Process frame
            processed_frame = self.process_frame(frame)
            
            # Display frame
            cv2.imshow('Facial Mouse Controller', processed_frame)
            
            # Handle keyboard input
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('p'):
                self.running = not self.running
                print(f"{'Paused' if not self.running else 'Resumed'}")
            elif key == ord('c'):
                print("Calibrating... Please keep your face centered")
                time.sleep(1)
                ret, cal_frame = self.cap.read()
                if ret:
                    cal_frame = cv2.flip(cal_frame, 1)
                    if self.calibrate(cal_frame):
                        print("Calibration successful!")
                    else:
                        print("Calibration failed - no face detected")
            
            # Limit frame rate
            time.sleep(0.01)
        
        # Cleanup
        self.cap.release()
        cv2.destroyAllWindows()
        print("\nFacial Mouse Controller stopped")

class ControlPanel:
    """GUI control panel for the facial mouse controller"""
    
    def __init__(self, controller):
        self.controller = controller
        self.root = tk.Tk()
        self.root.title("Facial Mouse Controller")
        self.root.geometry("400x500")
        
        # Status variables
        self.is_controller_running = False
        self.control_thread = None
        
        self._create_widgets()
        
    def _create_widgets(self):
        """Create GUI widgets"""
        # Title
        title_label = ttk.Label(self.root, text="Facial Mouse Controller", 
                               font=("Arial", 16, "bold"))
        title_label.pack(pady=10)
        
        # Status frame
        status_frame = ttk.LabelFrame(self.root, text="Status", padding=10)
        status_frame.pack(fill="x", padx=20, pady=10)
        
        self.status_label = ttk.Label(status_frame, text="Controller: Stopped")
        self.status_label.pack()
        
        # Control buttons
        button_frame = ttk.Frame(self.root)
        button_frame.pack(pady=10)
        
        self.start_button = ttk.Button(button_frame, text="Start Controller", 
                                      command=self.toggle_controller)
        self.start_button.pack(side="left", padx=5)
        
        ttk.Button(button_frame, text="Calibrate", 
                  command=self.calibrate).pack(side="left", padx=5)
        
        # Settings frame
        settings_frame = ttk.LabelFrame(self.root, text="Settings", padding=10)
        settings_frame.pack(fill="x", padx=20, pady=10)
        
        # Cursor speed
        ttk.Label(settings_frame, text="Cursor Speed:").grid(row=0, column=0, sticky="w", pady=5)
        self.speed_var = tk.DoubleVar(value=self.controller.config['cursor_speed'])
        speed_scale = ttk.Scale(settings_frame, from_=0.5, to=3.0, 
                               variable=self.speed_var, command=self.update_speed)
        speed_scale.grid(row=0, column=1, padx=10, pady=5)
        self.speed_label = ttk.Label(settings_frame, text=f"{self.speed_var.get():.1f}")
        self.speed_label.grid(row=0, column=2, pady=5)
        
        # Smoothing factor
        ttk.Label(settings_frame, text="Smoothing:").grid(row=1, column=0, sticky="w", pady=5)
        self.smooth_var = tk.DoubleVar(value=self.controller.config['smoothing_factor'])
        smooth_scale = ttk.Scale(settings_frame, from_=0.1, to=0.9, 
                                variable=self.smooth_var, command=self.update_smoothing)
        smooth_scale.grid(row=1, column=1, padx=10, pady=5)
        self.smooth_label = ttk.Label(settings_frame, text=f"{self.smooth_var.get():.2f}")
        self.smooth_label.grid(row=1, column=2, pady=5)
        
        # Click sensitivity
        ttk.Label(settings_frame, text="Click Sensitivity:").grid(row=2, column=0, sticky="w", pady=5)
        self.click_var = tk.DoubleVar(value=self.controller.config['click_threshold'])
        click_scale = ttk.Scale(settings_frame, from_=0.1, to=0.5, 
                               variable=self.click_var, command=self.update_click_sensitivity)
        click_scale.grid(row=2, column=1, padx=10, pady=5)
        self.click_label = ttk.Label(settings_frame, text=f"{self.click_var.get():.2f}")
        self.click_label.grid(row=2, column=2, pady=5)
        
        # Checkboxes for features
        features_frame = ttk.LabelFrame(self.root, text="Features", padding=10)
        features_frame.pack(fill="x", padx=20, pady=10)
        
        self.left_click_var = tk.BooleanVar(value=self.controller.config['enable_left_click'])
        ttk.Checkbutton(features_frame, text="Enable Left Click", 
                       variable=self.left_click_var,
                       command=self.update_left_click).pack(anchor="w", pady=2)
        
        self.right_click_var = tk.BooleanVar(value=self.controller.config['enable_right_click'])
        ttk.Checkbutton(features_frame, text="Enable Right Click", 
                       variable=self.right_click_var,
                       command=self.update_right_click).pack(anchor="w", pady=2)
        
        self.drag_var = tk.BooleanVar(value=self.controller.config['enable_dragging'])
        ttk.Checkbutton(features_frame, text="Enable Dragging", 
                       variable=self.drag_var,
                       command=self.update_dragging).pack(anchor="w", pady=2)
        
        self.feedback_var = tk.BooleanVar(value=self.controller.config['show_visual_feedback'])
        ttk.Checkbutton(features_frame, text="Show Visual Feedback", 
                       variable=self.feedback_var,
                       command=self.update_feedback).pack(anchor="w", pady=2)
        
        # Save/Load buttons
        save_load_frame = ttk.Frame(self.root)
        save_load_frame.pack(pady=10)
        
        ttk.Button(save_load_frame, text="Save Settings", 
                  command=self.save_settings).pack(side="left", padx=5)
        ttk.Button(save_load_frame, text="Load Settings", 
                  command=self.load_settings).pack(side="left", padx=5)
        
        # Instructions
        instructions = """
        Instructions:
        1. Click 'Start Controller'
        2. Position face in camera view
        3. Press 'c' in camera window to calibrate
        4. Move face to control cursor
        5. Blink for clicks (see console for details)
        """
        
        ttk.Label(self.root, text=instructions, justify="left").pack(pady=10)
        
        # Exit button
        ttk.Button(self.root, text="Exit", 
                  command=self.on_closing).pack(pady=10)
        
        # Handle window closing
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def update_speed(self, event=None):
        """Update cursor speed"""
        self.controller.config['cursor_speed'] = self.speed_var.get()
        self.speed_label.config(text=f"{self.speed_var.get():.1f}")
    
    def update_smoothing(self, event=None):
        """Update smoothing factor"""
        self.controller.config['smoothing_factor'] = self.smooth_var.get()
        self.smooth_label.config(text=f"{self.smooth_var.get():.2f}")
    
    def update_click_sensitivity(self, event=None):
        """Update click sensitivity"""
        self.controller.config['click_threshold'] = self.click_var.get()
        self.click_label.config(text=f"{self.click_var.get():.2f}")
    
    def update_left_click(self):
        """Update left click enable/disable"""
        self.controller.config['enable_left_click'] = self.left_click_var.get()
    
    def update_right_click(self):
        """Update right click enable/disable"""
        self.controller.config['enable_right_click'] = self.right_click_var.get()
    
    def update_dragging(self):
        """Update dragging enable/disable"""
        self.controller.config['enable_dragging'] = self.drag_var.get()
    
    def update_feedback(self):
        """Update visual feedback enable/disable"""
        self.controller.config['show_visual_feedback'] = self.feedback_var.get()
    
    def toggle_controller(self):
        """Start or stop the facial mouse controller"""
        if not self.is_controller_running:
            # Start controller in a separate thread
            self.control_thread = threading.Thread(target=self.controller.run, daemon=True)
            self.control_thread.start()
            self.is_controller_running = True
            self.start_button.config(text="Stop Controller")
            self.status_label.config(text="Controller: Running")
        else:
            # Signal controller to stop
            self.controller.running = False
            self.is_controller_running = False
            self.start_button.config(text="Start Controller")
            self.status_label.config(text="Controller: Stopped")
    
    def calibrate(self):
        """Trigger calibration"""
        if self.is_controller_running:
            print("Calibration triggered from GUI")
            # Note: Calibration is done through the camera window with 'c' key
    
    def save_settings(self):
        """Save current settings to file"""
        self.controller.save_config("facial_mouse_settings.json")
        tk.messagebox.showinfo("Settings Saved", "Settings have been saved to facial_mouse_settings.json")
    
    def load_settings(self):
        """Load settings from file"""
        self.controller.load_config("facial_mouse_settings.json")
        
        # Update GUI to reflect loaded settings
        self.speed_var.set(self.controller.config['cursor_speed'])
        self.smooth_var.set(self.controller.config['smoothing_factor'])
        self.click_var.set(self.controller.config['click_threshold'])
        self.left_click_var.set(self.controller.config['enable_left_click'])
        self.right_click_var.set(self.controller.config['enable_right_click'])
        self.drag_var.set(self.controller.config['enable_dragging'])
        self.feedback_var.set(self.controller.config['show_visual_feedback'])
        
        self.speed_label.config(text=f"{self.speed_var.get():.1f}")
        self.smooth_label.config(text=f"{self.smooth_var.get():.2f}")
        self.click_label.config(text=f"{self.click_var.get():.2f}")
        
        tk.messagebox.showinfo("Settings Loaded", "Settings have been loaded from facial_mouse_settings.json")
    
    def on_closing(self):
        """Handle window closing"""
        if self.is_controller_running:
            self.controller.running = False
            if self.control_thread:
                self.control_thread.join(timeout=2)
        self.root.destroy()
    
    def run(self):
        """Run the GUI"""
        self.root.mainloop()

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Facial Mouse Controller")
    parser.add_argument("--gui", action="store_true", help="Launch with GUI control panel")
    parser.add_argument("--config", type=str, help="Path to configuration file")
    args = parser.parse_args()
    
    # Create controller
    controller = FacialMouseController(args.config)
    
    if args.gui:
        # Launch with GUI
        panel = ControlPanel(controller)
        panel.run()
    else:
        # Launch without GUI (command line only)
        controller.run()

if __name__ == "__main__":
    main()