---
pretty_name: DeepTelecom UAV Dataset v1
library_name: webdataset
tags:
- wireless
- ray-tracing
- uav
- micro-doppler
- webdataset
size_categories:
- 10K<n<100K
---

# DeepTelecom UAV Dataset v1

**中文数据卡｜An English summary follows the Chinese data card.**

DeepTelecom v1 是一个面向无人机无线传播与微多普勒研究的、由射线追踪仿真产生的数据集。项目团队将三套计算环境中的分散输出统一清点、清洗、核验和重新编号，最终发布 **44,988 个正式样本**、**140 个 WebDataset TAR 分片**和 **138.76 GiB** 数据。

> 这是基于 Sionna RT 的运动点散射体与单站回波近似数据，不是实测飞行数据，也不是带真实无人机网格/RCS 的全波电磁仿真。

## 快速入口 / Quick links

- [中文项目首页](https://kygoyuan2004.github.io/DeepTelecom_Partial/)
- [English project page](https://kygoyuan2004.github.io/DeepTelecom_Partial/en/)
- [真实样本与对应关键参数 / Verified samples and paired key parameters](https://kygoyuan2004.github.io/DeepTelecom_Partial/gallery/)
- [生成方法与扩展教程 / Generation method](https://kygoyuan2004.github.io/DeepTelecom_Partial/generation/)
- [GitHub 文档、工具与开源生成器](https://github.com/kygoyuan2004/DeepTelecom_Partial)
- [冻结数据版本 `v1.0.0`](https://huggingface.co/datasets/KYGOYUAN/DeepTelecom_Partial/tree/v1.0.0)

## 数据概况 / At a glance

| 内容 / Item | v1.0.0 |
|---|---:|
| 正式样本 / accepted samples | **44,988** |
| 连续公开 ID / public IDs | `DTUAV-V1-000001`–`DTUAV-V1-044988` |
| WebDataset 分片 / shards | **140** |
| TAR 成员 / members | **134,964**（每样本 3 个） |
| TAR 总字节数 / bytes | **148,989,562,880** |
| 张量格式 / tensor schemas | 44,948 × 32-key；40 × legacy 24-key |
| 预定义 split | 无 / none |

## 四类工况不是四个难懂的代码

| 人类可读名称 | `class_id` | 生成条件 | 散射点 | 样本数 |
|---|---|---|---:|---:|
| 水平悬停 / Level hover | `level_v0` | 倾斜 0°，机体平移 0 m/s；旋翼仍转动 | 25 | 11,249 |
| 30° 倾斜飞行 / 30° pitched flight | `pitch30_v10` | 绕仿真 y 轴倾斜 30°，沿轨迹 10 m/s | 25 | 11,236 |
| 45° 倾斜飞行 / 45° pitched flight | `pitch45_v10` | 绕仿真 y 轴倾斜 45°，沿轨迹 10 m/s | 25 | 11,219 |
| 单叶片基准 / Isolated blade baseline | `single_blade_v0` | 一个旋转叶尖散射点，中心平移 0 m/s | 1 | 11,284 |

标签中的 `pitchNN` 表示生成器中的倾斜角（度），`vNN` 表示机体/轨迹速度（m/s），不是旋翼速度。正角通过 y 轴旋转实现，因此这里只写“倾斜”，不推断机头上仰或下俯。`single_blade_v0` 是隔离叶片效应的控制模型，不代表一架“单桨无人机”。

普通三类的 25 个点由 **1 个机体点 + 4 旋翼 × 2 叶片 × 每叶片 3 个径向点**组成。

## 真实频谱示例 / Verified release examples

以下 PNG 均来自最终发布 TAR；其源文件、TAR 成员和全局 manifest 的 SHA-256 已三方核验。图像横向是时间，纵向是多普勒频移，颜色表示相对谱强度。精确的 `t_axis`、`f_axis` 和 `S_dB` 在同名 NPZ 中。

<table>
  <tr>
    <td align="center"><img src="https://raw.githubusercontent.com/kygoyuan2004/DeepTelecom_Partial/c125baacc9851561317e3e3f9ab23c62e6e82fb5/site/assets/images/samples/DTUAV-V1-000007.png" width="330" alt="Level-hover micro-Doppler spectrogram"><br><b>水平悬停</b><br><code>DTUAV-V1-000007</code><br>0° · 0 m/s · 25 points</td>
    <td align="center"><img src="https://raw.githubusercontent.com/kygoyuan2004/DeepTelecom_Partial/c125baacc9851561317e3e3f9ab23c62e6e82fb5/site/assets/images/samples/DTUAV-V1-011252.png" width="330" alt="30-degree pitched-flight micro-Doppler spectrogram"><br><b>30° 倾斜飞行</b><br><code>DTUAV-V1-011252</code><br>30° · 10 m/s · 25 points</td>
  </tr>
  <tr>
    <td align="center"><img src="https://raw.githubusercontent.com/kygoyuan2004/DeepTelecom_Partial/c125baacc9851561317e3e3f9ab23c62e6e82fb5/site/assets/images/samples/DTUAV-V1-022488.png" width="330" alt="45-degree pitched-flight micro-Doppler spectrogram"><br><b>45° 倾斜飞行</b><br><code>DTUAV-V1-022488</code><br>45° · 10 m/s · 25 points</td>
    <td align="center"><img src="https://raw.githubusercontent.com/kygoyuan2004/DeepTelecom_Partial/c125baacc9851561317e3e3f9ab23c62e6e82fb5/site/assets/images/samples/DTUAV-V1-033705.png" width="330" alt="Isolated-blade baseline micro-Doppler spectrogram"><br><b>单叶片基准</b><br><code>DTUAV-V1-033705</code><br>0° · 0 m/s · 1 blade-tip</td>
  </tr>
</table>

[画廊页面](https://kygoyuan2004.github.io/DeepTelecom_Partial/gallery/)列出每个示例的分片、旋翼频率、叶片半径、载频、采样率、快照和 STFT 参数。

## 场景与飞行轨迹 / Scene and flight paths

<img src="https://raw.githubusercontent.com/kygoyuan2004/DeepTelecom_Partial/c125baacc9851561317e3e3f9ab23c62e6e82fb5/site/assets/images/scenes/etoile-trajectory-overview.png" width="900" alt="Sionna RT Étoile scene with the base station and configured UAV flight corridor">

场景图由正式生成器直接渲染 Sionna RT 2.0.1 内置 Étoile 资产：橙色点是 `(78.9293, 32.0468, 28.9687) m` 的基站，青色点列是高度 70 m、全长 88.914 m 的完整三次 Bézier 配置走廊。它用于解释场景和完整配置，不表示单个 0.1024 s 样本走完了整条轨迹。

<img src="https://raw.githubusercontent.com/kygoyuan2004/DeepTelecom_Partial/c125baacc9851561317e3e3f9ab23c62e6e82fb5/site/assets/images/trajectories/representative-trajectories.png" width="900" alt="Four verified UAV body paths drawn from release NPZ arrays">

第二张图直接读取上述四个正式 NPZ 的 `uav_positions_m` 数组。两个 10 m/s 样本在观测窗口内分别运动约 1.024 m；水平悬停和单叶片基准的机体中心保持定点，但旋翼或叶尖散射点仍在运动。绝对起终点和图像校验值见[机器可读画廊清单](https://github.com/kygoyuan2004/DeepTelecom_Partial/blob/c125baacc9851561317e3e3f9ab23c62e6e82fb5/site/data/gallery.json)。

## 每个样本包含什么 / Sample contract

每个连续公开 ID 在一个分片中恰好对应三个同名成员：

```text
DTUAV-V1-000001.npz   # channel, echo, motion, scatterer, STFT, and scene arrays
DTUAV-V1-000001.png   # paired 512 × 512 spectrogram preview
DTUAV-V1-000001.json  # normalized class, schema, checksum, and provenance metadata
```

JSON sidecar 遵循 [`schemas/v1/sample.schema.json`](https://huggingface.co/datasets/KYGOYUAN/DeepTelecom_Partial/resolve/v1.0.0/schemas/v1/sample.schema.json)。`all_samples.jsonl` 是分配与 provenance 清单，不是 sidecar 本身。

44,948 个样本使用 `dtuav-etoile-32key-v1` 张量，40 个早期正式样本使用 `dtuav-floor-wall-24key-v1`。外层 NPZ + PNG + JSON 合同完全一致；`tensor_schema_id` 决定内部数组合同，早期样本缺少的数组没有被人为伪造。

## 从分散输出到统一发布 / Curation path

1. 对三套计算环境做只读清点并冻结候选清单。
2. 在冻结前排除 39,240 份本地物理副本、1 个零字节无效样本、1,077 条未完成记录和 5,109 条测试/日志/非正式记录。
3. 依据内容哈希做全局核验。70 组旧编号冲突包含 144 条不同内容，全部保留并获得不同全局 ID。
4. 将 44,988 个正式样本重编号为 `DTUAV-V1-XXXXXX`，建立统一三成员合同。
5. 构建并逐一核验 140 个确定性 TAR、SHA-256、LFS 对象与提交链。

39,240 表示同一数据在本地目录中的重复存储，并不表示删除了 39,240 个独立训练样本。冻结候选中跨来源内容重复删除数为 0，待决冲突为 0。公开路径不按计算设备分组；来源只保存在 provenance 字段中。

## 下载 / Download

使用当前 `hf` CLI 下载冻结版本：

```bash
hf download KYGOYUAN/DeepTelecom_Partial \
  --repo-type dataset \
  --revision v1.0.0 \
  --include "data/v1/shards/*.tar" \
  --include "manifests/v1/*" \
  --include "schemas/v1/*" \
  --include "checksums/v1/SHA256SUMS" \
  --local-dir DeepTelecom_Partial
```

只下载一个分片做测试：

```bash
hf download KYGOYUAN/DeepTelecom_Partial \
  data/v1/shards/shard-00000.tar \
  manifests/v1/all_samples.jsonl.gz \
  schemas/v1/sample.schema.json \
  --repo-type dataset --revision v1.0.0 \
  --local-dir DeepTelecom_Partial
```

## 流式读取 / Stream with WebDataset

```python
import io
import json
import numpy as np
import webdataset as wds

base = (
    "https://huggingface.co/datasets/KYGOYUAN/DeepTelecom_Partial/"
    "resolve/v1.0.0/data/v1/shards"
)
urls = base + "/shard-{00000..00139}.tar"

dataset = wds.WebDataset(urls, shardshuffle=False).to_tuple("__key__", "npz", "png", "json")
for sample_id, npz_bytes, png_bytes, json_bytes in dataset:
    metadata = json.loads(json_bytes)
    with np.load(io.BytesIO(npz_bytes), allow_pickle=False) as tensor:
        print(sample_id, metadata["class_id"], tensor.files)
    break
```

本项目 GitHub 还提供带范围下载、断点续传、深度校验和安全 NPZ 读取的[辅助脚本](https://github.com/kygoyuan2004/DeepTelecom_Partial/tree/main/scripts)。

## 完整性校验 / Integrity

在下载仓库根目录执行：

```bash
grep '  data/v1/shards/' checksums/v1/SHA256SUMS | sha256sum -c -
```

`SHA256SUMS` 覆盖 140 个 TAR 与发布元数据（不自我包含）。实验应固定到 [`v1.0.0`](https://huggingface.co/datasets/KYGOYUAN/DeepTelecom_Partial/tree/v1.0.0) 或完整 commit [`de7fc35cb41af3d9c5b2f52dab5483e3ceb623b3`](https://huggingface.co/datasets/KYGOYUAN/DeepTelecom_Partial/tree/de7fc35cb41af3d9c5b2f52dab5483e3ceb623b3)，不要依赖会继续更新文档的 `main`。

## 开源生成器 / Open-source generator

[GitHub `generator/`](https://github.com/kygoyuan2004/DeepTelecom_Partial/tree/main/generator) 提供清理后的核心代码、固定依赖、配置、预检与小型冒烟测试。生成路径为：

```text
attitude/speed + trajectory
  → moving body/blade scatterer probes
  → per-snapshot Sionna RT one-way CIR
  → weighted coherent monostatic-return approximation + AWGN
  → STFT
  → NPZ + PNG + metadata
```

当前配置支持增加每叶片径向散射点、调整叶片数、直线轨迹和一段三次 Bézier 轨迹。当前拓扑固定为四旋翼；任意旋翼布局、waypoint/CSV 和多段轨迹属于后续扩展，不作为现成功能宣传。完整教程见[生成方法页](https://kygoyuan2004.github.io/DeepTelecom_Partial/generation/)。

## Split、组织与许可 / Split, organization, and license

- v1.0.0 不预设 train/validation/test split；请依据任务从连续全局 ID 构造并记录自己的划分。
- 项目由[浙江大学信息与电子工程学院（ISEE）](https://www.isee.zju.edu.cn/)团队整理发布。此说明用于识别项目组织，不额外暗示未声明的机构背书。
- GitHub 仓库中的代码与文档采用 Apache-2.0。该代码许可证不自动构成数据 payload 的独立授权；当前数据许可字段为 `null`，使用前请联系数据发布者确认适用条款。

## English summary

DeepTelecom UAV Dataset v1 contains 44,988 ray-tracing-derived UAV wireless-sensing samples in 140 deterministic WebDataset shards. Each public ID maps to one source-preserved NPZ tensor, one paired PNG spectrogram, and one normalized JSON sidecar. Four balanced conditions cover level hover, 30° and 45° pitched motion at 10 m/s, and an isolated rotating blade-tip baseline. The public namespace is source-neutral, while provenance remains available in metadata.

The project publishes a verified sample gallery, an exact checksum manifest, helper scripts, and a cleaned generator built on Sionna RT. Please read the modeling boundary above: these are point-scatterer monostatic-return approximations, not full-wave or measured-aircraft ground truth.

For experiments, pin `v1.0.0` or the exact release commit, create a task-appropriate split, record the tensor schema ID, and verify downloaded shards before use.
