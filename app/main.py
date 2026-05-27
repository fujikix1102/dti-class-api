from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Tuple, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

APP_VERSION = "dti-class-api-v0.0.1-min"

try:
    from classy import Class  # type: ignore
    CLASSY_AVAILABLE = True
    CLASSY_IMPORT_ERROR = ""
except Exception as exc:
    Class = None  # type: ignore
    CLASSY_AVAILABLE = False
    CLASSY_IMPORT_ERROR = repr(exc)

app = FastAPI(
    title="DTI CLASS API",
    version=APP_VERSION,
    description="External exploratory CLASS backend for DTI-Core Grand Auditor.",
)

class ClassRequest(BaseModel):
    H0: float = Field(72.9)
    omega_b: float = Field(0.02440)
    omega_cdm: float = Field(0.12700)
    f_EDE: float = Field(0.082)
    z_c: float = Field(3500.0)
    n_s: float = Field(0.9847)
    ln10_10_As: float = Field(3.058)
    tau_reio: float = Field(0.0511)

def safe_float(x: Any) -> Optional[float]:
    try:
        y = float(x)
        if math.isfinite(y):
            return y
    except Exception:
        pass
    return None


# === DTI_CLASS_API_CMB_ARRAY_EXPORT_V1 ===
# Backend response extension only.
# This exports real CLASS/PyCLASS CMB arrays when CLASS provides them.
# It does not evaluate Planck likelihoods, does not compare posteriors,
# and does not activate AxiCLASS/EDE microphysics.

def _dti_json_float_list_v1(value: Any) -> Optional[list]:
    try:
        if value is None:
            return None
        if hasattr(value, "tolist"):
            value = value.tolist()
        else:
            value = list(value)
        out = []
        for x in value:
            try:
                out.append(float(x))
            except Exception:
                out.append(None)
        return out
    except Exception:
        return None


def _dti_dl_from_cl_v1(ell: list, cl_values: list) -> Optional[list]:
    try:
        if not ell or not cl_values:
            return None
        n = min(len(ell), len(cl_values))
        out = []
        for i in range(n):
            l = ell[i]
            c = cl_values[i]
            if l is None or c is None:
                out.append(None)
            else:
                out.append(float(l) * (float(l) + 1.0) * float(c) / (2.0 * math.pi))
        return out
    except Exception:
        return None


def _dti_extract_cmb_cls_payload_v1(cosmo: Any, lmax: int = 2500) -> Dict[str, Any]:
    """Extract JSON-safe CMB arrays from CLASS.

    Returns empty dict if spectra are unavailable.
    cl_tt/cl_te/cl_ee are raw CLASS C_l arrays.
    dl_tt/dl_te/dl_ee are D_l = l(l+1)C_l/(2pi) convenience arrays.
    cl_pp is returned raw if CLASS provides a lensing/phi-phi-like field.
    """
    payload: Dict[str, Any] = {}

    cls = None
    cls_source = None

    try:
        cls = cosmo.lensed_cl(lmax)
        cls_source = "lensed_cl"
    except Exception:
        try:
            cls = cosmo.raw_cl(lmax)
            cls_source = "raw_cl"
        except Exception as exc:
            return {
                "cmb_array_export_status": "unavailable",
                "cmb_array_export_error": repr(exc),
            }

    try:
        keys = list(cls.keys()) if hasattr(cls, "keys") else []
    except Exception:
        keys = []

    def get_key(name: str) -> Any:
        try:
            return cls[name]
        except Exception:
            return None

    ell = _dti_json_float_list_v1(get_key("ell"))
    if not ell:
        return {
            "cmb_array_export_status": "unavailable",
            "cmb_array_export_error": "CLASS returned no ell array",
            "cmb_array_source": cls_source,
            "cmb_array_keys": keys,
        }

    payload["cmb_array_export_status"] = "ok"
    payload["cmb_array_source"] = cls_source
    payload["cmb_array_lmax_requested"] = int(lmax)
    payload["cmb_array_keys"] = keys
    payload["cmb_array_convention"] = (
        "cl_tt/cl_te/cl_ee are raw CLASS C_l arrays when available; "
        "dl_tt/dl_te/dl_ee are D_l = l(l+1)C_l/(2pi); "
        "cl_pp is raw lensing/phi-phi-like output when available."
    )
    payload["ell"] = ell

    tt = _dti_json_float_list_v1(get_key("tt"))
    te = _dti_json_float_list_v1(get_key("te"))
    ee = _dti_json_float_list_v1(get_key("ee"))

    if tt:
        payload["cl_tt"] = tt
        dl_tt = _dti_dl_from_cl_v1(ell, tt)
        if dl_tt:
            payload["dl_tt"] = dl_tt

    if te:
        payload["cl_te"] = te
        dl_te = _dti_dl_from_cl_v1(ell, te)
        if dl_te:
            payload["dl_te"] = dl_te

    if ee:
        payload["cl_ee"] = ee
        dl_ee = _dti_dl_from_cl_v1(ell, ee)
        if dl_ee:
            payload["dl_ee"] = dl_ee

    for lens_key in ["pp", "phiphi", "dd", "ll"]:
        lens = _dti_json_float_list_v1(get_key(lens_key))
        if lens:
            payload["cl_pp"] = lens
            payload["cl_pp_source_key"] = lens_key
            break

    return payload
# === END DTI_CLASS_API_CMB_ARRAY_EXPORT_V1 ===


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "service": "DTI CLASS API",
        "version": APP_VERSION,
        "status": "ok",
        "classy_available": CLASSY_AVAILABLE,
        "boundary": {
            "exploratory": True,
            "canonical": False,
            "likelihood_evaluation": False,
            "posterior_comparison": False,
        },
    }

@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "version": APP_VERSION,
        "classy_available": CLASSY_AVAILABLE,
        "classy_import_error": CLASSY_IMPORT_ERROR,
    }

@app.post("/class/compute")
def class_compute(req: ClassRequest) -> Dict[str, Any]:
    if not CLASSY_AVAILABLE or Class is None:
        h = req.H0 / 100.0
        omega_m = (req.omega_b + req.omega_cdm) / (h * h) if h > 0 else None
        return {
            "status": "unavailable",
            "engine": "classy/PyCLASS",
            "message": "classy/PyCLASS is not installed in this backend environment.",
            "classy_available": False,
            "classy_import_error": CLASSY_IMPORT_ERROR,
            "input": req.model_dump(),
            "fallback_derived": {
                "h": h,
                "Omega_m_computed": omega_m,
            },
            "boundary": {
                "likelihood_evaluation": False,
                "posterior_comparison": False,
                "canonical_checkpoint_update": False,
            },
        }

    h = req.H0 / 100.0
    A_s = math.exp(req.ln10_10_As) * 1e-10
    omega_m = (req.omega_b + req.omega_cdm) / (h * h)

    params = {
        "h": h,
        "omega_b": req.omega_b,
        "omega_cdm": req.omega_cdm,
        "A_s": A_s,
        "n_s": req.n_s,
        "tau_reio": req.tau_reio,
        "output": "mPk,tCl,pCl,lCl",
        "lensing": "yes",
        "l_max_scalars": 2500,
        "P_k_max_h/Mpc": 1.0,
        "z_pk": "0",
    }

    t0 = time.time()
    cosmo = Class()
    try:
        cosmo.set(params)
        cosmo.compute()

        sigma8 = safe_float(cosmo.sigma8())
        s8 = sigma8 * math.sqrt(omega_m / 0.3) if sigma8 is not None else None

        try:
            rs_drag = safe_float(cosmo.rs_drag())
        except Exception:
            rs_drag = None

        try:
            age = safe_float(cosmo.age())
        except Exception:
            age = None

        cmb_cls_payload = _dti_extract_cmb_cls_payload_v1(cosmo, lmax=2500)

        return {
            "status": "ok",
            "engine": "classy/PyCLASS",
            "runtime_sec": round(time.time() - t0, 6),
            "input": req.model_dump(),
            "derived": {
                "h": h,
                "Omega_m_computed": omega_m,
                "A_s": A_s,
                "sigma8_CLASS": sigma8,
                "S8_CLASS": s8,
                "rs_drag_Mpc_CLASS": rs_drag,
                "age_Gyr_CLASS": age,
                **cmb_cls_payload,
            },
            "boundary": {
                "likelihood_evaluation": False,
                "posterior_comparison": False,
                "canonical_checkpoint_update": False,
                "cmb_array_export": True,
                "cmb_graph_readiness_possible": True,
                "planck_likelihood_evaluation": False,
                "posterior_comparison": False,
                "note": "LCDM-like CLASS propagation with real CLASS CMB array export enabled when PyCLASS provides spectra. f_EDE and z_c are accepted for interface compatibility but are not used as AxiCLASS EDE microphysics in this minimal backend. Planck likelihoods are not evaluated.",
            },
        }
    except Exception as exc:
        return {
            "status": "failed",
            "engine": "classy/PyCLASS",
            "message": repr(exc),
            "input": req.model_dump(),
            "boundary": {
                "likelihood_evaluation": False,
                "posterior_comparison": False,
                "canonical_checkpoint_update": False,
            },
        }
    finally:
        try:
            cosmo.struct_cleanup()
            cosmo.empty()
        except Exception:
            pass

# === DTI_JUMP_TRANSLATOR_STUB_LOCAL_PATCH_V1 ===
# Local backend-only translator stub.
# This endpoint validates and normalizes jump parameters only.
# It does not call CLASS, does not call AxiCLASS, does not generate CMB spectra,
# does not evaluate Planck likelihoods, and does not compare posteriors.

def _dti_is_finite_number_v1(value: Any) -> bool:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(x)


def _dti_jump_translation_boundary_v1() -> Dict[str, bool]:
    return {
        "fake_arrays": False,
        "synthetic_graph": False,
        "cmb_spectra_generated": False,
        "class_run": False,
        "axiclass_run": False,
        "planck_chi2": False,
        "likelihood_evaluation": False,
        "posterior_comparison": False,
        "ede_microphysics_activation_claim": False,
        "physics_value_update": False,
        "manuscript_update": False,
        "canonical_checkpoint_update": False,
    }


def _dti_jump_translation_status_v1() -> Dict[str, bool]:
    return {
        "endpoint_implemented": True,
        "translator_schema_frozen": True,
        "backend_patch_applied": True,
        "class_c_patch_applied": False,
        "axiclass_patch_applied": False,
        "jump_model_active": False,
        "jump_background_active": False,
        "jump_perturbations_active": False,
        "jump_background_backend_implemented": False,
        "jump_perturbation_backend_implemented": False,
    }


def _dti_validate_jump_translation_payload_v1(payload: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    required = [
        "backend_mode",
        "H0",
        "omega_b",
        "omega_cdm",
        "ln10_10_As",
        "n_s",
        "tau_reio",
        "jump_model_enabled",
        "jump_target",
        "transition_form",
        "A_J",
        "z_J",
        "Delta_z",
        "jump_regime_label",
        "request_claim_level",
    ]

    for key in required:
        if key not in payload:
            errors.append(f"missing_required_field:{key}")

    if errors:
        warnings.append("translation_only: validation stopped after missing required fields")
        return errors, warnings

    if payload.get("backend_mode") != "jump_parameter_translation_only":
        errors.append("backend_mode_must_be_jump_parameter_translation_only")

    if payload.get("request_claim_level") != "translation_only":
        errors.append("request_claim_level_must_be_translation_only")

    if not isinstance(payload.get("jump_model_enabled"), bool):
        errors.append("jump_model_enabled_must_be_boolean")

    if payload.get("jump_target") not in {"E_z", "H_z"}:
        errors.append("jump_target_must_be_E_z_or_H_z")

    if payload.get("transition_form") != "smoothed_tanh_step":
        errors.append("transition_form_must_be_smoothed_tanh_step")

    if payload.get("jump_regime_label") not in {
        "low_z_geometry",
        "recombination_scale",
        "early_time_ede_like",
    }:
        errors.append("jump_regime_label_not_allowed")

    positive_fields = ["H0", "omega_b", "omega_cdm", "n_s", "z_J", "Delta_z"]
    for key in positive_fields:
        if not _dti_is_finite_number_v1(payload.get(key)) or float(payload.get(key)) <= 0.0:
            errors.append(f"{key}_must_be_finite_positive")

    finite_fields = ["ln10_10_As", "A_J"]
    for key in finite_fields:
        if not _dti_is_finite_number_v1(payload.get(key)):
            errors.append(f"{key}_must_be_finite")

    if not _dti_is_finite_number_v1(payload.get("tau_reio")) or float(payload.get("tau_reio")) < 0.0:
        errors.append("tau_reio_must_be_finite_nonnegative")

    if _dti_is_finite_number_v1(payload.get("A_J")):
        a_j = float(payload.get("A_J"))
        if abs(a_j) > 0.05:
            warnings.append("abs_A_J_large: numerical safety is not established")

    if _dti_is_finite_number_v1(payload.get("Delta_z")):
        delta_z = float(payload.get("Delta_z"))
        if delta_z <= 1.0:
            warnings.append("Delta_z_small: transition approaches a discontinuity")

    if _dti_is_finite_number_v1(payload.get("z_J")):
        z_j = float(payload.get("z_J"))
        if 800.0 <= z_j <= 1400.0:
            warnings.append("recombination_scale: perturbation-sector implementation is required before any CMB jump claim")

    regime = payload.get("jump_regime_label")
    if regime == "low_z_geometry":
        warnings.append("low_z_geometry: background geometry diagnostic only")
    elif regime == "early_time_ede_like":
        warnings.append("early_time_ede_like: this endpoint does not activate EDE or AxiCLASS microphysics")
    elif regime == "recombination_scale":
        warnings.append("recombination_scale: no recombination or perturbation modification is implemented")

    warnings.append("translation_only: no CLASS or AxiCLASS run was performed")
    warnings.append("current public CMB graph remains LCDM-like until jump-aware backend implementation exists")
    warnings.append("no Planck likelihood evaluation was performed")
    warnings.append("no posterior comparison was performed")

    return errors, warnings


def _dti_normalize_jump_translation_payload_v1(payload: Dict[str, Any]) -> Dict[str, Any]:
    a_j = float(payload["A_J"])
    z_j = float(payload["z_J"])
    delta_z = float(payload["Delta_z"])

    return {
        "backend_mode": "jump_parameter_translation_only",
        "jump_model_enabled_requested": bool(payload["jump_model_enabled"]),
        "jump_target": str(payload["jump_target"]),
        "transition_form": "smoothed_tanh_step",
        "A_J": a_j,
        "z_J": z_j,
        "Delta_z": delta_z,
        "J_high_z_limit": 1.0 + a_j,
        "jump_regime_label": str(payload["jump_regime_label"]),
        "H0": float(payload["H0"]),
        "omega_b": float(payload["omega_b"]),
        "omega_cdm": float(payload["omega_cdm"]),
        "ln10_10_As": float(payload["ln10_10_As"]),
        "n_s": float(payload["n_s"]),
        "tau_reio": float(payload["tau_reio"]),
    }


@app.post("/class/translate-jump-params")
def translate_jump_params(payload: Dict[str, Any]) -> Dict[str, Any]:
    errors, warnings = _dti_validate_jump_translation_payload_v1(payload)
    accepted = len(errors) == 0

    normalized: Dict[str, Any]
    if accepted:
        normalized = _dti_normalize_jump_translation_payload_v1(payload)
    else:
        normalized = {}

    return {
        "accepted": accepted,
        "errors": errors,
        "warnings": warnings,
        "normalized": normalized,
        "formula": {
            "S_z": "0.5*(1+tanh((z-z_J)/Delta_z))",
            "J_z": "1 + A_J*S_z",
            "E_jump_z": "J_z*E_base_z",
            "target_variable": "E(z)=H(z)/H0",
        },
        "implementation_status": _dti_jump_translation_status_v1(),
        "boundary": _dti_jump_translation_boundary_v1(),
        "next_allowed_stage": "background_only_backend_plan_or_explicit_local_patch",
        "note": (
            "Translator-only endpoint. No CLASS run, no AxiCLASS run, no CMB spectra, "
            "no Planck chi2, no likelihood evaluation, and no posterior comparison."
        ),
    }


# === END DTI_JUMP_TRANSLATOR_STUB_LOCAL_PATCH_V1 ===

