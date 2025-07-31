# Combined Script: YOLOv5 Object Detection + PTZ Control + Contextual Bandit Metadata Logging + Web Carousel
# Author: Rydlr Cloud Services Ltd. | Moverse Team

import cv2
import torch
import requests
from requests.auth import HTTPDigestAuth
from datetime import datetime
import json
import os
from flask import Flask, render_template_string, send_from_directory
import threading

# Configuration: Camera and API
CAMERA_IP = "192.168.1.64"
USERNAME = "admin"
PASSWORD = "your_password"
RTSP_URL = f"rtsp://{USERNAME}:{PASSWORD}@{CAMERA_IP}/Streaming/Channels/101"
PTZ_URL = f"http://{CAMERA_IP}/ISAPI/PTZCtrl/channels/1/continuous"
OUTPUT_DIR = "./labeled_dataset/University_Way_Roundabout"
METADATA_PATH = os.path.join(OUTPUT_DIR, "contextual_bandit_metadata.json")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Load YOLOv5 model
model = torch.hub.load('ultralytics/yolov5', 'yolov5s')
model.classes = [2, 3, 5, 7]  # cars, motorcycles, buses, trucks

# PTZ control function (Hikvision ISAPI)
def move_ptz(pan_speed=0, tilt_speed=0, zoom_speed=0):
    xml_data = f"""
    <PTZData>
        <pan>{pan_speed}</pan>
        <tilt>{tilt_speed}</tilt>
        <zoom>{zoom_speed}</zoom>
    </PTZData>
    """
    response = requests.put(
        PTZ_URL,
        data=xml_data.strip(),
        auth=HTTPDigestAuth(USERNAME, PASSWORD),
        headers={"Content-Type": "application/xml"}
    )
    return response.status_code == 200

# Metadata logging function
def log_metadata(frame_id, label, bbox):
    metadata = {
        "frame_id": frame_id,
        "timestamp": datetime.utcnow().isoformat(),
        "label": label,
        "bbox": bbox,
        "action": "captured_frame"
    }
    with open(METADATA_PATH, 'a') as f:
        json.dump(metadata, f)
        f.write("\n")

# Object detection and labeling
def detect_and_label():
    cap = cv2.VideoCapture(RTSP_URL)
    frame_id = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        results = model(frame)
        detections = results.pandas().xyxy[0]

        for _, row in detections.iterrows():
            label = row['name']
            confidence = row['confidence']
            if confidence > 0.5:
                x1, y1, x2, y2 = map(int, [row['xmin'], row['ymin'], row['xmax'], row['ymax']])
                cropped = frame[y1:y2, x1:x2]
                filename = os.path.join(OUTPUT_DIR, f"frame_{frame_id}_{label}.jpg")
                cv2.imwrite(filename, cropped)
                log_metadata(frame_id, label, [x1, y1, x2, y2])

                # Simple PTZ centering
                center_x = (x1 + x2) // 2
                frame_center = frame.shape[1] // 2
                offset = center_x - frame_center
                pan_speed = int(offset / frame.shape[1] * 100)
                move_ptz(pan_speed=pan_speed, tilt_speed=0, zoom_speed=0)

        frame_id += 1

    cap.release()
    cv2.destroyAllWindows()

# Web carousel for live detections
app = Flask(__name__)

@app.route('/')
def gallery():
    images = os.listdir(OUTPUT_DIR)
    images = sorted(images, reverse=True)[:20]  # latest 20
    return render_template_string('''
    <html>
    <head>
    <style>
    body { background-color: #121212; color: white; font-family: sans-serif; }
    .carousel { display: flex; overflow-x: scroll; position: fixed; bottom: 0; height: 20vh; width: 100vw; background: rgba(0,0,0,0.6); }
    .carousel img { margin: 5px; height: 100%; border-radius: 8px; }
    </style>
    </head>
    <body>
        <h2>Recent Detections - University Way Roundabout</h2>
        <div class="carousel">
        {% for image in images %}
            <img src="/images/{{ image }}">
        {% endfor %}
        </div>
    </body>
    </html>
    ''', images=images)

@app.route('/images/<path:filename>')
def images(filename):
    return send_from_directory(OUTPUT_DIR, filename)

# Threading detection and webserver
if __name__ == '__main__':
    # RTSP stream check before launch
    test_cap = cv2.VideoCapture(RTSP_URL)
    if not test_cap.isOpened():
        print("[WARNING] RTSP Stream is not available. Please check camera connection.")
    else:
        print("[INFO] Starting object detection thread...")
        thread = threading.Thread(target=detect_and_label)
        thread.daemon = True
        thread.start()
        test_cap.release()

    print("[INFO] Starting Flask web server...")
    app.run(host='0.0.0.0', port=5000, debug=False)
