"""
tools to determin python versions and download source code and signatures
"""
try:
    import requests
    from packaging.version import Version
except ImportError:
    raise RuntimeError("Required dependencies not found. Please pip install relenv[pyversions]")

from relenv.common import fetch_url_content

import subprocess
import logging
import re


KEYSERVERS = [
    "keyserver.ubuntu.com",
    "keys.openpgp.org",
    "pgp.mit.edu",
]


def ref_version(x):
    _ = x.split("Python ", 1)[1].split("<", 1)[0]
    return Version(_)

def ref_path(x):
    return x.split('href="')[1].split('"')[0]


ARCHIVE = "https://www.python.org/ftp/python/{version}/Python-{version}.{ext}"

def release_urls(version, gzip=False):
    if gzip:
        tarball = f"https://www.python.org/ftp/python/{version}/Python-{version}.tgz"
    else:
        tarball = f"https://www.python.org/ftp/python/{version}/Python-{version}.tar.xz"
    # No signatures prior to 2.3
    if version < Version("2.3"):
        return tarball, None
    return tarball, f"{tarball}.asc"


print("Get downloads page")
#reply = requests.get("https://www.python.org/downloads/")
content = fetch_url_content("https://www.python.org/downloads/")
print("Got downloads page")

matched = re.findall(rf'<a href="/downloads/.*">Python.*</a>', content)

versions = sorted([ref_version(_) for _ in matched], reverse=True)

def download_file(url):
    local_filename = url.split('/')[-1]
    # NOTE the stream=True parameter below
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(local_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=65032):
                # If you have chunk encoded response uncomment if
                # and set chunk_size parameter to None.
                #if chunk:
                f.write(chunk)
    return local_filename

def check_status(url):
    reply = requests.head(url)
    if reply.status_code != 200:
        print(f"Got {reply.status_code} for {url}")
        return False
    return True


def receive_key(keyid, server):
    proc = subprocess.run(["gpg", "--keyserver", server, "--recv-keys", keyid], capture_output=True)
    if proc.returncode == 0:
        return True
    return False

def get_keyid(proc):
    try:
        err = proc.stderr.decode()
        return err.splitlines()[1].rsplit(" ", 1)[-1]
    except (AttributeError, IndexError):
        return False

def verify_signature(path, signature):
    proc = subprocess.run(["gpg", "--verify", signature, path], capture_output=True)
    keyid = get_keyid(proc)
    if proc.returncode == 0:
        print(f"Valid signature {path} {keyid}")
        return True
    err = proc.stderr.decode()
    if "No public key" in err:
        for server in KEYSERVERS:
            if receive_key(keyid, server):
                print(f"found public key {keyid} on {server}")
                break
        else:
            print("Unable to find key {keyid}  on any server")
    else:
        print(f"Signature verification failed {proc.stderr.decode()}")
        return False
    proc = subprocess.run(["gpg", "--verify", signature, path], capture_output=True)
    if proc.returncode == 0:
        print(f"Valid signature {path} {signature}")
        return True
    err = proc.stderr.decode()
    print(f"Signature verification failed {proc.stderr.decode()}")
    return False

CHECK = True
VERSION = None # '3.13.2'

def main():
    for version in versions:
        if VERSION and Version(VERSION) != version:
            continue
        print(f"Check version {version}")

        # Prior to 3.2.0 the url format only included major and minor.
        if version <= Version('3.2') and version.micro == 0:
            version = Version(f"{version.major}.{version.minor}")

        # No xz archives prior to 3.1.4
        if version >= Version('3.1.4'):
            url = ARCHIVE.format(version=version, ext="tar.xz")
            if CHECK:
                check_status(url)
                check_status(f"{url}.asc")
            else:
                path = download_file(url)
                sig_path = download_file(f"{url}.asc")
                verify_signature(path, sig_path)

        url = ARCHIVE.format(version=version, ext="tgz")
        if CHECK:
            check_status(url)
            # No signatures prior to 2.3
            if version >= Version("2.3"):
                check_status(f"{url}.asc")
        else:
            path = download_file(url)
            if version >= Version("2.3"):
                sig_path = download_file(f"{url}.asc")
                verify_signature(path, sig_path)

if __name__ == "__main__":
    main()
