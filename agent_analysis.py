import json
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from config import AI_CFG, DB
from imaging import assess_risk_level

try:
    import anthropic
except ImportError:
    anthropic = None


SYSTEM_PROMPT = """You are an assistant agent helping a radiologist review a \
brain MRI segmentation result. You are NOT analyzing any image and you are \
NOT making a diagnosis — you only ever reason over already-computed, \
pixel-derived numbers (segmentation areas, scan quality metrics, and a \
heuristic risk band) that are given to you as facts, plus whatever \
additional on-file data you retrieve yourself using your tools.

You have tools to look up this patient's past scan history and on-file \
profile in the hospital database. Use them when they would help — for \
example, to check for a longer trend across more than one prior scan, to \
see how scan quality (noise/density) has changed across visits, to see \
how the computed risk band has moved over time, or to confirm patient \
context — but you do not have to call every tool on every case; call only \
what's useful, and it's fine to call none if the case is a simple baseline \
with nothing on file.

Rules:
- Reference only numbers you were given or that a tool returned. Never invent measurements.
- Use hedged clinical language ("consistent with", "suggestive of", "warrants review").
- Every output must note this is a preliminary, automated estimate requiring radiologist confirmation — never a diagnosis.
- If you call get_scan_history and it returns multiple prior scans, you may describe the overall multi-visit trend (e.g. "area has increased across the last 3 scans"), not just a single previous-vs-current comparison.
- If you call get_quality_trend, note whether scan quality (noise/density) has been consistent across visits — a large quality swing can itself explain part of an area change and is worth flagging, not just the area numbers themselves.
- If you call get_risk_trend, describe whether the automated risk band has escalated, held steady, or de-escalated across visits — but always call it a heuristic band, never a diagnosis.
- If no history exists, say this is the baseline/first recorded phase.
- When you are done gathering information (or if you need nothing further), respond with ONLY valid JSON, no markdown fences, matching exactly:
  {"summary": "...", "historical_trend": "...", "quality_trend": "...", "risk_assessment": "...", "recommendations": ["...", "..."], "flags_for_review": ["...", "..."]}
- Do not include any text outside that JSON object in your final response.
"""

TOOLS = [
    {
        "name": "get_scan_history",
        "description": (
            "Fetch this patient's past encrypted-scan records from the hospital "
            "database (timestamps + segmentation areas in mm² for each prior "
            "visit), newest first. Use this to reason about a trend across more "
            "than one prior scan, not just a single previous phase."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "The Patient ID to look up."},
                "limit": {"type": "integer", "description": "Max records to return (default 10)."},
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "get_patient_profile",
        "description": (
            "Fetch this patient's on-file demographic profile (name, age, sex) "
            "from the hospital database, if one exists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "The Patient ID to look up."},
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "get_quality_trend",
        "description": (
            "Fetch this patient's scan-quality readout (tissue density %, noise "
            "level) for each past visit, newest first. Use this to check whether "
            "quality has been consistent across visits — a big swing in noise or "
            "density can partly explain an area change on its own, separate from "
            "any real tumor change. Only visits where quality was recorded are "
            "returned; older records may not have it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "The Patient ID to look up."},
                "limit": {"type": "integer", "description": "Max records to return (default 10)."},
            },
            "required": ["patient_id"],
        },
    },
    {
        "name": "get_risk_trend",
        "description": (
            "Fetch the automated heuristic risk band (Minimal/Low/Moderate/High/"
            "Critical) computed for each of this patient's past visits, newest "
            "first, along with total segmented area and necrotic %. Use this to "
            "see whether the risk band has escalated, held steady, or "
            "de-escalated over time — still a heuristic, not a diagnosis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string", "description": "The Patient ID to look up."},
                "limit": {"type": "integer", "description": "Max records to return (default 10)."},
            },
            "required": ["patient_id"],
        },
    },
]

MAX_TOOL_TURNS = 5


def _execute_tool(name: str, tool_input: dict) -> dict:
    if name == "get_scan_history":
        pid = tool_input.get("patient_id", "")
        limit = int(tool_input.get("limit", 10))
        records = DB.get_scans_by_patient(pid, limit=limit) if DB.connected else []
        return {
            "patient_id": pid,
            "count": len(records),
            "scans": [
                {"timestamp": r.get("timestamp", ""), "areas_mm2": r.get("areas_mm2", {})}
                for r in records
            ],
        }
    if name == "get_patient_profile":
        pid = tool_input.get("patient_id", "")
        rec = DB.get_patient(pid) if DB.connected else None
        return rec or {"patient_id": pid, "found": False}

    if name == "get_quality_trend":
        pid = tool_input.get("patient_id", "")
        limit = int(tool_input.get("limit", 10))
        records = DB.get_scans_by_patient(pid, limit=limit) if DB.connected else []
        trend = []
        for r in records:
            q = r.get("quality")
            if not q:
                continue   # older records may predate quality tracking
            trend.append({
                "timestamp":   r.get("timestamp", ""),
                "density_pct": q.get("density_pct"),
                "noise_val":   q.get("noise_val"),
                "noise_label": q.get("noise_label"),
            })
        return {"patient_id": pid, "count": len(trend), "quality_trend": trend}

    if name == "get_risk_trend":
        pid = tool_input.get("patient_id", "")
        limit = int(tool_input.get("limit", 10))
        records = DB.get_scans_by_patient(pid, limit=limit) if DB.connected else []
        trend = []
        for r in records:
            risk = r.get("risk")
            if not risk or not risk.get("level"):
                # Older records may predate risk tracking — recompute from
                # the stored areas so the trend still covers them.
                areas = r.get("areas_mm2") or {}
                if not areas:
                    continue
                risk = assess_risk_level(areas)
            trend.append({
                "timestamp":     r.get("timestamp", ""),
                "risk_level":    risk.get("level"),
                "total_area":    risk.get("total_area"),
                "necrotic_pct":  risk.get("necrotic_pct"),
            })
        return {"patient_id": pid, "count": len(trend), "risk_trend": trend}

    return {"error": f"unknown tool {name}"}


class AgentAnalysisWorker(QThread):
    """
    Usage:
        worker = AgentAnalysisWorker(patient_id, areas, quality, risk, doctor_name)
        worker.log.connect(...)     # tool calls + progress, for the activity log
        worker.done.connect(...)    # (ok, result_dict_or_msg)
        worker.start()
    """
    log  = pyqtSignal(str)
    done = pyqtSignal(bool, dict)

    def __init__(self, patient_id: str, areas: dict, quality: dict,
                 risk: dict, doctor_name: str = ""):
        super().__init__()
        self.patient_id  = patient_id
        self.areas       = areas
        self.quality     = quality
        self.risk        = risk
        self.doctor_name = doctor_name

    def run(self):
        if not AI_CFG.api_key:
            self.done.emit(False, {"error": "no_api_key"})
            return
        if anthropic is None:
            self.log.emit("⚠️   Agent analysis skipped — pip install anthropic")
            self.done.emit(False, {"error": "anthropic package not installed"})
            return

        try:
            client = anthropic.Anthropic(api_key=AI_CFG.api_key)
            total = sum(self.areas.values()) or 1.0
            lines = [
                f"Patient ID: {self.patient_id}",
                f"Reviewing doctor: {self.doctor_name or '—'}",
                "",
                "CURRENT segmentation area measurements (mm²), pixel-derived:",
            ]
            for name, val in self.areas.items():
                pct = (val / total) * 100
                lines.append(f"- {name}: {val:.2f} mm² ({pct:.1f}% of total)")
            lines.append(f"- Total tumor area: {total:.2f} mm²")
            lines.append("")
            lines.append(
                f"Scan quality readout: density {self.quality.get('density_pct',0):.1f}% "
                f"tissue, noise level {self.quality.get('noise_label','—')} "
                f"({self.quality.get('noise_val',0):.3f})."
            )
            lines.append(
                f"Automated heuristic risk band: {self.risk.get('level','—')} "
                f"(necrotic {self.risk.get('necrotic_pct',0):.1f}% of tumor)."
            )
            lines.append("")
            lines.append(
                "You may use your tools to check this patient's scan history "
                "or on-file profile before answering, if useful."
            )

            messages = [{"role": "user", "content": "\n".join(lines)}]
            self.log.emit("🤖  Agent analysis starting...")

            for turn in range(MAX_TOOL_TURNS):
                resp = client.messages.create(
                    model=AI_CFG.model,
                    max_tokens=1200,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=messages,
                )

                if resp.stop_reason == "tool_use":
                    messages.append({"role": "assistant", "content": resp.content})
                    tool_results = []
                    for block in resp.content:
                        if getattr(block, "type", "") == "tool_use":
                            args_str = ", ".join(f"{k}={v}" for k, v in block.input.items())
                            self.log.emit(f"🔧  Agent tool call: {block.name}({args_str})")
                            result = _execute_tool(block.name, block.input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result),
                            })
                    messages.append({"role": "user", "content": tool_results})
                    continue

                # Final answer — no more tool calls
                raw = "".join(
                    b.text for b in resp.content if getattr(b, "type", "") == "text"
                ).strip()
                if raw.startswith("```"):
                    raw = raw.strip("`")
                    if raw.lower().startswith("json"):
                        raw = raw[4:].strip()

                result = json.loads(raw)
                self.log.emit("✅  Agent analysis complete.")
                self.done.emit(True, result)
                return

            # Exhausted tool-turn budget without a final answer
            self.log.emit("⚠️   Agent analysis skipped — too many tool calls without a final answer.")
            self.done.emit(False, {"error": "exceeded max tool turns"})

        except json.JSONDecodeError as e:
            self.log.emit(f"⚠️   Agent analysis skipped — invalid response ({e})")
            self.done.emit(False, {"error": f"invalid JSON: {e}"})
        except Exception as e:
            self.log.emit(f"⚠️   Agent analysis skipped — {e}")
            self.done.emit(False, {"error": f"{e}\n{traceback.format_exc(limit=1)}"})
