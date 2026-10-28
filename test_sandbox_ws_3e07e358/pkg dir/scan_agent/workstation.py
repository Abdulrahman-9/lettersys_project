"""Per-user device pairing and status; credentials never authorize document access."""
import base64
import ctypes
import json
import logging
import os
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import __version__, config, naps2

logger = logging.getLogger(__name__)


class _Blob(ctypes.Structure):
    _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _protect(value, decrypt=False):
    if os.name != 'nt':
        raise OSError('Device credentials require Windows user protection (DPAPI)')
    buffer = ctypes.create_string_buffer(value)
    source = _Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = _Blob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [
        ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_Blob),
    ]
    operation.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel32.LocalFree(output.data)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class DeviceMonitor:
    def __init__(self):
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.thread = None
        self.path = Path(config.data_dir()) / 'workstation.json'
        self.nonce = secrets.token_urlsafe(24)
        self.error = ''
        self.last_contact = None
        self.scanner_state = 'unknown'
        self.scanner_names = []
        self.scanner_checked = None
        try:
            self.requires_pairing = config.requires_pairing()
        except (OSError, ValueError, AttributeError) as exc:
            logger.error('Cannot read managed-client setting: %s', exc)
            raise OSError('Cannot read agent configuration') from exc
        self.data = self._load()

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, self.path)

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            uuid.UUID(data['client_uuid'])
            if 'token' in data:
                raise ValueError('Unprotected token is not supported')
            if data.get('protected_token') and (
                not isinstance(data['protected_token'], str) or
                not isinstance(data.get('server_origin'), str)
            ):
                raise ValueError('Invalid saved device credentials')
            return data
        except FileNotFoundError:
            data = {'client_uuid': str(uuid.uuid4()), 'machine_name': socket.gethostname()}
            self._write(data)
            return data
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            # Never silently replace an existing device identity or its ownership.
            logger.error('Cannot load workstation identity: %s', exc)
            raise OSError('Cannot read device identity; ask the administrator to repair it') from exc

    def public_status(self):
        with self.lock:
            return {
                'ok': True, 'client_uuid': self.data['client_uuid'],
                'machine_name': self.data.get('machine_name', ''),
                'name': self.data.get('name', ''),
                'paired': bool(self.data.get('protected_token')),
                'registration_required': self.requires_pairing and not self.data.get('protected_token'),
                'server_origin': self.data.get('server_origin', ''),
                'last_contact': self.last_contact, 'error': self.error,
                'pair_nonce': self.nonce,
            }

    def pair(self, payload, origin):
        with self.lock:
            normalized = config.normalize_origin(origin)
            if not normalized or normalized[0] != 'https' or normalized not in config.ALLOWED_ORIGINS:
                raise ValueError('Pairing requires the configured HTTPS origin')
            if not isinstance(payload, dict) or set(payload) != {
                'client_uuid', 'server_origin', 'name', 'token', 'pair_nonce'
            }:
                raise ValueError('Invalid pairing data')
            if config.normalize_origin(payload['server_origin']) != normalized:
                raise ValueError('Pairing server must match the requesting origin')
            if payload['client_uuid'] != self.data['client_uuid']:
                raise ValueError('Device identity does not match')
            nonce = payload['pair_nonce']
            if not isinstance(nonce, str) or not secrets.compare_digest(nonce, self.nonce):
                raise ValueError('Pairing approval expired; check this device again')
            token = payload['token']
            if not isinstance(token, str) or len(token) != 43 or any(
                c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-'
                for c in token
            ):
                raise ValueError('Invalid device credential')
            name = payload['name']
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                raise ValueError('Invalid device name')
            updated = dict(self.data)
            updated.update(
                name=name, server_origin=origin.rstrip('/'),
                protected_token=base64.b64encode(_protect(token.encode('ascii'))).decode('ascii'),
            )
            self._write(updated)
            self.data = updated
            self.nonce = secrets.token_urlsafe(24)
            self.error = ''
            self.wake.set()
        self.check_server()
        return self.public_status()

    def observe_scanner(self, state, names=None):
        with self.lock:
            self.scanner_state = state
            self.scanner_names = (names or [])[:20]
            self.scanner_checked = time.monotonic()
        self.wake.set()

    def check_server(self):
        with self.lock:
            if not self.data.get('protected_token'):
                if self.requires_pairing:
                    self.error = 'Sign in to the company site and approve device pairing before scanning'
                    return False
                return True  # Existing, unpaired installations retain their previous behavior.
            try:
                origin = self.data['server_origin']
                normalized = config.normalize_origin(origin)
                if not normalized or normalized[0] != 'https' or normalized not in config.ALLOWED_ORIGINS:
                    raise ValueError('Saved server is not in the configured HTTPS allowlist')
                token = _protect(base64.b64decode(self.data['protected_token'], validate=True), decrypt=True)
                age = int(time.monotonic() - self.scanner_checked) if self.scanner_checked is not None else None
                state = self.scanner_state if age is not None and age <= 86400 else 'unknown'
                payload = {
                    'client_uuid': self.data['client_uuid'], 'agent_version': __version__,
                    'naps2_available': bool(naps2.locate_exe()), 'scanner_state': state,
                    'scanner_names': self.scanner_names if state == 'ready' else [],
                    'scanner_age_seconds': age if state != 'unknown' else None,
                }
                request = urllib.request.Request(
                    origin + '/books/workstations/api/heartbeat/',
                    data=json.dumps(payload).encode('utf-8'),
                    headers={'Authorization': 'Bearer ' + token.decode('ascii'),
                             'Content-Type': 'application/json'},
                    method='POST',
                )
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({}), _NoRedirect(),
                    urllib.request.HTTPSHandler(context=ssl.create_default_context())
                )
                with opener.open(request, timeout=5) as response:
                    data = json.loads(response.read(4096))
                    if response.status != 200 or not isinstance(data, dict) or data.get('ok') is not True:
                        raise ValueError('Server did not confirm device connection')
                self.last_contact = time.time()
                self.error = ''
                return True
            except (OSError, ValueError, urllib.error.URLError) as exc:
                self.error = 'Server connection or device authorization failed; sign in and check this device again'
                logger.error('Workstation connection check failed: %s', exc)
                return False

    def start(self):
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self._run, name='lettersys-device-status', daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stopping.is_set():
            self.wake.clear()
            self.check_server()
            self.wake.wait(30)

    def stop(self):
        self.stopping.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join(timeout=6)
