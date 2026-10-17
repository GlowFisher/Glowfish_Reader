"""Frozen entry point for the optional isolated CUDA OCR Worker.

It intentionally delegates to the locked PP-OCRv6 ONNX pipeline.  The runtime
bundle contains CUDA/cuDNN and onnxruntime-gpu, while the models are read from
the main application through ``model_root`` supplied in the JSON-lines config.
"""

from recognize_ppocrv6_onnx import main


if __name__ == "__main__":
    main()
