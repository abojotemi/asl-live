import os
from torchvision import datasets, transforms
from torch.utils.data import DataLoader, random_split
# Configuration
DATA_DIR = "SignImages"
BATCH_SIZE = 32
IMAGE_SIZE = (64, 64) # Resize images as needed
# Transformations (you can customize these)
transform = transforms.Compose([
transforms.Resize(IMAGE_SIZE),
transforms.ToTensor(),
transforms.Normalize(mean=[0.5], std=[0.5]) # adjust channels if RGB
])
# Load dataset from folder structure
dataset = datasets.ImageFolder(root=DATA_DIR, transform=transform)
# Split into train and validation sets
train_size = int(0.8 * len(dataset))
val_size = len(dataset) - train_size
train_dataset, val_dataset = random_split(dataset, [train_size, val_size])
# Create DataLoaders
train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE,
shuffle=True)
val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE, shuffle=False)
# Label mapping
class_names = dataset.classes # ['A', 'B', ..., 'Z']
print(f"Classes: {class_names}")
if __name__ == "__main__":
# Quick test to check one batch
images, labels = next(iter(train_loader))
print(f"Loaded batch of {len(images)} images. First 5 labels: {labels[:5]}")