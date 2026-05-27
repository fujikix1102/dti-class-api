from __future__ import annotations

import math
import time
from typing import Any, Dict, Optional

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
