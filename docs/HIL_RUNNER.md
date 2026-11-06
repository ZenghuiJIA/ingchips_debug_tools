# HIL runner v1.7.1

桌面 Sequencer、CLI 和 MCP 使用共享 Rust 原生执行器；PyOCD/J-Link 等探针操作保留 Python 兼容 worker。UI 保留步骤编辑、排序、启用/禁用、参数修改和单步运行，另提供纯串口起步模板、HIL 自测模板与 JSON 编辑器。独立串口、ING 烧录、内存和寄存器页面继续保留。

启动任务时固定配置。运行期间修改 UI 仅影响下一次提交；切页不会取消任务。桌面提交时将配置中的串口从终端交给 runner，运行日志在 Sequencer 查看，完成后不会自动重开原终端。任务执行期间其他进程无法打开同一串口，探针锁覆盖整轮运行。

关闭整个桌面应用或 MCP 服务不等于切页：服务退出会取消工作进程，阻塞调用超过宽限期后被终止。长期无人值守运行应使用 CLI。当前还不是独立安装的常驻系统服务。

## CLI

发布包根目录执行，先复制并填写 `examples/hil/bench.example.yaml`。探针必须是完整唯一 ID，芯片必须是 Pack 支持的目标名。

```powershell
bin/hil-daemon-x86_64-pc-windows-msvc.exe --mode hiltest --file examples/hil/flash_stress.hiltest.yaml --set firmware=C:/firmware/app.hex --report-dir reports
bin/hil-daemon-x86_64-pc-windows-msvc.exe --validate --file examples/hil/flash_stress.hiltest.yaml --set firmware=C:/firmware/app.hex
```

退出码：0 通过；1 设备断言/等待失败；2 配置、环境、报告错误或任务异常中断；3 用户取消。验证模式不连接硬件。`smoke.hiltest.json` 只验证基础设施，不能作为板卡测试结果。

每次运行生成独立目录，包含 `plan.json`、`status.json`、`events.jsonl`、`serial.log`、逐端口 `serial-N.bin`、`report.json`、`junit.xml`、`report.html` 和工作进程日志。失败时另外保存串口尾部和可取得的寄存器/指定 RAM。原始串口文件保留字节；事件文件以 HEX 记录数据和主机接收时间。串口数据每轮最多 512 MiB，事件文件可能约为其两倍；超过上限明确失败。

## 脚本格式

JSON 与 YAML 共用 `schema_version: 2`。现有 `.hiltest` JSON 可加载；缺失设备、未知字段、不支持的动作在启动前报错。第一版不支持将旧 ING/引脚复位步骤自动迁移为另一种硬件操作。

`examples/hil/hiltest.schema.json` 可用于编辑器补全；实际运行仍执行后端的路径、设备和范围校验。v2 中整数和不带前缀的数字字符串按十进制，十六进制必须写 `0x`；未声明 schema_version 的旧脚本，其预期内存/寄存器值保留原 UI 的十六进制解释。

文档字段为 `name`、`description`、`schema_version`、`version`、`bench`、`parameters`、`steps`、`loop_count`、`stop_on_error`、`timeout_ms`、`evidence`。`bench` 可以是对象或 YAML/JSON 文件路径，支持 `probe_id`、`target_device`、`frequency`（Hz）、`pack_path`、`port_name`、`baud_rate`。步骤参数覆盖工位默认值，空设备字符串使用工位默认值。文件路径相对所属测试文件；工位中的 Pack 路径相对工位文件。UI 直接提交对象时，固件建议使用文件选择器取得的绝对路径。

`parameters` 是默认值映射，`${name}` 只作文本替换，不执行表达式；CLI 的 `--set name=value` 覆盖已声明参数。时间接受整数毫秒或 `30s`、`5m`、`1h`。步骤有 `id`、`name`、`action`、`enabled`、`params`、`timeout_ms`、`on_failure`、`retry_count`；省略 ID 自动生成。`timeout_ms` 以步骤层为准，旧参数层同名字段作为默认值。

支持的动作：

| action | 主要 params |
| --- | --- |
| serial_open | port_name、baud_rate；所有声明的串口在第一步前开始采集 |
| flash_firmware | file_path、probe_id、target_device、frequency、pack_path、after_flash |
| reset_target | reset_method=swd_soft_reset、probe_id、target_device |
| serial_send | send_data、send_format=string/hex、send_ending=none/lf/crlf |
| serial_wait_match | pattern、match_type=contains/regex、idle_timeout_ms |
| hil_observe | boot_timeout_ms、idle_timeout_ms、boot_count、continue_on_failure |
| swd_read_assert | memory_addr、read_width=8/16/32、operator、expected_value |
| swd_read_block | memory_addr 或 symbol+axf_path、count（1–4096 字节） |
| svd_check_reg | peripheral、register、field_name、operator、expected_reg_val |
| delay | delay_ms |
| loop_block | count；子步骤放该步骤的 steps 数组 |

仅 PyOCD 地址明确的 HEX/ELF/AXF 支持自动烧录，`after_flash` 默认 `halt`，可选 `reset/none`。固件布局和目标擦除粒度仍需由项目验证；HEX 自带地址不保证邻近区域一定不受擦除影响。固件应自行改时钟、扫矩阵、记录故障，runner 不参与频点控制。

普通等待使用字节游标，仅消费至匹配末尾，同一接收块中的后续应答仍保留。正则采用 Rust bytes regex 语法；不支持的反向引用、前后向断言会在预检时拒绝，不静默降级。ASCII 行协议可用 `(?P<fail>\d+)` 命名捕获。发送命令和复位前建立新观察边界，历史结果不会跨轮复用。每个匹配窗口最多 1 MiB，溢出明确报错。

`on_failure` 支持 `abort/continue/retry`；retry 仅限读取与断言，`retry_count` 是额外尝试次数。每次失败均保留，即使重试通过，整轮仍判失败，避免掩盖不稳定。`loop_block` 是明确重复执行，最多 8 层、整轮最多 10000 个展开步骤；不自动重试烧录和命令发送。

## HILv1 与取证

`hil_observe` 同时处理 BOOT、PLAN、HB、RESULT、CRASH、DONE，支持拆包与粘包。BOOT 必须先到；统计本轮 BOOT 数量，累计 boot 字段可从任意正值开始，额外 BOOT 必须按 1 递增并符合配置。普通日志不会刷新 HB 超时。DONE 必须含 total/pass/fail/fault，total 大于 0 且等于三种结果之和；存在 PLAN/RESULT 时交叉检查。FAIL/CRASH 不会被后续成功 DONE 覆盖。

默认收到设备 FAIL 后继续收集到 DONE，再判失败；`continue_on_failure: false` 则立即结束观察并取证。意外启动、协议错误、心跳超时直接失败。当前没有进度停滞检测、任意 JSON 行字段断言或 UART START/STOP 协议动作封装，可使用串口基础动作组合。

失败取证先保存串口尾部，再尝试 attach、暂停目标并读取同一现场的 PC/LR/SP 和 SCB 寄存器；配置 `evidence.memory_addr/count` 后读取 RAM。不会为连接而先复位，也不会自动恢复目标，后续 continue 步骤应显式安排复位。超时由监督器终止工作进程，报告标记 `INTERRUPTED` 和“硬件结果可能未知”，不启动后续操作。已自行复位的固件应以 CRASH/noinit 为历史故障证据，当前寄存器只代表采集时刻。

## 回放与 MCP

```powershell
bin/hil-daemon-x86_64-pc-windows-msvc.exe --file examples/hil/flash_stress.hiltest.yaml --set firmware=C:/firmware/app.hex --replay-events reports/RUN_ID/events.jsonl --report-dir reports
```

回放读取主机时间戳，只验证一个 HIL 观察段，不操作硬件。报告标明 `REPLAY_ONLY` 和 `hardware_verified: false`，不能当作实机通过记录。跨轮、多个观察段回放和可视时间线尚未提供。

MCP 提供 `validate_hiltest`、`run_hiltest`、`get_hiltest_status`、`get_hiltest_events`、`stop_hiltest`、`get_hiltest_report`。启动立即返回 run_id；事件按 after 游标读取；停止返回 STOPPING，确认工作进程结束后才返回最终状态。单个服务一次运行一个任务，运行记录保存在 reports 目录。ING INI 已有 Rust headless 下载路径：必须先由用户手动进入 ISP，或通过带已核对接线配置的显式复位步骤进入；不根据适配器品牌猜测 RTS/DTR 接线。多板调度、电源控制、通用子流程库、步骤间暂停与从中间步骤恢复尚未提供。

## 编辑、提交与统计口径

JSON 编辑及导入保留 `parameters`、嵌套 `steps`、未知字段和旧 schema 语义；后端统一验证未知字段，不再由前端静默删除。工位默认值由执行器合并，不用动作库默认波特率覆盖导入配置。桌面 JSON 需要内嵌 bench 对象；相对路径工位文件使用 CLI 文件入口。

提交期间立即锁定启动按钮。开始请求已发出但结果未知时不得重复提交硬件操作；界面保留保护并提示核查后台状态。停止请求不等于已经停止，只有后端最终状态才能解锁。任务结果与启动时的快照对应，编辑器变更仅影响下次运行。

新报告区分 `planned_steps`（启用叶步骤按循环展开）、`executed_steps`、`skipped_steps`（计划中未执行）、`attempt_count`（包含重试，不含清理）、`passed_steps`、`failed_steps`、`cancelled_steps`。同一逻辑步骤先失败再重试通过，仍不能计为稳定通过。全计划通过率使用 `passed_steps / planned_steps`；旧报告缺少该口径时显示未知。纯延时/采集/发送成功不能证明硬件测试通过，`hardware_verified` 为 false。

## 验证边界

自动化测试覆盖解析、游标、重试与失败保留、资源锁、子进程任务和取消；冻结程序另做 CLI/MCP 回归。不通过模拟数据宣称硬件通过。真实板卡上的烧录后暂停、复位边界、串口拔插、长时间高吞吐和 HardFault 取证仍需按具体工位上板验收。
