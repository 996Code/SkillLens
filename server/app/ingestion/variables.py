from app.ingestion.process import summarize_api


def param_variables(skeleton: list[dict], windows_per_session: list[tuple[str, list[dict]]]) -> list[dict]:
    windows_by_sid = dict(windows_per_session)
    out: list[dict] = []
    for step in skeletons_safe(skeleton):
        signature = step["signature"]
        values: dict[str, dict[str, str]] = {}
        for sid, window_seq in step.get("session_window_seqs", {}).items():
            windows = windows_by_sid.get(sid) or []
            if window_seq >= len(windows):
                continue
            for member in windows[window_seq].get("members") or []:
                for p in summarize_api(member).get("params") or []:
                    values.setdefault(p["name"], {})[sid] = str(p["value"])
        for param, per_session in values.items():
            if len(set(per_session.values())) > 1:
                out.append({"step": signature, "param": param, "values": per_session})
    return out


def skeletons_safe(skeleton: list[dict]) -> list[dict]:
    return [s for s in skeleton if isinstance(s, dict) and "signature" in s]


def input_variables(events_per_session: list[tuple[str, list[dict]]]) -> list[dict]:
    collected: dict[str, dict[str, list]] = {}
    positions: dict[str, dict[str, int]] = {}
    for sid, events in events_per_session:
        idx = 0
        for e in events:
            payload = e.get("payload") or {}
            if e.get("kind") != "action" or payload.get("type") != "input":
                continue
            name = payload.get("name")
            if not name:
                continue
            collected.setdefault(name, {}).setdefault(sid, []).append(str(payload.get("value")))
            positions.setdefault(name, {}).setdefault(sid, idx)
            idx += 1
    out: list[dict] = []
    for name, per_session in collected.items():
        first_vals = {sid: vals[0] for sid, vals in per_session.items()}
        if len(set(first_vals.values())) > 1:
            out.append({"name": name, "values": first_vals,
                        "positions": positions.get(name, {})})
    return out
