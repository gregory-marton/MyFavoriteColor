import binascii

def hexlify(data):
    return binascii.hexlify(data)

def unhexlify(data):
    return binascii.unhexlify(data)
