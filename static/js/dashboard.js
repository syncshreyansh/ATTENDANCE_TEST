// Enhanced dashboard with success sound and instant updates
const token = localStorage.getItem('token');
const user = JSON.parse(localStorage.getItem('user') || '{}');

if (!token || !user.id || user.role !== 'admin') {
  localStorage.removeItem('token');
  localStorage.removeItem('user');
  window.location.href = '/login';
}

document.addEventListener("DOMContentLoaded", () => {
  // === THEME TOGGLE LOGIC ===
  const themeToggle = document.getElementById("themeToggle");
  function applyTheme(theme) {
    if (theme === "dark") {
      document.body.classList.add("dark-mode");
      themeToggle.classList.add("dark");
    } else {
      document.body.classList.remove("dark-mode");
      themeToggle.classList.remove("dark");
    }
  }
  themeToggle.addEventListener("click", () => {
    const isDark = document.body.classList.toggle("dark-mode");
    themeToggle.classList.toggle("dark", isDark);
    localStorage.setItem("theme", isDark ? "dark" : "light");
  });
  const savedTheme = localStorage.getItem("theme");
  const prefersDark =
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(savedTheme || (prefersDark ? "dark" : "light"));

  window.dashboard = new AttendanceDashboard();
});

// === SUCCESS SOUND ===
function playSuccessSound() {
  // Create success sound using Web Audio API
  const audioContext = new (window.AudioContext || window.webkitAudioContext)();
  
  // Create oscillator for success tone
  const oscillator = audioContext.createOscillator();
  const gainNode = audioContext.createGain();
  
  oscillator.connect(gainNode);
  gainNode.connect(audioContext.destination);
  
  // Success sound: pleasant "ding" (C major chord)
  oscillator.frequency.value = 523.25; // C5
  oscillator.type = 'sine';
  
  // Envelope
  gainNode.gain.setValueAtTime(0, audioContext.currentTime);
  gainNode.gain.linearRampToValueAtTime(0.3, audioContext.currentTime + 0.01);
  gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.5);
  
  oscillator.start(audioContext.currentTime);
  oscillator.stop(audioContext.currentTime + 0.5);
}

// === MAIN DASHBOARD CLASS ===
class AttendanceDashboard {
  constructor() {
    this.socket = io();
    this.isSystemRunning = false;
    this.videoStream = null;
    this.liveStream = null;
    this.processingInterval = null;
    this.processingCanvas = null;
    this.cameraStopRequested = false; // NEW: Flag for camera stop

    // Cache DOM elements
    this.captureBtn = document.getElementById("capturePhoto");
    this.recaptureBtn = document.getElementById("recapturePhoto");
    this.videoPreview = document.getElementById("videoPreview");
    this.photoCanvas = document.getElementById("photoCanvas");
    this.enrollSubmitBtn = document.getElementById("enrollSubmitBtn");
    this.enrollModal = document.getElementById("enrollModal");
    this.enrollForm = document.getElementById("enrollForm");

    this.startBtn = document.getElementById("startSystem");
    this.stopBtn = document.getElementById("stopSystem");
    this.statusDot = document.getElementById("statusDot");
    this.statusText = document.getElementById("statusText");

    this.liveFeedVideo = document.getElementById("liveFeedVideo");
    this.feedPlaceholder = document.getElementById("feedPlaceholder");

    this.recognitionOverlay = document.getElementById("recognitionOverlay");
    this.recognitionOverlayText = document.getElementById("recognitionOverlayText");
    this.overlayTimeout = null;

    this.presentCountEl = document.getElementById("presentCount");
    this.absentCountEl = document.getElementById("absentCount");
    this.attendanceRateEl = document.getElementById("attendanceRate");
    this.totalStudentsEl = document.getElementById("totalStudents");

    this.recentEventsList = document.getElementById("recentEvents");

    this.processingCanvas = document.createElement('canvas');
    this.processingCanvas.width = 640;
    this.processingCanvas.height = 480;

    this.initializeEventListeners();
    this.loadInitialData();
  }

  initializeEventListeners() {
    this.startBtn.addEventListener("click", () => this.startSystem());
    this.stopBtn.addEventListener("click", () => this.stopSystem());

    document.querySelector('.header').addEventListener('click', (e) => {
      if (e.target.closest('#logoutBtn')) {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        window.location.href = '/login';
      }
    });

    document.getElementById("enrollBtn").addEventListener("click", () => this.openModal());
    document.getElementById("closeModal").addEventListener("click", () => this.closeModal());
    document.getElementById("cancelEnroll").addEventListener("click", () => this.closeModal());

    this.enrollForm.addEventListener("submit", (e) => this.handleEnrollSubmit(e));
    this.captureBtn.addEventListener("click", () => this.capturePhoto());
    this.recaptureBtn.addEventListener("click", () => this.recapturePhoto());

    // Enhanced validation for form inputs
    document.getElementById("studentName").addEventListener("input", (e) => {
      // Only allow alphabets and spaces
      e.target.value = e.target.value.replace(/[^A-Za-z\s]/g, '');
    });

    document.getElementById("parentPhone").addEventListener("input", (e) => {
      // Only allow digits
      e.target.value = e.target.value.replace(/\D/g, '');
    });

    // SocketIO Listeners
    this.socket.on("recognition_status", (data) => {
      if (data.status === "clear") {
        this.showOverlay(null);
      } else if (data.status === "unknown") {
        this.showOverlay(data.message, "error");
      } else if (data.status === "recognizing" || data.status === "verifying") {
        this.showOverlay(data.message, "recognizing");
      } else if (data.status === "already_marked") {
        this.showOverlay(data.message, "error");
      } else if (data.status === "cooldown") {
        this.showOverlay(data.message, "error");
      }
    });

    this.socket.on("attendance_update", (data) => {
      console.log('✅ Attendance update received:', data);
      this.handleAttendanceUpdate(data);
    });
    
    this.socket.on("system_started", () => this.updateSystemStatus(true));
    this.socket.on("system_stopped", () => this.updateSystemStatus(false));
  }

  // === Video Stream Methods ===

  async startVideoStream() {
    if (this.videoStream) return;
    try {
      this.videoStream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480 },
      });
      this.videoPreview.srcObject = this.videoStream;
      this.videoPreview.style.display = "block";
      this.photoCanvas.style.display = "none";
    } catch (error) {
      this.showNotification(
        "Camera access denied. Please allow camera permissions.",
        "error"
      );
      this.closeModal();
    }
  }

  stopVideoStream() {
    if (this.videoStream) {
      this.videoStream.getTracks().forEach((track) => {
        track.stop();
        console.log('Enrollment camera track stopped:', track.label);
      });
      this.videoStream = null;
    }
    if (this.videoPreview) {
      this.videoPreview.srcObject = null;
    }
  }

  async startLiveFeed() {
    if (this.liveStream) return;
    
    this.cameraStopRequested = false; // Reset flag
    
    try {
      this.liveStream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480 },
      });
      
      this.liveFeedVideo.srcObject = this.liveStream;
      this.liveFeedVideo.style.display = "block";
      this.feedPlaceholder.style.display = "none";

      this.startFrameProcessing();
      console.log('Live camera started successfully');
    } catch (error) {
      this.showNotification(
        "Camera access denied. Please allow camera permissions.",
        "error"
      );
      this.updateSystemStatus(false);
    }
  }

  stopLiveFeed() {
    console.log('Stopping live feed...');
    
    this.cameraStopRequested = true; // Set flag to prevent restarts
    
    // Stop frame processing first
    this.stopFrameProcessing();

    // Stop camera stream with proper cleanup
    if (this.liveStream) {
      const tracks = this.liveStream.getTracks();
      tracks.forEach((track) => {
        track.stop();
        console.log('Live camera track stopped:', track.label, track.readyState);
      });
      this.liveStream = null;
    }
    
    // Clear video element
    if (this.liveFeedVideo) {
      this.liveFeedVideo.srcObject = null;
      this.liveFeedVideo.style.display = "none";
      this.liveFeedVideo.pause();
    }
    
    this.feedPlaceholder.style.display = "flex";
    console.log('Live feed stopped completely');
    
    // Extra safety: Check after 500ms
    setTimeout(() => {
      if (this.liveStream && !this.cameraStopRequested) {
        console.warn('Camera still active after stop - forcing cleanup');
        this.stopLiveFeed();
      }
    }, 500);
  }

  startFrameProcessing() {
    if (this.processingInterval) {
      clearInterval(this.processingInterval);
    }
    
    this.processingInterval = setInterval(() => {
      if (!this.cameraStopRequested) {
        this.captureAndSendFrame();
      }
    }, 500);
    console.log('Frame processing started');
  }

  stopFrameProcessing() {
    if (this.processingInterval) {
      clearInterval(this.processingInterval);
      this.processingInterval = null;
      console.log('Frame processing stopped');
    }
  }

  captureAndSendFrame() {
    if (!this.liveFeedVideo || !this.liveStream || !this.isSystemRunning || this.cameraStopRequested) {
      return;
    }

    try {
      const ctx = this.processingCanvas.getContext('2d');
      
      ctx.drawImage(
        this.liveFeedVideo,
        0, 0,
        this.processingCanvas.width,
        this.processingCanvas.height
      );

      const frameData = this.processingCanvas.toDataURL('image/jpeg', 0.8).split(',')[1];
      this.socket.emit('process_frame', { frame: frameData });
    } catch (error) {
      console.error('Error capturing frame:', error);
    }
  }

  // === Enrollment Modal Methods ===

  openModal() {
    if (this.isSystemRunning) {
      this.showNotification(
        "Please stop the system before enrolling a new student.",
        "warning"
      );
      return;
    }
    this.enrollModal.style.display = "block";
    this.startVideoStream();
    this.resetCaptureUI();
  }

  closeModal() {
    this.stopVideoStream();
    this.enrollModal.style.display = "none";
    this.enrollForm.reset();
    this.resetCaptureUI();
    
    const context = this.photoCanvas.getContext("2d");
    context.clearRect(0, 0, this.photoCanvas.width, this.photoCanvas.height);
  }

  capturePhoto() {
    if (!this.videoStream) {
      this.showNotification("Camera is not active.", "warning");
      return;
    }
    const context = this.photoCanvas.getContext("2d");

    this.photoCanvas.width = this.videoPreview.videoWidth;
    this.photoCanvas.height = this.videoPreview.videoHeight;

    context.translate(this.photoCanvas.width, 0);
    context.scale(-1, 1);
    context.drawImage(
      this.videoPreview,
      0, 0,
      this.photoCanvas.width,
      this.photoCanvas.height
    );

    this.stopVideoStream();

    this.videoPreview.style.display = "none";
    this.photoCanvas.style.display = "block";

    this.captureBtn.classList.add("hidden");
    this.recaptureBtn.classList.remove("hidden");
    this.enrollSubmitBtn.disabled = false;
  }

  recapturePhoto() {
    this.videoPreview.style.display = "block";
    this.photoCanvas.style.display = "none";

    this.captureBtn.classList.remove("hidden");
    this.recaptureBtn.classList.add("hidden");
    this.enrollSubmitBtn.disabled = true;

    this.startVideoStream();
  }

  resetCaptureUI() {
    this.videoPreview.style.display = "block";
    this.photoCanvas.style.display = "none";

    this.captureBtn.classList.remove("hidden");
    this.recaptureBtn.classList.add("hidden");

    this.enrollSubmitBtn.disabled = true;
    this.captureBtn.disabled = false;
    this.enrollSubmitBtn.innerHTML = '<i class="fas fa-check"></i> Submit';
  }

  // === Data Loading & API Methods ===

  async loadInitialData() {
    this.loadStats();
    this.loadRecentAttendance();
  }

  async loadStats() {
    try {
      const response = await fetch("/api/stats", {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      const data = await response.json();

      this.presentCountEl.textContent = data.present_today;
      this.absentCountEl.textContent = data.absent_today;
      this.attendanceRateEl.textContent = `${Math.round(data.attendance_rate)}%`;
      this.totalStudentsEl.textContent = data.total_students;
    } catch (error) {
      console.error("Error loading stats:", error);
    }
  }

  async loadRecentAttendance() {
    try {
      const response = await fetch("/api/attendance", {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      const data = await response.json();

      this.recentEventsList.innerHTML = "";

      if (data.length === 0) {
        this.recentEventsList.innerHTML =
          '<p style="text-align: center; color: var(--text-secondary)">No events yet</p>';
        return;
      }

      data.forEach((event) => {
        this.addRecentEvent(event);
      });
    } catch (error) {
      console.error("Error loading recent attendance:", error);
    }
  }

  // === System & Socket Methods ===

  startSystem() {
    this.socket.emit("start_system");
    this.startBtn.disabled = true;
  }

  stopSystem() {
    this.socket.emit("stop_system");
    this.stopBtn.disabled = true;
  }

  updateSystemStatus(isRunning) {
    this.isSystemRunning = isRunning;
    if (isRunning) {
      this.startBtn.disabled = true;
      this.stopBtn.disabled = false;
      this.statusDot.classList.remove("offline");
      this.statusDot.classList.add("online");
      this.statusText.textContent = "Online";
      this.startLiveFeed();
    } else {
      this.startBtn.disabled = false;
      this.stopBtn.disabled = true;
      this.statusDot.classList.remove("online");
      this.statusDot.classList.add("offline");
      this.statusText.textContent = "Offline";
      this.stopLiveFeed();
      this.showOverlay(null);
    }
  }

  handleAttendanceUpdate(data) {
    // Play success sound
    playSuccessSound();
    
    this.showOverlay(`${data.student_name} Marked!`, "success");

    this.showNotification(
      `${data.student_name} marked present! (+${data.points} points)`,
      "success"
    );

    this.addRecentEvent({
      student_name: data.student_name,
      time_in: data.timestamp,
    });

    // INSTANT UPDATE: Update stats immediately
    this.updateStatsInstantly();
  }

  updateStatsInstantly() {
    // Increment present count
    const currentPresent = parseInt(this.presentCountEl.textContent) || 0;
    const newPresent = currentPresent + 1;
    this.animateStatChange(this.presentCountEl, currentPresent, newPresent);

    // Decrement absent count
    const currentAbsent = parseInt(this.absentCountEl.textContent) || 0;
    const newAbsent = Math.max(0, currentAbsent - 1);
    this.animateStatChange(this.absentCountEl, currentAbsent, newAbsent);

    // Recalculate attendance rate
    const totalStudents = parseInt(this.totalStudentsEl.textContent) || 0;
    if (totalStudents > 0) {
      const currentRate = parseInt(this.attendanceRateEl.textContent) || 0;
      const newRate = Math.round((newPresent / totalStudents) * 100);
      this.animateStatChange(this.attendanceRateEl, currentRate, newRate, '%');
    }

    // Refresh from server after 200ms for accuracy
    setTimeout(() => {
      this.loadStats();
    }, 200);
  }

  animateStatChange(element, oldValue, newValue, suffix = '') {
    element.style.transform = 'scale(1.2)';
    element.style.color = 'var(--primary-purple)';
    element.style.transition = 'all 0.3s ease';

    const duration = 300;
    const steps = 10;
    const stepValue = (newValue - oldValue) / steps;
    const stepDuration = duration / steps;
    
    let currentStep = 0;
    const interval = setInterval(() => {
      currentStep++;
      const displayValue = Math.round(oldValue + (stepValue * currentStep));
      element.textContent = displayValue + suffix;
      
      if (currentStep >= steps) {
        clearInterval(interval);
        element.textContent = newValue + suffix;
        
        setTimeout(() => {
          element.style.transform = 'scale(1)';
          element.style.color = 'var(--text-primary)';
        }, 200);
      }
    }, stepDuration);
  }

  async handleEnrollSubmit(event) {
    event.preventDefault();

    const isPhotoTaken = this.photoCanvas.style.display === "block";
    if (!isPhotoTaken) {
      this.showNotification(
        "Please capture a photo before enrolling.",
        "warning"
      );
      return;
    }

    // Enhanced validation
    const name = document.getElementById("studentName").value.trim();
    const studentId = document.getElementById("studentId").value.trim();
    const studentClass = document.getElementById("studentClass").value.trim();
    const section = document.getElementById("studentSection").value.trim();
    const parentPhone = document.getElementById("parentPhone").value.trim();

    if (!name || !studentId || !studentClass || !section || !parentPhone) {
      this.showNotification("All fields are mandatory.", "error");
      return;
    }

    if (!/^[A-Za-z\s]+$/.test(name)) {
      this.showNotification("Name must contain only alphabets.", "error");
      return;
    }

    if (parentPhone.length < 10) {
      this.showNotification("Phone number must be at least 10 digits.", "error");
      return;
    }

    this.enrollSubmitBtn.disabled = true;
    this.enrollSubmitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Enrolling...';

    const studentData = {
      name: name,
      student_id: studentId,
      class: studentClass,
      section: section,
      parent_phone: parentPhone,
    };

    try {
      // Create student
      console.log('Creating student...');
      const createResponse = await fetch("/api/students", {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(studentData),
      });

      const createResult = await createResponse.json();

      if (!createResponse.ok) {
        this.showNotification(createResult.message, "error");
        this.enrollSubmitBtn.disabled = false;
        this.enrollSubmitBtn.innerHTML = '<i class="fas fa-check"></i> Submit';
        return;
      }
      
      // Create login
      console.log('Creating login...');
      const createLoginResponse = await fetch("/api/auth/register", {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          username: studentData.student_id,
          email: studentData.student_id + '@school.com',
          password: 'student123',
          role: 'student',
          student_id: createResult.id
        }),
      });

      // Enroll face
      console.log('Enrolling face...');
      const canvas = document.getElementById("photoCanvas");
      const frameData = canvas.toDataURL("image/jpeg", 0.95).split(",")[1];

      const enrollResponse = await fetch("/api/enroll", {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          student_id: studentData.student_id,
          frame: frameData,
        }),
      });

      const enrollResult = await enrollResponse.json();

      if (enrollResult.success) {
        this.showNotification(
          "Student enrolled successfully!",
          "success"
        );
        this.loadInitialData();
        setTimeout(() => {
          this.closeModal();
        }, 500);
      } else {
        this.showNotification(
          `Enrollment failed: ${enrollResult.message}`,
          "error"
        );
        this.enrollSubmitBtn.disabled = false;
        this.enrollSubmitBtn.innerHTML = '<i class="fas fa-check"></i> Retry';
      }
    } catch (error) {
      console.error("Enrollment error:", error);
      this.showNotification(`Error: ${error.message}`, "error");
      this.enrollSubmitBtn.disabled = false;
      this.enrollSubmitBtn.innerHTML = '<i class="fas fa-check"></i> Submit';
    }
  }

  // === Helper & UI Methods ===

  showOverlay(message, type) {
    clearTimeout(this.overlayTimeout);

    if (!message) {
      this.recognitionOverlay.classList.remove("show");
      return;
    }

    this.recognitionOverlayText.textContent = message;
    this.recognitionOverlay.className = "recognition-overlay";
    this.recognitionOverlay.classList.add(type);
    this.recognitionOverlay.classList.add("show");

    this.overlayTimeout = setTimeout(() => {
      this.recognitionOverlay.classList.remove("show");
    }, 2000);
  }

  addRecentEvent(data) {
    const placeholder = this.recentEventsList.querySelector("p");
    if (placeholder) {
      this.recentEventsList.innerHTML = "";
    }

    const item = document.createElement("div");
    item.className = "list-item";

    let time = data.time_in;
    
    if (typeof time === 'number') {
      time = this.formatTime(time);
    } else if (time && time.includes("T")) {
      time = this.formatTime(new Date(time).getTime() / 1000);
    }

    item.innerHTML = `
      <div class="item-info">
        <strong>${data.student_name}</strong>
        <small>Marked present</small>
      </div>
      <div class="item-badge">
        <small>${time || "Just now"}</small>
      </div>
    `;

    this.recentEventsList.prepend(item);
  }

  formatTime(timestamp) {
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: true,
    });
  }

  showNotification(message, type = "success") {
    const notification = document.createElement("div");
    notification.className = `notification ${type}`;
    notification.textContent = message;

    document.body.appendChild(notification);

    const style = document.createElement("style");
    style.innerHTML = `
      .notification {
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 15px 20px;
        border-radius: 12px;
        color: #fff;
        font-weight: 600;
        z-index: 2000;
        animation: slideIn 0.3s ease-out, fadeOut 0.3s ease-in 2.7s;
        box-shadow: 0 5px 15px rgba(0,0,0,0.2);
      }
      .notification.success {
        background: linear-gradient(135deg, #10b981, #059669);
      }
      .notification.error {
        background: linear-gradient(135deg, #ef4444, #dc2626);
      }
      .notification.warning {
        background: linear-gradient(135deg, #f59e0b, #d97706);
      }
      @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
      }
      @keyframes fadeOut {
        from { opacity: 1; }
        to { opacity: 0; transform: translateX(100%); }
      }
    `;
    document.head.appendChild(style);

    setTimeout(() => {
      notification.remove();
      style.remove();
    }, 3000);
  }
}