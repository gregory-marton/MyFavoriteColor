import os

def test_standalone_filesize_limit():
    # Path to standalone.py relative to the root directory
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    standalone_path = os.path.join(base_dir, "standalone.py")
    
    assert os.path.exists(standalone_path), "standalone.py does not exist"
    
    filesize = os.path.getsize(standalone_path)
    print(f"Current standalone.py size: {filesize} bytes")
    
    # 35k limit to leave headroom under the 36.4KB upload buffer limit
    MAX_SIZE_BYTES = 35000
    assert filesize <= MAX_SIZE_BYTES, f"standalone.py is {filesize} bytes, exceeding the {MAX_SIZE_BYTES} byte limit!"
