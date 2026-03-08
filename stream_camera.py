#!/usr/bin/env python3
"""Focus Tool - HTTP MJPEG stream for headless camera focusing."""

import cv2
import sys
import os
import uvicorn
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import time

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.hardware.camera import Camera

app = FastAPI()
camera = Camera(device_id=0, width=1280, height=720)

def generate_frames():
    if not camera.open():
        print("Error: Could not open camera.")
        return

    try:
        while True:
            ret, frame = camera.read_frame()
            if not ret or frame is None:
                break
            
            # Encode frame to JPEG
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ret:
                continue
                
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            
            # Limit frame rate to save bandwidth/CPU
            time.sleep(0.05)
    finally:
        camera.close()

@app.get("/")
def video_feed():
    return StreamingResponse(generate_frames(), 
                             media_type="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    print("\n" + "="*60)
    print("Roz Focus Tool - Headless Mode")
    print("="*60)
    print("\nAccess the camera feed at: http://0.0.0.0:8080")
    print("Press Ctrl+C to stop.")
    print("\n" + "="*60 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
