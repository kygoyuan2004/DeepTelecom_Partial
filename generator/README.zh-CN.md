# DeepTelecom 无人机数据生成器

[English](README.en.md) · [第三方软件说明](THIRD_PARTY_NOTICES.md)

本目录由浙江大学信息与电子工程学院（ISEE）的 DeepTelecom 项目整理，公开 UAV 数据生成流程中可独立运行的核心部分：无人机与旋翼运动建模、Sionna RT 路径求解、单基地回波合成、STFT 频谱生成，以及逐样本元数据保存。默认配置直接使用 Sionna RT 自带的 Étoile 场景，不依赖实验室服务器路径或未公开的场景文件。

> **复现范围。** 这是一份便于审阅、修改和继续研究的参考生成器。它保留数据生成的核心计算路径，但不是现有 v1 发布包的逐字节复刻工具：场景资产、GPU/驱动、求解器版本和运行时计时都可能影响输出。若修改场景、散射点数或轨迹，请创建新的数据版本，不要把结果无标记地混入 v1。

## 方法概览

标准四旋翼样本采用一个机身散射点，以及 `4 个旋翼 × 2 个叶片 × points_per_blade` 个叶片散射点。默认 `points_per_blade: 3`，因此共有 `1 + 4×2×3 = 25` 个点。每个点作为被动探针交给 `sionna.rt.PathSolver` 求解单程信道，生成器以 `wᵢ·hᵢ²` 近似单基地往返信号，再对各点相干求和、加入 AWGN 并计算 STFT。

这一模型适合研究由机身运动和旋翼运动产生的微多普勒结构，但有明确边界：

- 散射点及其权重是近似模型，不是叶片网格的全波电磁散射或经过标定的 RCS 模型；
- 当前固定为每个样本一架四旋翼无人机，标准类别固定为每旋翼两片叶片；
- `single_blade_v0` 是一个单叶尖散射点的受控基准，代码会强制使用一个点；
- 当前支持直线和单段三次 Bézier 轨迹，不支持任意 waypoint 列表、多段样条或避障规划；
- 材料、极化、漫反射、绕射等假设应结合配置和 Sionna RT 版本一起解释。

## 四个默认类别

| `class_id` | 直观含义 | 倾斜角 | 平移速度 |
| --- | --- | ---: | ---: |
| `level_v0` | 水平悬停四旋翼 | 0° | 0 m/s |
| `pitch30_v10` | 绕仿真 y 轴倾斜 30° 的四旋翼运动 | 30° | 10 m/s |
| `pitch45_v10` | 绕仿真 y 轴倾斜 45° 的四旋翼运动 | 45° | 10 m/s |
| `single_blade_v0` | 静止机体下的单叶片基准 | 0° | 0 m/s |

`pitchNN` 表示生成器中的倾斜角，`vNN` 表示机体/路径速度，单位为 m/s；它不是旋翼速度。正角通过 y 轴旋转实现，因此这里不额外推断机头上仰或下俯。

## 安装

建议使用 Linux、Python 3.11 和一张可用的 NVIDIA GPU。先确认 NVIDIA 驱动和 `nvidia-smi` 正常，再运行：

```bash
cd generator
./scripts/setup_env.sh
./scripts/preflight.py
```

`preflight.py` 会优先使用 `DEEPTELECOM_PYTHON`，其次使用本目录的 `.conda-env/bin/python`。依赖版本写在 `requirements.txt` 和 `environment.yml` 中。Sionna RT、TensorFlow、Mitsuba/Dr.Jit 与驱动之间可能存在兼容性要求；首次安装时请同时参考相应上游文档。

## 最安全的第一次运行

冒烟测试只使用一张 GPU、生成一个 `pitch30_v10` 的 8-snapshot 样本；它会覆盖标准 25 散射点分支，并随后验证无人机坐标和速度数组：

```bash
DEEPTELECOM_GPU_ID=0 ./scripts/run_smoke_test.sh
```

如果不使用本目录的 Conda 环境，可以显式指定 Python：

```bash
DEEPTELECOM_PYTHON=/path/to/python \
DEEPTELECOM_GPU_ID=0 \
./scripts/run_smoke_test.sh
```

## 生成一个正式长度样本

下面生成一个 `pitch30_v10` 样本，使用配置中的 2,048 个 snapshot：

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

完整 RT 求解会对每个散射点和多个时间快照计算路径，耗时显著高于 smoke test。开发时可以临时使用 `--snapshot-override` 和 `--rt-snapshot-stride`，但这会改变数据语义，不应伪装成正式配置结果。

输出结构如下：

```text
outputs/example/
├── images/<class_id>/<sample_id>.png
├── tensors/<class_id>/<sample_id>.npz
├── database/metadata.csv
├── database/manifest.jsonl
├── database/timing.csv
└── database/metadata.md
```

NPZ 包含干净/加噪回波、复数 STFT、频率和时间轴、各散射点轨迹、逐点 RT 信道与路径计数、无人机坐标/速度，以及 JSON 元数据。`scene_source` 只保存如 `sionna.rt.scene.etoile` 这样的逻辑标识，不写入本机绝对路径。

## 增加叶片散射点

编辑 `config/etoile.yaml`：

```yaml
points_per_blade: 5
```

标准类别会从 25 个点变为 `1 + 4×2×5 = 41` 个点。采样点沿叶片半径等距分布，默认叶片总权重会在这些点之间重新分配。更多点可以提高径向离散程度，但也会增加接收探针数、RT 求解时间、显存/内存占用和输出体积；它并不自动让点散射近似变成全波模型。`single_blade_v0` 始终强制为一个叶尖点，不受该参数影响。

把 `points_per_blade` 从 3 改为 5 属于新的生成配置。建议在 manifest 中记录配置哈希，并使用新的数据集版本或实验名。

## 修改或添加轨迹

### 直线轨迹

```yaml
body_trajectory_model: linear
body_position_x: 146.0
body_position_y: -52.0
body_position_z: 70.0
```

直线模式从上述位置开始，速度大小由类别定义，方向固定为世界坐标 `+x`。当前配置接口没有单独的方向参数。

### 单段三次 Bézier 轨迹

```yaml
body_trajectory_model: etoile_bezier
etoile_trajectory_speed_mode: class_speed
etoile_start_fraction_min: 0.00
etoile_start_fraction_max: 0.98
etoile_control0_x_m: 146.0
etoile_control0_y_m: -52.0
etoile_control0_z_m: 70.0
# 继续设置 control1、control2、control3 的 x/y/z
```

四个控制点定义一条三次 Bézier 曲线。`class_speed` 使用类别速度；也可以将速度模式设为 `handoff_nominal`，并通过 `etoile_trajectory_nominal_speed_m_s` 设置统一速度。起点会在允许的曲线区间内按样本随机种子确定。

若要支持多个 waypoint，应在 `src/build_rt_uav_stft_dataset.py` 的 `build_body_path()` 增加一个明确命名的新模型，并返回形状为 `[time, 3]` 的 `positions` 和 `velocities`。还需要补充连续性测试、配置 schema 和新版本标识；当前代码只接受 `linear` 和 `etoile_bezier`，填入 `waypoint` 会明确报错。

## 可复现性与编号

- 科学随机数只由 `random_seed + sample_index + class offset` 决定，UTC `created_time` 不参与运动、噪声或 STFT 的随机过程；
- `created_time`、RT 耗时、软件栈和底层 GPU 求解仍可能使文件字节不同，因此不要只凭“相同编号”推断内容相同；
- 多机并行时必须给不同任务分配互不重叠的编号区间；合并前应按内容 SHA256 做全局去重和冲突检查；
- 修改类别顺序、场景、轨迹、散射点数、步长或依赖版本后，应冻结完整配置并创建新版本。

## 代码范围与许可

本目录只包含核心生成、校验和单 GPU smoke 脚本，不包含原始场景目录、生成输出、调度日志、服务器启动器、历史编号登记或数据合并副本。仓库自有代码按根目录 [Apache License 2.0](../LICENSE) 发布；依赖和 Sionna RT 内置场景遵循各自许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
