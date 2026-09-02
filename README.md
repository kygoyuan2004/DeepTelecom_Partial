# DeepTelecom UAV Dataset v1

DeepTelecom UAV Dataset v1 is a ray-tracing-derived UAV wireless sensing dataset published as deterministic, integrity-verifiable WebDataset shards. The frozen `v1.0.0` release contains **44,988 accepted samples** in **140 TAR shards**, with continuous public IDs from `DTUAV-V1-000001` to `DTUAV-V1-044988`.

- Dataset: [Hugging Face `v1.0.0`](https://huggingface.co/datasets/KYGOYUAN/DeepTelecom_Partial/tree/v1.0.0)
- Exact frozen revision: [`de7fc35cb41af3d9c5b2f52dab5483e3ceb623b3`](https://huggingface.co/datasets/KYGOYUAN/DeepTelecom_Partial/tree/de7fc35cb41af3d9c5b2f52dab5483e3ceb623b3)
- Project website: [DeepTelecom Pages](https://kygoyuan2004.github.io/DeepTelecom_Partial/)
- Integrity manifest: [SHA256SUMS](https://huggingface.co/datasets/KYGOYUAN/DeepTelecom_Partial/resolve/de7fc35cb41af3d9c5b2f52dab5483e3ceb623b3/checksums/v1/SHA256SUMS)

## Data layout

The approximately 149 GB payload lives on Hugging Face. This GitHub repository contains its documentation, frozen compressed manifest, schema, checksums, helper scripts, and website—not the TAR/NPZ/PNG payload.

```text
Hugging Face
├── data/v1/shards/shard-00000.tar ... shard-00139.tar
├── manifests/v1/
├── schemas/v1/sample.schema.json
├── checksums/v1/SHA256SUMS
└── dataset_registry.json

GitHub
├── manifests/v1/all_samples.jsonl.gz
├── schemas/sample-v1.schema.json
├── checksums/v1/SHA256SUMS
├── scripts/
└── site/
```

There are no source-machine directories in the public data layout. Provenance is retained as metadata fields, never encoded into public shard paths or filenames.

## Sample contract

Each public ID occurs in exactly one shard and has exactly three members:

```text
DTUAV-V1-000001.npz   # tensor arrays; source bytes preserved
DTUAV-V1-000001.png   # paired visualization; source bytes preserved
DTUAV-V1-000001.json  # normalized metadata sidecar
```

The JSON sidecar follows [`schemas/sample-v1.schema.json`](schemas/sample-v1.schema.json). The flat `all_samples.jsonl.gz` allocation/provenance manifest is a different record type and does not itself claim to satisfy the sidecar schema.

| Sidecar field | Meaning |
|---|---|
| `global_sample_id` | Immutable public `DTUAV-V1-XXXXXX` identifier |
| `class_id` | One of the four frozen class labels |
| `tensor_schema_id` | Selects the 32-key or legacy 24-key tensor contract |
| `semantic_sha256` | Deterministic semantic digest of tensor content |
| `target_shard` | Unified public TAR path |
| `members` | Exact NPZ, PNG, and JSON member names |
| `files` | NPZ/PNG byte counts and SHA-256 values |
| `provenance` | Source metadata retained without changing public paths |

## Counts

| Class label | Samples |
|---|---:|
| `level_v0` | 11,249 |
| `pitch30_v10` | 11,236 |
| `pitch45_v10` | 11,219 |
| `single_blade_v0` | 11,284 |
| **Total** | **44,988** |

The label suffixes are preserved generator configuration codes; no additional physical units are inferred here. The tensors comprise 44,948 `dtuav-etoile-32key-v1` samples and 40 early formal `dtuav-floor-wall-24key-v1` samples. The outer NPZ + PNG + JSON protocol is uniform, while `tensor_schema_id` selects the tensor schema; missing legacy arrays were not fabricated.

The 140 TAR files contain 134,964 members and total 148,989,562,880 bytes. This release intentionally defines **no train/validation/test split**.

## Quick start

Download a shard range at the immutable revision:

```bash
python scripts/download_dataset.py --output-dir DeepTelecom_Partial --start 0 --end 3
```

Verify files against the frozen checksum manifest:

```bash
python scripts/verify_dataset.py DeepTelecom_Partial --start-shard 0 --end-shard 3 --deep
```

Inspect samples without extracting a TAR:

```bash
python scripts/load_webdataset.py DeepTelecom_Partial/data/v1/shards/shard-00000.tar --limit 2
```

The scripts default to the exact HF revision `de7fc35cb41af3d9c5b2f52dab5483e3ceb623b3`, not the floating `main` branch. See each command's `--help` for range, retry, verification, and loading options.

For direct CLI download:

```bash
hf download KYGOYUAN/DeepTelecom_Partial \
  --repo-type dataset \
  --revision de7fc35cb41af3d9c5b2f52dab5483e3ceb623b3 \
  --include "data/v1/shards/*.tar" \
  --include "manifests/v1/*" \
  --include "schemas/v1/*" \
  --include "checksums/v1/SHA256SUMS" \
  --local-dir DeepTelecom_Partial
```

## Curation and integrity

Before freezing the candidate set, the scan excluded 39,240 local physical copies, 1 truly invalid zero-length sample, 1,077 incomplete records, and 5,109 performance/smoke/single-site/log or other non-formal records. Seventy original-ID conflict groups (144 records) had different content and were retained with distinct global IDs. There are no held conflicts and no cross-source content duplicate removed from the 44,988 frozen candidates.

Every shard is tied to its allocation-row digest and SHA-256 in the release registry. The checked upload chain, frozen metadata, and all 140 LFS objects resolve through both the full commit above and the immutable `v1.0.0` tag. [`checksums/v1/SHA256SUMS`](checksums/v1/SHA256SUMS) is a byte-identical copy of the HF release checksum file, so paths in it are relative to a downloaded HF repository root.

## License

The code and documentation in this GitHub repository are licensed under [Apache-2.0](LICENSE). That repository license does not assert a separate license grant for the dataset payload.
