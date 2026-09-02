# DeepTelecom UAV dataset generator

[中文](README.zh-CN.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

Prepared by the DeepTelecom project at the College of Information Science and Electronic Engineering (ISEE), Zhejiang University, this directory publishes the independently runnable core of the UAV data-generation workflow: UAV and rotor motion, Sionna RT path solving, monostatic return synthesis, STFT rendering, and per-sample metadata. The portable default uses the Étoile scene bundled with Sionna RT and contains no laboratory-server paths or private scene files.

> **Reproduction scope.** This is a research-facing reference generator, not a promise of byte-for-byte reproduction of the existing v1 release. The core computation path is retained, while scene assets, GPU/driver behavior, solver versions, and runtime metadata can affect output. Changes to the scene, scatterer count, or trajectory should be released as a new data version rather than silently mixed into v1.

## Method at a glance

A standard quadrotor sample contains one body scatterer plus `4 rotors × 2 blades × points_per_blade` blade scatterers. The default `points_per_blade: 3` therefore creates `1 + 4×2×3 = 25` points. Each point is represented as a passive probe for `sionna.rt.PathSolver`. The generator approximates the monostatic return as `wᵢ·hᵢ²`, coherently sums the points, adds AWGN, and computes an STFT.

This model is useful for studying micro-Doppler structure from body and rotor motion, but its limits matter:

- weighted points are an approximation, not full-wave blade-mesh scattering or a calibrated RCS model;
- the current implementation fixes one quadrotor per sample and two blades per rotor for the standard classes;
- `single_blade_v0` is a controlled one-tip-scatterer baseline and always uses one point;
- only a straight path and one cubic Bézier segment are implemented—arbitrary waypoint lists, piecewise splines, and path planning are not;
- materials, polarization, diffuse reflection, and diffraction assumptions must be interpreted together with the configuration and Sionna RT version.

## Default classes

| `class_id` | Human meaning | Tilt | Translation speed |
| --- | --- | ---: | ---: |
| `level_v0` | level-hover quadrotor | 0° | 0 m/s |
| `pitch30_v10` | quadrotor motion tilted 30° about the simulation y-axis | 30° | 10 m/s |
| `pitch45_v10` | quadrotor motion tilted 45° about the simulation y-axis | 45° | 10 m/s |
| `single_blade_v0` | stationary-body, single-blade baseline | 0° | 0 m/s |

`pitchNN` records the generator tilt angle and `vNN` the body/path speed in m/s; it is not rotor speed. The positive angle is applied as a y-axis rotation, so the release does not infer nose-up or nose-down.

## Install

Use Linux, Python 3.11, and an NVIDIA GPU. Confirm that the driver and `nvidia-smi` work, then run:

```bash
cd generator
./scripts/setup_env.sh
./scripts/preflight.py
```

`preflight.py` prefers `DEEPTELECOM_PYTHON` when set, then the local `.conda-env/bin/python`. Pinned dependencies are in `requirements.txt` and `environment.yml`. Sionna RT, TensorFlow, Mitsuba/Dr.Jit, and the NVIDIA stack have their own compatibility constraints; consult their upstream documentation when installing on a new system.

## Safe first run

The smoke test deliberately uses one GPU and generates one eight-snapshot `pitch30_v10` sample. This covers the standard 25-scatterer branch before validating the explicit UAV position and velocity arrays:

```bash
DEEPTELECOM_GPU_ID=0 ./scripts/run_smoke_test.sh
```

To use an existing environment:

```bash
DEEPTELECOM_PYTHON=/path/to/python \
DEEPTELECOM_GPU_ID=0 \
./scripts/run_smoke_test.sh
```

## Generate one full-length sample

This command produces one `pitch30_v10` sample with the configured 2,048 snapshots:

```bash
CUDA_VISIBLE_DEVICES=0 TF_FORCE_GPU_ALLOW_GROWTH=true \
  ./.conda-env/bin/python src/build_rt_uav_stft_dataset.py \
  --root outputs/example \
  --config config/etoile.yaml \
  --classes pitch30_v10 \
  --start-index 0 \
  --end-index 0 \
  --max-new-samples 1 \
  --resume

./.conda-env/bin/python src/verify_uav_kinematics.py \
  --root outputs/example --verify-only
```

Full RT generation solves paths across multiple time snapshots and scatterers, so it is much more expensive than the smoke test. `--snapshot-override` and `--rt-snapshot-stride` are useful during development, but they change the data semantics and must not be presented as full-configuration results.

```text
outputs/example/
├── images/<class_id>/<sample_id>.png
├── tensors/<class_id>/<sample_id>.npz
├── database/metadata.csv
├── database/manifest.jsonl
├── database/timing.csv
└── database/metadata.md
```

Each NPZ carries clean/noisy returns, complex STFT data and axes, scatterer trajectories, per-scatterer RT channels and path counts, UAV kinematics, and JSON metadata. Public `scene_source` values are logical identifiers such as `sionna.rt.scene.etoile`, never machine-local absolute paths.

## Increase the blade scatterer count

Edit `config/etoile.yaml`:

```yaml
points_per_blade: 5
```

The standard classes then use `1 + 4×2×5 = 41` points instead of 25. Points are uniformly sampled along blade radius, and the default total blade weight is redistributed across them. More points improve radial discretization while increasing the probe count, RT runtime, memory pressure, and output size; they do not turn the point approximation into a full-wave model. `single_blade_v0` remains fixed to one blade-tip point.

Changing 3 to 5 is a new generation configuration. Record a configuration hash in the manifest and assign a new dataset version or experiment name.

## Change or add a trajectory

### Straight path

```yaml
body_trajectory_model: linear
body_position_x: 146.0
body_position_y: -52.0
body_position_z: 70.0
```

The straight path starts at this position. Speed comes from the class definition and direction is fixed to world `+x`; the current configuration has no separate direction parameter.

### One cubic Bézier segment

```yaml
body_trajectory_model: etoile_bezier
etoile_trajectory_speed_mode: class_speed
etoile_start_fraction_min: 0.00
etoile_start_fraction_max: 0.98
etoile_control0_x_m: 146.0
etoile_control0_y_m: -52.0
etoile_control0_z_m: 70.0
# Define control1, control2, and control3 in the same way.
```

Four control points define the cubic curve. `class_speed` uses the class speed; `handoff_nominal` uses `etoile_trajectory_nominal_speed_m_s`. A sample's start point within the allowed curve interval is selected from its deterministic random seed.

To support waypoints, add an explicitly named model to `build_body_path()` in `src/build_rt_uav_stft_dataset.py` that returns `[time, 3]` `positions` and `velocities`, then add continuity tests, a configuration schema, and a new version identifier. At present, only `linear` and `etoile_bezier` are accepted; setting `waypoint` raises an explicit error.

## Reproducibility and IDs

- Scientific randomness is derived only from `random_seed + sample_index + class offset`; the UTC `created_time` does not drive motion, noise, or STFT randomness.
- `created_time`, RT timings, the software stack, and GPU solver behavior can still change file bytes, so identical numeric IDs alone do not prove identical content.
- Parallel workers must use disjoint index ranges. Perform global SHA256-based deduplication and conflict checks before merging results.
- Freeze the complete configuration and create a new version after changing class order, scene, trajectory, scatterer count, stride, or dependency versions.

## Scope and license

This directory includes only the core generator, verifier, and one-GPU smoke scripts. It excludes original scene directories, generated outputs, scheduler logs, server launchers, historical index registries, and merge copies. Repository-authored code is released under the root [Apache License 2.0](../LICENSE). Dependencies and the Sionna RT built-in scene remain subject to their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
