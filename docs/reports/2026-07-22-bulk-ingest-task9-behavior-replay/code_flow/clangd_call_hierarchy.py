#!/usr/bin/env python3
"""Replay the fixture's clangd call-hierarchy query from its target cwd."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path.cwd()
SOURCE = ROOT / "source" / "runtime.cpp"


def send(process, payload):
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    process.stdin.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data)
    process.stdin.flush()


def receive(process, request_id):
    while True:
        headers = {}
        while True:
            line = process.stdout.readline()
            if not line:
                raise RuntimeError("clangd closed stdout")
            if line in (b"\r\n", b"\n"):
                break
            key, value = line.decode("ascii").split(":", 1)
            headers[key.lower()] = value.strip()
        response = json.loads(process.stdout.read(int(headers["content-length"])))
        if response.get("id") == request_id:
            if "error" in response:
                raise RuntimeError(response["error"])
            return response.get("result")


def request(process, request_id, method, params):
    send(process, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    return receive(process, request_id)


def callers(items):
    return [{"name": item["from"]["name"], "uri": Path(item["from"]["uri"]).name,
             "range": item["fromRanges"][0]} for item in items]


process = subprocess.Popen(["clangd", "--compile-commands-dir=.", "--log=error"], stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    request(process, 1, "initialize", {"processId": os.getpid(), "rootUri": ROOT.as_uri(),
            "capabilities": {"textDocument": {"callHierarchy": {"dynamicRegistration": False}}}})
    send(process, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
    send(process, {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {"textDocument": {
        "uri": SOURCE.as_uri(), "languageId": "cpp", "version": 1, "text": SOURCE.read_text(encoding="utf-8")}}})
    prepared = request(process, 2, "textDocument/prepareCallHierarchy", {"textDocument": {"uri": SOURCE.as_uri()},
                       "position": {"line": 2, "character": 5}})[0]
    transform_callers = request(process, 3, "callHierarchy/incomingCalls", {"item": prepared})
    dispatch_callers = request(process, 4, "callHierarchy/incomingCalls", {"item": transform_callers[0]["from"]})
    print(json.dumps({"prepare": {"name": prepared["name"], "symbol": "runtime::transform", "position": [2, 5]},
                      "incoming_transform": callers(transform_callers), "incoming_dispatch": callers(dispatch_callers)}))
finally:
    process.terminate()
    process.wait(timeout=3)
