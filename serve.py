#!/usr/bin/env python3
"""Serve the mapper and a shared, persistent workshop session.

People who open the printed address can start or join a session from Share.
Grouping classes and mappings are stored on disk and pushed to everyone
connected, as they change.

    python3 serve.py
    python3 serve.py --port 8731

Standard library only.
"""
from __future__ import annotations

import json
import os
import queue
import re
import secrets
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
ROOM_DIR = Path(os.environ.get("BER_ROOM_DIR", ROOT / ".data" / "rooms"))
HOST = os.environ.get("BER_HOST", "0.0.0.0")
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
CODE_RE = re.compile(r"^[a-z0-9]{4,12}$")
BUCKET_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
SCHEMA_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
BUILTIN_IDS = {
    "sampling", "samples", "processing", "processed", "datagen", "dataproc",
    "products", "site_meta", "sample_meta", "other",
}
PALETTE = {
    "sampling", "samples", "processed", "processing", "datagen", "dataproc",
    "products", "sitemeta", "samplemeta", "other",
}
BANDS = {"flow", "flow_tail", "meta"}
MAX_BODY = 2_000_000
MAX_CUSTOM = 40

_lock = threading.Lock()
_subscribers: list[dict] = []


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clip(value, n: int) -> str:
    if value is None:
        return ""
    text = str(value)
    return text[:n]


def sanitize_groups(raw) -> dict:
    overrides = {}
    custom = []
    src = raw.get("overrides") if isinstance(raw, dict) else None
    if isinstance(src, dict):
        for gid in BUILTIN_IDS:
            item = src.get(gid)
            if not isinstance(item, dict):
                continue
            label = _clip(item.get("label"), 80).strip()
            short = _clip(item.get("short"), 24).strip()
            desc = _clip(item.get("desc"), 400) if isinstance(item.get("desc"), str) else ""
            if label or short or isinstance(item.get("desc"), str):
                overrides[gid] = {"label": label or gid, "short": short or gid, "desc": desc}
    seen = set(BUILTIN_IDS)
    items = raw.get("custom") if isinstance(raw, dict) else None
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict) or len(custom) >= MAX_CUSTOM:
                continue
            gid = str(item.get("id") or "")
            if not BUCKET_RE.match(gid) or gid in seen:
                continue
            label = _clip(item.get("label"), 80).strip()
            if not label:
                continue
            seen.add(gid)
            custom.append({
                "id": gid,
                "label": label,
                "short": _clip(item.get("short"), 24).strip() or label[:24],
                "desc": _clip(item.get("desc"), 400) if isinstance(item.get("desc"), str) else "",
                "color": item.get("color") if item.get("color") in PALETTE else "other",
                "band": item.get("band") if item.get("band") in BANDS else "meta",
            })
    return {"overrides": overrides, "custom": custom}


def sanitize_mappings(raw) -> dict:
    out = {}
    if not isinstance(raw, dict):
        return out
    for schema, classes in raw.items():
        if not isinstance(schema, str) or not SCHEMA_RE.match(schema) or not isinstance(classes, dict):
            continue
        kept = {}
        for name, item in classes.items():
            if not isinstance(name, str) or not isinstance(item, dict) or not name or len(name) > 200:
                continue
            bucket = item.get("bucket")
            if not isinstance(bucket, str) or not BUCKET_RE.match(bucket):
                continue
            target = item.get("target")
            if not isinstance(target, str) or not target:
                target = None
            elif len(target) > 200:
                target = target[:200]
            notes = item.get("notes") if isinstance(item.get("notes"), str) else ""
            ts = item.get("ts")
            kept[name] = {
                "bucket": bucket,
                "target": target,
                "notes": notes[:2000],
                "ts": int(ts) if isinstance(ts, (int, float)) else 0,
            }
        out[schema] = kept
    return out


def _broadcast(code: str, event: dict) -> None:
    with _lock:
        targets = [s for s in _subscribers if s["code"] == code]
    for sub in targets:
        sub["q"].put(event)


def apply_op(state: dict, op: dict) -> None:
    kind = op.get("type")
    groups = state["groups"]
    mappings = state["mappings"]
    if kind == "map":
        schema, name = op.get("schema"), op.get("class")
        if not isinstance(schema, str) or not isinstance(name, str):
            raise ValueError("map needs a schema and class")
        mappings.setdefault(schema, {})[name] = {
            "bucket": op.get("bucket"),
            "target": op.get("target"),
            "notes": op.get("notes") or "",
            "ts": op.get("ts") or 0,
        }
        state["mappings"] = sanitize_mappings(mappings)
    elif kind == "unmap":
        schema, name = op.get("schema"), op.get("class")
        classes = mappings.get(schema)
        if isinstance(classes, dict) and isinstance(name, str):
            classes.pop(name, None)
    elif kind == "clear-schema":
        schema = op.get("schema")
        if isinstance(schema, str):
            mappings[schema] = {}
    elif kind == "override":
        gid = op.get("id")
        if gid not in BUILTIN_IDS:
            raise ValueError("unknown grouping class")
        if op.get("override") is None:
            groups["overrides"].pop(gid, None)
        else:
            groups["overrides"][gid] = op.get("override")
        state["groups"] = sanitize_groups(groups)
    elif kind == "overrides":
        groups["overrides"] = op.get("overrides") if isinstance(op.get("overrides"), dict) else {}
        state["groups"] = sanitize_groups(groups)
    elif kind == "upsert":
        group = op.get("group")
        if not isinstance(group, dict):
            raise ValueError("upsert needs a group")
        custom = [c for c in groups["custom"] if c.get("id") != group.get("id")]
        custom.append(group)
        groups["custom"] = custom
        state["groups"] = sanitize_groups(groups)
    elif kind == "delete-group":
        gid = op.get("id")
        if not isinstance(gid, str):
            raise ValueError("delete needs an id")
        if gid in BUILTIN_IDS:
            raise ValueError("built-in grouping classes stay")
        groups["custom"] = [c for c in groups["custom"] if c.get("id") != gid]
        for classes in mappings.values():
            if not isinstance(classes, dict):
                continue
            for item in classes.values():
                if isinstance(item, dict) and item.get("bucket") == gid:
                    item["bucket"] = "other"
                    item["target"] = None
        state["groups"] = sanitize_groups(groups)
        state["mappings"] = sanitize_mappings(mappings)
    elif kind == "snapshot":
        state["groups"] = sanitize_groups(op.get("groups"))
        state["mappings"] = sanitize_mappings(op.get("mappings"))
    else:
        raise ValueError("unknown change")


def _room_path(code: str) -> Path:
    return ROOM_DIR / f"{code}.json"


def load_room(code: str) -> dict | None:
    path = _room_path(code)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data["code"] = code
    data["groups"] = sanitize_groups(data.get("groups"))
    data["mappings"] = sanitize_mappings(data.get("mappings"))
    data["rev"] = int(data.get("rev") or 0)
    return data


def save_room(state: dict) -> None:
    ROOM_DIR.mkdir(parents=True, exist_ok=True)
    path = _room_path(state["code"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)


def _new_code() -> str:
    for _ in range(30):
        code = "".join(secrets.choice(ALPHABET) for _ in range(6))
        if not _room_path(code).exists():
            return code
    raise RuntimeError("could not allocate a session code")


def _people(code: str) -> list[dict]:
    return [{"client": s["client"], "name": s["name"]} for s in _subscribers if s["code"] == code]


def _clean_name(value: str | None) -> str:
    name = _clip(value or "", 40).strip()
    name = "".join(ch for ch in name if ch.isprintable())
    return name or "Someone"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "BERSchemaMapper/1.0"

    def log_message(self, fmt: str, *args) -> None:
        if len(args) > 1 and str(args[1]) == "200":
            return
        super().log_message(fmt, *args)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > MAX_BODY:
            raise ValueError("body too large")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode() or "{}")
        if not isinstance(data, dict):
            raise ValueError("expected an object")
        return data

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        parts = [unquote(p) for p in parsed.path.split("/") if p]
        if parts == ["api", "health"]:
            self._json(200, {"ok": True})
            return
        if len(parts) == 3 and parts[:2] == ["api", "rooms"] and CODE_RE.match(parts[2]):
            state = load_room(parts[2])
            if not state:
                self._json(404, {"error": "No session with that code"})
                return
            self._json(200, public_state(state))
            return
        if len(parts) == 4 and parts[:2] == ["api", "rooms"] and parts[3] == "events" and CODE_RE.match(parts[2]):
            self._events(parts[2], parse_qs(parsed.query))
            return
        self._static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        parts = [unquote(p) for p in parsed.path.split("/") if p]
        try:
            body = self._read_json()
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "Could not read that change"})
            return
        if parts == ["api", "rooms"]:
            self._create(body)
            return
        if len(parts) == 4 and parts[:2] == ["api", "rooms"] and parts[3] == "ops" and CODE_RE.match(parts[2]):
            self._op(parts[2], body)
            return
        self._json(404, {"error": "Not found"})

    def _create(self, body: dict) -> None:
        with _lock:
            code = _new_code()
            state = {
                "code": code,
                "rev": 1,
                "groups": sanitize_groups(body.get("groups")),
                "mappings": sanitize_mappings(body.get("mappings")),
                "updated_at": _now(),
            }
            save_room(state)
        self._json(200, public_state(state))

    def _op(self, code: str, body: dict) -> None:
        op = body.get("op")
        client = _clip(body.get("client"), 40) or "anon"
        if not isinstance(op, dict):
            self._json(400, {"error": "Missing change"})
            return
        with _lock:
            state = load_room(code)
            if not state:
                self._json(404, {"error": "No session with that code"})
                return
            try:
                apply_op(state, op)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            state["rev"] = int(state.get("rev") or 0) + 1
            state["updated_at"] = _now()
            save_room(state)
            people = _people(code)
            subs = [s for s in _subscribers if s["code"] == code]
        event = {"kind": "op", "rev": state["rev"], "client": client, "op": op, "people": people}
        for sub in subs:
            sub["q"].put(event)
        self._json(200, {"rev": state["rev"]})

    def _events(self, code: str, query: dict) -> None:
        state = load_room(code)
        if not state:
            self._json(404, {"error": "No session with that code"})
            return
        name = _clean_name((query.get("name") or [""])[0])
        client = _clip((query.get("client") or [""])[0], 40) or secrets.token_hex(4)
        sub = {"code": code, "name": name, "client": client, "q": queue.Queue()}
        with _lock:
            _subscribers.append(sub)
            people = _people(code)
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            self._sse({"kind": "state", **public_state(state), "people": people})
            _broadcast(code, {"kind": "presence", "people": people})
            while True:
                try:
                    event = sub["q"].get(timeout=15)
                except queue.Empty:
                    self._chunk(b": keepalive\n\n")
                    continue
                self._sse(event)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass
        finally:
            with _lock:
                if sub in _subscribers:
                    _subscribers.remove(sub)
                people = _people(code)
            _broadcast(code, {"kind": "presence", "people": people})

    def _chunk(self, data: bytes) -> None:
        self.wfile.write(f"{len(data):X}\r\n".encode() + data + b"\r\n")
        self.wfile.flush()

    def _sse(self, payload: dict) -> None:
        self._chunk(("data: " + json.dumps(payload, separators=(",", ":")) + "\n\n").encode())

    def _static(self, url_path: str) -> None:
        rel = unquote(url_path.split("?", 1)[0]).lstrip("/") or "index.html"
        if rel.endswith("/"):
            rel += "index.html"
        candidate = (ROOT / rel).resolve()
        root = ROOT.resolve()
        if not str(candidate).startswith(str(root)) or not candidate.is_file():
            self._json(404, {"error": "Not found"})
            return
        if any(part.startswith(".") for part in candidate.relative_to(root).parts):
            self._json(404, {"error": "Not found"})
            return
        data = candidate.read_bytes()
        kind = "text/html; charset=utf-8" if candidate.suffix == ".html" else "application/octet-stream"
        if candidate.suffix == ".js":
            kind = "text/javascript; charset=utf-8"
        if candidate.suffix == ".css":
            kind = "text/css; charset=utf-8"
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def public_state(state: dict) -> dict:
    return {
        "code": state["code"],
        "rev": state["rev"],
        "groups": state["groups"],
        "mappings": state["mappings"],
        "updated_at": state.get("updated_at"),
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Serve the BER schema mapper for a shared session")
    parser.add_argument("--port", type=int, default=int(os.environ.get("BER_PORT", "8731")))
    args = parser.parse_args()
    ROOM_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, args.port), Handler)
    httpd.daemon_threads = True
    print(f"BER Schema Mapper")
    print(f"  local   http://127.0.0.1:{args.port}/")
    lan = _lan_ip()
    if lan and lan != "127.0.0.1":
        print(f"  network http://{lan}:{args.port}/")
    print("Open Share in the header to start a session. Everyone on that address sees grouping classes and mappings as they change.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


def _lan_ip() -> str | None:
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return None


if __name__ == "__main__":
    main()
