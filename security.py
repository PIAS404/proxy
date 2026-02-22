# security.py
from cryptography.fernet import Fernet

class CryptoBox:
    def __init__(self, fernet_secret: str):
        self.f = Fernet(fernet_secret.encode() if isinstance(fernet_secret, str) else fernet_secret)

    def enc(self, plaintext: str) -> str:
        return self.f.encrypt(plaintext.encode()).decode()

    def dec(self, ciphertext: str) -> str:
        return self.f.decrypt(ciphertext.encode()).decode()
