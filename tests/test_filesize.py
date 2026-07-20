import os

def test_manifest_filesize_limits():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    manifest_path = os.path.join(base_dir, "EngAI_MANIFEST.txt")
    
    assert os.path.exists(manifest_path), "EngAI_MANIFEST.txt does not exist"
    
    with open(manifest_path, 'r') as f:
        files = [line.strip() for line in f if line.strip()]
        
    MAX_SIZE_BYTES = 35000
    for filename in files:
        filepath = os.path.join(base_dir, filename)
        if os.path.exists(filepath):
            filesize = os.path.getsize(filepath)
            assert filesize <= MAX_SIZE_BYTES, f"{filename} is {filesize} bytes, exceeding the {MAX_SIZE_BYTES} byte limit!"
        else:
            print(f"Warning: {filename} in manifest not found locally.")
