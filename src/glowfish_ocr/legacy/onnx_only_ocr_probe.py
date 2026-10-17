"""Standalone PP-OCRv6 ONNX probe, intentionally independent of Paddle/PaddleX.

This is a packaging feasibility probe, not a production OCR backend.  It keeps
the model-side preprocessing/postprocessing local so a future optional Worker
can be measured without importing Paddle or PaddleX.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
import pyclipper
import yaml


def _cuda_dll_handles():
    """Keep Windows DLL-directory handles alive for the whole process."""
    roots = (Path(sys.prefix) / "Lib" / "site-packages" / "nvidia", Path(sys.prefix) / "nvidia")
    paths = [path for root in roots if root.is_dir() for path in root.glob("*/bin") if path.is_dir()]
    if not paths:
        raise RuntimeError("bundled NVIDIA runtime DLL directories are missing")
    os.environ["PATH"] = os.pathsep.join([*(str(path) for path in paths), os.environ.get("PATH", "")])
    return [os.add_dll_directory(str(path)) for path in paths]


def _cuda_session(model: Path):
    session = ort.InferenceSession(str(model), providers=["CUDAExecutionProvider"])
    if "CUDAExecutionProvider" not in session.get_providers():
        raise RuntimeError(f"CUDAExecutionProvider did not load: {session.get_providers()}")
    return session


def _resize_det(image: np.ndarray, limit=4000, limit_type="max"):
    height, width = image.shape[:2]
    if limit_type == "min":
        ratio = max(1.0, limit / min(height, width))
    else:
        ratio = min(1.0, limit / max(height, width))
    resized_h, resized_w = max(32, round(height * ratio / 32) * 32), max(32, round(width * ratio / 32) * 32)
    resized = cv2.resize(image, (resized_w, resized_h)) if (resized_h, resized_w) != (height, width) else image
    return resized, resized_h / height, resized_w / width


def _det_tensor(image: np.ndarray):
    value = image.astype(np.float32) / 255.0
    value = (value - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array([0.229, 0.224, 0.225], dtype=np.float32)
    return np.transpose(value, (2, 0, 1))[None, ...]


def _mini_box(contour):
    rect = cv2.minAreaRect(contour)
    points = sorted(cv2.boxPoints(rect).tolist(), key=lambda point: point[0])
    left_top, left_bottom = (points[0], points[1]) if points[1][1] > points[0][1] else (points[1], points[0])
    right_top, right_bottom = (points[2], points[3]) if points[3][1] > points[2][1] else (points[3], points[2])
    return np.array([left_top, right_top, right_bottom, left_bottom], dtype=np.float32), min(rect[1])


def _box_score(bitmap, box):
    height, width = bitmap.shape
    xmin, xmax = max(0, math.floor(box[:, 0].min())), min(width - 1, math.ceil(box[:, 0].max()))
    ymin, ymax = max(0, math.floor(box[:, 1].min())), min(height - 1, math.ceil(box[:, 1].max()))
    mask = np.zeros((ymax - ymin + 1, xmax - xmin + 1), dtype=np.uint8)
    shifted = box.copy(); shifted[:, 0] -= xmin; shifted[:, 1] -= ymin
    cv2.fillPoly(mask, shifted.astype(np.int32)[None, ...], 1)
    return float(cv2.mean(bitmap[ymin:ymax + 1, xmin:xmax + 1], mask)[0])


def _unclip(box, ratio=1.4):
    distance = cv2.contourArea(box) * ratio / max(cv2.arcLength(box, True), 1e-6)
    offset = pyclipper.PyclipperOffset(); offset.AddPath(box, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    expanded = offset.Execute(distance)
    return np.asarray(expanded[0] if len(expanded) == 1 else [], dtype=np.float32)


def _detect(session, image, limit=4000, limit_type="max"):
    resized, ratio_h, ratio_w = _resize_det(image, limit, limit_type)
    bitmap = session.run(None, {session.get_inputs()[0].name: _det_tensor(resized)})[0][0, 0]
    contours, _ = cv2.findContours(((bitmap > 0.2).astype(np.uint8) * 255), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours[:3000]:
        box, side = _mini_box(contour)
        if side < 3 or _box_score(bitmap, box) < 0.45:
            continue
        expanded = _unclip(box)
        if len(expanded) < 4:
            continue
        box, side = _mini_box(expanded.reshape(-1, 1, 2))
        if side < 5:
            continue
        box[:, 0] = np.clip(np.rint(box[:, 0] / ratio_w), 0, image.shape[1] - 1)
        box[:, 1] = np.clip(np.rint(box[:, 1] / ratio_h), 0, image.shape[0] - 1)
        # PaddleX emits integer detection boxes before handing them to its crop
        # component.  Preserve that boundary so the direct route sees the same
        # geometry as the established OCR pipeline.
        boxes.append(box.astype(np.int16))
    return boxes


def _crop(image, box):
    # This is deliberately equivalent to PaddleX's get_rotate_crop_image().
    # Cropping details alter OCR logits, so "close enough" OpenCV defaults are
    # not suitable for a parity candidate.
    bounding_box = cv2.minAreaRect(np.asarray(box).astype(np.int32))
    points = sorted(list(cv2.boxPoints(bounding_box)), key=lambda point: point[0])
    if points[1][1] > points[0][1]:
        index_a, index_d = 0, 1
    else:
        index_a, index_d = 1, 0
    if points[3][1] > points[2][1]:
        index_b, index_c = 2, 3
    else:
        index_b, index_c = 3, 2
    points = np.asarray([points[index_a], points[index_b], points[index_c], points[index_d]], dtype=np.float32)
    width = max(1, int(max(np.linalg.norm(points[0] - points[1]), np.linalg.norm(points[2] - points[3]))))
    height = max(1, int(max(np.linalg.norm(points[0] - points[3]), np.linalg.norm(points[1] - points[2]))))
    transform = cv2.getPerspectiveTransform(points, np.float32([[0, 0], [width, 0], [width, height], [0, height]]))
    cropped = cv2.warpPerspective(image, transform, (width, height), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_CUBIC)
    if cropped.shape[0] / cropped.shape[1] >= 1.5:
        cropped = np.rot90(cropped)
    return cropped


def _sort_boxes(boxes):
    """Match PaddleX SortQuadBoxes before its six-crop recognition batches."""
    ordered = list(sorted(np.asarray(boxes), key=lambda box: (box[0][1], box[0][0])))
    for index in range(len(ordered) - 1):
        for previous in range(index, -1, -1):
            if abs(ordered[previous + 1][0][1] - ordered[previous][0][1]) < 10 and ordered[previous + 1][0][0] < ordered[previous][0][0]:
                ordered[previous], ordered[previous + 1] = ordered[previous + 1], ordered[previous]
            else:
                break
    return ordered


def _prepare_rec_image(image):
    # PaddleX's TextRecPredictor reads NumPy crop arrays as RGB before applying
    # RecResizeImg.  The document pipeline supplies BGR OpenCV crops.
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    height, width = image.shape[:2]
    max_wh_ratio = max(320 / 48, width / height)
    target_w = min(3200, int(48 * max_wh_ratio))
    resized_w = target_w if math.ceil(48 * width / height) > target_w else int(math.ceil(48 * width / height))
    resized = cv2.resize(image, (resized_w, 48)).astype(np.float32).transpose(2, 0, 1) / 255.0
    resized = (resized - 0.5) / 0.5
    tensor = np.zeros((3, 48, target_w), dtype=np.float32); tensor[:, :, :resized_w] = resized
    return tensor


def _recognize_batch(session, dictionary, images):
    tensors = [_prepare_rec_image(image) for image in images]
    widest = max(tensor.shape[2] for tensor in tensors)
    batch = np.zeros((len(tensors), 3, 48, widest), dtype=np.float32)
    for index, tensor in enumerate(tensors):
        batch[index, :, :, :tensor.shape[2]] = tensor
    logits_batch = session.run(None, {session.get_inputs()[0].name: batch})[0]
    results = []
    for logits in logits_batch:
        indices, scores = logits.argmax(axis=-1), logits.max(axis=-1)
        kept = [index for index, value in enumerate(indices) if value and (index == 0 or value != indices[index - 1])]
        results.append(("".join(dictionary[indices[index] - 1] for index in kept), float(np.mean(scores[kept])) if kept else 0.0))
    return results


@dataclass
class _Result:
    json: dict


class OnnxOnlyEngine:
    """PaddleOCR-compatible prediction surface for parity-only A/B runs."""

    def __init__(self, model_root: Path):
        self._dll_handles = _cuda_dll_handles()
        root = model_root / "ppocrv6_onnx"
        self.det = _cuda_session(root / "det" / "inference.onnx")
        self.rec = _cuda_session(root / "rec" / "inference.onnx")
        self.dictionary = yaml.safe_load((root / "rec" / "inference.yml").read_text(encoding="utf-8"))["PostProcess"]["character_dict"]

    def predict(self, image_path, **det):
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError(f"cannot read image: {image_path}")
        limit = int(det.get("text_det_limit_side_len") or 4000)
        limit_type = str(det.get("text_det_limit_type") or "max")
        boxes = _sort_boxes(_detect(self.det, image, limit=limit, limit_type=limit_type))
        texts, scores = [], []
        crops = [_crop(image, box) for box in boxes]
        for offset in range(0, len(crops), 6):
            for text, score in _recognize_batch(self.rec, self.dictionary, crops[offset:offset + 6]):
                texts.append(text); scores.append(score)
        return [_Result({"res": {"rec_texts": texts, "rec_scores": scores, "rec_polys": boxes}})]


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--image", required=True); parser.add_argument("--models-root", required=True)
    parser.add_argument("--parity-pipeline", action="store_true"); parser.add_argument("--high-accuracy", action="store_true")
    parser.add_argument("--baseline-json", help="require an exact line-text match against this established OCR result")
    args = parser.parse_args(); engine = OnnxOnlyEngine(Path(args.models_root))
    if args.parity_pipeline:
        import recognize_ppocrv6_onnx as established
        established.ACTIVE_DEVICE = "gpu:0"
        norm_dir = Path(args.image).parent / "onnx_only_norm"
        norm_dir.mkdir(parents=True, exist_ok=True)
        page = established.recognize_one(engine, args.image, norm_dir, "high_accuracy" if args.high_accuracy else None)
        page["ocr_meta"].update({"provider": "cuda", "requested_provider": "cuda", "backend": "onnx_only_probe"})
        if args.baseline_json:
            baseline = json.loads(Path(args.baseline_json).read_text(encoding="utf-8"))
            if isinstance(baseline, dict) and "lines" not in baseline:
                baseline = baseline.get(Path(args.image).stem) or baseline.get("1") or baseline
            expected = [str(line.get("text", "")) for line in baseline.get("lines", [])]
            actual = [str(line.get("text", "")) for line in page["lines"]]
            if actual != expected:
                raise RuntimeError(f"parity rejected: expected {len(expected)} exact lines, got {len(actual)}; text output differs")
        print(json.dumps(page, ensure_ascii=True)); return
    image = cv2.imread(args.image)
    if image is None: raise ValueError(f"cannot read image: {args.image}")
    boxes = _sort_boxes(_detect(engine.det, image))
    texts_scores = [item for offset in range(0, len(boxes), 6) for item in _recognize_batch(engine.rec, engine.dictionary, [_crop(image, box) for box in boxes[offset:offset + 6]])]
    lines = [{"text": text, "score": score, "box": box.round().astype(int).tolist()} for box, (text, score) in zip(boxes, texts_scores) if text]
    print(json.dumps({"provider": "cuda", "lines": lines}, ensure_ascii=True))


if __name__ == "__main__":
    main()
