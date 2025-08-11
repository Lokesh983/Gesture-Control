import cv2
import numpy as np
import pyautogui
import time
import os
from datetime import datetime
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from HandTrackingModule import handDetector

# --------------------- Constants ---------------------
CAM_WIDTH = 640
CAM_HEIGHT = 480
ICON_SIZE = 100
SCROLL_AMOUNT = 40
SCROLL_SLEEP = 0.1
CLICK_SLEEP = 0.3
MODE_SELECT_HOLD = 2
SCREENSHOT_HOLD = 2
HOVER_HOLD = 1

# --------------------- Setup ---------------------
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
cap.set(3, CAM_WIDTH)
cap.set(4, CAM_HEIGHT)

detector = handDetector(detectionCon=0.8, maxHands=1)
screen_width, screen_height = pyautogui.size()

xp, yp = 0, 0
brush_thickness = 10
draw_color = (0, 0, 255)
draw_color_name = "red"
last_color = draw_color
img_canvas = np.ones((CAM_HEIGHT, CAM_WIDTH, 3), np.uint8) * 255  # White canvas

# Mode Icons
icon_folder = "Icons"
icon_names = ["mouse.png", "volume.png", "painter.png", "scroll.png"]
mode_icons = []
for name in icon_names:
    icon = cv2.imread(f"{icon_folder}/{name}")
    if icon is None:
        print(f"[Warning] Icon {name} not found in {icon_folder}")
        icon = np.ones((ICON_SIZE, ICON_SIZE, 3), np.uint8) * 128  # Placeholder gray icon
    mode_icons.append(icon)
mode_icon_positions = [(40, 20), (180, 20), (320, 20), (460, 20)]

# Painter Icons
painter_icon_folder = "PainterIcons"
painter_icon_names = ["red.png", "green.png", "blue.png", "thick.png", "thin.png", "eraser.png"]
painter_icons = []
for name in painter_icon_names:
    icon = cv2.imread(f"{painter_icon_folder}/{name}")
    if icon is None:
        print(f"[Warning] Painter icon {name} not found in {painter_icon_folder}")
        icon = np.ones((ICON_SIZE, ICON_SIZE, 3), np.uint8) * 128
    painter_icons.append(icon)
# Adjusted positions so all 6 icons fit within 640px width
painter_icon_positions = [(10, 20), (115, 20), (220, 20), (325, 20), (430, 20), (535, 20)]
painter_options = dict(zip(
    ["red", "green", "blue", "thick", "thin", "eraser"],
    zip(painter_icon_positions, painter_icons)
))

# Volume setup
try:
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    vol_min, vol_max = volume.GetVolumeRange()[:2]
except Exception as e:
    print(f"[Error] Audio device initialization failed: {e}")
    volume = None
    vol_min, vol_max = 0, 100

# States
prev_time = 0
select_mode_start = 0
screenshot_start = 0
hover_start = 0
hovered_icon = -1
current_mode = "mouse"
selecting_mode = False
click_armed = False

if not os.path.exists("Screenshots"):
    os.makedirs("Screenshots")


# --------------------- Helper Functions ---------------------
def draw_overlay_info(img, fingers, fps):
    cv2.putText(img, f"Mode: {current_mode}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    cv2.putText(img, f"FPS: {int(fps)}", (10, 50),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)


def check_hover(index_pos):
    global hovered_icon, hover_start, current_mode, selecting_mode
    for i, (x, y) in enumerate(mode_icon_positions):
        if x < index_pos[0] < x + ICON_SIZE and y < index_pos[1] < y + ICON_SIZE:
            if hovered_icon == i:
                if time.time() - hover_start > HOVER_HOLD:
                    current_mode = ["mouse", "volume", "painter", "scroll"][i]
                    selecting_mode = False
            else:
                hovered_icon = i
                hover_start = time.time()
            return
    hovered_icon = -1


def overlay_canvas(img, canvas):
    """Overlay the canvas on top of the webcam feed with transparency."""
    mask = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    _, mask_inv = cv2.threshold(mask, 250, 255, cv2.THRESH_BINARY_INV)
    mask_inv = cv2.cvtColor(mask_inv, cv2.COLOR_GRAY2BGR)
    img = cv2.bitwise_and(img, 255 - mask_inv)
    img = cv2.add(img, cv2.bitwise_and(canvas, mask_inv))
    return img


# --------------------- Main Loop ---------------------
while True:
    success, img = cap.read()
    if not success:
        print("[Warning] Camera frame not received.")
        time.sleep(0.1)
        continue

    img = cv2.flip(img, 1)
    img = detector.findHands(img)
    lmList = detector.findPosition(img, draw=True)
    fingers = detector.fingersUp() if lmList else [0, 0, 0, 0, 0]

    cTime = time.time()
    fps = 1 / (cTime - prev_time) if cTime != prev_time else 0
    prev_time = cTime

    if lmList:  # Only process gestures if hand is detected
        # Screenshot: fist for 2 seconds
        if fingers == [0, 0, 0, 0, 0]:
            if screenshot_start == 0:
                screenshot_start = cTime
            elif cTime - screenshot_start >= SCREENSHOT_HOLD:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                pyautogui.screenshot(f"Screenshots/screenshot_{ts}.png")
                print(f"[Screenshot] Saved screenshot_{ts}.png")
                screenshot_start = 0
        else:
            screenshot_start = 0

        # Mode selection: 5 fingers for 2 sec
        if sum(fingers) == 5:
            if select_mode_start == 0:
                select_mode_start = cTime
            elif cTime - select_mode_start > MODE_SELECT_HOLD:
                selecting_mode = True
        else:
            select_mode_start = 0

        if selecting_mode:
            for i, (x, y) in enumerate(mode_icon_positions):
                icon = mode_icons[i]
                img[y:y + ICON_SIZE, x:x + ICON_SIZE] = cv2.resize(icon, (ICON_SIZE, ICON_SIZE))
            if len(lmList) > 8:
                check_hover(lmList[8][1:])

        elif current_mode == "mouse" and len(lmList) > 12:
            ix, iy = lmList[8][1:]
            mx, my = lmList[12][1:]

            # Cursor move
            if fingers[1] and not any(fingers[2:]):
                sx = np.interp(ix, (0, CAM_WIDTH), (0, screen_width))
                sy = np.interp(iy, (0, CAM_HEIGHT), (0, screen_height))
                pyautogui.moveTo(sx, sy)

            # Click gestures
            if fingers[1] and fingers[2]:
                click_armed = True
            elif click_armed:
                if not fingers[1] and fingers[2]:  # index dipped
                    pyautogui.click(button="left")
                    click_armed = False
                elif not fingers[1] and not fingers[2]:  # both dipped
                    pyautogui.click(button="right")
                    click_armed = False
                # Use a timer instead of sleep for responsiveness

        elif current_mode == "volume" and len(lmList) > 8 and volume is not None:
            length, _, _ = detector.findDistance(4, 8, img, draw=True)
            vol = np.interp(length, [20, 200], [vol_min, vol_max])
            volume.SetMasterVolumeLevel(vol, None)
            vol_bar = np.interp(length, [20, 200], [400, 150])
            cv2.rectangle(img, (50, 150), (85, 400), (0, 255, 0), 2)
            cv2.rectangle(img, (50, int(vol_bar)), (85, 400), (0, 255, 0), cv2.FILLED)

        elif current_mode == "painter":
            # Overlay painter icons on top of the webcam feed (no white background)
            painter_img = img.copy()
            for name, ((x, y), icon) in painter_options.items():
                # Bounds check to prevent array out of bounds crash
                if x + ICON_SIZE <= CAM_WIDTH and y + ICON_SIZE <= CAM_HEIGHT:
                    painter_img[y:y + ICON_SIZE, x:x + ICON_SIZE] = cv2.resize(icon, (ICON_SIZE, ICON_SIZE))
                else:
                    continue

            if len(lmList) > 8:
                cx, cy = lmList[8][1:]
                if fingers[1] and not any(fingers[2:]):
                    for name, ((x, y), _) in painter_options.items():
                        if x < cx < x + ICON_SIZE and y < cy < y + ICON_SIZE:
                            if name == "thick":
                                brush_thickness = 20
                                draw_color_name = "thick"
                            elif name == "thin":
                                brush_thickness = 5
                                draw_color_name = "thin"
                            elif name == "eraser":
                                draw_color = (255, 255, 255)
                                draw_color_name = "eraser"
                            else:
                                draw_color = (0, 0, 255) if name == "red" else (0, 255, 0) if name == "green" else (255, 0, 0)
                                draw_color_name = name
                                last_color = draw_color
                            # If switching from eraser to color, restore last color
                            if draw_color_name != "eraser":
                                draw_color = last_color

                if fingers[1] and fingers[2]:
                    if xp == 0 and yp == 0:
                        xp, yp = cx, cy
                    cv2.line(img_canvas, (xp, yp), (cx, cy), draw_color, brush_thickness)
                    xp, yp = cx, cy
                else:
                    xp, yp = 0, 0

            # Overlay the canvas (drawing) on the webcam feed with icons
            img = overlay_canvas(painter_img, img_canvas)

            # --- Save the paint if 's' is pressed ---
            key = cv2.waitKey(1) & 0xFF
            if key == ord('s'):
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                cv2.imwrite(f"Screenshots/paint_{ts}.png", img_canvas)
                print(f"[Painter] Saved paint_{ts}.png")

        elif current_mode == "scroll":
            if fingers[1] and fingers[2] and not fingers[3]:  # 2 fingers up
                pyautogui.scroll(SCROLL_AMOUNT)
                # Use a timer or state flag instead of sleep for responsiveness
            elif fingers[1] and fingers[2] and fingers[3]:  # 3 fingers up
                pyautogui.scroll(-SCROLL_AMOUNT)
                # Use a timer or state flag instead of sleep for responsiveness

    draw_overlay_info(img, fingers, fps)
    cv2.imshow("Gesture Controller", img)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
