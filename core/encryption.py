"""
Utility functions for encrypting and decrypting files using Fernet (symmetric encryption).
"""

from cryptography.fernet import Fernet, InvalidToken
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Generate a key file for encryption - stored securely in the project
ENCRYPTION_KEY_FILE = Path(__file__).resolve().parent.parent / '.encryption_key'

# Marker used by transparent string encryption (model fields).
ENCRYPTED_PREFIX = 'enc::'


def get_or_create_encryption_key():
    """Get the encryption key, creating it if it doesn't exist."""
    if ENCRYPTION_KEY_FILE.exists():
        return ENCRYPTION_KEY_FILE.read_bytes()
    else:
        # Generate a new key
        key = Fernet.generate_key()
        ENCRYPTION_KEY_FILE.write_bytes(key)
        ENCRYPTION_KEY_FILE.chmod(0o600)  # Restrict access to owner only
        logger.info("Created new encryption key for backups")
        return key


def encrypt_file(file_path):
    """
    Encrypt a file using Fernet encryption.
    
    Args:
        file_path: Path to the file to encrypt
        
    Returns:
        Path to the encrypted file (with .enc extension)
    """
    try:
        key = get_or_create_encryption_key()
        cipher = Fernet(key)
        
        file_path = Path(file_path)
        
        # Read the original file
        with open(file_path, 'rb') as f:
            original_data = f.read()
        
        # Encrypt the data
        encrypted_data = cipher.encrypt(original_data)
        
        # Save encrypted data to a new file
        encrypted_path = file_path.parent / f"{file_path.name}.enc"
        with open(encrypted_path, 'wb') as f:
            f.write(encrypted_data)
        
        # Delete the original unencrypted file
        file_path.unlink()
        
        logger.info(f"File encrypted successfully: {encrypted_path}")
        return encrypted_path
    except Exception as e:
        logger.error(f"Error encrypting file: {e}", exc_info=True)
        raise


def decrypt_file(encrypted_file_path, output_path=None):
    """
    Decrypt a file that was encrypted with Fernet encryption.
    
    Args:
        encrypted_file_path: Path to the encrypted file
        output_path: Where to save the decrypted file (default: remove .enc extension)
        
    Returns:
        Path to the decrypted file
    """
    try:
        key = get_or_create_encryption_key()
        cipher = Fernet(key)
        
        encrypted_file_path = Path(encrypted_file_path)
        
        if output_path is None:
            # Remove .enc extension
            output_path = Path(str(encrypted_file_path).replace('.enc', ''))
        else:
            output_path = Path(output_path)
        
        # Read encrypted data
        with open(encrypted_file_path, 'rb') as f:
            encrypted_data = f.read()
        
        # Decrypt the data
        decrypted_data = cipher.decrypt(encrypted_data)
        
        # Save decrypted data
        with open(output_path, 'wb') as f:
            f.write(decrypted_data)
        
        logger.info(f"File decrypted successfully: {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"Error decrypting file: {e}", exc_info=True)
        raise


# ════════════════════════════════════════════════════════════════════════════════
# Transparent string encryption for model fields (e.g., EmailSettings passwords)
# ════════════════════════════════════════════════════════════════════════════════

def encrypt_text(plaintext):
    """
    Encrypt a plaintext string with Fernet.
    
    Args:
        plaintext: str to encrypt (can be empty)
        
    Returns:
        Encrypted token with ENCRYPTED_PREFIX marker (format: "enc::base64token")
        Empty string if plaintext is empty.
    """
    if not plaintext:
        return ""
    try:
        key = get_or_create_encryption_key()
        cipher = Fernet(key)
        encrypted_bytes = cipher.encrypt(plaintext.encode('utf-8'))
        return ENCRYPTED_PREFIX + encrypted_bytes.decode('utf-8')
    except Exception as e:
        logger.error(f"Error encrypting text: {e}", exc_info=True)
        raise


def decrypt_text(encrypted_token):
    """
    Decrypt a Fernet-encrypted token with ENCRYPTED_PREFIX marker.
    
    Args:
        encrypted_token: str prefixed with ENCRYPTED_PREFIX
        
    Returns:
        Decrypted plaintext string, or empty string if token is empty.
        
    Raises:
        ValueError if token is invalid or decryption fails.
    """
    if not encrypted_token:
        return ""
    
    if not encrypted_token.startswith(ENCRYPTED_PREFIX):
        logger.warning("decrypt_text called on non-encrypted value; returning as-is")
        return encrypted_token
    
    try:
        key = get_or_create_encryption_key()
        cipher = Fernet(key)
        token = encrypted_token[len(ENCRYPTED_PREFIX):]
        decrypted_bytes = cipher.decrypt(token.encode('utf-8'))
        return decrypted_bytes.decode('utf-8')
    except InvalidToken as e:
        logger.error(f"Invalid encryption token: {e}", exc_info=True)
        raise ValueError(f"Failed to decrypt token: {e}")
    except Exception as e:
        logger.error(f"Error decrypting text: {e}", exc_info=True)
        raise


def is_encrypted(text):
    """Check if a string is encrypted (has ENCRYPTED_PREFIX marker)."""
    return isinstance(text, str) and text.startswith(ENCRYPTED_PREFIX)
