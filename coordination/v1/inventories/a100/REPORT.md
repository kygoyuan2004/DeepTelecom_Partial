# DeepTelecom UAV v1 — A100 frozen inventory

- Freeze start (UTC): `2026-09-01T15:00:18Z`
- Inventory completed (UTC): `2026-09-01T15:01:40Z`
- Formal payloads discovered: **9,538**
- Candidate payloads: **9,537**
- Invalid payloads: **1**
- Local exact duplicate groups in selected roots: **0**

## Candidate classes

| Class | Count |
|---|---:|
| `level_v0` | 2,383 |
| `pitch30_v10` | 2,387 |
| `pitch45_v10` | 2,378 |
| `single_blade_v0` | 2,389 |

## Selected sources

| Source root ID | Formal | Candidate | Invalid |
|---|---:|---:|---:|
| `a100-legacy-floor-wall` | 40 | 40 | 0 |
| `a100-old-shards-2000-3999` | 5,898 | 5,897 | 1 |
| `a100-round-40000-40449` | 1,800 | 1,800 | 0 |
| `a100-round-40450-40899` | 1,800 | 1,800 | 0 |

## Tensor schemas

- `dtuav-etoile-32key-v1`: 32 keys, 9,497 candidates.
- `dtuav-floor-wall-24key-v1`: 24 keys, 40 candidates.

## Important exclusions and handling

- `pitch45_v10_2268` is invalid: its NPZ and PNG are both zero bytes and it is excluded from payload candidates.
- The archive copy, the first A100 round's duplicate shard copy, performance tests, smoke test, monostatic/single-station experiment and run/log outputs are outside the selected roots/layouts.
- Samples held only because their legacy numeric ranges overlap remain candidates; only cross-server content hashes may deduplicate them.
- The 24-key floor_wall schema and 32-key Etoile schema remain distinct. Missing arrays are never fabricated.
- The active second-round merger and supervisor were observed but not modified; the inventory reads the completed static source shards.

This inventory is read-only and is not a global allocation. Public IDs and shards must wait for both worker inventories.
