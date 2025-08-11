"""
gui_main.py
PyQt5 GUI wrapper for the gesture-controlled OS project.

Place this file in the same folder as:
 - HandTrackingModule.py
 - Icons/ (mouse.png, volume.png, painter.png, scroll.png)
 - PainterIcons/ (red.png, green.png, blue.png, thick.png, thin.png, eraser.png)
"""

import sys
import os
import time
from datetime import datetime

import cv2
import numpy as np
import pyautogui

from PyQt5 import QtCore, QtGui, QtWidgets
from HandTrackingModule import handDetector

# Try to import pycaw for volume control; handle gracefully if not available
try:
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    _pycaw_available = True
except Exception:
    _pycaw_available = False

# --------------------- Constants ---------------------
CAM_WIDTH = 640
CAM_HEIGHT = 480
ICON_SIZE = 80
SCROLL_AMOUNT = 40
MODE_SELECT_HOLD = 2
SCREENSHOT_HOLD = 2
HOVER_HOLD = 1
FPS_UPDATE_INTERVAL = 0.5  # seconds

# --------------------- Helper Functions ---------------------


def overlay_canvas_on_frame(frame, canvas):
    """Overlay the canvas on top of the webcam feed with transparency like original code."""
    mask = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    _, mask_inv = cv2.threshold(mask, 250, 255, cv2.THRESH_BINARY_INV)
    mask_inv = cv2.cvtColor(mask_inv, cv2.COLOR_GRAY2BGR)
    frame = cv2.bitwise_and(frame, 255 - mask_inv)
    frame = cv2.add(frame, cv2.bitwise_and(canvas, mask_inv))
    return frame


def cv2_to_qimage(frame):
    """Convert an OpenCV BGR image to QImage."""
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    bytes_per_line = ch * w
    qimg = QtGui.QImage(rgb.data, w, h, bytes_per_line,
                        QtGui.QImage.Format_RGB888)
    return qimg

# --------------------- Main Window ---------------------


class GestureGui(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gesture Controller - GUI")
        self.setGeometry(50, 50, 1100, 620)
        self._init_audio()
        self._init_detector()
        self._init_state()
        self._init_ui()
        self._init_capture()

    def _init_audio(self):
        if _pycaw_available:
            try:
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(
                    IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                self.volume = cast(interface, POINTER(IAudioEndpointVolume))
                self.vol_min, self.vol_max = self.volume.GetVolumeRange()[:2]
            except Exception:
                self.volume = None
                self.vol_min, self.vol_max = 0, 100
        else:
            self.volume = None
            self.vol_min, self.vol_max = 0, 100

    def _init_detector(self):
        # Keep defaults similar to your original main
        self.detector = handDetector(detectionCon=0.8, maxHands=1)

    def _init_state(self):
        self.cap = None
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.last_frame_time = time.time()
        self.prev_time_for_fps = time.time()
        self.fps = 0.0

        # Mode & UI state
        self.current_mode = "mouse"
        self.selecting_mode = False
        self.hovered_icon = -1
        self.hover_start = 0.0
        self.select_mode_start = 0.0
        self.screenshot_start = 0.0
        self.click_armed = False

        # Painter state
        self.xp, self.yp = 0, 0
        self.brush_thickness = 10
        self.draw_color = (0, 0, 255)
        self.last_color = self.draw_color
        self.draw_color_name = "red"
        self.img_canvas = np.ones((CAM_HEIGHT, CAM_WIDTH, 3), np.uint8) * 255

        # Icons
        self.icon_folder = "Icons"
        self.icon_names = ["mouse.png", "volume.png",
                           "painter.png", "scroll.png"]
        self.mode_icon_positions = [(40, 20), (140, 20), (240, 20), (340, 20)]
        self.mode_icons = []
        for name in self.icon_names:
            path = os.path.join(self.icon_folder, name)
            if os.path.exists(path):
                img = cv2.imread(path)
                img = cv2.resize(img, (ICON_SIZE, ICON_SIZE))
            else:
                # placeholder
                img = np.ones((ICON_SIZE, ICON_SIZE, 3), np.uint8) * 128
            self.mode_icons.append(img)

        # Painter icons
        self.painter_icon_folder = "PainterIcons"
        painter_icon_names = ["red.png", "green.png",
                              "blue.png", "thick.png", "thin.png", "eraser.png"]
        painter_positions = [(10, 20), (110, 20), (210, 20),
                             (310, 20), (410, 20), (510, 20)]
        self.painter_options = {}
        for name, pos in zip(painter_icon_names, painter_positions):
            path = os.path.join(self.painter_icon_folder, name)
            if os.path.exists(path):
                icon = cv2.imread(path)
                icon = cv2.resize(icon, (ICON_SIZE, ICON_SIZE))
            else:
                icon = np.ones((ICON_SIZE, ICON_SIZE, 3), np.uint8) * 128
            key = name.split('.')[0]
            self.painter_options[key] = (pos, icon)

    def _init_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QHBoxLayout()
        central.setLayout(layout)

        # Left: Video display + status
        left_panel = QtWidgets.QVBoxLayout()
        layout.addLayout(left_panel, stretch=4)

        self.video_label = QtWidgets.QLabel()
        self.video_label.setFixedSize(CAM_WIDTH, CAM_HEIGHT)
        self.video_label.setStyleSheet("background-color: black;")
        left_panel.addWidget(self.video_label)

        # Status bar area
        status_layout = QtWidgets.QHBoxLayout()
        self.mode_label = QtWidgets.QLabel(f"Mode: {self.current_mode}")
        self.fps_label = QtWidgets.QLabel("FPS: 0")
        status_layout.addWidget(self.mode_label)
        status_layout.addStretch()
        status_layout.addWidget(self.fps_label)
        left_panel.addLayout(status_layout)

        # Right: Controls
        right_panel = QtWidgets.QVBoxLayout()
        layout.addLayout(right_panel, stretch=2)

        # Mode buttons
        modes_group = QtWidgets.QGroupBox("Modes")
        modes_layout = QtWidgets.QVBoxLayout()
        modes_group.setLayout(modes_layout)
        right_panel.addWidget(modes_group)

        self.mode_buttons = {}
        for mode_name in ["mouse", "volume", "painter", "scroll"]:
            btn = QtWidgets.QPushButton(mode_name.capitalize())
            btn.setCheckable(True)
            btn.clicked.connect(
                lambda checked, m=mode_name: self.set_mode(m, user=True))
            modes_layout.addWidget(btn)
            self.mode_buttons[mode_name] = btn
        # Set default button checked
        self.mode_buttons["mouse"].setChecked(True)

        # Painter controls
        painter_group = QtWidgets.QGroupBox("Painter Tools")
        painter_layout = QtWidgets.QGridLayout()
        painter_group.setLayout(painter_layout)
        right_panel.addWidget(painter_group)

        # color buttons
        self.painter_buttons = {}
        color_keys = ["red", "green", "blue", "thick", "thin", "eraser"]
        for i, key in enumerate(color_keys):
            b = QtWidgets.QPushButton(key.capitalize())
            b.clicked.connect(lambda _, k=key: self.on_painter_option(k))
            painter_layout.addWidget(b, i // 2, i % 2)
            self.painter_buttons[key] = b

        # Manual control buttons
        control_group = QtWidgets.QGroupBox("Manual Controls")
        control_layout = QtWidgets.QVBoxLayout()
        control_group.setLayout(control_layout)
        right_panel.addWidget(control_group)

        self.start_btn = QtWidgets.QPushButton("Start Camera")
        self.start_btn.clicked.connect(self.start_capture)
        control_layout.addWidget(self.start_btn)

        self.stop_btn = QtWidgets.QPushButton("Stop Camera")
        self.stop_btn.clicked.connect(self.stop_capture)
        control_layout.addWidget(self.stop_btn)

        self.screenshot_btn = QtWidgets.QPushButton("Take Screenshot")
        self.screenshot_btn.clicked.connect(self.take_screenshot_manual)
        control_layout.addWidget(self.screenshot_btn)

        self.save_paint_btn = QtWidgets.QPushButton("Save Drawing")
        self.save_paint_btn.clicked.connect(self.save_painting)
        control_layout.addWidget(self.save_paint_btn)

        self.clear_canvas_btn = QtWidgets.QPushButton("Clear Canvas")
        self.clear_canvas_btn.clicked.connect(self.clear_canvas)
        control_layout.addWidget(self.clear_canvas_btn)

        # Log area
        self.log_box = QtWidgets.QTextEdit()
        self.log_box.setReadOnly(True)
        right_panel.addWidget(self.log_box, stretch=1)

        # Exit
        exit_btn = QtWidgets.QPushButton("Exit")
        exit_btn.clicked.connect(self.close)
        right_panel.addWidget(exit_btn)

    def _init_capture(self):
        # Do not auto-start camera; wait for user to press Start (gives flexibility)
        pass

    # --------------------- Camera Control ---------------------
    def start_capture(self):
        if self.cap and self.cap.isOpened():
            self.log("Camera is already running.")
            return
        self.cap = cv2.VideoCapture(0)
        # set frame size
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self.cap.isOpened():
            self.log("Failed to open camera.")
            return
        # fastest possible; actual FPS controlled by processing time
        self.timer.start(1)
        self.start_btn.setEnabled(False)
        self.log("Camera started.")

    def stop_capture(self):
        if self.timer.isActive():
            self.timer.stop()
        if self.cap:
            self.cap.release()
            self.cap = None
        self.video_label.clear()
        self.start_btn.setEnabled(True)
        self.log("Camera stopped.")

    # --------------------- Mode & Painter handlers ---------------------
    def set_mode(self, mode, user=False):
        # user=True when set by button, False when set by gesture
        self.current_mode = mode
        self.mode_label.setText(f"Mode: {self.current_mode}")
        for m, btn in self.mode_buttons.items():
            btn.setChecked(m == mode)
        self.log(f"Mode set to: {mode} {'(user)' if user else '(gesture)'}")

    def on_painter_option(self, key):
        if key == "thick":
            self.brush_thickness = 20
            self.draw_color_name = "thick"
        elif key == "thin":
            self.brush_thickness = 5
            self.draw_color_name = "thin"
        elif key == "eraser":
            self.draw_color = (255, 255, 255)
            self.draw_color_name = "eraser"
        else:
            # colors
            if key == "red":
                color = (0, 0, 255)
            elif key == "green":
                color = (0, 255, 0)
            else:
                color = (255, 0, 0)
            self.draw_color = color
            self.last_color = color
            self.draw_color_name = key
        self.log(f"Painter option: {key} selected")

    # --------------------- Actions ---------------------
    def take_screenshot_manual(self):
        if not os.path.exists("Screenshots"):
            os.makedirs("Screenshots")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if hasattr(self, "last_frame") and self.last_frame is not None:
            cv2.imwrite(f"Screenshots/screenshot_{ts}.png", self.last_frame)
            self.log(f"[Screenshot] Saved screenshot_{ts}.png")
        else:
            self.log("No frame available to save.")

    def save_painting(self):
        if not os.path.exists("Screenshots"):
            os.makedirs("Screenshots")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        cv2.imwrite(f"Screenshots/paint_{ts}.png", self.img_canvas)
        self.log(f"[Painter] Saved paint_{ts}.png")

    def clear_canvas(self):
        self.img_canvas = np.ones((CAM_HEIGHT, CAM_WIDTH, 3), np.uint8) * 255
        self.log("Canvas cleared.")

    # --------------------- Main per-frame processing ---------------------
    def update_frame(self):
        if not self.cap or not self.cap.isOpened():
            return
        success, frame = self.cap.read()
        if not success:
            self.log("Frame not received.")
            return

        frame = cv2.flip(frame, 1)
        self.last_frame = frame.copy()
        # Detect hands and landmarks
        frame = self.detector.findHands(frame)
        lmList = self.detector.findPosition(frame, draw=True)
        fingers = self.detector.fingersUp() if lmList else [0, 0, 0, 0, 0]

        # Timing / FPS
        now = time.time()
        dt = now - self.prev_time_for_fps
        if dt >= FPS_UPDATE_INTERVAL:
            self.fps = 1.0 / \
                (now - self.last_frame_time) if now != self.last_frame_time else 0.0
            self.prev_time_for_fps = now
        self.last_frame_time = now
        self.fps_label.setText(f"FPS: {int(self.fps)}")

        # Gesture logic (mirrors your main.py)
        if lmList:
            # Screenshot: fist for SCREENSHOT_HOLD seconds
            if fingers == [0, 0, 0, 0, 0]:
                if self.screenshot_start == 0:
                    self.screenshot_start = now
                elif now - self.screenshot_start >= SCREENSHOT_HOLD:
                    self.take_screenshot_manual()
                    self.screenshot_start = 0
            else:
                self.screenshot_start = 0

            # Mode selection by 5 fingers
            if sum(fingers) == 5:
                if self.select_mode_start == 0:
                    self.select_mode_start = now
                elif now - self.select_mode_start > MODE_SELECT_HOLD:
                    self.selecting_mode = True
            else:
                self.select_mode_start = 0

            if self.selecting_mode:
                # show icons on frame
                for i, (x, y) in enumerate(self.mode_icon_positions):
                    icon = self.mode_icons[i]
                    frame[y:y + ICON_SIZE, x:x + ICON_SIZE] = icon
                # hover check using index tip (landmark 8) position if available
                if len(lmList) > 8:
                    self._check_hover(lmList[8][1:])
            elif self.current_mode == "mouse" and len(lmList) > 12:
                ix, iy = lmList[8][1:]
                # Cursor move: index finger only
                if fingers[1] and not any(fingers[2:]):
                    sx = np.interp(ix, (0, CAM_WIDTH),
                                   (0, pyautogui.size().width))
                    sy = np.interp(iy, (0, CAM_HEIGHT),
                                   (0, pyautogui.size().height))
                    try:
                        pyautogui.moveTo(sx, sy)
                    except Exception:
                        pass
                # Click gestures
                if fingers[1] and fingers[2]:
                    self.click_armed = True
                elif self.click_armed:
                    if not fingers[1] and fingers[2]:
                        pyautogui.click(button="left")
                        self.click_armed = False
                    elif not fingers[1] and not fingers[2]:
                        pyautogui.click(button="right")
                        self.click_armed = False

            elif self.current_mode == "volume" and len(lmList) > 8 and self.volume is not None:
                length, _, _ = self.detector.findDistance(
                    4, 8, frame, draw=True)
                vol = np.interp(length, [20, 200], [
                                self.vol_min, self.vol_max])
                try:
                    self.volume.SetMasterVolumeLevel(vol, None)
                except Exception:
                    pass
                vol_bar = np.interp(length, [20, 200], [400, 150])
                cv2.rectangle(frame, (50, 150), (85, 400), (0, 255, 0), 2)
                cv2.rectangle(frame, (50, int(vol_bar)),
                              (85, 400), (0, 255, 0), cv2.FILLED)

            elif self.current_mode == "painter":
                painter_img = frame.copy()
                # draw painter icons onto painter_img
                for name, ((x, y), icon) in self.painter_options.items():
                    if x + ICON_SIZE <= CAM_WIDTH and y + ICON_SIZE <= CAM_HEIGHT:
                        painter_img[y:y + ICON_SIZE, x:x + ICON_SIZE] = icon

                if len(lmList) > 8:
                    cx, cy = lmList[8][1:]
                    # select color/tool by pointing at icon
                    if fingers[1] and not any(fingers[2:]):
                        for name, ((x, y), _) in self.painter_options.items():
                            if x < cx < x + ICON_SIZE and y < cy < y + ICON_SIZE:
                                if name == "thick":
                                    self.brush_thickness = 20
                                    self.draw_color_name = "thick"
                                elif name == "thin":
                                    self.brush_thickness = 5
                                    self.draw_color_name = "thin"
                                elif name == "eraser":
                                    self.draw_color = (255, 255, 255)
                                    self.draw_color_name = "eraser"
                                else:
                                    self.draw_color = (0, 0, 255) if name == "red" else (
                                        0, 255, 0) if name == "green" else (255, 0, 0)
                                    self.draw_color_name = name
                                    self.last_color = self.draw_color
                                if self.draw_color_name != "eraser":
                                    self.draw_color = self.last_color

                    # drawing when index+middle are up
                    if fingers[1] and fingers[2]:
                        if self.xp == 0 and self.yp == 0:
                            self.xp, self.yp = cx, cy
                        cv2.line(self.img_canvas, (self.xp, self.yp),
                                 (cx, cy), self.draw_color, self.brush_thickness)
                        self.xp, self.yp = cx, cy
                    else:
                        self.xp, self.yp = 0, 0

                # overlay canvas onto painter_img
                frame = overlay_canvas_on_frame(painter_img, self.img_canvas)

            elif self.current_mode == "scroll":
                # 2 fingers -> scroll up, 3 fingers -> scroll down
                if fingers[1] and fingers[2] and not fingers[3]:
                    pyautogui.scroll(SCROLL_AMOUNT)
                elif fingers[1] and fingers[2] and fingers[3]:
                    pyautogui.scroll(-SCROLL_AMOUNT)

        # If not selecting mode, and we previously were, reset
        if not self.selecting_mode:
            self.hovered_icon = -1

        # Draw overlay info
        cv2.putText(frame, f"Mode: {self.current_mode}", (10, CAM_HEIGHT - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        # Convert to QImage and display
        qimg = cv2_to_qimage(frame)
        pix = QtGui.QPixmap.fromImage(qimg)
        self.video_label.setPixmap(pix)

    def _check_hover(self, index_pos):
        # index_pos: (x,y) in camera coordinates
        x_idx, y_idx = index_pos
        for i, (x, y) in enumerate(self.mode_icon_positions):
            if x < x_idx < x + ICON_SIZE and y < y_idx < y + ICON_SIZE:
                if self.hovered_icon == i:
                    if time.time() - self.hover_start > HOVER_HOLD:
                        mode = ["mouse", "volume", "painter", "scroll"][i]
                        self.set_mode(mode, user=False)
                        self.selecting_mode = False
                        self.hovered_icon = -1
                else:
                    self.hovered_icon = i
                    self.hover_start = time.time()
                return
        self.hovered_icon = -1

    def log(self, text: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{ts}] {text}")

    def closeEvent(self, event):
        # cleanup
        self.stop_capture()
        event.accept()


# --------------------- Run App ---------------------
def main():
    app = QtWidgets.QApplication(sys.argv)
    gui = GestureGui()
    gui.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
