import os
import shutil
from tkinter import Tk, filedialog
from PIL import Image

def resize_and_convert(input_path, output_path, size=(1024, 1024), quality=90):
    """Resize PNG to given size and convert to JPG."""
    with Image.open(input_path) as img:
        # Convert to RGB (JPEG doesn't support transparency)
        img = img.convert("RGB")
        img = img.resize(size, Image.LANCZOS)
        img.save(output_path, "JPEG", quality=quality)

def main():
    # Hide the Tkinter root window
    Tk().withdraw()

    # Select folder
    folder = filedialog.askdirectory(title="Select folder containing PNG files")
    if not folder:
        print("No folder selected. Exiting...")
        return

    folder_name = os.path.basename(folder)
    parent_dir = os.path.dirname(folder)

    # Backup folder for PNGs
    backup_folder = os.path.join(parent_dir, f"{folder_name}_PNG")
    os.makedirs(backup_folder, exist_ok=True)

    # Process PNG files
    count = 0
    for filename in os.listdir(folder):
        if filename.lower().endswith(".png"):
            input_path = os.path.join(folder, filename)
            backup_path = os.path.join(backup_folder, filename)
            output_filename = os.path.splitext(filename)[0] + ".jpg"
            output_path = os.path.join(folder, output_filename)

            try:
                # Move original PNG to backup
                shutil.move(input_path, backup_path)

                # Convert and save JPG in original folder
                resize_and_convert(backup_path, output_path)

                print(f"Converted: {filename} → {output_filename}")
                count += 1
            except Exception as e:
                print(f"Failed to convert {filename}: {e}")

    print(f"\nDone! Converted {count} PNG files to JPG in '{folder}'.")
    print(f"Original PNGs were moved to: '{backup_folder}'")

if __name__ == "__main__":
    main()
