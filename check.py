# XXX Merge this into relenv.build.common.Download
import requests
from html.parser import HTMLParser
import re
from packaging.version import parse, Version, InvalidVersion


def tarball_version(href):
    if href.endswith("tar.gz"):
        try:
            x = href.split('-', 1)[1][:-7]
            if x != "latest":
                return x
        except IndexError:
            return None


def sqlite_version(href):
    if "releaselog" in href:
        link = href.split('/')[1][:-5]
        return "{:d}{:02d}{:02d}00".format(*[int(_) for _ in link.split('_')])


def ffi_version(href):
    if "tag/" in href:
        return href.split("/v")[-1]

def krb_version(href):
    if re.match("\d\.\d\d/", href):
        return href[:-1]

def python_version(href):
    if re.match("(\d+\.)+\d/", href):
        return href[:-1]

def uuid_version(href):
    if "download" in href and "latest" not in href:
        return href[:-16].rsplit('/')[-1].replace('libuuid-', '')

def parse_links(text):
    class HrefParser(HTMLParser):
        hrefs = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                link = dict(attrs).get("href", "")
                if link:
                    self.hrefs.append(link)

    parser = HrefParser()
    parser.feed(text)
    return parser.hrefs


def check_files(location, func, current):
    resp = requests.get(location)
    versions = []
    for _ in parse_links(resp.text):
        version = func(_)
        if version:
            #print('*' * 10)
            #print(repr(version))
            #print('*' * 10)
            try:
                versions.append(parse(version))
            except InvalidVersion:
                pass
    #print([i for i in versions])
    versions.sort()
    compare_versions(current, versions)

NOOP = object()

def compare_versions(current, versions):
    current = parse(current)
    for version in versions:
        #if s == "latest":
        #    continue
        #version = Version(s)
        try:
            if version > current:
                print(f"Found new version {version} > {current}")
#                return (version, current)
        except TypeError:
            print(f"Unable to compare versions {version}")
#            raise
#    return NOOP, NOOP


def check_named_versions(name, current, versions):
    version, current = check_versions
    if version == NOOP:
        return
    print(f"{name}: {version} > {current}")


print("openssl")
check_files("https://www.openssl.org/source/", tarball_version, "1.1.1")
print("xz")
check_files("http://tukaani.org/xz/", tarball_version, "5.4.1")
print("sqlite")
check_files("https://sqlite.org/", sqlite_version, "3400100")
print("bzip2")
check_files("https://sourceware.org/pub/bzip2/", tarball_version, "1.0.8")
print("gdbm")
check_files("https://ftp.gnu.org/gnu/gdbm/", tarball_version, "1.23")
print("ncurses")
check_files("https://ftp.gnu.org/pub/gnu/ncurses/", tarball_version, "6.4")
print("libffi")
check_files("https://github.com/libffi/libffi/releases/", ffi_version, "3.4.4")
print("zlib")
check_files("https://zlib.net/fossils/", tarball_version, "1.2.13")
print('krb')
check_files("https://kerberos.org/dist/krb5/", krb_version, "1.20")
print("libuuid")
check_files("https://sourceforge.net/projects/libuuid/files/", uuid_version, "1.0.3")
print("readline")
check_files("https://ftp.gnu.org/gnu/readline/", tarball_version, "8.2")
print("python")
check_files("https://www.python.org/ftp/python/", python_version, "3.10.9")
