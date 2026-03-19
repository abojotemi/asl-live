import os
import psutil
from ai_edge_litert.interpreter import Interpreter
try:
    Interpreter(model_path="asl_word_light.tflite")
except Exception as e:
    print(e)
import tensorflow as tf
print(f"Memory used by tf import: {psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024:.2f} MB")
interpreter = tf.lite.Interpreter(model_path="asl_word_light.tflite")
interpreter.allocate_tensors()
print(f"Memory used after allocate_tensors: {psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024:.2f} MB")
print("OK")
