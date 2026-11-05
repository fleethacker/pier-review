"""Train a YOLO bollard detector from the Roboflow Universe "Bollards" dataset (CC BY 4.0, testing-0bbg4/bollards).

    uv pip install ultralytics roboflow
    ROBOFLOW_API_KEY=... python scripts/train_bollard_detector.py --version 7 --epochs 100
    # then:  BOLLARD_MODEL_PATH=models/bollard.pt make mock

Use --data DIR to train from an already-exported YOLOv8 dataset (containing data.yaml) instead of downloading.
Attribution: dataset author "Testing", https://universe.roboflow.com/testing-0bbg4/bollards, CC BY 4.0.
"""
import argparse
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', type=Path, help='existing YOLOv8-format dataset directory')
    ap.add_argument('--workspace', default='testing-0bbg4')
    ap.add_argument('--project', default='bollards')
    ap.add_argument('--version', type=int, default=7)
    ap.add_argument('--base', default='yolov8n.pt', help='pretrained starting weights')
    ap.add_argument('--epochs', type=int, default=100)
    ap.add_argument('--imgsz', type=int, default=640)
    ap.add_argument('--device', default=None, help="e.g. 0 for GPU, 'cpu'")
    ap.add_argument('--out', type=Path, default=ROOT / 'models' / 'bollard.pt')
    a = ap.parse_args()

    from ultralytics import YOLO
    if a.data is None:
        from roboflow import Roboflow
        key = os.environ.get('ROBOFLOW_API_KEY')
        if not key:
            raise SystemExit('Set ROBOFLOW_API_KEY (or pass --data)')
        a.data = Path(Roboflow(api_key=key).workspace(a.workspace).project(a.project).version(a.version)
                      .download('yolov8', location=str(ROOT / 'data' / 'raw' / 'bollards')).location)
    yaml = a.data / 'data.yaml'
    if not yaml.is_file():
        raise SystemExit(f'{yaml} not found')

    model = YOLO(a.base)
    model.train(data=str(yaml), epochs=a.epochs, imgsz=a.imgsz, device=a.device, project=str(ROOT / 'data' / 'runs'),
                name='bollard', exist_ok=True)
    metrics = model.val(data=str(yaml), split='test' if (a.data / 'test').is_dir() else 'val', device=a.device)
    print(f'precision={metrics.box.mp:.3f} recall={metrics.box.mr:.3f} mAP50={metrics.box.map50:.3f} mAP50-95={metrics.box.map:.3f}')
    best = ROOT / 'data' / 'runs' / 'bollard' / 'weights' / 'best.pt'
    a.out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(best, a.out)
    print(f'Wrote {a.out}')


if __name__ == '__main__':
    main()
