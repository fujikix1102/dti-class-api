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
        "output": "mPk",
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
            },
            "boundary": {
                "likelihood_evaluation": False,
                "posterior_comparison": False,
                "canonical_checkpoint_update": False,
                "note": "LCDM-like CLASS propagation only. f_EDE and z_c are accepted for interface compatibility but are not used as AxiCLASS EDE microphysics in this minimal backend.",
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
