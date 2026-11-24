#!/usr/bin/env python3
"""Encrypt the speaker-points payload for the private page.

    SPEAKS_PASSPHRASE='...' python3 tools/speaks/encrypt.py      # or run without the variable and type it at the prompt

Reads  tools/speaks/out/speaks.plain.json  (gitignored, never committed)
Writes data/speaks.enc.json                (ciphertext only, safe to publish)

gzip -> PBKDF2-HMAC-SHA256 (600,000 iterations, random 16-byte salt) -> AES-256-GCM (random 12-byte IV).
The passphrase is never written anywhere and is never accepted as a command-line argument (it would land in shell
history). To rotate it, run this again with the new passphrase and commit the new data/speaks.enc.json."""
import base64, getpass, gzip, json, os, sys
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'out', 'speaks.plain.json')
DST = os.path.join(HERE, '..', '..', 'data', 'speaks.enc.json')
ITER = 600_000


def main():
    if len(sys.argv) > 1:
        sys.exit('No arguments: the passphrase comes from SPEAKS_PASSPHRASE or the prompt, never the command line.')
    pw = os.environ.get('SPEAKS_PASSPHRASE')
    if not pw:
        pw = getpass.getpass('Passphrase: ')
        if pw != getpass.getpass('Again: '):
            sys.exit('Passphrases do not match.')
    if len(pw) < 12:
        sys.exit('Passphrase too short: the ciphertext is public, so use at least 12 characters (4+ random words is better).')
    payload = json.load(open(SRC))
    plain = gzip.compress(json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8'), 9, mtime=0)
    salt, iv = os.urandom(16), os.urandom(12)
    k = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(pw.encode('utf-8'))
    ct = AESGCM(k).encrypt(iv, plain, None)
    b64 = lambda b: base64.b64encode(b).decode('ascii')
    env = {'v': 1, 'kdf': 'PBKDF2-SHA256', 'iter': ITER, 'gz': True, 'salt': b64(salt), 'iv': b64(iv), 'ct': b64(ct)}
    json.dump(env, open(DST, 'w'), separators=(',', ':'))
    print(f'wrote {os.path.relpath(DST)}: {len(plain):,} bytes compressed -> {os.path.getsize(DST):,} bytes encrypted envelope')


if __name__ == '__main__':
    main()
