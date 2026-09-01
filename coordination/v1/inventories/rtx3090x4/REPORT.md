# DeepTelecom UAV Dataset v1 冻结 inventory 协调报告

- SERVER_ID：`rtx3090x4`
- freeze_time_utc：`2026-09-01T13:19:06Z`
- 状态：`INVENTORY_VERIFIED`
- 本文件为脱敏协调材料；本机绝对路径、登录用户名、秘密和进程命令均未包含。

## 冻结统计

- valid_candidate：16,454
- collision_candidate：10
- 冻结候选合计：16,464
- duplicate_local：21,240
- invalid：0
- incomplete：1,073（不进入 v1）
- excluded_nonformal：1
- 正式 NPZ+PNG 总字节：54,456,731,925

| class_id | 数量 |
|---|---:|
| level_v0 | 4,115 |
| pitch30_v10 | 4,113 |
| pitch45_v10 | 4,112 |
| single_blade_v0 | 4,124 |

## Canonical source_root_id

- `merged_1000_1999`
- `conflict_2000_2999`
- `quarantine_4000_4999`
- `merged_20000_20299`
- `merged_20300_20599`
- `merged_20600_20899`
- `merged_20900_21199`
- `merged_21200_21499`
- `merged_21500_21799`
- `merged_21800_22099`
- `merged_22100_22399`
- `merged_22400_22699`
- `merged_22700_22999`


`2000–2999` 的 10 条保持 collision_candidate，未经协调计划不得接受、删除或重编号。
`4000–4999` 的 454 条保持 valid_candidate，不因本地目录命名而排除。
冻结时的 incomplete 和冻结后的新增样本全部留待下一版本。

## 校验

- 冻结 manifest 压缩字节保持不变。
- 正式候选总数和四类合计均为 16,464。
- 原始与脱敏 manifest SHA256 均记录于 `SOURCE_ATTESTATION.json`。
- `SHA256SUMS` 覆盖本目录除其自身外的全部协调文件。
