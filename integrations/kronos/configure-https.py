"""Opt-in fix for the existing private Trading Lab HTTPS gateway.

Only /api/kronos/forecast gains POST. The original root location, Basic Auth,
headers and all other routes stay intact. Unknown configuration shapes fail
closed. No model, package, password file or systemd operation is performed.
"""
import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

CONFIG_PATH = Path("/etc/trading-lab-https/nginx.conf")
NGINX = "/usr/sbin/nginx"
ROUTE = "/api/kronos/forecast"
MARKER = "# Trading Lab Kronos: explicit forecast POST only"
MAX_CONFIG_BYTES = 128 * 1024
PROXY_DIRECTIVES = {
    "proxy_pass", "proxy_set_header", "proxy_http_version",
    "proxy_connect_timeout", "proxy_send_timeout", "proxy_read_timeout",
    "proxy_buffering", "proxy_buffer_size", "proxy_buffers",
    "proxy_busy_buffers_size", "proxy_request_buffering", "proxy_redirect",
    "proxy_pass_request_headers", "proxy_pass_request_body",
}


class ConfigError(Exception):
    """Safe diagnostic: never include configuration contents or credentials."""


@dataclass
class Token:
    value: str
    start: int
    end: int
    punctuation: bool = False


@dataclass
class Directive:
    words: list
    start: int
    end: int
    children: list | None = None
    opening: int | None = None
    closing: int | None = None

    @property
    def values(self):
        return [word.value for word in self.words]


def tokenize(source):
    """Keep source spans while ignoring braces in comments/quoted values."""
    tokens, i, size = [], 0, len(source)
    while i < size:
        if source[i].isspace():
            i += 1
            continue
        if source[i] == "#":
            end = source.find("\n", i)
            i = size if end < 0 else end + 1
            continue
        start, value = i, []
        if source[i] in "{};":
            tokens.append(Token(source[i], i, i + 1, True))
            i += 1
            continue
        quote = None
        while i < size:
            char = source[i]
            if char == "\\":
                if i + 1 >= size:
                    raise ConfigError("Unfinished escape in gateway configuration.")
                value.append(source[i + 1])
                i += 2
            elif quote:
                if char == quote:
                    quote = None
                else:
                    value.append(char)
                i += 1
            elif char in "\"'":
                quote = char
                i += 1
            elif char == "$" and i + 1 < size and source[i + 1] == "{":
                end = source.find("}", i + 2)
                if end < 0:
                    raise ConfigError("Unfinished variable in gateway configuration.")
                value.append(source[i:end + 1])
                i = end + 1
            elif char.isspace() or char in "{};#":
                break
            else:
                value.append(char)
                i += 1
        if quote:
            raise ConfigError("Unfinished quoted value in gateway configuration.")
        tokens.append(Token("".join(value), start, i))
    return tokens


def parse(source):
    tokens = tokenize(source)
    position = 0

    def block(nested=False):
        nonlocal position
        result = []
        while position < len(tokens):
            if tokens[position].punctuation and tokens[position].value == "}":
                if not nested:
                    raise ConfigError("Unexpected closing brace in gateway configuration.")
                return result
            words = []
            while position < len(tokens) and not tokens[position].punctuation:
                words.append(tokens[position])
                position += 1
            if not words or position >= len(tokens):
                raise ConfigError("Unsupported or incomplete gateway directive.")
            delimiter = tokens[position]
            position += 1
            if delimiter.value == ";":
                result.append(Directive(words, words[0].start, delimiter.end))
            elif delimiter.value == "{":
                children = block(True)
                if position >= len(tokens):
                    raise ConfigError("Unclosed gateway block.")
                closing = tokens[position]
                position += 1
                result.append(Directive(words, words[0].start, closing.end,
                                        children, delimiter.start, closing.start))
            else:
                raise ConfigError("Unexpected gateway directive delimiter.")
        if nested:
            raise ConfigError("Unclosed gateway block.")
        return result

    return block()


def named(nodes, name):
    return [node for node in nodes if node.values[0] == name]


def singleton(nodes, name):
    found = named(nodes, name)
    if len(found) != 1:
        raise ConfigError("Gateway requires exactly one verified " + name + " directive.")
    return found[0]


def expected_value(nodes, name, values):
    node = singleton(nodes, name)
    if node.children is not None or node.values != [name] + values:
        raise ConfigError("Gateway " + name + " does not match the supported configuration.")
    return node


def forecast_configuration(source):
    """Return a reviewed clone, or the original text if our clone already exists."""
    if "\x00" in source:
        raise ConfigError("NUL byte in gateway configuration.")
    main = parse(source)
    http = singleton(main, "http")
    if http.values != ["http"] or http.children is None:
        raise ConfigError("Unsupported gateway http block.")
    # Includes may hide another server or route. mime.types only defines types.
    for node in named(main, "include") + named(http.children, "include"):
        if node.values != ["include", "/etc/nginx/mime.types"] or node.children is not None:
            raise ConfigError("Gateway includes hide rules; manual review is required.")
    servers = []
    for node in named(http.children, "server"):
        if node.values != ["server"] or node.children is None:
            raise ConfigError("Unsupported gateway server block.")
        for listen in named(node.children, "listen"):
            if len(listen.values) > 1 and listen.values[1].split(":")[-1] == "8443":
                servers.append(node)
    if len(servers) != 1:
        raise ConfigError("Expected exactly one explicit HTTPS server on port 8443.")
    server = servers[0]
    listens = named(server.children, "listen")
    if len(listens) != 1 or listens[0].children is not None or listens[0].values != ["listen", "0.0.0.0:8443", "ssl"]:
        raise ConfigError("Unsupported HTTPS listen configuration.")
    for name in ("include", "if", "return", "rewrite"):
        if named(server.children, name):
            raise ConfigError("Gateway server has additional routing rules; manual review is required.")
    auth = singleton(server.children, "auth_basic")
    if auth.children is not None or len(auth.values) != 2 or auth.values[1].lower() == "off" or not auth.values[1] or "$" in auth.values[1]:
        raise ConfigError("Gateway must retain explicit server Basic Auth.")
    users = singleton(server.children, "auth_basic_user_file")
    if users.children is not None or len(users.values) != 2 or users.values[1] != "/etc/trading-lab-https/users":
        raise ConfigError("Gateway must retain its existing Basic Auth password-file directive.")
    for context in (http.children, server.children):
        if named(context, "satisfy"):
            expected_value(context, "satisfy", ["all"])
    roots = [node for node in named(server.children, "location") if node.values == ["location", "/"]]
    if len(roots) != 1 or roots[0].children is None:
        raise ConfigError("Expected exactly one plain root location.")
    root = roots[0]
    locations = named(server.children, "location")
    if any(node is not root and node.values != ["location", "=", ROUTE] for node in locations):
        raise ConfigError("Gateway has other location access rules; manual review is required.")
    for node in root.children:
        if node.values[0] != "limit_except" and (node.values[0] not in PROXY_DIRECTIVES or node.children is not None):
            raise ConfigError("Root location has unsupported rules; manual review is required.")
    expected_value(root.children, "proxy_pass", ["http://127.0.0.1:8787"])
    host = [node for node in named(root.children, "proxy_set_header") if len(node.values) > 1 and node.values[1].lower() == "host"]
    if len(host) != 1 or host[0].values != ["proxy_set_header", "Host", "127.0.0.1:8787"]:
        raise ConfigError("Root proxy must preserve the exact loopback Host header.")
    headers = named(root.children, "proxy_set_header")
    if any(len(node.values) != 3 for node in headers):
        raise ConfigError("Unsupported proxy header directive.")
    controls = [node for node in headers if node.values[1].lower() == "x-lab-control"]
    if len(controls) > 1 or any(node.values[2] != "$http_x_lab_control" for node in controls):
        raise ConfigError("Gateway may not replace the panel control header.")
    for context in (http.children, server.children):
        if named(context, "proxy_method") or named(context, "proxy_set_body"):
            raise ConfigError("Gateway has inherited request rewriting; manual review is required.")
    for name in ("proxy_pass_request_headers", "proxy_pass_request_body"):
        effective = "on"
        for context in (http.children, server.children, root.children):
            if named(context, name):
                directive = singleton(context, name)
                if directive.children is not None or len(directive.values) != 2:
                    raise ConfigError("Unsupported inherited request forwarding directive.")
                effective = directive.values[1]
        if effective != "on":
            raise ConfigError("Gateway must forward request headers and bodies.")
    limit = singleton(root.children, "limit_except")
    if limit.values != ["limit_except", "GET"] or limit.children is None or len(limit.children) != 1:
        raise ConfigError("Root location must have only limit_except GET with deny all.")
    expected_value(limit.children, "deny", ["all"])
    getter = limit.words[1]
    if source[getter.start:getter.end] != "GET":
        raise ConfigError("Unsupported quoted method guard.")
    body = source[root.opening + 1:root.closing]
    offset = getter.start - root.opening - 1
    clone_body = body[:offset] + "GET POST" + body[offset + len("GET"):]
    existing = [node for node in named(server.children, "location") if ROUTE in node.values[1:]]
    if existing:
        if (len(existing) != 1 or existing[0].values != ["location", "=", ROUTE]
                or existing[0].children is None
                or source[existing[0].opening + 1:existing[0].closing] != clone_body):
            raise ConfigError("Forecast location already exists with different rules; manual review is required.")
        before = source[:existing[0].start].rstrip()
        if not before.endswith(MARKER):
            raise ConfigError("Existing forecast location is not this helper's verified clone; manual review is required.")
        return source
    line_start = source.rfind("\n", 0, root.start) + 1
    indent = source[line_start:root.start]
    if indent.strip():
        raise ConfigError("Root location must begin on its own line.")
    newline = "\r\n" if "\r\n" in source else "\n"
    addition = (MARKER + newline + indent + "location = " + ROUTE + " {"
                + clone_body + "}" + newline + newline + indent)
    return source[:root.start] + addition + source[root.start:]


def read_configuration(path, root_owned=True):
    if not path.is_absolute() or path.resolve() != path:
        raise ConfigError("Gateway configuration path must be absolute and contain no symlinks.")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ConfigError("Refusing a symlink in the gateway configuration path.")
    if root_owned and any(parent.stat().st_uid != 0 or parent.stat().st_mode & 0o022 for parent in path.parents):
        raise ConfigError("Gateway configuration directories must be root-owned and not group/world writable.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_CONFIG_BYTES:
            raise ConfigError("Gateway configuration must be a small regular file.")
        if root_owned and (metadata.st_uid != 0 or metadata.st_mode & 0o022):
            raise ConfigError("Gateway configuration must be root-owned and not group/world writable.")
        data = stream.read(MAX_CONFIG_BYTES + 1)
    if len(data) > MAX_CONFIG_BYTES:
        raise ConfigError("Gateway configuration exceeds the supported size.")
    try:
        source = data.decode("utf-8")
    except UnicodeError as error:
        raise ConfigError("Gateway configuration must be UTF-8.") from error
    return source, metadata


def same_file(first, second):
    return all(getattr(first, key) == getattr(second, key)
               for key in ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_mtime_ns", "st_size"))


def run_nginx(arguments, runner):
    try:
        result = runner([NGINX] + arguments, capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise ConfigError("Target gateway Nginx command could not complete.") from error
    if result.returncode:
        raise ConfigError("Target gateway Nginx command failed (exit " + str(result.returncode) + ").")


def sync_directory(path):
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def temporary_file(path, data, metadata, backup=False):
    descriptor, name = tempfile.mkstemp(prefix=".nginx.conf.kronos-backup." if backup else ".nginx.conf.kronos-new.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            if hasattr(os, "fchown"):
                os.fchown(stream.fileno(), 0 if backup else metadata.st_uid, 0 if backup else metadata.st_gid)
            mode = 0o600 if backup else stat.S_IMODE(metadata.st_mode)
            if hasattr(os, "fchmod"):
                os.fchmod(stream.fileno(), mode)
            else:
                temporary.chmod(mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return temporary
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def configure(path=CONFIG_PATH, apply=False, runner=None, root_owned=True):
    runner = subprocess.run if runner is None else runner
    source, metadata = read_configuration(path, root_owned)
    candidate = forecast_configuration(source)
    run_nginx(["-t", "-c", str(path)], runner)
    if candidate == source:
        return "Forecast HTTPS route already verified; no files changed and no reload performed."
    if not apply:
        return "CHECK OK: only /api/kronos/forecast would gain POST; Basic Auth and the GET-only root location are preserved. Run again with --apply."
    current, current_metadata = read_configuration(path, root_owned)
    if current != source or not same_file(metadata, current_metadata):
        raise ConfigError("Gateway configuration changed during preflight; nothing was written.")
    original = source.encode("utf-8")
    backup = temporary_file(path, original, metadata, backup=True)
    sync_directory(path.parent)
    replacement, installed, reload_attempted = None, False, False
    try:
        replacement = temporary_file(path, candidate.encode("utf-8"), metadata)
        # Recheck after backup creation before replacing the live pathname.
        current, current_metadata = read_configuration(path, root_owned)
        if current != source or not same_file(metadata, current_metadata):
            raise ConfigError("Gateway configuration changed before replacement.")
        os.replace(replacement, path)
        installed = True
        sync_directory(path.parent)
        run_nginx(["-t", "-c", str(path)], runner)
        reload_attempted = True
        run_nginx(["-s", "reload", "-c", str(path)], runner)
    except (OSError, ConfigError, KeyboardInterrupt) as error:
        restored = not installed
        rollback_error = False
        if installed:
            try:
                rollback = temporary_file(path, original, metadata)
                os.replace(rollback, path)
                sync_directory(path.parent)
                restored = True
                if reload_attempted:
                    run_nginx(["-t", "-c", str(path)], runner)
                    run_nginx(["-s", "reload", "-c", str(path)], runner)
            except (OSError, ConfigError):
                rollback_error = True
        if replacement is not None:
            replacement.unlink(missing_ok=True)
        outcome = ("Live configuration left unchanged by helper." if not installed else
                   "Original configuration restored." if restored else "Automatic restoration failed.")
        if rollback_error:
            outcome += " Restored gateway reload could not be verified."
        raise ConfigError("HTTPS route was not applied. " + outcome + " Private backup: " + str(backup)) from error
    return "APPLIED: forecast POST enabled through the private HTTPS gateway. Original GET-only root location retained. Private backup: " + str(backup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--check", action="store_true", help="validate without changing files (default)")
    choice.add_argument("--apply", action="store_true", help="explicitly apply and reload only this gateway")
    args = parser.parse_args()
    if args.apply and (sys.platform != "linux" or not hasattr(os, "geteuid") or os.geteuid() != 0):
        parser.error("--apply requires root on Linux")
    try:
        print(configure(apply=args.apply))
    except (ConfigError, OSError) as error:
        print("Kronos HTTPS: " + (str(error) if isinstance(error, ConfigError) else "Gateway file operation failed."), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
