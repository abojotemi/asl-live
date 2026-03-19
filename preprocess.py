import os
import cv2
# Define directories
dataset_dir = 'dataset' # Directory containing the original dataset
processed_dir = 'cropped_dataset' # Directory to save cropped images
# Create processed dataset directory if it doesn't exist
if not os.path.exists(processed_dir):
os.makedirs(processed_dir)
# Letters representing subdirectories in the dataset
letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
# Rectangle coordinates (same as in collection.py)
RECT_X1, RECT_Y1 = 102, 102
RECT_X2, RECT_Y2 = 398, 398
def crop_images():
print("Cropping images...")
for letter in letters:
letter_dir = os.path.join(dataset_dir, letter)
processed_letter_dir = os.path.join(processed_dir, letter)
# Create subdirectory for cropped images
if not os.path.exists(processed_letter_dir):
os.makedirs(processed_letter_dir)
# Process images if the letter directory exists
if os.path.exists(letter_dir):
for img_name in os.listdir(letter_dir):
img_path = os.path.join(letter_dir, img_name)
if img_path.endswith(('.jpg', '.jpeg', '.png')):
# Read the image
img = cv2.imread(img_path)
if img is not None:
# Crop the image to the defined rectangle
cropped_img = img[RECT_Y1:RECT_Y2, RECT_X1:RECT_X2]
# Save the cropped image
processed_img_path = os.path.join(processed_letter_dir,
img_name)
cv2.imwrite(processed_img_path, cropped_img)
print("Cropping complete. Cropped images saved in:", processed_dir)
# Run the crop function
crop_images()