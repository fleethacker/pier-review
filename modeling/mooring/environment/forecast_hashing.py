"""Canonical content hashes for composed forecasts."""

import hashlib
import json

from pydantic import BaseModel


def canonical_bytes(value) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def component_content_sha256(component) -> str:
    payload = component.model_dump(mode="json") if isinstance(component, BaseModel) else dict(component)
    payload.pop("content_sha256", None)
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def manifest_revision(manifest) -> str:
    payload = manifest.model_dump(mode="json") if isinstance(manifest, BaseModel) else dict(manifest)
    payload.pop("revision", None)
    return "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest()
