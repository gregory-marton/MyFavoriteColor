import random

def seed(n):
    random.seed(n)

def uniform(a, b):
    return random.uniform(a, b)

def choice(seq):
    return random.choice(seq)

def randint(a, b):
    return random.randint(a, b)

def getrandbits(n):
    return random.getrandbits(n)
