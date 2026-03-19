import os
from tensorflow.keras.preprocessing.image import ImageDataGenerator #
type: ignore
from PIL import Image
import numpy as np
# Directories
input_dir = "cropped_dataset" # Folder with cropped images
output_dir =
"SignImages" # Folder to save resized and normalized images
# Parameters
target_size = (224, 224) # Use 224x224 for higher detail
batch_size = 32 # For training data generators
# Splitting Function
def split_dataset(input_dir, output_dir):
train_dir = os.path.join(output_dir, 'train')
val_dir = os.path.join(output_dir, 'validation')
test_dir = os.path.join(output_dir, 'test')
os.makedirs(train_dir, exist_ok=True)
os.makedirs(val_dir, exist_ok=True)
os.makedirs(test_dir, exist_ok=True)
for label in os.listdir(input_dir):
label_dir = os.path.join(input_dir, label)
if os.path.isdir(label_dir):
images = os.listdir(label_dir)
np.random.shuffle(images)
train_split = int(0.8 * len(images))
val_split = int(0.9 * len(images))
# Assign splits
train_images = images[:train_split]
val_images = images[train_split:val_split]
test_images = images[val_split:]
# Move to respective folders
for img in train_images:
os.makedirs(os.path.join(train_dir, label), exist_ok=True)
os.rename(os.path.join(label_dir, img), os.path.join(train_dir, label,
img))
for img in val_images:
os.makedirs(os.path.join(val_dir, label), exist_ok=True)
os.rename(os.path.join(label_dir, img), os.path.join(val_dir, label,
img))
for img in test_images:
os.makedirs(os.path.join(test_dir, label), exist_ok=True)
os.rename(os.path.join(label_dir, img), os.path.join(test_dir, label,
img))
print("Dataset split into train, validation, and test sets.")
# Data Augmentation
def create_generators(train_dir, val_dir, test_dir):
train_datagen = ImageDataGenerator(
rescale=1.0/255,
rotation_range=30,
width_shift_range=0.2,
height_shift_range=0.2,
shear_range=0.2,
zoom_range=0.2,
horizontal_flip=True,
fill_mode='nearest'
)
val_test_datagen = ImageDataGenerator(rescale=1.0/255)
train_generator = train_datagen.flow_from_directory(
train_dir,
target_size=target_size,
batch_size=batch_size,
class_mode='categorical'
)
val_generator = val_test_datagen.flow_from_directory(
val_dir,
target_size=target_size,
batch_size=batch_size,
class_mode='categorical'
)
test_generator = val_test_datagen.flow_from_directory(
test_dir,
target_size=target_size,
batch_size=batch_size,
class_mode='categorical'
)
return train_generator, val_generator, test_generator
# Run Preprocessing
split_dataset(input_dir, output_dir)
train_dir = os.path.join(output_dir, 'train')
val_dir = os.path.join(output_dir, 'validation')
test_dir = os.path.join(output_dir, 'test')
train_gen, val_gen, test_gen = create_generators(train_dir, val_dir, test_dir)
print("Preprocessing complete. Data generators are ready.")