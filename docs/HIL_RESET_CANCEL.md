# 自动复位、BOOT 与烧录取消

Sequencer 的 reset_target 可选择 SWD、DTR 脉冲或 RTS+DTR Bootloader。串口方式必须选择控制串口，并填写 pin_reset：profile_id、wiring_verified、reset_asserted_dtr、boot_asserted_rts、settle_ms、pulse_ms、boot_hold_ms。true/false 指主机串口 API 的控制值，不等同于 MCU 管脚的电压；按板级接线核对。缺少配置或未核对时，整份计划在执行前拒绝。

接收窗口在复位之前建立。顺序为：释放复位 → 选择 Boot 状态 → 等待稳定 → 拉有效复位 → 保持脉冲 → 释放复位 → 保持 Boot → 释放 Boot。取消和异常会尝试释放控制线；无法确认释放时报 PIN_STATE_UNKNOWN。完成控制线序列仅证明主机控制调用成功，进入 Bootloader 必须用下一步的串口应答断言确认。示例见 examples/hil/uart-boot.hiltest.yaml，默认 wiring_verified=false，不可直接对未知板卡运行。

HIL PyOCD 烧录传入运行专属取消标记。点击停止后，正在执行的扇区擦除/页编程算法允许完成；回到已完成边界后不再启动后续算法，执行清理并确认核心 HALTED。此时报告 CANCELLED、erase_program_stopped=true、target_halted=true，固件镜像可能不完整，不自动复位运行。已经发给 Flash 控制器的擦写无法通用地瞬时撤销。

压测固件运行期间的取消使用顶层 `stop` 合约：后端先记下当前串口会话游标，再发送配置的 STOP 字节，等待本次请求之后同一会话中的 `ack_pattern`（建议 `HILv1 STOPPED`）。旧日志、其他会话、断线或超时都不能确认停止；确认失败报告为 `ERROR`，`target_state=UNKNOWN`，并保留 `stop_detail`。

`stop` 支持 `send_data`、`send_format`（string/hex）、`send_ending`（none/lf/crlf）、`match_type`（contains/regex）、`ack_pattern` 和 `timeout_ms`；port_name/baud_rate 可继承 bench。示例已加入 flash_stress.hiltest.yaml 与 UI 压测模板，可在源码编辑器修改。固件必须先停止排入新擦写、等待当前操作结束，再发送 STOPPED；仅回显 STOP 不能作为停止确认。没有停止协议时，上位机不能证明正在运行的固件已停止。

ING 自动化步骤使用 `flash_type: ing_ini`、`file_path`、`port_name`，不要求探针。`baud_rate` 是下载结束后的应用串口速率，ISP 下载速率读取 INI。可以在同一步的 `pin_reset` 中配置已验证的 BOOT 接线，下载器打开串口后执行进 Boot 序列，避免独立复位步骤提前消费 ISP 握手；没有此配置时需要设备已在 Boot 或人工进入 Boot。HIL 下载忽略 INI 的 launch，保持 ISP 空闲，随后用显式 reset_target 启动应用，以便先恢复串口采集。ING 的 `after_flash` 只接受省略或 halt（表示不启动应用，不表示调试核心 HALTED）。

ING 下载取消使用当前任务独立的取消检查，并等待在途命令应答。只有已确认的页/扇区边界才标记 `erase_program_stopped=true`；握手未完成、应答失败不推断目标已停止。压测阶段走上面的 STOP 协议，与下载阶段取消分开记录。

监督器不再在烧录取消后固定 10 秒杀进程；仍受原步骤截止时间约束。算法超时、探针断线或清理/暂停无法确认时，结果为 ERROR/INTERRUPTED，Flash 状态为 UNKNOWN，不能报告取消成功。flash-state.json 和操作日志保留阶段及完整性。写前持久化标记位于 `%LOCALAPPDATA%/AI-HIL-Debugger/flash-state`；未知状态会阻止该探针的后续写入、烧录和 SWD 复位。恢复后可使用 `acknowledge_flash_recovery(probe_id, confirmation="board_recovery_verified")` 显式解除，活跃任务不能被解除。该确认表示操作人员已完成板级恢复核验，不是工具自动证明 Flash 安全。

回归通过可控设备 I/O 替身验证生产逻辑：取消前/算法执行中/算法返回后、下一写入阻止、失败算法、HALTED 未确认、持久化未知记录、接线预检、正反极性、每个等待阶段取消释放。没有实际板卡烧录、复位和 USB 拔插验收；PyOCD 私有算法调用边界的兼容性在安装版本中检查，不支持时拒绝执行可取消烧录。
