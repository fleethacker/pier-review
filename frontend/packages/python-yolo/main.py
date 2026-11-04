import io
import os
import json
from typing import Optional, List
from functools import partial

import torch
_original_load = torch.load
torch.load = partial(_original_load, weights_only=False)

import numpy as np
from fastapi import FastAPI, UploadFile, File, Body
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from ultralytics import YOLO
from openai import OpenAI

app = FastAPI(title="YOLO Detection Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4000", "http://localhost:4001"],
    allow_methods=["*"],
    allow_headers=["*"],
)

model: Optional[YOLO] = None


@app.on_event("startup")
async def startup():
    global model
    model = YOLO("yolov8m-obb.pt")
    # Warm up with a dummy image
    dummy = np.zeros((640, 640, 3), dtype=np.uint8)
    model.predict(dummy, verbose=False)
    print("YOLO OBB (aerial) model loaded and warmed up")


@app.get("/health")
async def health():
    return {"status": "ok", "model": "yolov8m-obb"}


@app.post("/detect")
async def detect(image: UploadFile = File(...)):
    contents = await image.read()
    img = Image.open(io.BytesIO(contents)).convert("RGB")
    width, height = img.size

    # Very low base confidence to catch all vehicles
    results = model.predict(img, verbose=False, conf=0.05)

    # Vehicles have low threshold, everything else needs 70%+
    # Exact DOTA class names that should pass at low confidence
    LOW_CONF_CLASSES = {"small vehicle", "large vehicle"}
    DEFAULT_THRESHOLD = 0.70

    detections = []
    for result in results:
        # OBB models use result.obb instead of result.boxes
        if hasattr(result, 'obb') and result.obb is not None and len(result.obb) > 0:
            for obb in result.obb:
                cls_name = result.names[int(obb.cls[0])]
                conf = float(obb.conf[0])
                # Vehicles pass at low conf, everything else needs 70%+
                if cls_name not in LOW_CONF_CLASSES and conf < DEFAULT_THRESHOLD:
                    continue
                xyxy = obb.xyxy[0].tolist()
                x1, y1, x2, y2 = xyxy
                detections.append({
                    "class": cls_name,
                    "confidence": round(conf, 3),
                    "bbox": {
                        "x1": round(x1),
                        "y1": round(y1),
                        "x2": round(x2),
                        "y2": round(y2),
                    },
                })
        # Fallback to regular boxes if present
        elif hasattr(result, 'boxes') and result.boxes is not None and len(result.boxes) > 0:
            for box in result.boxes:
                cls_name = result.names[int(box.cls[0])]
                conf = float(box.conf[0])
                if cls_name in HIGH_CONF_CLASSES and conf < HIGH_CONF_THRESHOLD:
                    continue
                if cls_name in VERY_HIGH_CONF_CLASSES and conf < VERY_HIGH_CONF_THRESHOLD:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append({
                    "class": cls_name,
                    "confidence": round(conf, 3),
                    "bbox": {
                        "x1": round(x1),
                        "y1": round(y1),
                        "x2": round(x2),
                        "y2": round(y2),
                    },
                })

    return {
        "detections": detections,
        "image_width": width,
        "image_height": height,
    }


@app.post("/analyze")
async def analyze(data: dict = Body(...)):
    waypoints = data.get("waypoints", [])
    location = data.get("location", "Unknown location")

    # Build context for GPT
    wp_summaries = []
    for wp in waypoints:
        idx = wp.get("index", 0)
        lat = wp.get("lat", 0)
        lon = wp.get("lon", 0)
        detections = wp.get("detections", [])
        class_counts = {}
        for d in detections:
            cls = d.get("class", "unknown")
            class_counts[cls] = class_counts.get(cls, 0) + 1
        summary = ", ".join(f"{count} {cls}" for cls, count in class_counts.items()) or "no targets"
        wp_summaries.append(f"WP-{str(idx + 1).zfill(2)} ({lat:.4f}, {lon:.4f}): {summary}")

    prompt = f"""You are a military intelligence analyst reviewing drone ISR (Intelligence, Surveillance, Reconnaissance) mission results.

Mission location: {location}

Mission data from {len(waypoints)} scan points:
{chr(10).join(wp_summaries)}

Provide a concise operational intelligence report in JSON format:
{{
  "summary": "2-3 sentence assessment of the area based on detected objects",
  "threat_level": "low" or "medium" or "high",
  "recommendations": ["1-3 actionable recommendations"]
}}

Reference the mission location ({location}) in your assessment. Be specific about what was observed and its significance given the location. If vehicles or ships are detected, note potential military significance. If nothing was detected, note the area appears clear. Respond ONLY with valid JSON."""

    try:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            # Try loading from .env file at project root
            env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
            if os.path.exists(env_path):
                with open(env_path) as f:
                    for line in f:
                        if line.startswith("OPENAI_API_KEY="):
                            api_key = line.strip().split("=", 1)[1]
                            break

        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500,
        )
        content = response.choices[0].message.content.strip()
        # Parse JSON from response
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(content)
        return result
    except Exception as e:
        print(f"OpenAI analysis error: {e}")
        return {
            "summary": f"Automated analysis: {len(waypoints)} waypoints surveyed. Manual review recommended.",
            "threat_level": "low",
            "recommendations": ["Review ISR imagery manually", "Schedule follow-up reconnaissance"],
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5050)
