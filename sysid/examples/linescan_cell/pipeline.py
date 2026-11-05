"""The scan tunnel's optics: a 16-band SWIR push-broom line camera triggered by the belt encoder, and a D435 downstream.

Line camera, geometry: a dot on the target card crosses the scan plane at one belt travel s and lands at one pixel u along the line.
The real (u, s) come from bam_scan_tunnel's PinholeCamera at the hidden pose and lens, restricted to its centre row (the dot's
crossing found by bisection on the projected row); the fit is the closed-form push-broom model u = f a / (h - z) + c - 0.5,
s = x0 - x_d - (y_d - y0) tan(psi) over 6 numbers. Dots at two heights (the card's 40 mm step) separate the focal length from the
height. Roll and pitch are the drawing's (not identified: the card's dots are planar but for the step).
Line camera, radiometry: DN_b = g_b R + d_b per band, from white / grey / black references and dark frames (linear least squares).
Held-out: the reflectance of three plastics recovered through each model, its spectral angle to the truth; and where held-out dots
are on the belt, from their (u, s).
D435: pinhole K, pose and depth scale and offset by one least squares of corner pixels and depths (depth noise by intel_rgbd's
stereo law, sigma = subpixel z^2 / (f b)). Held-out: the point cloud of other dots against the truth.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, field

import numpy as np

from sysid import camera as cam
from sysid import cards, result
from sysid import world as hidden

EXAMPLE = "linescan_cell"
BELT_Z = 0.72
GEOM = ("hsi.focal_px", "hsi.principal_px", "hsi.height_m", "hsi.across_offset_m", "hsi.scan_line_x_m", "hsi.scan_yaw_rad")
RGBD = tuple(f"rgbd.{n}" for n in cam.K_NAMES + cam.POSE_NAMES) + ("rgbd.depth_scale", "rgbd.depth_offset_m")
LINE_PIXELS = 640
REFERENCE_PIXELS = 120
MATERIAL_PIXELS = 200


def rng_for(seed: int, *names) -> np.random.Generator:
    return np.random.default_rng([seed, *(zlib.crc32(str(n).encode()) for n in names)])


def bands(description) -> np.ndarray:
    return np.asarray(description.known["bands_nm"], float)


def plastic(name: str, wavelengths: np.ndarray) -> np.ndarray:
    """Synthetic stand-ins for PET, HDPE and PP in the SWIR (a smooth baseline with C-H / C=O absorption dips near 1150-1220,
    1390-1420 and 1660-1730 nm): shaped like the polymers' published spectra, NOT library data; the oracle needs only that they are
    held out of the calibration and not flat."""
    shape = {"PET": (0.78, ((1660, 40, 0.18), (1130, 45, 0.10), (1415, 50, 0.08))),
             "HDPE": (0.86, ((1210, 35, 0.22), (1415, 40, 0.15), (1725, 35, 0.30))),
             "PP": (0.82, ((1195, 40, 0.16), (1390, 45, 0.18), (1700, 45, 0.24)))}[name]
    base, dips = shape
    r = np.full(wavelengths.shape, base) - 0.06 * (wavelengths - 900) / 800
    for centre, width, depth in dips:
        r -= depth * np.exp(-0.5 * ((wavelengths - centre) / width) ** 2)
    return np.clip(r, 0.02, 0.98)


# --- the line camera's geometry --------------------------------------------------------------------------------------------------

def line_pose(values: dict) -> tuple[np.ndarray, np.ndarray]:
    """World-from-CV rotation and centre of the line camera: looking down, the line along -y at yaw 0 (the description's camera)."""
    psi = float(values["hsi.scan_yaw_rad"])
    right = np.array([math.sin(psi), -math.cos(psi), 0.0])
    up = np.array([math.cos(psi), math.sin(psi), 0.0])
    R = np.column_stack([right, -up, np.array([0.0, 0.0, -1.0])])
    t = np.array([float(values["hsi.scan_line_x_m"]), float(values["hsi.across_offset_m"]), BELT_Z + float(values["hsi.height_m"])])
    return R, t


def push_broom(values: dict, dots: np.ndarray) -> np.ndarray:
    """(u, s) of each dot (x_d, y_d, z_d) on the card, closed form: the travel at which it crosses the scan plane and its pixel."""
    f, c, h, y0, x0, psi = (float(values[n]) for n in GEOM)
    x, y, z = dots[:, 0], dots[:, 1], dots[:, 2]
    s = x0 - x - (y - y0) * math.tan(psi)
    a = (x + s - x0) * math.sin(psi) - (y - y0) * math.cos(psi)
    return np.column_stack([f * a / (h - z) + c - 0.5, s])


def stock_line_observation(values: dict, dot: np.ndarray) -> tuple[float, float]:
    """The same (u, s) by bam_scan_tunnel's PinholeCamera: the card rides the belt (travel s), the dot is seen when its projected
    row crosses the line's centre row (bisection on s), and u is read there."""
    R, t = line_pose(values)
    pin = cam.Pinhole(float(values["hsi.focal_px"]), float(values["hsi.focal_px"]), float(values["hsi.principal_px"]), 0.5, R, t, LINE_PIXELS, 1).stock()
    row = lambda s: pin.project(np.array([dot[0] + s, dot[1], BELT_Z + dot[2]]))[1]  # noqa: E731
    lo, hi = -0.6, 0.6
    f_lo = row(lo)
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if (row(mid) > 0) == (f_lo > 0):
            lo, f_lo = mid, row(mid)
        else:
            hi = mid
    s = 0.5 * (lo + hi)
    return pin.project(np.array([dot[0] + s, dot[1], BELT_Z + dot[2]]))[0], s


def rgbd_pinhole(description, values: dict) -> cam.Pinhole:
    c = description.cameras["rgbd"]
    import numpy as _np  # noqa: PLC0415

    right, up = _np.asarray(c.xyaxes[:3]), _np.asarray(c.xyaxes[3:])
    R0 = _np.column_stack([right, -up, -_np.cross(right, up)])
    d, r = cam.correction_of(values, "rgbd")
    R, t = cam.corrected(R0, _np.asarray(c.pos, float), d, r)
    return cam.Pinhole(float(values["rgbd.fx_px"]), float(values["rgbd.fy_px"]), float(values["rgbd.cx_px"]), float(values["rgbd.cy_px"]), R, t,
                       int(c.resolution[0]), int(c.resolution[1]))


def stereo_sigma_m(z: np.ndarray, fx: float, subpixel: float) -> np.ndarray:
    """intel_rgbd's stereo-error law (isp.py): sigma(z) = subpixel z^2 / (fx b), b the D435's baseline."""
    from intel_rgbd.records import D435_STEREO_BASELINE_M  # noqa: PLC0415

    return subpixel * z ** 2 / (fx * D435_STEREO_BASELINE_M)


# --- plan ------------------------------------------------------------------------------------------------------------------------

@dataclass
class Plan:
    dots: np.ndarray                 # (n, 3) on the card: flat and on the step
    passes: dict                     # split -> card placements (x offset of the card's origin, y offset)
    rgbd_travels: dict               # split -> belt travels at which the D435 frame is taken
    coverage: dict = field(default_factory=dict)


def plan(description) -> Plan:
    k = description.known["target"]
    flat = [[x, y, 0.0] for x, y in k["dots_flat_m"]]
    step = [[x, y, float(k["step_height_m"])] for x, y in k["dots_step_m"]]
    dots = np.array(flat + step)
    s = description.schedule
    rng = rng_for(s["seed"], "passes")
    # each pass the card goes on the belt pushed against the guide at a different across offset (the guide's slots: known)
    offsets = [-0.06, 0.0, 0.06, -0.03, 0.03, 0.09, -0.09, 0.045, -0.045]
    passes = {"train": [(0.0, o) for o in offsets[: s["target_passes_train"]]], "held_out": [(0.0, o) for o in offsets[s["target_passes_train"]: s["target_passes_train"] + s["target_passes_held_out"]]]}
    # WHY a riser for half the D435 frames (measured 2026-11-05: with the card only on the belt, 4 cm of step relief at 0.55 m, the fit
    # left fx +-0.8 %, the standoff +-4.5 mm and the depth scale +-0.007: a near-planar target cannot separate focal length, distance
    # and depth scale); the risers are the description's (a certified block), the card's dots unchanged
    risers = description.known["target"].get("risers_m", [0.0])
    travels = {"train": [(t, risers[i % len(risers)]) for i, t in enumerate(rng.uniform(0.25, 0.65, 12))],
               "held_out": [(t, risers[i % len(risers)]) for i, t in enumerate(rng.uniform(0.25, 0.65, 6))]}
    p = Plan(dots, passes, travels)
    p.coverage = coverage(description, p)
    return p


def card_dots(p: Plan, placement) -> np.ndarray:
    return p.dots + np.array([placement[0], placement[1], 0.0])


def coverage(description, p: Plan) -> dict:
    """The line camera's own calibration coverage (sysid adapter): the planned dots' across-track position in 16 bins of the 640-pixel
    line, at each of the card's two heights, by the drawn camera; and every band at every reference level (dark, black, grey, white)."""
    nominal = {k: v.value for k, v in description.nominal.items()}
    out = {}
    for split in ("train", "held_out"):
        cells = set()
        for placement in p.passes[split]:
            dots = card_dots(p, placement)
            u = push_broom(nominal, dots)[:, 0]
            for ui, z in zip(u, dots[:, 2]):
                if 0 <= ui < LINE_PIXELS:
                    cells.add((int(ui // (LINE_PIXELS / 16)), int(z > 0)))
        out[split] = {"pct": round(100.0 * len(cells) / 32, 2), "visited": len(cells), "reachable": 32, "samples": int(sum(len(card_dots(p, pl)) for pl in p.passes[split])),
                      "axes": {"bands x reference levels": 100.0 if split == "train" else None, "rgbd frames": len(p.rgbd_travels[split])},
                      "unplanned": ["illumination", "exposure", "incidence angle"]}
    out["function"] = "sysid adapter: across-track bins (16 of the 640-pixel line) x the card's two heights"
    out["rule"] = "share of the 32 (line bin, height) cells the planned dots fall in; the radiometric references cover every band at four levels"
    return out


# --- the real tunnel --------------------------------------------------------------------------------------------------------

@dataclass
class Measured:
    line: list                      # (dots on the belt (n, 3), observed (n, 2) [u px, s m])
    references: dict                # level -> (n, bands) DN
    materials: dict                 # name -> (n, bands) DN
    rgbd: list                      # (world points (n, 3), pixels (n, 2), depth (n,))


class RealWorld:
    def __init__(self, description, *, workers: int = 6):
        self.description = description
        doc = hidden.load(EXAMPLE)
        self.truth, self.noise, self.seed = doc["truth"], doc["noise"], doc["seed"]

    def gains(self) -> tuple[np.ndarray, np.ndarray]:
        return (np.array([self.truth[f"hsi.gain_b{k:02d}"] for k in range(16)]), np.array([self.truth[f"hsi.dark_b{k:02d}"] for k in range(16)]))

    def dn(self, reflectance: np.ndarray, rng, n: int) -> np.ndarray:
        g, d = self.gains()
        clean = g * reflectance + d
        return clean + rng.normal(0.0, 1.0, (n, clean.size)) * (self.noise["dn_floor"] + self.noise["dn_relative"] * clean)

    def measure(self, p: Plan) -> dict:
        refs = self.description.known["target"]["references"]
        out = {}
        for split in ("train", "held_out"):
            line = []
            for j, placement in enumerate(p.passes[split]):
                rng = rng_for(self.seed, split, "line", j)
                dots = card_dots(p, placement)
                obs = np.array([stock_line_observation(self.truth, dot) for dot in dots])
                ok = (obs[:, 0] > 0) & (obs[:, 0] < LINE_PIXELS)
                obs = obs + np.column_stack([rng.normal(0, self.noise["hsi_pixel_px"], len(obs)), rng.normal(0, self.noise["hsi_line_m"], len(obs))])
                line.append((dots[ok], obs[ok]))
            pin = rgbd_pinhole(self.description, self.truth)
            stock = pin.stock()
            frames = []
            for j, (travel, riser) in enumerate(p.rgbd_travels[split]):
                rng = rng_for(self.seed, split, "rgbd", j)
                world = card_dots(p, p.passes[split][j % len(p.passes[split])]) + np.array([travel, 0.0, BELT_Z + riser])
                px = np.array([stock.project(w)[:2] for w in world])
                z = pin.camera_points(world)[:, 2]
                ok = pin.visible(px, z)
                reported = self.truth["rgbd.depth_scale"] * z + self.truth["rgbd.depth_offset_m"]
                sigma = stereo_sigma_m(z, pin.fx, self.noise["rgbd_subpixel_px"])
                frames.append((world[ok], px[ok] + rng.normal(0, self.noise["rgbd_pixel_px"], px[ok].shape), reported[ok] + rng.normal(0, 1.0, int(ok.sum())) * sigma[ok]))
            references = {level: self.dn(np.full(16, value), rng_for(self.seed, split, "ref", level), REFERENCE_PIXELS) for level, value in refs.items()}
            materials = {}
            if split == "held_out":
                w = bands(self.description)
                materials = {name: self.dn(plastic(name, w), rng_for(self.seed, "material", name), MATERIAL_PIXELS) for name in self.description.schedule["held_out_materials"]}
            out[split] = Measured(line, references, materials, frames)
        return _Split(out["train"], out["held_out"])


@dataclass
class _Split:
    train: Measured
    held_out: Measured


# --- identification ---------------------------------------------------------------------------------------------------------

@dataclass
class Fit:
    values: dict
    ci95: dict
    methods: dict


def identify(description, measured: Measured) -> Fit:
    """The line camera's geometry (6 numbers, closed-form push broom), each band's gain and dark (linear), the D435's K, pose and
    depth scale and offset (one least squares): from the description's values and the train references, dots and frames."""
    nominal = {k: v.value for k, v in description.nominal.items()}
    dots = np.vstack([d for d, _ in measured.line])
    obs = np.vstack([o for _, o in measured.line])

    def geometry_residual(x):
        values = {**nominal, **dict(zip(GEOM, x))}
        pred = push_broom(values, dots)
        return np.concatenate([(pred[:, 0] - obs[:, 0]) / 0.3, (pred[:, 1] - obs[:, 1]) / 3e-4])

    x0 = np.array([nominal[n] for n in GEOM])
    xg, ci_g, _ = cam.least_squares_with_ci(geometry_residual, x0, np.array([10.0, 1.0, 0.01, 0.005, 0.005, 0.005]), names=GEOM)
    values, ci = dict(zip(GEOM, map(float, xg))), dict(ci_g)

    refs = description.known["target"]["references"]
    for k in range(16):
        R = np.concatenate([np.full(measured.references[level].shape[0], value) for level, value in refs.items()])
        dn = np.concatenate([measured.references[level][:, k] for level in refs])
        A = np.column_stack([R, np.ones_like(R)])
        coef, *_ = np.linalg.lstsq(A, dn, rcond=None)
        resid = dn - A @ coef
        cov = np.linalg.pinv(A.T @ A) * float(resid @ resid) / max(1, dn.size - 2)
        half = 1.96 * np.sqrt(np.diag(cov))
        values[f"hsi.gain_b{k:02d}"], values[f"hsi.dark_b{k:02d}"] = float(coef[0]), float(coef[1])
        ci[f"hsi.gain_b{k:02d}"] = (float(coef[0] - half[0]), float(coef[0] + half[0]))
        ci[f"hsi.dark_b{k:02d}"] = (float(coef[1] - half[1]), float(coef[1] + half[1]))

    points = np.vstack([w for w, _, _ in measured.rgbd])
    px = np.vstack([p for _, p, _ in measured.rgbd])
    depth = np.concatenate([d for _, _, d in measured.rgbd])
    sigma = stereo_sigma_m(np.maximum(depth, 0.1), nominal["rgbd.fx_px"], 0.08)
    cam.check_against_stock(rgbd_pinhole(description, nominal), points[:5])

    def rgbd_residual(x):
        v = {**nominal, **dict(zip(RGBD, x))}
        pin = rgbd_pinhole(description, v)
        pred, z = pin.project(points)
        return np.concatenate([((pred - px) / 0.3).ravel(), (v["rgbd.depth_scale"] * z + v["rgbd.depth_offset_m"] - depth) / sigma])

    x0 = np.array([nominal[n] for n in RGBD])
    scale = np.array([5.0, 5.0, 2.0, 2.0, 0.005, 0.005, 0.005, 0.005, 0.005, 0.005, 0.002, 0.001])
    xr, ci_r, _ = cam.least_squares_with_ci(rgbd_residual, x0, scale, names=RGBD)
    values.update(dict(zip(RGBD, map(float, xr))))
    ci.update(ci_r)
    methods = {"geometry": f"Levenberg-Marquardt of the push-broom model on {len(dots)} dot crossings (pixel, belt travel) over {len(measured.line)} passes",
               "radiometry": f"per band, linear least squares of DN on the reference reflectance ({', '.join(refs)}; {REFERENCE_PIXELS} pixels each)",
               "rgbd": f"Levenberg-Marquardt of {len(points)} dot pixels and depths ({len(measured.rgbd)} frames), depth weighted by intel_rgbd's stereo law"}
    return Fit(values, ci, methods)


# --- held-out score ---------------------------------------------------------------------------------------------------------

def spectral_angle(a: np.ndarray, b: np.ndarray) -> float:
    return float(math.acos(np.clip(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)), -1.0, 1.0)))


def locate(values: dict, obs: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Where on the card a dot is, from its (u, s) and its known height: the push-broom model inverted."""
    f, c, h, y0, x0, psi = (float(values[n]) for n in GEOM)
    a = (obs[:, 0] - c + 0.5) * (h - z) / f
    # a = (x + s - x0) sin(psi) - (y - y0) cos(psi) and (x + s - x0) cos(psi) + (y - y0) sin(psi) = 0
    y = y0 - a * math.cos(psi)
    x = x0 - obs[:, 1] + a * math.sin(psi)
    return np.column_stack([x, y])


def score(description, p: Plan, fit: Fit, measured: _Split, *, workers: int = 6) -> dict:
    nominal = {k: v.value for k, v in description.nominal.items()}
    held = measured.held_out
    w = bands(description)
    out = {"models": {}}
    for label, values in (("nominal", nominal), ("fitted", {**nominal, **fit.values})):
        g = np.array([values[f"hsi.gain_b{k:02d}"] for k in range(16)])
        d = np.array([values[f"hsi.dark_b{k:02d}"] for k in range(16)])
        angles = [spectral_angle((dn.mean(axis=0) - d) / g, plastic(name, w)) for name, dn in held.materials.items()]
        dots = np.vstack([dd for dd, _ in held.line])
        obs = np.vstack([o for _, o in held.line])
        where = locate(values, obs, dots[:, 2])
        line_err = np.linalg.norm(where - dots[:, :2], axis=1)
        pin = rgbd_pinhole(description, values)
        cloud = []
        for world, px, depth in held.rgbd:
            z = (depth - values["rgbd.depth_offset_m"]) / values["rgbd.depth_scale"]
            cloud.append(np.linalg.norm(pin.t + pin.ray(px) * z[:, None] - world, axis=1))
        out["models"][label] = {"spectral_angle_mrad": 1e3 * float(np.mean(angles)), "scan_position_mm": 1e3 * cam.rms(line_err),
                                "cloud_mm": 1e3 * cam.rms(np.concatenate(cloud))}
    out["counts"] = {"held_out_dots": int(sum(len(d) for d, _ in held.line)), "rgbd_points": int(sum(len(w_) for w_, _, _ in held.rgbd)),
                     "materials": list(held.materials)}
    return out


def assemble(description, p: Plan, fit: Fit, scores: dict, *, truth: dict) -> dict:
    def method(key):
        return fit.methods["geometry" if key in GEOM else "rgbd" if key.startswith("rgbd.") else "radiometry"]

    recovered = {k: {"value": v, "ci95": fit.ci95[k], "rung": method(k).split(" ")[0], "method": method(k)} for k, v in fit.values.items()}
    m = scores["models"]
    md = description.manifest["model"]
    c = scores["counts"]
    return {
        "title": description.manifest["title"], "subtitle": description.manifest.get("subtitle", ""), "summary": description.manifest.get("summary", ""),
        "description": {"manifest": f"sysid/examples/{EXAMPLE}/description.json", "model": {"format": md["format"], "source": md["source"],
                        "parts": [{"id": pt["id"], "path": pt["path"], "prefix": pt["prefix"]} for pt in md["parts"]], "cameras": md.get("cameras", [])},
                        "sensors": description.manifest.get("sensors", []), "known": description.known, "components": len(description.components)},
        "tree": description.tree(),
        "schedule": {"train": {"passes": len(p.passes["train"]), "dots": int(sum(len(card_dots(p, pl)) for pl in p.passes["train"])), "rgbd_frames": len(p.rgbd_travels["train"]),
                               "references": list(description.known["target"]["references"])},
                     "held_out": {"passes": len(p.passes["held_out"]), "dots": c["held_out_dots"], "rgbd_points": c["rgbd_points"], "materials": c["materials"]},
                     "coverage": p.coverage},
        "parameters": result.parameter_rows(EXAMPLE, description, truth, recovered),
        "metrics": [result.metric(EXAMPLE, "held_out_spectral_angle_mrad", "Plastics' recovered reflectance vs true (spectral angle)", "mrad",
                                  m["nominal"]["spectral_angle_mrad"], m["fitted"]["spectral_angle_mrad"], after_model="fitted", note=", ".join(c["materials"]) + " (synthetic stand-ins, held out)"),
                    result.metric(EXAMPLE, "held_out_scan_position_mm", "Where a dot is on the belt, from its line pixel and travel", "mm",
                                  m["nominal"]["scan_position_mm"], m["fitted"]["scan_position_mm"], after_model="fitted", note=f"{c['held_out_dots']} held-out dot crossings"),
                    result.metric(EXAMPLE, "held_out_cloud_mm", "D435 point cloud vs the true dots", "mm", m["nominal"]["cloud_mm"], m["fitted"]["cloud_mm"],
                                  after_model="fitted", note=f"{c['rgbd_points']} held-out points")],
        "models": [{"model": label, **row} for label, row in m.items()], "card_ladders": cards.card_ladders(EXAMPLE, fit.values), "selected_rung": None,
        "notes": ["Band centres and widths are the vendor's: identifying them needs a spectral lamp, not simulated.",
                  "The plastics are synthetic spectra shaped like the polymers' SWIR features, not library data.",
                  "Dot detections are simulated as exact crossings plus noise (no rendered line images, no detector in the loop)."],
    }
