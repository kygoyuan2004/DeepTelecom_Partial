# DeepTelecom UAV Dataset v1 冻结 inventory（协调版）

- SERVER_ID：`rtx4090`
- freeze_time_utc：`2026-09-01T13:10:37.037719Z`
- 本文件已脱敏：仅使用 `source_root_id` 和样本相对路径，不包含本机绝对路径、登录账户或认证信息。

## 冻结统计

- `valid_candidate`：18,923
- `collision_candidate`：64
- 冻结候选合计：18,987
- `duplicate_local`：18,000
- `invalid`：0
- `incomplete`：4（全部排除）
- 正式图片与 NPZ 总字节：62,795,079,502

类别：

- `level_v0`：4,751
- `pitch30_v10`：4,736
- `pitch45_v10`：4,729
- `single_blade_v0`：4,771

批次：

- `0000-0999`：4,000
- `2000-2999`：24
- `10000-19999`：14,963

算术已验证：18,923 + 64 = 18,987；四类之和等于 18,987。`duplicate_local` 是物理镜像计数，未从逻辑候选中再次相减。

## Canonical 来源

按优先级使用以下 `source_root_id`：

1. `merged_main`
2. `namespace_shards`
3. `etoile_extra_2000_2999`

## 基线差异

相对 18,938 基线，本冻结版本多 +49 条；差异全部来自冻结时间前已登记且验证通过的 `10000-19999` 样本。冻结后的样本不进入 v1。

## 冲突与问题

64 条 `collision_candidate` 保留原编号和状态，等待全局 allocation 决策。4 条 `incomplete` 不进入候选。`invalid=0`。详细记录见 `problems.jsonl`。

## Schema 与校验

正式候选已逐条完成 NPZ 全数组读取、ZIP CRC、PNG 解码、SHA256、semantic SHA256、manifest 一致性、非有限数检查及扫描稳定性检查。schema 的 keys、dtype、shape、PNG 尺寸与参数见 `schemas.json`。

## 排除来源

以下 `source_root_id` 只保留为审计证据，不进入 v1 正式候选：

- `etoile_baseline_shards_0000_0029`
- `etoile_baseline_shards_0010_0099_trial`
- `etoile_baseline_shards_0010_0099_original`
- `floor_wall_early_rt`
- `floor_wall_early_trial_copy`
- `geometric_los_dataset`
- `dataset_500_derivative`
- `server_performance_eval_trial`
- `server_performance_eval_original`
- `monostatic_single_station_experiments`
- `calibration_uav_etoile`
- `archive_dataset_500_zip`
- `archive_etoile_500_export_zip`
- `archive_etoile_scene_bundle_zip`


## 发布环境只读检查

- 官方 HF CLI：`1.29.0`
- `huggingface_hub`：`1.29.0`
- `hf_xet`：`1.6.0`
- 已认证：是
- 目标 Dataset 可读取：是

本协调包不授权提前构建 shard 或上传；必须等待已验证的全局 plan、allocation 和前序 receipt。
