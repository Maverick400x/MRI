import json
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from config import AI_CFG

try:
    import anthropic
except ImportError:
    anthropic = None


SYSTEM_PROMPT = """You are assisting a radiologist by drafting the narrative \
portion of a preliminary MRI brain tumor report from ALREADY-COMPUTED \
segmentation area measurements. You are not analyzing any image and you \
are not making a diagnosis — the measurements are given to you as facts.
Rules:
- Reference only the numbers provided. Never invent measurements.
- Use hedged clinical language ("consistent with", "suggestive of").
- Include a line noting these are preliminary segmentation estimates
  requiring radiologist confirmation.
- If PREVIOUS PHASE measurements are provided alongside the current ones,
  compare current vs. that single previous phase only — describe per-region
  percentage change and whether the pattern suggests progression,
  regression, or stability. Do not speculate about phases before that;
  the comparison is strictly previous-vs-current, two phases only.
- If no previous phase is provided, note this is the baseline/first
  recorded phase for this patient and no comparison is being made.
- Output ONLY valid JSON, no markdown fences, matching:
  {"findings": "...", "impression": "...", "flags_for_review": ["...", "..."]}
"""


class AIFindingsWorker(QThread):
    """
    Usage (mirrors EmailWorker / EncryptWorker in workers.py):
        worker = AIFindingsWorker(areas, patient_id, doctor_name)
        worker.done.connect(self._on_ai_findings_done)   # (ok, result_dict_or_msg)
        worker.start()
    """

    log  = pyqtSignal(str)
    done = pyqtSignal(bool, dict)   # ok, {"findings","impression","flags_for_review"} or {"error": msg}

    def __init__(self, areas: dict, patient_id: str = "", doctor_name: str = "",
                 previous_areas: dict | None = None):
        super().__init__()
        self.areas = areas
        self.patient_id = patient_id
        self.doctor_name = doctor_name
        self.previous_areas = previous_areas

    def run(self):
        if not AI_CFG.api_key:
            # Not configured — not an error, just skip silently.
            self.done.emit(False, {"error": "no_api_key"})
            return
        if anthropic is None:
            self.log.emit("⚠️   AI report skipped — pip install anthropic")
            self.done.emit(False, {"error": "anthropic package not installed"})
            return

        try:
            self.log.emit("🤖  Drafting AI-assisted findings narrative...")
            client = anthropic.Anthropic(api_key=AI_CFG.api_key)

            total = sum(self.areas.values()) or 1.0
            lines = [f"Segmentation area measurements (mm²), pixel-derived — CURRENT phase:"]
            for name, val in self.areas.items():
                pct = (val / total) * 100
                lines.append(f"- {name}: {val:.2f} mm² ({pct:.1f}% of total tumor area)")
            lines.append(f"- Total tumor area: {total:.2f} mm²")

            if self.previous_areas:
                prev_total = sum(self.previous_areas.values()) or 1.0
                lines.append("")
                lines.append("PREVIOUS phase measurements (mm²), for comparison only:")
                for name, val in self.previous_areas.items():
                    lines.append(f"- {name}: {val:.2f} mm²")
                lines.append(f"- Total tumor area: {prev_total:.2f} mm²")
                lines.append("")
                lines.append(
                    "Compare CURRENT vs this single PREVIOUS phase only "
                    "(two phases total) — note per-region % change and "
                    "overall progression/regression/stability.")
            else:
                lines.append("")
                lines.append("No previous phase on record — this is the baseline phase; do not compare.")

            resp = client.messages.create(
                model=AI_CFG.model,
                max_tokens=800,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": "\n".join(lines)}],
            )
            raw = "".join(
                b.text for b in resp.content if getattr(b, "type", "") == "text"
            ).strip()
            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.lower().startswith("json"):
                    raw = raw[4:].strip()

            result = json.loads(raw)
            self.log.emit("✅  AI findings draft ready.")
            self.done.emit(True, result)

        except json.JSONDecodeError as e:
            self.log.emit(f"⚠️   AI report skipped — invalid response ({e})")
            self.done.emit(False, {"error": f"invalid JSON: {e}"})
        except Exception as e:
            self.log.emit(f"⚠️   AI report skipped — {e}")
            self.done.emit(False, {"error": f"{e}\n{traceback.format_exc(limit=1)}"})
