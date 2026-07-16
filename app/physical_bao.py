from __future__ import annotations

import csv
import hashlib
import importlib
import inspect
import json
import math
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel, Field

import cobaya
from cobaya.conventions import Const
from cobaya.likelihoods.bao.desi_dr2.desi_bao_all import (
    desi_bao_all,
)
from cobaya.likelihoods.base_classes.bao import BAO
from cobaya.model import get_model
from cobaya.theory import Theory


router = APIRouter(
    prefix="/axiclass/desi-dr2-bao",
    tags=["AxiCLASS DESI DR2 BAO"],
)

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data" / "desi_dr2_bao"

MEAN_PATH = DATA_DIR / "OFFICIAL_DESI_DR2_MEAN.txt"
COV_PATH = DATA_DIR / "OFFICIAL_DESI_DR2_COVARIANCE.txt"
INI_PATH = DATA_DIR / "PLANCK2018_BASELINE_LIKE_INPUT.ini"
FROZEN_VECTOR_PATH = (
    DATA_DIR / "FROZEN_PHYSICAL_THEORY_VECTOR.tsv"
)

BUILD_IDENTITY_PATH = Path(
    "/opt/axiclass_build_identity.json"
)

AXICLASS_COMMIT = os.environ.get(
    "AXICLASS_COMMIT",
    "UNKNOWN",
)

EXPECTED_COMPONENT_SHA = (
    "ef8c3b4a02daa7e75ed086753dc4719b5fe823d92040933355de2327b7b4119c"
)

EXPECTED_PARENT_SHA = (
    "c17387ddab15ca80f9a928f98b27a3e786cf0cc4f366047b6c82843431d2c13d"
)

EXPECTED_MEAN_SHA = (
    "9ac154ab583ce759c0f7eef3c978c7c70a6ead2d18774caceadf1a350a640585"
)

EXPECTED_COV_SHA = (
    "252a143274c8a07c78694c119617d36594f6d7965d00319ca611c6ffb886e509"
)

EXPECTED_INI_SHA = (
    "549160924345dad88be62b182c53e13f419a47dfabc032fe5303ad57a2ff2d7d"
)

EXPECTED_RDRAG = 147.05426160663038
EXPECTED_LOGLIKE = -15.716955497968195
EXPECTED_CHI2 = 31.43391099593639

# AXICLASS_CROSS_PLATFORM_NUMERIC_TOLERANCE_FIX8
# macOS and Linux builds are compared using bounded numerical
# equivalence rather than bitwise-style equality.
CROSS_PLATFORM_RDRAG_ABS_TOL = 2e-5
CROSS_PLATFORM_VECTOR_ABS_TOL = 5e-6
CROSS_PLATFORM_STAT_ABS_TOL = 1e-3

_RUNTIME_LOCK = threading.Lock()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except Exception:
        return None

    if not math.isfinite(result):
        return None

    return result


def _parse_mean(path: Path) -> pd.DataFrame:
    rows: list[tuple[float, float, str]] = []

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            parts = line.split()

            if len(parts) != 3:
                continue

            try:
                redshift = float(parts[0])
                value = float(parts[1])
            except ValueError:
                continue

            observable = parts[2]

            if observable not in {
                "DV_over_rs",
                "DM_over_rs",
                "DH_over_rs",
            }:
                continue

            rows.append(
                (
                    redshift,
                    value,
                    observable,
                )
            )

    if len(rows) != 13:
        raise RuntimeError(
            f"official mean row count={len(rows)}, expected=13"
        )

    return pd.DataFrame(
        rows,
        columns=[
            "z",
            "value",
            "observable",
        ],
    )


def _parse_ini(path: Path) -> dict[str, Any]:
    required = [
        "H0",
        "omega_b",
        "N_ur",
        "omega_cdm",
        "N_ncdm",
        "m_ncdm",
        "T_ncdm",
        "YHe",
        "tau_reio",
        "n_s",
        "A_s",
    ]

    raw_values: dict[str, str] = {}

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()

            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.split("#", 1)[0].strip()

            if key in required and key not in raw_values:
                raw_values[key] = value

    missing = [
        key
        for key in required
        if key not in raw_values
    ]

    if missing:
        raise RuntimeError(
            "missing INI parameters: "
            + ", ".join(missing)
        )

    parameters: dict[str, Any] = {}

    for key in required:
        if key == "N_ncdm":
            parameters[key] = int(
                float(raw_values[key])
            )
        else:
            parameters[key] = float(
                raw_values[key]
            )

    return parameters


def _read_frozen_vector(
    path: Path,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    redshifts: list[float] = []
    observables: list[str] = []
    values: list[float] = []

    with path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as handle:
        reader = csv.DictReader(
            handle,
            delimiter="\t",
        )

        for row in reader:
            redshifts.append(
                float(row["redshift"])
            )
            observables.append(
                row["observable"]
            )
            values.append(
                float(row["physical_value"])
            )

    if len(values) != 13:
        raise RuntimeError(
            f"frozen vector row count={len(values)}"
        )

    return (
        np.asarray(redshifts, dtype=np.float64),
        np.asarray(values, dtype=np.float64),
        observables,
    )


OFFICIAL_DATA = _parse_mean(MEAN_PATH)
OFFICIAL_COV = np.loadtxt(
    COV_PATH,
    dtype=np.float64,
)
PARAMETERS = _parse_ini(INI_PATH)

(
    REDSHIFTS,
    FROZEN_VECTOR,
    OBSERVABLES,
) = _read_frozen_vector(
    FROZEN_VECTOR_PATH
)


def _source_identity() -> dict[str, Any]:
    component_path = Path(
        inspect.getsourcefile(desi_bao_all)
        or inspect.getfile(desi_bao_all)
    ).resolve()

    parent_path = Path(
        inspect.getsourcefile(BAO)
        or inspect.getfile(BAO)
    ).resolve()

    build_identity: dict[str, Any] = {}

    if BUILD_IDENTITY_PATH.exists():
        build_identity = json.loads(
            BUILD_IDENTITY_PATH.read_text(
                encoding="utf-8"
            )
        )

    return {
        "python_version": sys.version.replace(
            "\n",
            " ",
        ),
        "cobaya_version": getattr(
            cobaya,
            "__version__",
            "UNKNOWN",
        ),
        "component_source_path": str(
            component_path
        ),
        "component_source_sha256": _sha256(
            component_path
        ),
        "BAO_parent_source_path": str(
            parent_path
        ),
        "BAO_parent_source_sha256": _sha256(
            parent_path
        ),
        "AxiCLASS_commit": AXICLASS_COMMIT,
        "build_identity": build_identity,
        "official_mean_sha256": _sha256(
            MEAN_PATH
        ),
        "official_covariance_sha256": _sha256(
            COV_PATH
        ),
        "parameter_ini_sha256": _sha256(
            INI_PATH
        ),
    }


def static_identity_review() -> dict[str, Any]:
    identity = _source_identity()

    checks = {
        "component_source_sha_exact":
            identity[
                "component_source_sha256"
            ] == EXPECTED_COMPONENT_SHA,
        "BAO_parent_source_sha_exact":
            identity[
                "BAO_parent_source_sha256"
            ] == EXPECTED_PARENT_SHA,
        "official_mean_sha_exact":
            identity[
                "official_mean_sha256"
            ] == EXPECTED_MEAN_SHA,
        "official_covariance_sha_exact":
            identity[
                "official_covariance_sha256"
            ] == EXPECTED_COV_SHA,
        "parameter_ini_sha_exact":
            identity[
                "parameter_ini_sha256"
            ] == EXPECTED_INI_SHA,
        "AxiCLASS_commit_exact":
            identity[
                "AxiCLASS_commit"
            ] == (
                "ba4ede7b1d735aa6312ab5f4355d26b5e617e70c"
            ),
        "official_data_shape_13":
            OFFICIAL_DATA.shape == (13, 3),
        "official_covariance_shape_13x13":
            OFFICIAL_COV.shape == (13, 13),
        "official_covariance_finite":
            bool(
                np.all(
                    np.isfinite(
                        OFFICIAL_COV
                    )
                )
            ),
        "official_covariance_symmetric":
            bool(
                np.allclose(
                    OFFICIAL_COV,
                    OFFICIAL_COV.T,
                    rtol=0.0,
                    atol=1e-14,
                )
            ),
        "frozen_vector_shape_13":
            FROZEN_VECTOR.shape == (13,),
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]

    return {
        "status": (
            "ok"
            if not failed
            else "failed"
        ),
        "checks": checks,
        "failed_checks": failed,
        "identity": identity,
        "boundary": {
            "unmodified_official_bao_data_installation":
                False,
            "normalized_likelihood_claim":
                False,
            "sampler_runtime":
                False,
            "posterior_sampling":
                False,
            "MCMC":
                False,
            "historical_reproduction":
                False,
            "reuse_30_06":
                "FORBIDDEN",
        },
    }


class PhysicalBAORequest(BaseModel):
    use_locked_baseline: bool = Field(
        default=True,
    )


class RuntimePhysicalDesiBaoAll(
    desi_bao_all
):
    @classmethod
    def is_installed(
        cls,
        path=None,
        data=True,
        code=True,
        **kwargs,
    ):
        return True

    def _runtime_logpdf(
        self,
        theory_vector,
    ):
        theory = np.asarray(
            theory_vector,
            dtype=np.float64,
        ).reshape(-1)

        observed = self.data[
            "value"
        ].to_numpy(dtype=np.float64)

        residual = theory - observed

        return float(
            -0.5
            * residual.dot(
                self.invcov
            ).dot(residual)
        )

    def initialize(self):
        super().initialize()

        self.data = OFFICIAL_DATA.copy()
        self.cov = np.asarray(
            OFFICIAL_COV,
            dtype=np.float64,
        )
        self.invcov = np.linalg.inv(
            self.cov
        )
        self.logpdf = self._runtime_logpdf
        self.runtime_data_binding_adapter = True

    def initialize_with_provider(
        self,
        provider,
    ):
        super().initialize_with_provider(
            provider
        )
        self.logpdf = self._runtime_logpdf
        self.runtime_logpdf_rebound_after_provider = True


class AxiCLASSPhysicalProvider(Theory):
    params = {
        "runtime_anchor": None,
        "rdrag": {
            "derived": True,
        },
    }

    def initialize(self):
        classy = importlib.import_module(
            "classy"
        )

        self._Class = classy.Class
        self._parameters = dict(
            PARAMETERS
        )
        self._cosmo = None
        self._rdrag = None

        self.calculate_call_count = 0
        self.compute_success_count = 0
        self.Hubble_call_count = 0
        self.distance_call_count = 0
        self.rdrag_call_count = 0
        self.must_provide_calls: list[
            dict[str, Any]
        ] = []

    def get_can_provide_params(self):
        return ["rdrag"]

    def must_provide(
        self,
        **requirements,
    ):
        self.must_provide_calls.append(
            {
                str(key): value
                for key, value in requirements.items()
            }
        )
        return {}

    def _cleanup_current(self):
        if self._cosmo is None:
            return

        try:
            self._cosmo.struct_cleanup()
        finally:
            try:
                self._cosmo.empty()
            finally:
                self._cosmo = None

    def calculate(
        self,
        state,
        want_derived=True,
        **params_values_dict,
    ):
        self.calculate_call_count += 1
        self._cleanup_current()

        cosmo = self._Class()
        cosmo.set(
            dict(
                self._parameters
            )
        )
        cosmo.compute()

        self._cosmo = cosmo
        self._rdrag = float(
            cosmo.rs_drag()
        )
        self.compute_success_count += 1

        state["runtime_anchor"] = float(
            params_values_dict.get(
                "runtime_anchor",
                0.0,
            )
        )

        if want_derived:
            state["derived"] = {
                "rdrag": self._rdrag,
            }

        return True

    def _require_cosmo(self):
        if self._cosmo is None:
            raise RuntimeError(
                "AxiCLASS called before calculate"
            )

        return self._cosmo

    def get_angular_diameter_distance(
        self,
        z,
    ):
        self.distance_call_count += 1
        cosmo = self._require_cosmo()

        values = np.atleast_1d(
            np.asarray(
                z,
                dtype=np.float64,
            )
        )

        return np.asarray(
            [
                float(
                    cosmo.angular_distance(
                        float(item)
                    )
                )
                for item in values
            ],
            dtype=np.float64,
        )

    def get_Hubble(
        self,
        z,
        units="km/s/Mpc",
    ):
        self.Hubble_call_count += 1
        cosmo = self._require_cosmo()

        values = np.atleast_1d(
            np.asarray(
                z,
                dtype=np.float64,
            )
        )

        inverse_mpc = np.asarray(
            [
                float(
                    cosmo.Hubble(
                        float(item)
                    )
                )
                for item in values
            ],
            dtype=np.float64,
        )

        if units == "1/Mpc":
            return inverse_mpc

        if units == "km/s/Mpc":
            return (
                inverse_mpc
                * Const.c_km_s
            )

        raise ValueError(
            f"unsupported Hubble units: {units}"
        )

    def get_param(self, name):
        if name == "rdrag":
            self.rdrag_call_count += 1

            if self._rdrag is None:
                raise RuntimeError(
                    "rdrag requested before calculate"
                )

            return self._rdrag

        return super().get_param(name)

    def close(self):
        self._cleanup_current()


def _run_locked_physical_bao() -> dict[str, Any]:
    identity_review = static_identity_review()

    if identity_review["status"] != "ok":
        return {
            "status": "identity_failed",
            **identity_review,
        }

    defaults = desi_bao_all.get_defaults()

    likelihood_options: dict[str, Any] = {
        "external":
            RuntimePhysicalDesiBaoAll,
        "measurements_file":
            str(MEAN_PATH),
        "cov_file":
            str(COV_PATH),
    }

    for optional_key in (
        "rs_rescale",
        "prob_dist",
        "use_grid_1d",
        "use_grid_2d",
        "use_grid_3d",
    ):
        if optional_key in defaults:
            likelihood_options[
                optional_key
            ] = defaults[optional_key]

    runtime_packages = Path(
        "/tmp/dti_runtime_packages"
    )
    (
        runtime_packages
        / "data"
        / "bao_data"
    ).mkdir(
        parents=True,
        exist_ok=True,
    )

    info = {
        "packages_path":
            str(runtime_packages),
        "params": {
            "runtime_anchor": {
                "value": 0.0,
            },
            "rdrag": {
                "derived": True,
            },
        },
        "theory": {
            "axiclass_physical_provider": {
                "external":
                    AxiCLASSPhysicalProvider,
            },
        },
        "likelihood": {
            "desi_bao_all_physical_runtime": (
                likelihood_options
            ),
        },
        "debug": False,
        "timing": False,
    }

    model = None
    started = time.time()

    try:
        model = get_model(info)

        theory_component = model.theory[
            "axiclass_physical_provider"
        ]

        likelihood_component = (
            model.likelihood[
                "desi_bao_all_physical_runtime"
            ]
        )

        logpost = model.logposterior(
            {
                "runtime_anchor": 0.0,
            },
            cached=False,
        )

        loglikes = np.asarray(
            logpost.loglikes,
            dtype=np.float64,
        ).reshape(-1)

        model_loglike = float(
            loglikes[0]
        )
        model_chi2 = (
            -2.0 * model_loglike
        )

        theory_vector = np.asarray(
            [
                likelihood_component.theory_fun(
                    z,
                    observable,
                )
                for z, observable in zip(
                    REDSHIFTS,
                    OBSERVABLES,
                    strict=True,
                )
            ],
            dtype=np.float64,
        ).reshape(-1)

        direct_logp = float(
            likelihood_component.logp()
        )

        rdrag = float(
            theory_component.get_param(
                "rdrag"
            )
        )

        difference = (
            theory_vector
            - FROZEN_VECTOR
        )

        max_difference = float(
            np.max(
                np.abs(
                    difference
                )
            )
        )

        checks = {
            "AxiCLASS_compute_executed":
                (
                    theory_component
                    .compute_success_count
                    >= 1
                ),
            "rdrag_matches_locked":
                math.isclose(
                    rdrag,
                    EXPECTED_RDRAG,
                    rel_tol=0.0,
                    abs_tol=CROSS_PLATFORM_RDRAG_ABS_TOL,
                ),
            "theory_vector_shape_13":
                theory_vector.shape
                == (13,),
            "theory_vector_matches_locked":
                bool(
                    np.allclose(
                        theory_vector,
                        FROZEN_VECTOR,
                        rtol=0.0,
                        atol=CROSS_PLATFORM_VECTOR_ABS_TOL,
                    )
                ),
            "model_loglike_matches_locked":
                math.isclose(
                    model_loglike,
                    EXPECTED_LOGLIKE,
                    rel_tol=0.0,
                    abs_tol=CROSS_PLATFORM_STAT_ABS_TOL,
                ),
            "model_chi2_matches_locked":
                math.isclose(
                    model_chi2,
                    EXPECTED_CHI2,
                    rel_tol=0.0,
                    abs_tol=CROSS_PLATFORM_STAT_ABS_TOL,
                ),
            "direct_logp_matches_model":
                math.isclose(
                    direct_logp,
                    model_loglike,
                    rel_tol=1e-13,
                    abs_tol=1e-13,
                ),
            "BAO_theory_fun_inherited":
                (
                    "theory_fun"
                    not in
                    RuntimePhysicalDesiBaoAll
                    .__dict__
                ),
            "BAO_logp_inherited":
                (
                    "logp"
                    not in
                    RuntimePhysicalDesiBaoAll
                    .__dict__
                ),
        }

        failed = [
            name
            for name, passed in checks.items()
            if not passed
        ]

        return {
            "status": (
                "ok"
                if not failed
                else "numeric_mismatch"
            ),
            "checks": checks,
            "failed_checks": failed,
            "runtime_sec": round(
                time.time() - started,
                6,
            ),
            "identity": identity_review[
                "identity"
            ],
            "input_contract": {
                "mode":
                    "locked_planck2018_baseline_like",
                "parameters":
                    PARAMETERS,
            },
            "result": {
                "rdrag_Mpc":
                    rdrag,
                "model_loglike":
                    model_loglike,
                "model_chi2":
                    model_chi2,
                "direct_component_logp":
                    direct_logp,
                "theory_vector":
                    [
                        {
                            "row_index": index,
                            "redshift":
                                float(
                                    REDSHIFTS[index]
                                ),
                            "observable":
                                OBSERVABLES[index],
                            "value":
                                float(
                                    theory_vector[index]
                                ),
                            "locked_value":
                                float(
                                    FROZEN_VECTOR[index]
                                ),
                            "difference":
                                float(
                                    difference[index]
                                ),
                        }
                        for index in range(13)
                    ],
                "theory_vector_max_abs_difference":
                    max_difference,
                "calculate_call_count":
                    theory_component
                    .calculate_call_count,
                "compute_success_count":
                    theory_component
                    .compute_success_count,
                "Hubble_call_count":
                    theory_component
                    .Hubble_call_count,
                "distance_call_count":
                    theory_component
                    .distance_call_count,
                "rdrag_call_count":
                    theory_component
                    .rdrag_call_count,
            },
            "boundary": {
                "physical_AxiCLASS_compute":
                    True,
                "Cobaya_get_model":
                    True,
                "inherited_BAO_theory_fun":
                    True,
                "inherited_BAO_logp":
                    True,
                "explicit_mean_cov_binding_adapter":
                    True,
                "unmodified_official_bao_data_installation":
                    False,
                "normalized_likelihood_claim":
                    False,
                "sampler_runtime":
                    False,
                "posterior_sampling":
                    False,
                "MCMC":
                    False,
                "historical_reproduction":
                    False,
                "EDE_branch_claim":
                    False,
                "reuse_30_06":
                    "FORBIDDEN",
                "cross_platform_numeric_equivalence":
                    True,
                "cross_platform_rdrag_abs_tolerance":
                    CROSS_PLATFORM_RDRAG_ABS_TOL,
                "cross_platform_vector_abs_tolerance":
                    CROSS_PLATFORM_VECTOR_ABS_TOL,
                "cross_platform_stat_abs_tolerance":
                    CROSS_PLATFORM_STAT_ABS_TOL,
            },
        }

    finally:
        if model is not None:
            try:
                model.close()
            except Exception:
                pass


@router.get("/provenance")
def physical_bao_provenance():
    return static_identity_review()


@router.get("/health")
def physical_bao_health():
    review = static_identity_review()

    return {
        "status": review["status"],
        "service":
            "AxiCLASS Cobaya DESI DR2 BAO",
        "identity_review":
            review,
        "compute_executed":
            False,
    }


@router.post("")
def physical_bao_compute(
    request: PhysicalBAORequest,
):
    if not request.use_locked_baseline:
        return {
            "status": "rejected",
            "message":
                "Only the locked baseline contract is currently allowed.",
            "boundary": {
                "arbitrary_parameter_execution":
                    False,
                "sampler_runtime":
                    False,
                "posterior_sampling":
                    False,
                "reuse_30_06":
                    "FORBIDDEN",
            },
        }

    acquired = _RUNTIME_LOCK.acquire(
        blocking=False
    )

    if not acquired:
        return {
            "status": "busy",
            "message":
                "A physical solver request is already running.",
            "retryable": True,
        }

    try:
        return _run_locked_physical_bao()
    finally:
        _RUNTIME_LOCK.release()
