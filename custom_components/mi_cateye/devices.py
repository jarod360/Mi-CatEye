"""Validated device catalog; names and client input never become source URLs."""
from __future__ import annotations

import re
from .media import MediaError, stream_configuration


def is_camera_model(model):
    return isinstance(model, str) and bool(re.fullmatch(r"[a-z0-9_]+\.(?:camera|cateye)\.[a-z0-9_]+", model))


def selected_cameras(data, options):
    rows = options.get("cameras", [])
    if not isinstance(rows, list) or len(rows) > 32:
        raise MediaError("invalid_camera_selection")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise MediaError("invalid_camera_selection")
        did, model = row.get("did"), row.get("model")
        if (not isinstance(did, str) or did == data["did"] or did in result
                or row.get("media_user_id") != data["media_user_id"] or not is_camera_model(model)):
            raise MediaError("invalid_camera_selection")
        stream_configuration(data["media_user_id"], data["region"], did, row.get("camera_host", ""), model=model)
        result[did] = {"did": did, "model": model, "media_user_id": data["media_user_id"],
                       "camera_host": row["camera_host"], "name": str(row.get("name") or model)[:80]}
    return result


def source_for(data, cameras, device=None, codec="h265"):
    if codec not in {"h265", "h264"}:
        raise MediaError("invalid_codec")
    if device is None or device == data["did"]:
        return "doorbell_live" if codec == "h265" else "doorbell_compatible"
    if device not in cameras:
        raise MediaError("camera_not_selected")
    return f"camera_{device}" + ("_compatible" if codec == "h264" else "")


def media_streams(data, cameras):
    result = stream_configuration(data["media_user_id"], data["region"], data["did"], data["camera_host"])
    for did, camera in cameras.items():
        name = f"camera_{did}"
        result[name] = stream_configuration(data["media_user_id"], data["region"], did,
                                             camera["camera_host"], model=camera["model"])["doorbell_live"]
        result[name + "_compatible"] = f"ffmpeg:{name}#video=h264#audio=opus"
    return result
