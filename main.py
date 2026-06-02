import ast
import json
import os
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


class EngineSpecs(BaseModel):
    displacement: float = Field(..., gt=0, description="Engine displacement in cc")
    cylinders: int = Field(..., gt=0)
    compression_ratio: float = Field(..., gt=0)
    redline: int = Field(..., ge=1000)
    forced_induction: Literal["none", "turbo", "supercharger"]
    boost_psi: float = Field(0, ge=0)
    fuel_type: Literal["petrol", "diesel", "e85"]
    engine_type: Literal["NA", "forced"]
    cam_profile: Literal["stock", "sport", "race"]
    drive_type: Literal["rwd", "fwd", "awd"]


app = FastAPI(title="DynoSim")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def generate_dyno_curve(specs: EngineSpecs) -> dict[str, Any]:
    rpm_points = list(range(500, specs.redline + 100, 250))

    displacement_liters = specs.displacement / 1000.0
    fuel_mod = {"petrol": 1.0, "diesel": 0.92, "e85": 1.12}[specs.fuel_type]
    cam_mod = {"stock": 1.0, "sport": 1.08, "race": 1.18}[specs.cam_profile]

    if specs.forced_induction == "turbo":
        induction_mod = 1.0 + (specs.boost_psi * 0.065)
        peak_rpm_ratio = 0.72
        is_forced = True
    elif specs.forced_induction == "supercharger":
        induction_mod = 1.0 + (specs.boost_psi * 0.055)
        peak_rpm_ratio = 0.78
        is_forced = True
    else:
        induction_mod = 1.0
        peak_rpm_ratio = 0.85
        is_forced = False

    base_hp = (displacement_liters * 50) * fuel_mod * cam_mod * induction_mod
    compression_bonus = 1.0 + max(0.0, (specs.compression_ratio - 9.0) * 0.018)
    peak_hp = base_hp * compression_bonus

    peak_rpm = int(round(specs.redline * peak_rpm_ratio / 50) * 50)
    peak_torque_rpm = int(round((peak_rpm * 0.65) / 50) * 50)
    peak_torque_nm = (peak_hp * 7127) / max(peak_rpm, 1)

    torque_curve: list[dict[str, float | int]] = []
    power_curve: list[dict[str, float | int]] = []

    for rpm in rpm_points:
        if is_forced:
            if rpm <= peak_torque_rpm:
                progress = max(rpm / peak_torque_rpm, 0.05)
                torque = peak_torque_nm * (0.42 + 0.58 * (progress**0.7))
            elif rpm <= peak_rpm:
                span = max(peak_rpm - peak_torque_rpm, 1)
                taper = (rpm - peak_torque_rpm) / span
                torque = peak_torque_nm * (1.0 - 0.05 * taper)
            else:
                span = max(specs.redline - peak_rpm, 1)
                drop = min((rpm - peak_rpm) / span, 1.0)
                torque = peak_torque_nm * 0.95 * (1.0 - 0.34 * (drop**1.4))
        else:
            if rpm <= peak_torque_rpm:
                progress = max(rpm / peak_torque_rpm, 0.05)
                torque = peak_torque_nm * (0.34 + 0.66 * (progress**0.8))
            elif rpm <= peak_rpm:
                span = max(peak_rpm - peak_torque_rpm, 1)
                taper = (rpm - peak_torque_rpm) / span
                torque = peak_torque_nm * (1.0 - 0.10 * taper)
            else:
                span = max(specs.redline - peak_rpm, 1)
                drop = min((rpm - peak_rpm) / span, 1.0)
                torque = peak_torque_nm * 0.90 * (1.0 - 0.37 * (drop**1.2))

        torque = max(torque, peak_torque_nm * 0.24)
        hp = (torque * rpm) / 7127

        torque_curve.append({"rpm": rpm, "value": round(torque, 1)})
        power_curve.append({"rpm": rpm, "value": round(hp, 1)})

    peak_power_point = max(power_curve, key=lambda point: point["value"])
    peak_torque_point = max(torque_curve, key=lambda point: point["value"])

    return {
        "torque_curve": torque_curve,
        "power_curve": power_curve,
        "peak_hp": round(float(peak_power_point["value"]), 1),
        "peak_torque": round(float(peak_torque_point["value"]), 1),
        "peak_hp_rpm": int(peak_power_point["rpm"]),
        "peak_tq_rpm": int(peak_torque_point["rpm"]),
        "estimated_peak_hp_target": round(peak_hp, 1),
        "estimated_peak_torque_target": round(peak_torque_nm, 1),
    }


def build_fallback_analysis(specs: EngineSpecs, dyno: dict[str, Any]) -> dict[str, Any]:
    peak_hp = dyno["peak_hp"]
    peak_torque = dyno["peak_torque"]
    hp_per_liter = peak_hp / max(specs.displacement / 1000.0, 0.1)

    if hp_per_liter >= 110 or peak_hp >= 500:
        rating = "Beast"
    elif hp_per_liter >= 85 or peak_hp >= 320:
        rating = "Strong"
    elif hp_per_liter >= 60 or peak_hp >= 180:
        rating = "Average"
    elif hp_per_liter >= 40:
        rating = "Weak"
    else:
        rating = "Gutless"

    induction_text = "naturally aspirated" if specs.forced_induction == "none" else specs.forced_induction
    return {
        "rating": rating,
        "summary": f"A {induction_text} {specs.cylinders}-cylinder with a usable curve and a clear tuning ceiling.",
        "suggestions": [
            {
                "title": "Calibrate ignition advance",
                "detail": "Use dyno logging to creep timing toward MBT in 1-2 degree steps while watching knock activity and EGT.",
                "gain": "+4 to 10 HP",
            },
            {
                "title": "Refine fuel targets",
                "detail": "Stabilize AFR under load; forced engines often like richer high-load targets, while NA builds can sharpen response slightly leaner near torque peak.",
                "gain": "Cleaner curve",
            },
            {
                "title": "Match cam and rev range",
                "detail": f"Shift the torque bias around {dyno['peak_tq_rpm']} RPM with cam phasing or lobe selection so the power peak lands just before the {specs.redline} RPM redline.",
                "gain": "Broader top end",
            },
            {
                "title": "Reduce inlet restriction",
                "detail": "Check pressure drop across filter, intercooler, and throttle path; even small reductions improve area under the curve.",
                "gain": "+qualitative",
            },
        ],
        "fun_fact": f"At {dyno['peak_hp_rpm']} RPM, this setup is making roughly {round((peak_torque * dyno['peak_hp_rpm']) / 7127, 1)} HP from the torque curve itself.",
    }


def parse_claude_json(raw_text: str) -> dict[str, Any]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(cleaned)
        except (ValueError, SyntaxError) as exc:
            raise ValueError(f"Could not parse Claude JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Claude response was not a JSON object")
    return parsed


async def request_claude_analysis(
    specs: EngineSpecs,
    dyno: dict[str, Any],
    forwarded_api_key: str | None = None,
) -> dict[str, Any]:
    api_key = forwarded_api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return build_fallback_analysis(specs, dyno)

    induction_line = (
        f"{specs.forced_induction} @ {specs.boost_psi} PSI"
        if specs.forced_induction != "none"
        else "NA"
    )
    prompt = f"""You are a professional engine tuner. Analyze these engine specs and dyno results, then give 4-5 specific, technical tuning suggestions.

Engine: {specs.displacement}cc, {specs.cylinders}-cylinder, {specs.compression_ratio}:1 CR, {specs.redline} RPM redline
Induction: {induction_line}
Fuel: {specs.fuel_type}, Cam: {specs.cam_profile}, Drive: {specs.drive_type}
Results: {dyno['peak_hp']} HP @ {dyno['peak_hp_rpm']} RPM | {dyno['peak_torque']} Nm @ {dyno['peak_tq_rpm']} RPM

Respond ONLY in this exact JSON format (no markdown):
{{
  'rating': 'Beast / Strong / Average / Weak / Gutless',
  'summary': 'One punchy sentence about this engine',
  'suggestions': [
    {{'title': 'short title', 'detail': 'specific technical detail with numbers', 'gain': '+X HP or qualitative'}}
  ],
  'fun_fact': 'One interesting technical insight about this specific engine configuration'
}}"""

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 700,
        "temperature": 0.5,
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=25.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    text_parts: list[str] = []
    for block in data.get("content", []):
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
    parsed = parse_claude_json("\n".join(text_parts))

    parsed.setdefault("rating", "Average")
    parsed.setdefault("summary", "A simulated engine combo with room to tune.")
    parsed.setdefault("suggestions", [])
    parsed.setdefault("fun_fact", "Torque shape drives the character of the whole curve.")

    return parsed


@app.post("/api/dyno")
async def run_dyno(
    specs: EngineSpecs,
    x_anthropic_api_key: str | None = Header(default=None, alias="X-Anthropic-Api-Key"),
) -> JSONResponse:
    dyno = generate_dyno_curve(specs)

    try:
        ai_analysis = await request_claude_analysis(specs, dyno, x_anthropic_api_key)
    except httpx.HTTPStatusError as exc:
        fallback = build_fallback_analysis(specs, dyno)
        return JSONResponse(
            status_code=200,
            content={
                **dyno,
                **fallback,
                "ai_warning": f"Claude API returned {exc.response.status_code}; using fallback suggestions.",
            },
        )
    except httpx.HTTPError as exc:
        fallback = build_fallback_analysis(specs, dyno)
        return JSONResponse(
            status_code=200,
            content={
                **dyno,
                **fallback,
                "ai_warning": f"Claude request failed ({exc.__class__.__name__}); using fallback suggestions.",
            },
        )
    except ValueError as exc:
        fallback = build_fallback_analysis(specs, dyno)
        return JSONResponse(
            status_code=200,
            content={
                **dyno,
                **fallback,
                "ai_warning": f"{exc}; using fallback suggestions.",
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected dyno analysis error: {exc}") from exc

    return JSONResponse(content={**dyno, **ai_analysis})


static_dir = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
